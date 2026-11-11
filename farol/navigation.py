import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import compare_digest
from threading import Lock
from uuid import uuid4

from farol.dashboard import FIXTURES, ROOT, brief_view
from farol.tonight import tonight_brief


def google_maps_url(latitude: float, longitude: float) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1&travelmode=driving"
        f"&destination={latitude:.6f},{longitude:.6f}"
    )


@dataclass(frozen=True)
class NavigationPoint:
    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class NavigationCommand:
    command_id: str
    created_at: str
    expires_at: str
    action: str
    destination: NavigationPoint
    waypoints: tuple[NavigationPoint, ...]
    source_mode: str
    driver_confirmation_required: bool
    demo_only: bool

    def public(self) -> dict:
        row = asdict(self)
        row["maps_url"] = google_maps_url(self.destination.latitude, self.destination.longitude)
        return row


class NavigationMailbox:
    """One-command local mailbox; transport can later be replaced without changing payloads."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._command: NavigationCommand | None = None
        self._lock = Lock()
        self._store_path = store_path

    def _effective_path(self) -> Path | None:
        if self._store_path is not None:
            return self._store_path
        if os.getenv("PYTEST_CURRENT_TEST"):
            return None
        return ROOT / ".cache" / "navigation_mailbox.json"

    def _save(self, command: NavigationCommand | None) -> None:
        path = self._effective_path()
        if path is None:
            return
        try:
            if command is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(command)), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            return

    def _load(self) -> NavigationCommand | None:
        path = self._effective_path()
        if path is None or not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            dest = raw["destination"]
            waypoints = tuple(NavigationPoint(**wp) for wp in (raw.get("waypoints") or []))
            return NavigationCommand(
                command_id=str(raw["command_id"]),
                created_at=str(raw["created_at"]),
                expires_at=str(raw["expires_at"]),
                action=str(raw["action"]),
                destination=NavigationPoint(**dest),
                waypoints=waypoints,
                source_mode=str(raw["source_mode"]),
                driver_confirmation_required=bool(raw["driver_confirmation_required"]),
                demo_only=bool(raw["demo_only"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def publish(self, command: NavigationCommand) -> None:
        with self._lock:
            self._command = command
            self._save(command)

    def current(self) -> NavigationCommand | None:
        with self._lock:
            if self._command is None:
                self._command = self._load()
            if self._command is None:
                return None
            if datetime.fromisoformat(self._command.expires_at) <= datetime.now(UTC):
                self._command = None
                self._save(None)
            return self._command


mailbox = NavigationMailbox()
_viewed_lock = Lock()
_viewed_opportunities: dict[str, dict] = {}
_viewed_mode = ""
_viewed_as_of = ""


def remember_brief(brief: dict) -> None:
    """Bind Send-to-Volvo to the brief the driver actually saw."""
    global _viewed_mode, _viewed_as_of
    with _viewed_lock:
        _viewed_opportunities.clear()
        for item in brief.get("opportunities") or []:
            if item.get("id"):
                _viewed_opportunities[str(item["id"])] = item
        _viewed_mode = str(brief.get("mode") or "")
        _viewed_as_of = str(brief.get("as_of") or "")


def valid_car_token(supplied: str | None) -> bool:
    expected = os.getenv("FAROL_CAR_TOKEN", "")
    return bool(expected and supplied and compare_digest(expected, supplied))


def command_from_replay(vehicle_cost: float, decision: int) -> NavigationCommand:
    brief = brief_view(vehicle_cost, decision)
    recommendation = brief["recommendation"]
    model = json.loads((FIXTURES / "friday_model_v1.json").read_text(encoding="utf-8"))
    zone = model["zones"][recommendation["zone"]]
    now = datetime.now(UTC)
    point = NavigationPoint(
        label=f"DEMO {recommendation['zone'].replace('_', ' ').title()}",
        latitude=float(zone["lat"]),
        longitude=float(zone["lon"]),
    )
    return NavigationCommand(
        command_id=str(uuid4()),
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=20)).isoformat(),
        action=recommendation["action"],
        destination=point,
        waypoints=(),
        source_mode=brief["mode"],
        driver_confirmation_required=True,
        demo_only=True,
    )


def _parse_iso_utc(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


def command_from_opportunity(opportunity_id: str, vehicle_cost: float) -> NavigationCommand:
    from farol import tonight

    now = datetime.now(UTC)
    with _viewed_lock:
        opportunity = _viewed_opportunities.get(opportunity_id)
        source_mode = _viewed_mode
        viewed_as_of = _viewed_as_of
    if opportunity is None or (opportunity.get("anchor") or {}).get("approval_status") != "approved":
        brief = tonight_brief(vehicle_cost_per_mile=vehicle_cost)
        remember_brief(brief)
        opportunity = next(
            (item for item in brief["opportunities"] if item["id"] == opportunity_id), None
        )
        source_mode = brief["mode"]
        viewed_as_of = str(brief.get("as_of") or "")
    if opportunity is None:
        raise ValueError("opportunity not found")

    anchor = dict(opportunity.get("anchor") or {})
    anchor_id = str(anchor.get("id") or "")
    try:
        live_anchors = {a.id: a for a in tonight.load_anchors(FIXTURES / "anchors.json")}
    except Exception as exc:
        raise ValueError("navigation requires a readable driver-approved anchor store") from exc
    if not anchor_id or anchor_id not in live_anchors:
        raise ValueError("navigation requires a driver-approved anchor")
    live_anc = live_anchors[anchor_id]
    if live_anc.approval_status != "approved":
        raise ValueError("navigation requires a driver-approved anchor")
    anchor["approval_status"] = live_anc.approval_status
    anchor["label"] = live_anc.label
    anchor["latitude"] = live_anc.latitude
    anchor["longitude"] = live_anc.longitude

    if opportunity.get("navigation_available") is False:
        raise ValueError("navigation requires a driver-approved anchor and available navigation")
    action = str(opportunity.get("action") or "")
    if action not in {"MOVE", "WAIT", "STAGE"}:
        raise ValueError(f"navigation cannot publish a {action or 'non-actionable'} opportunity")

    ends_dt = _parse_iso_utc(opportunity.get("ends_at"))
    if ends_dt is None:
        raise ValueError("opportunity has a missing or invalid expiration window")
    is_demo = any(tag in source_mode.upper() for tag in ("DEMO", "MOCK", "FIXTURE"))
    ref_now = (_parse_iso_utc(viewed_as_of) or now) if is_demo else now
    if ends_dt <= ref_now:
        raise ValueError("opportunity window has already ended")

    default_exp = now + timedelta(minutes=20)
    expires_dt = (
        min(default_exp, ends_dt)
        if (ends_dt is not None and not is_demo)
        else default_exp
    )
    return NavigationCommand(
        command_id=str(uuid4()),
        created_at=now.isoformat(),
        expires_at=expires_dt.isoformat(),
        action=action,
        destination=NavigationPoint(
            label=str(anchor["label"]),
            latitude=float(anchor["latitude"]),
            longitude=float(anchor["longitude"]),
        ),
        waypoints=(),
        source_mode=source_mode,
        driver_confirmation_required=True,
        demo_only=False,
    )
