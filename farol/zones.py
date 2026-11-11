"""Canonical operating zones and aliases.

Historical Friday fixtures still use older names such as kirkland_bar_strip.
Tonight Brief, live adapters, and new ingest all resolve through this registry
so those names land on the same Eastside-first map.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from farol.dashboard import FIXTURES


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    cluster: str
    latitude: float
    longitude: float
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class PickupCenter:
    id: str
    zone: str
    label: str
    latitude: float
    longitude: float
    staging_spot: str
    active_start_hour: int
    active_end_hour: int
    suitability_score: float
    anchor_approved: bool = False
    anchor_id: str | None = None


@dataclass(frozen=True)
class ZoneRegistry:
    home_zone: str
    origin_latitude: float
    origin_longitude: float
    zones: tuple[Zone, ...]
    by_id: dict[str, Zone]
    by_alias: dict[str, str]
    pickup_centers: tuple[PickupCenter, ...] = ()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


@lru_cache(maxsize=8)
def load_zones(path: Path | None = None) -> ZoneRegistry:
    payload = json.loads((path or FIXTURES / "zones.json").read_text(encoding="utf-8"))
    origin = payload["origin"]
    zones = tuple(
        Zone(
            id=item["id"],
            label=item["label"],
            cluster=item["cluster"],
            latitude=float(item["lat"]),
            longitude=float(item["lon"]),
            aliases=tuple(item.get("aliases") or ()),
        )
        for item in payload["zones"]
    )
    centers = tuple(
        PickupCenter(
            id=item["id"],
            zone=item["zone"],
            label=item["label"],
            latitude=float(item["lat"]),
            longitude=float(item["lon"]),
            staging_spot=str(item.get("staging_spot") or item["label"]),
            active_start_hour=int(item.get("active_start_hour", 6)),
            active_end_hour=int(item.get("active_end_hour", 23)),
            suitability_score=float(item.get("suitability_score", 8.0)),
            anchor_approved=bool(item.get("anchor_approved", False)),
            anchor_id=str(item["anchor_id"]) if item.get("anchor_id") else None,
        )
        for item in (payload.get("pickup_centers") or ())
    )
    by_id = {zone.id: zone for zone in zones}
    by_alias = {}
    for zone in zones:
        by_alias[zone.id] = zone.id
        by_alias[_slug(zone.label)] = zone.id
        for alias in zone.aliases:
            by_alias[_slug(alias)] = zone.id
    home_zone = str(payload.get("home_zone") or "").strip()
    if home_zone in by_id:
        for home_alias in ("home", str(origin.get("label") or ""), "example_public_origin"):
            slug = _slug(home_alias)
            if slug and slug not in by_alias:
                by_alias[slug] = home_zone
    for center in centers:
        if center.zone in by_id:
            for center_alias in (center.id, center.label):
                slug = _slug(center_alias)
                if slug and slug not in by_alias:
                    by_alias[slug] = center.zone
    return ZoneRegistry(
        home_zone=payload["home_zone"],
        origin_latitude=float(origin["lat"]),
        origin_longitude=float(origin["lon"]),
        zones=zones,
        by_id=by_id,
        by_alias=by_alias,
        pickup_centers=centers,
    )


def canonical_zone(name: str) -> str:
    slug = _slug(name)
    if not slug:
        return "unknown"
    registry = load_zones()
    return registry.by_alias.get(slug, slug)


def zone_record(name: str) -> Zone | None:
    registry = load_zones()
    return registry.by_id.get(canonical_zone(name))
