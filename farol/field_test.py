import json
import os
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from threading import Lock
from uuid import uuid4

from farol.dashboard import ROOT, brief_view

ACTIONS = {"WAIT", "ROAM", "MOVE", "GO_HOME"}
EVENTS = {"OFFER_ACCEPTED", "OFFER_DECLINED", "OFFER_MISSED", "OVERRIDE", "BREAK", "OFFLINE"}
POLICY_VERSION = "farol-policy-2026-08-14-v1"
WINDOW_MINUTES = 15


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _public_recommendation(brief: dict) -> dict:
    recommendation = dict(brief["recommendation"])
    if recommendation["action"] == "STAY":
        recommendation["action"] = "WAIT"
    return recommendation


class FieldTestStore:
    """Durable local shadow-shift records; no model updates occur here."""

    def __init__(self, directory: Path | None = None) -> None:
        configured = os.getenv("FAROL_FIELD_DATA_DIR")
        if directory is not None:
            self.directory = directory
        elif configured:
            self.directory = Path(configured)
        else:
            self.directory = ROOT / "field_data"
        self._lock = Lock()

    def _path(self, session_id: str) -> Path:
        if not session_id or any(character not in "0123456789abcdef-" for character in session_id):
            raise ValueError("invalid session_id")
        return self.directory / f"{session_id}.json"

    def _read(self, session_id: str) -> dict:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError("field-test session not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, session: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(session["session_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def start(
        self,
        *,
        driver_zone: str,
        vehicle_cost: float,
        decision_index: int,
        odometer_miles: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict:
        if not driver_zone.strip():
            raise ValueError("driver_zone is required")
        brief = brief_view(vehicle_cost, decision_index)
        started = datetime.now(UTC)
        session = {
            "session_id": str(uuid4()),
            "status": "AWAITING_DRIVER_CHOICE",
            "policy_version": POLICY_VERSION,
            "policy_frozen": True,
            "learning_enabled": False,
            "started_at": started.isoformat(),
            "expires_at": None,
            "window_minutes": WINDOW_MINUTES,
            "ended_at": None,
            "driver_zone": driver_zone.strip(),
            "vehicle_cost_per_mile": brief["vehicle_cost_per_mile"],
            "starting_odometer_miles": odometer_miles,
            "ending_odometer_miles": None,
            "model_snapshot": {
                "source": "friday_model_v1.json",
                "decision_index": decision_index,
                "recommendation": _public_recommendation(brief),
                "runner_up": brief["runner_up"],
                "explanation": brief["explanation"],
            },
            "driver_choice": None,
            "recommendation_revealed_at": None,
            "actual_action": None,
            "observability": "UNCERTAIN",
            "presence_samples": [],
            "events": [],
        }
        if latitude is not None and longitude is not None:
            session["presence_samples"].append({
                "at": started.isoformat(),
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_meters": None,
            })
        with self._lock:
            self._write(session)
        return self.public(session)

    def choose(self, session_id: str, action: str) -> dict:
        normalized = action.upper()
        if normalized not in ACTIONS:
            raise ValueError(f"action must be one of {sorted(ACTIONS)}")
        with self._lock:
            session = self._read(session_id)
            if session["status"] != "AWAITING_DRIVER_CHOICE":
                raise ValueError("driver choice is already locked")
            session["driver_choice"] = {"action": normalized, "recorded_at": _now()}
            revealed = datetime.now(UTC)
            session["recommendation_revealed_at"] = revealed.isoformat()
            session["expires_at"] = (revealed + timedelta(minutes=WINDOW_MINUTES)).isoformat()
            session["status"] = "ACTIVE"
            self._write(session)
        return self.public(session, reveal=True)

    def add_event(self, session_id: str, event_type: str, note: str = "") -> dict:
        normalized = event_type.upper()
        if normalized not in EVENTS:
            raise ValueError(f"event_type must be one of {sorted(EVENTS)}")
        with self._lock:
            session = self._read(session_id)
            if session["status"] != "ACTIVE":
                raise ValueError("events require an active field test")
            session["events"].append({"type": normalized, "at": _now(), "note": note.strip()})
            if normalized in {"BREAK", "OFFLINE"}:
                session["observability"] = "UNCERTAIN"
            self._write(session)
        return self.public(session, reveal=True)

    def add_presence(
        self,
        session_id: str,
        *,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None = None,
    ) -> dict:
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("invalid coordinates")
        with self._lock:
            session = self._read(session_id)
            if session["status"] != "ACTIVE":
                raise ValueError("presence samples require an active field test")
            session["presence_samples"].append({
                "at": _now(),
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_meters": accuracy_meters,
            })
            self._write(session)
        return self.public(session, reveal=True)

    @staticmethod
    def _automatically_observable(session: dict) -> bool:
        samples = session["presence_samples"]
        if len(samples) < 2:
            return False
        times = [datetime.fromisoformat(sample["at"]) for sample in samples]
        covered_minutes = (times[-1] - times[0]).total_seconds() / 60
        largest_gap = max(
            (later - earlier).total_seconds() / 60 for earlier, later in pairwise(times)
        )
        return covered_minutes >= WINDOW_MINUTES - 1 and largest_gap <= 3

    def finish(
        self,
        session_id: str,
        *,
        actual_action: str | None = None,
        observable: bool | None = None,
        odometer_miles: float | None = None,
    ) -> dict:
        with self._lock:
            session = self._read(session_id)
            if session["status"] != "ACTIVE":
                raise ValueError("only an active field test can end")
            normalized = (actual_action or session["driver_choice"]["action"]).upper()
            if normalized not in ACTIONS:
                raise ValueError(f"actual_action must be one of {sorted(ACTIONS)}")
            if any(event["type"] == "OVERRIDE" for event in session["events"]) and actual_action is None:
                raise ValueError("actual_action is required after an override")
            duty_blocked = any(
                event["type"] in {"BREAK", "OFFLINE"} for event in session["events"]
            )
            automatically_observable = (
                False if duty_blocked else self._automatically_observable(session)
            )
            if observable is None:
                is_observable = automatically_observable
                basis = "presence_sampler"
            else:
                is_observable = bool(observable) and not duty_blocked
                basis = "driver_confirmation" if not duty_blocked else "offline_overrides_gps"
            session["actual_action"] = normalized
            session["observability"] = "OBSERVABLE" if is_observable else "UNCERTAIN"
            session["observability_basis"] = basis
            session["ending_odometer_miles"] = odometer_miles
            session["ended_at"] = _now()
            session["status"] = "COMPLETE"
            recommendation = session["model_snapshot"]["recommendation"]
            session["advice_gradeable"] = is_observable and normalized == recommendation["action"]
            self._write(session)
        return self.public(session, reveal=True)

    @staticmethod
    def public(session: dict, reveal: bool = False) -> dict:
        result = json.loads(json.dumps(session))
        if not reveal and result["recommendation_revealed_at"] is None:
            result["model_snapshot"].pop("recommendation", None)
            result["model_snapshot"].pop("runner_up", None)
            result["model_snapshot"].pop("explanation", None)
        return result


store = FieldTestStore()
