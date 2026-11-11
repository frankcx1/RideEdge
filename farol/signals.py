import json
import math
import os
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

_ANCHOR_LOCK = threading.RLock()

Basis = Literal["scheduled", "live", "assumed"]


@dataclass(frozen=True)
class Signal:
    id: str
    kind: str
    zone: str
    starts_at: str
    ends_at: str
    magnitude: float
    basis: Basis
    source: str
    fetched_at: str
    expires_at: str
    evidence_quality: float
    details: dict


@dataclass(frozen=True)
class Anchor:
    id: str
    zone: str
    label: str
    latitude: float
    longitude: float
    action: str
    approval_status: Literal["approved", "pending", "demo_only"]
    safety_notes: str


@dataclass(frozen=True)
class RouteEstimate:
    origin_zone: str
    destination_anchor_id: str
    traffic_minutes: float
    distance_miles: float
    vehicle_cost: float
    basis: Basis
    source: str
    fetched_at: str


class SignalAdapter(Protocol):
    name: str

    def fetch(self, window_start: datetime, window_end: datetime) -> list[Signal]: ...


class FixtureSignalAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = "fixture"

    def fetch(self, window_start: datetime, window_end: datetime) -> list[Signal]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        signals = [Signal(**item) for item in payload["signals"]]
        return [
            signal for signal in signals
            if datetime.fromisoformat(signal.ends_at) >= window_start
            and datetime.fromisoformat(signal.starts_at) <= window_end
        ]


def _local_anchors_path(base_path: Path, local_dir: Path | None = None) -> Path | None:
    if local_dir is not None:
        return local_dir / "anchors_local.json"
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("FAROL_USE_LOCAL_ANCHORS", "") != "1":
        return None
    override = os.getenv("FAROL_FIELD_DATA_DIR")
    directory = Path(override) if override else base_path.resolve().parent.parent / "field_data"
    return directory / "anchors_local.json"


def _read_local_anchor_store(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"overrides": {}, "custom": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"overrides": {}, "custom": []}
        return {
            "overrides": payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            "custom": payload.get("custom") if isinstance(payload.get("custom"), list) else [],
        }
    except (OSError, ValueError):
        return {"overrides": {}, "custom": []}


def _write_local_anchor_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(store, indent=2), encoding="utf-8")
    temporary.replace(path)


def _validate_coords(latitude: float, longitude: float) -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("Anchor coordinates must be finite numbers")
    if not (47.0 <= latitude <= 48.2 and -123.0 <= longitude <= -121.5):
        raise ValueError("Anchor coordinates must be within Seattle/Eastside bounds")


def load_anchors(path: Path | None = None, *, local_dir: Path | None = None) -> list[Anchor]:
    if path is None:
        from farol.dashboard import FIXTURES

        path = FIXTURES / "anchors.json"
    with _ANCHOR_LOCK:
        payload = json.loads(path.read_text(encoding="utf-8"))
        by_id: dict[str, Anchor] = {item["id"]: Anchor(**item) for item in payload["anchors"]}
        store = _read_local_anchor_store(_local_anchors_path(path, local_dir))
        for item in store["custom"]:
            if isinstance(item, dict) and item.get("id"):
                try:
                    by_id[str(item["id"])] = Anchor(**item)
                except TypeError:
                    continue
        for anchor_id, patch in store["overrides"].items():
            if anchor_id not in by_id or not isinstance(patch, dict):
                continue
            allowed = {
                key: patch[key]
                for key in ("label", "latitude", "longitude", "action", "approval_status", "safety_notes")
                if key in patch and patch[key] is not None
            }
            if allowed:
                by_id[anchor_id] = replace(by_id[anchor_id], **allowed)
        return list(by_id.values())


def save_anchor_override(
    anchor_id: str,
    *,
    approval_status: Literal["approved", "pending", "demo_only"] = "approved",
    label: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    safety_notes: str | None = None,
    base_path: Path | None = None,
    local_dir: Path | None = None,
) -> Anchor:
    if approval_status not in {"approved", "pending", "demo_only"}:
        raise ValueError("approval_status must be approved, pending, or demo_only")
    from farol.dashboard import FIXTURES

    fixture_path = base_path or (FIXTURES / "anchors.json")
    with _ANCHOR_LOCK:
        current = {item.id: item for item in load_anchors(fixture_path, local_dir=local_dir)}
        if anchor_id not in current:
            try:
                from farol.zones import load_zones

                reg = load_zones()
                pc = next(
                    (c for c in reg.pickup_centers if c.id == anchor_id or c.zone == anchor_id),
                    None,
                )
                if pc is not None and pc.anchor_id and pc.anchor_id in current:
                    anchor_id = pc.anchor_id
                else:
                    by_zone = next((a.id for a in current.values() if a.zone == anchor_id), None)
                    if by_zone is not None:
                        anchor_id = by_zone
            except Exception:
                pass
        if anchor_id not in current:
            raise ValueError(f"anchor {anchor_id!r} not found")
        target = current[anchor_id]
        lat = float(latitude) if latitude is not None else target.latitude
        lon = float(longitude) if longitude is not None else target.longitude
        _validate_coords(lat, lon)
        override_dir = local_dir
        if override_dir is None:
            env_dir = os.getenv("FAROL_FIELD_DATA_DIR")
            override_dir = Path(env_dir) if env_dir else fixture_path.resolve().parent.parent / "field_data"
        local_path = override_dir / "anchors_local.json"
        store = _read_local_anchor_store(local_path)
        patch = dict(store["overrides"].get(anchor_id) or {})
        patch["approval_status"] = approval_status
        if label is not None and label.strip():
            patch["label"] = label.strip()
        if latitude is not None:
            patch["latitude"] = round(lat, 6)
        if longitude is not None:
            patch["longitude"] = round(lon, 6)
        if safety_notes is not None:
            patch["safety_notes"] = safety_notes.strip()
        store["overrides"][anchor_id] = patch
        _write_local_anchor_store(local_path, store)
        return next(
            item for item in load_anchors(fixture_path, local_dir=override_dir) if item.id == anchor_id
        )


def save_custom_anchor(
    *,
    zone: str,
    label: str,
    latitude: float,
    longitude: float,
    action: str = "WAIT",
    approval_status: Literal["approved", "pending", "demo_only"] = "approved",
    safety_notes: str = "Driver-saved parked spot.",
    base_path: Path | None = None,
    local_dir: Path | None = None,
) -> Anchor:
    if approval_status not in {"approved", "pending", "demo_only"}:
        raise ValueError("approval_status must be approved, pending, or demo_only")
    if action not in {"WAIT", "MOVE", "STAGE"}:
        raise ValueError("action must be WAIT, MOVE, or STAGE")
    lat, lon = float(latitude), float(longitude)
    _validate_coords(lat, lon)
    if not label or not label.strip():
        raise ValueError("label is required")
    from farol.dashboard import FIXTURES
    from farol.zones import canonical_zone, load_zones

    canon = canonical_zone(zone)
    if canon not in load_zones().by_id:
        raise ValueError(f"unknown zone {zone!r}")
    fixture_path = base_path or (FIXTURES / "anchors.json")
    override_dir = local_dir
    if override_dir is None:
        env_dir = os.getenv("FAROL_FIELD_DATA_DIR")
        override_dir = Path(env_dir) if env_dir else fixture_path.resolve().parent.parent / "field_data"
    local_path = override_dir / "anchors_local.json"
    with _ANCHOR_LOCK:
        store = _read_local_anchor_store(local_path)
        anchor_id = f"{canon}-driver-curb"
        record = Anchor(
            id=anchor_id,
            zone=canon,
            label=label.strip(),
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            action=action,
            approval_status=approval_status,
            safety_notes=safety_notes.strip() or "Driver-saved parked spot.",
        )
        custom = [item for item in store["custom"] if isinstance(item, dict) and item.get("id") != anchor_id]
        custom.append(asdict(record))
        store["custom"] = custom
        _write_local_anchor_store(local_path, store)
        return next(
            item for item in load_anchors(fixture_path, local_dir=override_dir) if item.id == anchor_id
        )


def public_record(value: Signal | Anchor | RouteEstimate) -> dict:
    row = asdict(value)
    if isinstance(value, Anchor):
        row["maps_url"] = (
            "https://www.google.com/maps/dir/?api=1&travelmode=driving"
            f"&destination={value.latitude:.6f},{value.longitude:.6f}"
        )
    return row
