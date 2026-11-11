"""Normalize BestTime filter receipts without confusing live windows and daily curves.

Pure parser: no requests, scoring, or writes. Raw receipts remain the source of truth.
"""

from __future__ import annotations

from farol.besttime import number, successful


def normalize_filter(receipt: dict, receipt_id: str) -> dict:
    payload = receipt.get("payload") or {}
    params = receipt.get("parameters") or {}
    live_query = str(params.get("live", "false")).lower() == "true"
    window = payload.get("window") or {}
    index = window.get("time_local_index")
    valid_index = type(index) is int and 0 <= index < 24
    result = {
        "state": "available" if successful(receipt) else "unavailable",
        "retrieved_at": receipt.get("retrieved_at"),
        "venues": [],
        "limit": params.get("limit"),
        "returned": 0,
        "possibly_truncated": False,
        "notes": [
            "Sample counts are not population or a complete venue inventory.",
            "Percentages are relative to each venue's own weekly peak.",
            "Retrieval time is not an underlying measurement timestamp.",
        ],
    }
    if not successful(receipt):
        return result
    venues = payload.get("venues")
    if not isinstance(venues, list):
        result["state"] = "unavailable"
        return result
    result["returned"] = len(venues)
    result["possibly_truncated"] = (
        type(params.get("limit")) is int and len(venues) >= params["limit"]
    )
    for offset, raw in enumerate(venues):
        if not isinstance(raw, dict):
            continue
        lat, lon = number(raw.get("venue_lat")), number(raw.get("venue_lng"))
        if not (
            raw.get("venue_id")
            and raw.get("venue_name")
            and lat is not None
            and lon is not None
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            continue
        whole = raw.get("day_raw_whole")
        curve_field = "day_raw_whole"
        # A full daily forecast is accepted only on a forecast query. Never turn
        # a multi-hour live window into a historical daily curve.
        if not isinstance(whole, list) or len(whole) != 24:
            whole, curve_field = (raw.get("day_raw"), "day_raw") if not live_query else (None, None)
        curve = (
            [number(v) if number(v) is not None and 0 <= v <= 100 else None for v in whole]
            if isinstance(whole, list) and len(whole) == 24
            else None
        )
        live_raw = raw.get("day_raw")
        value = (
            number(live_raw[0])
            if live_query and isinstance(live_raw, list) and len(live_raw) == 1
            else None
        )
        value = value if value is not None and value >= 0 else None
        prefix = f"payload.venues[{offset}]"
        provenance = {
            "identity": {"receipt": receipt_id, "field": prefix},
            "live": {"receipt": receipt_id, "field": prefix + ".day_raw[0]"}
            if value is not None
            else None,
            "typical": {"receipt": receipt_id, "field": prefix + "." + curve_field}
            if curve is not None
            else None,
        }
        result["venues"].append(
            {
                "id": str(raw["venue_id"]),
                "name": raw["venue_name"],
                "address": raw.get("venue_address"),
                "type": raw.get("venue_type"),
                "latitude": lat,
                "longitude": lon,
                "live_percent": value,
                "typical_day": curve,
                "typical_now": curve[index] if curve is not None and valid_index else None,
                "day_int": (raw.get("day_info") or {}).get("day_int", raw.get("day_int")),
                "time_local_index": index if valid_index else None,
                "open_status": None,  # zero activity does not establish closure
                "opening_periods": (raw.get("day_info") or {}).get("venue_open_close_v2"),
                "measurement_time": None,
                "retrieved_at": receipt.get("retrieved_at"),
                "provenance": provenance,
            }
        )
    return result
