"""Conservative catalog positioning, deliberately distinct from activity evidence."""
from __future__ import annotations

import copy
import math
from datetime import timedelta

from farol import radar

LABEL = "Area to consider · current activity unverified"


def prepare(row, at, generated):
    """Only owned commercial centers; transit/airport/context signals cannot qualify.

    Catalog active hours are a policy window, NOT observed business opening hours.
    Do not turn these areas into six hours of repeated fabricated opportunities.
    """
    centers = {"hub:"+c.id: c for c in radar.load_zones().pickup_centers}
    center = centers.get(row["id"])
    if not center or center.zone == "sea_airport" or not center.staging_spot.strip():
        return None
    lat, lon = row.get("latitude"), row.get("longitude")
    if (not radar.number(lat) or not radar.number(lon) or not 47 <= lat <= 48.2 or not -123 <= lon <= -121.5 or
            radar.distance(lat, lon, center.latitude, center.longitude) > .01):
        return None
    if row.get("closed") is True:
        return None
    # Determine the end of the current catalog policy window using elapsed time,
    # so overnight and daylight-saving transitions do not extend it accidentally.
    def active(t):
        hour = t.astimezone(radar.PACIFIC).hour
        start, end = center.active_start_hour, center.active_end_hour
        return start <= hour < end if start < end else hour >= start or hour < end
    if not active(at):
        return None
    end = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while active(end) and end < at+timedelta(hours=24):
        end += timedelta(hours=1)
    result = copy.deepcopy(row)
    result.update(decision_class="contextual_fallback", strength=LABEL,
                  uncertainty="Current activity and opening hours unverified",
                  hours_status="unknown", context_only=False,
                  fallback_catalog_id=center.id,
                  fallback_expires_at=(generated+timedelta(minutes=20)).isoformat())
    result["evidence"] = [{"id": "positioning:"+center.id, "source": "Local commercial-area catalog",
        "basis": "best guess", "text": "Catalogued commercial area; opening hours and current activity unverified. "
        "Options are ordered by travel, not predicted demand.", "role": "context", "family": "positioning_context",
        "activity_weight": 0, "fetched_at": None, "remaining_minutes": 0,
        "eligible_start": at.isoformat(), "eligible_end": end.isoformat(),
        "expires_at": result["fallback_expires_at"], "hours_status": "unknown",
        "provenance": [{"source": "fixtures/zones.json", "catalog_id": center.id,
                        "active_hours_basis": "authored_policy_not_verified_opening_hours"}]}]
    return result


def feasible(row, route):
    return (row.get("decision_class") == "contextual_fallback" and row.get("arrival_eligible") and
            route.get("feasible") is not False and route.get("status") not in {"unreachable", "no_route"} and
            type(route.get("minutes")) in (int, float) and math.isfinite(route["minutes"]) and
            0 <= route["minutes"] <= 30)


def sort_key(row):
    return row["route"]["minutes"], row["radius_miles"], row["id"]
