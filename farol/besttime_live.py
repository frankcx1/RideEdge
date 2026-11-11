"""Live & Weekly BestTime Foot-Traffic Engine for RideEdge (Basic Plan).

Provides:
1. Curated high-yield Seattle & Eastside nightlife/dining venues (`BESTTIME_UBER_VENUES`).
2. 14-day cached 7x24h weekly forecast curves (`POST /api/v1/forecasts`) to compute
   the "Spillout / Tab-Out Slope" (when a packed venue is about to empty onto the curb).
3. 30-minute cached live foot-traffic checks (`POST /api/v1/forecasts/live`) to detect
   real-time surges (`+15%` or more above typical busyness for this hour).
4. Merges live readings into `.cache/besttime/live_active/report.json` and emits
   high-confidence demand signals into `.cache/feeds/awareness_snapshot.json`.
"""

from __future__ import annotations

import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from farol.besttime import (
    normalize_forecast,
    normalize_live,
    number,
    review_entry,
    sanitize,
    save,
    venue_match,
)
from farol.dashboard import ROOT
from farol.besttime_cache import hour_record, merge_entries, usable_hour
from farol.signals import Signal
from farol.zones import canonical_zone, load_zones

API = "https://besttime.app/api/v1"
PACIFIC = ZoneInfo("America/Los_Angeles")
FORECAST_TTL_SECONDS = 14 * 24 * 3600
LIVE_TTL_SECONDS = 30 * 60
LIVE_SIGNAL_MAX_AGE_SECONDS = 90 * 60

_PUBLISH_LOCK = threading.RLock()
_PUBLISHED_BY_CONTEXT: dict[tuple[str, int], dict[str, dict]] = {}
_RADAR_ATTEMPT = threading.local()


def _entry_timestamp(entry: dict | None) -> float:
    if not isinstance(entry, dict):
        return 0.0
    lv = entry.get("live") or {}
    fc = entry.get("forecast") or {}
    raw = lv.get("retrieved_at") or fc.get("retrieved_at")
    if not raw or not isinstance(raw, str):
        return 0.0
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo is not None else 0.0
    except ValueError:
        return 0.0

BESTTIME_UBER_VENUES: list[dict] = [
    # Bellevue Core
    {
        "id": "joey_bellevue",
        "name": "JOEY Bellevue",
        "address": "800 Bellevue Way NE, Bellevue, WA 98004",
        "city": "Bellevue",
        "area": "Bellevue",
        "zone": "bellevue_core",
        "kind": "bar",
        "latitude": 47.6177,
        "longitude": -122.2010,
    },
    {
        "id": "tavern_hall_bellevue",
        "name": "Tavern Hall",
        "address": "505 Bellevue Square, Bellevue, WA 98004",
        "city": "Bellevue",
        "area": "Bellevue",
        "zone": "bellevue_core",
        "kind": "bar",
        "latitude": 47.6156,
        "longitude": -122.2035,
    },
    # Kirkland Waterfront & Rose Hill
    {
        "id": "moss_bay_hall_kirkland",
        "name": "Moss Bay Hall",
        "address": "111 Central Way, Kirkland, WA 98033",
        "city": "Kirkland",
        "area": "Kirkland",
        "zone": "kirkland_waterfront",
        "kind": "bar",
        "latitude": 47.6762,
        "longitude": -122.2044,
    },
    {
        "id": "flatstick_kirkland",
        "name": "Flatstick Pub - Kirkland",
        "address": "15 Lake St, Kirkland, WA 98033",
        "city": "Kirkland",
        "area": "Kirkland",
        "zone": "kirkland_waterfront",
        "kind": "bar",
        "latitude": 47.6759,
        "longitude": -122.2072,
    },
    {
        "id": "the_lime_kirkland",
        "name": "The Lime",
        "address": "8544 122nd Ave NE, Kirkland, WA 98033",
        "city": "Kirkland",
        "area": "Kirkland",
        "zone": "kirkland_rose_hill",
        "kind": "bar",
        "latitude": 47.6804,
        "longitude": -122.1776,
    },
    # Redmond
    {
        "id": "palmers_east_redmond",
        "name": "Palmer's East",
        "address": "16260 Redmond Way, Redmond, WA 98052",
        "city": "Redmond",
        "area": "Redmond",
        "zone": "redmond_downtown",
        "kind": "bar",
        "latitude": 47.6736,
        "longitude": -122.1235,
    },
    {
        "id": "matador_redmond",
        "name": "Matador Redmond",
        "address": "7824 Leary Way NE, Redmond, WA 98052",
        "city": "Redmond",
        "area": "Redmond",
        "zone": "redmond_downtown",
        "kind": "bar",
        "latitude": 47.6734,
        "longitude": -122.1246,
    },
    # Capitol Hill
    {
        "id": "caffe_vita_capitol_hill",
        "name": "Caffe Vita",
        "address": "1005 E Pike St, Seattle, WA 98122",
        "city": "Seattle",
        "area": "Capitol Hill",
        "zone": "capitol_hill",
        "kind": "cafe",
        "latitude": 47.6140,
        "longitude": -122.3191,
    },
    {
        "id": "dicks_capitol_hill",
        "name": "Dick's Drive-In",
        "address": "115 Broadway E, Seattle, WA 98102",
        "city": "Seattle",
        "area": "Capitol Hill",
        "zone": "capitol_hill",
        "kind": "dining",
        "latitude": 47.6194,
        "longitude": -122.3211,
    },
    {
        "id": "unicorn_capitol_hill",
        "name": "Unicorn",
        "address": "1118 E Pike St, Seattle, WA 98122",
        "city": "Seattle",
        "area": "Capitol Hill",
        "zone": "capitol_hill",
        "kind": "bar",
        "latitude": 47.6143,
        "longitude": -122.3175,
    },
    {
        "id": "comet_tavern",
        "name": "The Comet Tavern",
        "address": "922 E Pike St, Seattle, WA 98122",
        "city": "Seattle",
        "area": "Capitol Hill",
        "zone": "capitol_hill",
        "kind": "bar",
        "latitude": 47.6142,
        "longitude": -122.3199,
    },
    {
        "id": "rhein_haus_seattle",
        "name": "Rhein Haus Seattle",
        "address": "912 12th Ave, Seattle, WA 98122",
        "city": "Seattle",
        "area": "Capitol Hill",
        "zone": "capitol_hill",
        "kind": "bar",
        "latitude": 47.6109,
        "longitude": -122.3165,
    },
    # Downtown / Belltown / SLU
    {
        "id": "jupiter_bar_belltown",
        "name": "Jupiter Bar",
        "address": "2126 2nd Ave, Seattle, WA 98121",
        "city": "Seattle",
        "area": "Belltown",
        "zone": "belltown",
        "kind": "bar",
        "latitude": 47.6134,
        "longitude": -122.3435,
    },
    {
        "id": "tapster_slu",
        "name": "Tapster",
        "address": "1011 Valley St, Seattle, WA 98109",
        "city": "Seattle",
        "area": "SLU",
        "zone": "seattle_core",
        "kind": "bar",
        "latitude": 47.6263,
        "longitude": -122.3361,
    },
    # Ballard / Fremont
    {
        "id": "tractor_tavern_ballard",
        "name": "Tractor Tavern",
        "address": "5213 Ballard Ave NW, Seattle, WA 98107",
        "city": "Seattle",
        "area": "Ballard",
        "zone": "fremont_ballard",
        "kind": "bar",
        "latitude": 47.6657,
        "longitude": -122.3827,
    },
    {
        "id": "nectar_lounge_fremont",
        "name": "Nectar Lounge",
        "address": "412 N 36th St, Seattle, WA 98103",
        "city": "Seattle",
        "area": "Fremont",
        "zone": "fremont_ballard",
        "kind": "bar",
        "latitude": 47.6522,
        "longitude": -122.3539,
    },
]


def _active_dir() -> Path:
    return ROOT / ".cache" / "besttime" / "live_active"


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _bt_post(endpoint: str, params: dict, private_key: str, public_key: str) -> dict:
    from farol.besttime_control import reserve_request
    reserve_request()
    url = API + endpoint + "?" + urlencode({"api_key_private": private_key, **params})
    req = Request(url, method="POST", headers={"User-Agent": "rideedge-besttime-basic/1"})
    try:
        with urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
            code = resp.status
    except HTTPError as err:
        code = err.code
        try:
            payload = json.loads(err.read())
        except (ValueError, OSError):
            payload = {"status": "Error", "message": "Non-JSON HTTP error"}
    except (URLError, OSError, ValueError):
        return {"http_status": None, "payload": {}, "error": "Transport or JSON error"}
    if not isinstance(payload, dict):
        return {"http_status": code, "payload": {}, "error": "Unexpected response schema"}
    return sanitize({"http_status": code, "payload": payload}, (private_key, public_key))


def _read_json(path: Path) -> dict | None:
    try:
        val = json.loads(path.read_text(encoding="utf-8"))
        return val if isinstance(val, dict) else None
    except (OSError, ValueError):
        return None


def _is_fresh(receipt: dict | None, ttl_seconds: int, now: datetime) -> bool:
    if not receipt or receipt.get("http_status") != 200:
        return False
    raw = receipt.get("retrieved_at")
    if not raw:
        return False
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - stamp).total_seconds() <= ttl_seconds


def _typical_for_hour(forecast_norm: dict, dt: datetime, *, now: datetime | None = None) -> int | None:
    # All merged records enforce per-hour expiry, including legacy consumers.
    hr = (usable_hour(forecast_norm, dt, now or dt) if now or forecast_norm.get("hourly_provenance")
          else hour_record(forecast_norm, dt))
    val = number(hr.get("typical_busyness")) if hr and hr.get("closed") is not True else None
    return int(val) if val is not None and 0 <= val <= 100 else None


def poll_besttime_venues(
    area: str = "Bellevue",
    *,
    max_venues: int = 5,
    force_live: bool = False,
) -> dict:
    """Poll BestTime weekly (cached 14d) + live (cached 30m) for venues near `area`."""
    from farol.besttime_control import status
    if not status()["enabled"]:
        return {"ok": False, "mode": "paused", "detail": status()["detail"],
                "http_requests_made": 0, "polled_live_count": 0, "polled_weekly_count": 0,
                "radar_requests": 0, "radar_hotspots_found": 0}
    private_key = os.getenv("BESTTIME_API_KEY_PRIVATE", "").strip()
    public_key = os.getenv("BESTTIME_API_KEY_PUBLIC", "").strip()
    if not private_key or not public_key:
        raise ValueError("Set BESTTIME_API_KEY_PRIVATE and BESTTIME_API_KEY_PUBLIC in .env")

    now = datetime.now(UTC)
    registry = load_zones()
    zone_id = canonical_zone(area)
    center = registry.by_id.get(zone_id) or registry.by_id["bellevue_core"]

    # Sort curated venues by proximity to the selected area
    ranked_venues = sorted(
        BESTTIME_UBER_VENUES,
        key=lambda v: (
            0 if v["zone"] == center.id else 1,
            _distance_miles(center.latitude, center.longitude, v["latitude"], v["longitude"]),
        ),
    )
    selected = ranked_venues[: max(1, min(max_venues, 8))]
    selected_ids = {v["id"] for v in selected}

    base_dir = _active_dir()
    fc_dir = base_dir / "forecasts"
    lv_dir = base_dir / "live"

    # Load any previously polled venues so the report accumulates across areas
    valid_ids = {v["id"] for v in BESTTIME_UBER_VENUES}
    existing_report = _read_json(base_dir / "report.json") or {}
    baseline_by_id: dict[str, dict] = {
        str((item.get("requested") or {}).get("id")): item
        for item in (existing_report.get("venues") or [])
        if isinstance(item, dict)
        and (
            str((item.get("requested") or {}).get("id")) in valid_ids
            or (
                str((item.get("requested") or {}).get("id")).startswith("radar_")
                and not any(
                    skip in str((item.get("requested") or {}).get("name") or "").lower()
                    for skip in _EXCLUDED_RADAR_NAMES
                )
            )
        )
    }
    by_id: dict[str, dict] = dict(baseline_by_id)
    updated_by_id: dict[str, dict] = {}

    def _poll_one(venue: dict) -> tuple[str, dict, int, int]:
        vid = venue["id"]
        params = {"venue_name": venue["name"], "venue_address": venue["address"]}
        wk_cnt = 0
        lv_cnt = 0

        # 1. Weekly forecast (cached 14 days)
        fc_path = fc_dir / f"{vid}.forecast.json"
        fc_receipt = _read_json(fc_path)
        if not _is_fresh(fc_receipt, FORECAST_TTL_SECONDS, now):
            fc_receipt = {
                "venue_key": vid,
                "kind": "forecast",
                "parameters": params,
                "requested_at": now.isoformat(),
            }
            res = _bt_post("/forecasts", params, private_key, public_key)
            fc_receipt.update(res)
            fc_receipt["retrieved_at"] = datetime.now(UTC).isoformat()
            save(fc_path, fc_receipt)
            wk_cnt += 1

        fc_norm = normalize_forecast(fc_receipt or {})
        bt_venue_id = str((fc_norm.get("venue") or {}).get("venue_id") or "")
        forecast_matched = bool(bt_venue_id and venue_match(venue, fc_norm.get("venue") or {}))

        # 2. Live busyness check (cached 30 minutes unless force_live=True)
        lv_path = lv_dir / f"{vid}.live.json"
        lv_receipt = _read_json(lv_path)
        if force_live or not _is_fresh(lv_receipt, LIVE_TTL_SECONDS, now):
            live_params = {"venue_id": bt_venue_id} if forecast_matched else params
            lv_receipt = {
                "venue_key": vid,
                "kind": "live",
                "parameters": live_params,
                "requested_at": now.isoformat(),
            }
            res = _bt_post("/forecasts/live", live_params, private_key, public_key)
            lv_receipt.update(res)
            lv_receipt["retrieved_at"] = datetime.now(UTC).isoformat()
            save(lv_path, lv_receipt)
            lv_cnt += 1

        lv_norm = normalize_live(lv_receipt or {}, bt_venue_id)
        entry = review_entry({
            "requested": venue,
            "identity_matched": forecast_matched,
            "forecast": fc_norm,
            "live": lv_norm,
        })
        return vid, entry, lv_cnt, wk_cnt

    polled_live_count = 0
    polled_weekly_count = 0
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(selected)))) as pool:
        for vid, entry, lv_cnt, wk_cnt in pool.map(_poll_one, selected):
            entry = merge_entries(by_id.get(vid), entry)
            by_id[vid] = entry
            updated_by_id[vid] = entry
            polled_live_count += lv_cnt
            polled_weekly_count += wk_cnt

    # 2. Also run the BestTime Area-Wide Radar Scan (/api/v1/venues/filter) to discover
    #    the highest-foot-traffic hotspots right now across the radius + their 24h curves!
    before_radar_ids = {k: id(v) for k, v in by_id.items()}
    _RADAR_ATTEMPT.attempts = 0
    radar_added = _merge_radar_hotspots(
        by_id=by_id,
        lat=center.latitude,
        lon=center.longitude,
        radius_m=16000,
        private_key=private_key,
        public_key=public_key,
        now=now,
        registry=registry,
    )
    for k, v in by_id.items():
        if id(v) != before_radar_ids.get(k):
            updated_by_id[k] = v

    ctx_key = (str(base_dir), id(_read_json), id(save))
    with _PUBLISH_LOCK:
        shared_by_id = _PUBLISHED_BY_CONTEXT.setdefault(ctx_key, {})
        for k, v in baseline_by_id.items():
            if k not in shared_by_id:
                shared_by_id[k] = v
        for k, v in updated_by_id.items():
            prev = shared_by_id.get(k)
            if prev is not None and _entry_timestamp(prev) > _entry_timestamp(v):
                shared_by_id[k] = merge_entries(v, prev)
            else:
                shared_by_id[k] = merge_entries(prev, v)
        merged_venues = list(shared_by_id.values())
        report = {
            "started_at": now.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "area_polled": center.label,
            "polled_live_count": polled_live_count,
            "polled_weekly_count": polled_weekly_count,
            "radar_discovered_count": radar_added,
            "venues": merged_venues,
        }
        save(base_dir / "report.json", report)
        _inject_besttime_signals_into_snapshot(merged_venues, now)

    radar_requests = max(int(getattr(_RADAR_ATTEMPT, "attempts", 0)), 1 if radar_added > 0 else 0)
    return {
        "ok": True,
        "area": center.label,
        "polled_venues": len(selected_ids) + radar_added,
        "polled_live_requests": polled_live_count,
        "polled_weekly_requests": polled_weekly_count,
        "radar_requests": radar_requests,
        "http_requests_made": polled_live_count + polled_weekly_count + radar_requests,
        "radar_hotspots_found": radar_added,
        "total_cached_venues": len(merged_venues),
        "finished_at": report["finished_at"],
    }


_EXCLUDED_RADAR_TYPES = {
    "GROCERY",
    "SUPERMARKET",
    "GAS_STATION",
    "BANK",
    "POST_OFFICE",
    "PHARMACY",
    "STORAGE",
    "CAR_REPAIR",
    "CAR_DEALER",
    "AUTO_DEALER",
    "CAR_WASH",
    "CAR_RENTAL",
    "PARKING",
    "HARDWARE_STORE",
    "HOME_GOODS_STORE",
    "CEMETERY",
    "GYM",
    "FITNESS_CENTER",
    "DOCTOR",
    "DENTIST",
    "LAUNDRY",
    "INSURANCE_AGENCY",
    "REAL_ESTATE_AGENCY",
}

_EXCLUDED_RADAR_NAMES = (
    "costco",
    "walmart",
    "safeway",
    "fred meyer",
    "qfc",
    "trader joe",
    "whole foods",
    "home depot",
    "lowe's",
    "target",
    "walgreens",
    "rite aid",
    "usps",
    "chick-fil-a",
    "mcdonald's",
    "wendy's",
    "taco bell",
    "burger king",
    "jack in the box",
    "panda express",
    "lexus",
    "toyota",
    "honda",
    "ford",
    "chevrolet",
    "subaru",
    "bmw",
    "mercedes",
    "audi",
    "porsche",
    "nissan",
    "hyundai",
    "kia",
    "mazda",
    "volkswagen",
    "volvo",
    "tesla",
    "dealership",
    "puzzle break",
    "room escape",
)


def _merge_radar_hotspots(
    *,
    by_id: dict[str, dict],
    lat: float,
    lon: float,
    radius_m: int,
    private_key: str,
    public_key: str,
    now: datetime,
    registry: object,
) -> int:
    """Query BestTime GET /api/v1/venues/filter to discover and refresh highest foot-traffic venues now."""
    from farol.besttime_control import reserve_request
    reserve_request()
    local = now.astimezone(PACIFIC)
    day_int = (local.weekday() - (local.hour < 6)) % 7
    idx_now = (local.hour - 6) % 24
    params = {
        "api_key_private": private_key,
        "lat": round(lat, 4),
        "lng": round(lon, 4),
        "radius": radius_m,
        "now": "true",
        "own_venues_only": "false",
        "foot_traffic": "both",
        "limit": 50,
    }
    url = API + "/venues/filter?" + urlencode(params)
    req = Request(url, method="GET", headers={"User-Agent": "rideedge-besttime-radar/1"})
    _RADAR_ATTEMPT.attempts = int(getattr(_RADAR_ATTEMPT, "attempts", 0)) + 1
    try:
        with urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if str(payload.get("status", "")).lower() != "ok":
        return 0

    from calendar import day_name

    # Only skip radar rows that duplicate a curated BESTTIME_UBER_VENUES entry;
    # existing radar_* entries MUST be upserted/refreshed on every scan (R08).
    curated_names = {
        str((item.get("requested") or {}).get("name") or "").strip().lower()
        for key, item in by_id.items()
        if not str(key).startswith("radar_")
    }
    seen_this_scan: set[str] = set()
    upserted = 0
    raw_venues = payload.get("venues") or []

    def _cur_busy(v: dict) -> int:
        if not isinstance(v, dict):
            return 0
        dr = v.get("day_raw_whole", v.get("day_raw"))
        if isinstance(dr, list) and len(dr) == 24 and number(dr[idx_now]) is not None:
            return int(dr[idx_now])
        return 0

    for v in sorted(raw_venues, key=_cur_busy, reverse=True):
        if not isinstance(v, dict):
            continue
        vname = str(v.get("venue_name") or "").strip()
        vaddr = str(v.get("venue_address") or "").strip()
        vtype = str(v.get("venue_type") or "VENUE").upper()
        vlat = v.get("venue_lat")
        vlng = v.get("venue_lng")
        day_raw = v.get("day_raw_whole", v.get("day_raw"))
        if not vname or number(vlat) is None or number(vlng) is None:
            continue
        if not (47 <= vlat <= 48.2 and -123 <= vlng <= -121.5):
            continue
        if not isinstance(day_raw, list) or len(day_raw) != 24:
            continue
        if vtype in _EXCLUDED_RADAR_TYPES:
            continue
        lower_name = vname.lower()
        if any(skip in lower_name for skip in _EXCLUDED_RADAR_NAMES):
            continue
        if lower_name in curated_names or lower_name in seen_this_scan:
            continue

        vid = "radar_" + str(v.get("venue_id") or lower_name.replace(" ", "_"))[:28]
        cur_pct = number(day_raw[idx_now])
        # At 5AM the next 6AM belongs to a different provider day; this receipt
        # cannot supply that curve by wrapping back to yesterday's first value.
        next_pct = number(day_raw[idx_now + 1]) if idx_now < 23 else None
        cur_pct = cur_pct if cur_pct is not None and 0 <= cur_pct <= 100 else None
        next_pct = next_pct if next_pct is not None and 0 <= next_pct <= 100 else None
        if (cur_pct or 0) < 35 and (next_pct or 0) < 45 and vid not in by_id:
            continue

        nearest_zone = min(
            registry.zones,
            key=lambda z: _distance_miles(float(vlat), float(vlng), z.latitude, z.longitude),
        )

        hours_list = []
        for index, val in enumerate(day_raw):
            hr = (index + 6) % 24
            cal_day = (day_int + (index + 6) // 24) % 7
            num_val = number(val)
            num_val = num_val if num_val is not None and 0 <= num_val <= 100 else None
            hours_list.append({
                "hour": hr,
                "weekday": cal_day,
                "label": f"{day_name[cal_day]} {hr:02d}:00",
                "typical_busyness": num_val,
                "closed": None,
            })

        live_val = v.get("venue_live_busyness")
        has_live = (isinstance(live_val, (int, float)) and not isinstance(live_val, bool)
                    and math.isfinite(live_val) and live_val >= 0)

        incoming = {
            "requested": {
                "id": vid,
                "name": vname,
                "address": vaddr,
                "city": nearest_zone.label,
                "area": nearest_zone.label,
                "zone": nearest_zone.id,
                "kind": vtype.lower(),
                "latitude": float(vlat),
                "longitude": float(vlng),
            },
            "identity_matched": True,
            "forecast": {
                "available": True,
                "days_available": 1,
                "days": [
                    {
                        "weekday": day_int,
                        "day": day_name[day_int],
                        "hours": hours_list,
                    }
                ],
                "venue": {
                    "venue_id": v.get("venue_id"),
                    "venue_name": vname,
                    "venue_address": vaddr,
                },
                "retrieved_at": now.isoformat(),
                "basis": "BestTime area radar scan (/venues/filter)",
                "provider_record": sanitize(v),
            },
            "live": {
                "available": has_live,
                "busyness": int(live_val) if has_live else None,
                "typical_this_hour": cur_pct,
                "delta_percentage_points": (int(live_val) - cur_pct) if has_live and cur_pct is not None else None,
                "open_status": None,
                "retrieved_at": now.isoformat(),
                "state": "available" if has_live else "radar_curve",
            },
        }
        by_id[vid] = merge_entries(by_id.get(vid), incoming)
        seen_this_scan.add(lower_name)
        upserted += 1
        if upserted >= 20:
            break
    return upserted


def _is_reading_fresh(retrieved_at: object, now: datetime, max_age_seconds: int = LIVE_SIGNAL_MAX_AGE_SECONDS) -> bool:
    if not retrieved_at or not isinstance(retrieved_at, str):
        return False
    try:
        dt = datetime.fromisoformat(retrieved_at.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        return False
    age = (now.astimezone(UTC) - dt.astimezone(UTC)).total_seconds()
    return -300.0 <= age <= float(max_age_seconds)


def _inject_besttime_signals_into_snapshot(venues_rows: list[dict], now: datetime) -> None:
    from farol.adapters.base import cache_dir

    snap_path = cache_dir() / "awareness_snapshot.json"
    with _PUBLISH_LOCK:
        snap = _read_json(snap_path)
        if not snap:
            return

        local_now = now.astimezone(PACIFIC)
        next_hr = local_now + timedelta(hours=1)
        bt_signals: list[dict] = []

        for row in venues_rows:
            row = review_entry(row)
            if not row["identity_matched"]:
                continue
            req = row.get("requested") or {}
            fc = row.get("forecast") or {}
            lv = row.get("live") or {}

            live_fresh = (row["identity_review"]["live_matched"] and bool(lv.get("available"))
                          and _is_reading_fresh(lv.get("retrieved_at"), now, LIVE_SIGNAL_MAX_AGE_SECONDS))
            current_hour = usable_hour(fc, local_now, now, LIVE_SIGNAL_MAX_AGE_SECONDS)
            fc_fresh = current_hour is not None
            # R08: Do not revive old readings as new current live signals
            if not live_fresh and not fc_fresh:
                continue

            typ_now = lv.get("typical_this_hour") if live_fresh else _typical_for_hour(fc, local_now, now=now)
            if typ_now is None:
                typ_now = _typical_for_hour(fc, local_now, now=now)
            typ_next = _typical_for_hour(fc, next_hr, now=now)
            live_val = lv.get("busyness") if live_fresh else None
            delta = lv.get("delta_percentage_points") if live_fresh else None

            effective_now = live_val if live_val is not None else typ_now
            if effective_now is None:
                continue

            spillout_drop = (effective_now - typ_next) if (typ_next is not None) else 0
            is_surging = (live_val is not None and live_val >= 65) or (delta is not None and delta >= 12)
            is_spillout = effective_now >= 50 and spillout_drop >= 15
            is_busy_hub = effective_now >= 50

            if not (is_surging or is_spillout or is_busy_hub):
                continue

            tags = []
            if live_val is not None:
                tags.append(f"Live {int(live_val)}% busy")
            elif typ_now is not None:
                tags.append(f"Typical {int(typ_now)}% busy")
            if delta is not None and delta != 0:
                sign = "+" if delta > 0 else ""
                tags.append(f"{sign}{int(delta)}% vs normal")
            if is_spillout and typ_next is not None:
                tags.append(f"🚶 Spillout wave ({int(effective_now)}% → {int(typ_next)}% next hr)")

            title = f"BestTime foot traffic at {req.get('name')}: " + " · ".join(tags)
            obs_time = str(lv.get("retrieved_at") if live_fresh else current_hour["retrieved_at"])
            sig = Signal(
                id=f"bt-live-{req.get('id')}-{local_now.strftime('%Y%m%d%H')}",
                kind="special_event",
                zone=str(req.get("zone") or "bellevue_core"),
                starts_at=local_now.isoformat(),
                ends_at=(local_now + timedelta(minutes=75)).isoformat(),
                magnitude=12000.0 if (is_surging and is_spillout) else 9500.0,
                basis="live" if live_val is not None else "scheduled",
                source="besttime:api/v1/forecasts/live",
                fetched_at=obs_time,
                expires_at=(local_now + timedelta(minutes=75)).isoformat(),
                evidence_quality=0.85 if live_val is not None else 0.72,
                details={
                    "title": title,
                    "venue": req.get("name"),
                    "category": "foot_traffic",
                    "live_busyness": live_val,
                    "typical_busyness": typ_now,
                    "spillout_drop": spillout_drop,
                    "notes": (
                        "Live BestTime foot-traffic reading. Elevated live busyness with a dropping next-hour curve indicates patrons leaving."
                        if live_val is not None
                        else "Typical weekly activity curve only (live reading unavailable). Pickup demand is unverified."
                    ),
                },
            )
            bt_signals.append(asdict(sig))

        kept = [
            s for s in (snap.get("signals") or [])
            if not str(s.get("id") or "").startswith("bt-live-")
        ]
        snap["signals"] = kept + bt_signals
        save(snap_path, snap)

