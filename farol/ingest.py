import argparse
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from farol.zones import canonical_zone

TIME_FORMAT = "%A, %B %d, %YT%I:%M:%S %p"
LOCAL_TIME = timezone(timedelta(hours=-7), "PDT")


def _number(value: str) -> float:
    cleaned = re.sub(r"[^0-9.-]", "", value or "")
    return float(cleaned or 0)


def _timestamp(value: str) -> datetime:
    # Receipt timestamps explicitly state the seasonal offset. Preserve it when
    # importing past weeks in winter as well as summer, without OS tzdata.
    offset = -8 if "Pacific Standard Time" in value else -7
    label = "PST" if offset == -8 else "PDT"
    return datetime.strptime(
        value.replace(" Pacific Daylight Time", "").replace(" Pacific Standard Time", ""),
        TIME_FORMAT,
    ).replace(tzinfo=timezone(timedelta(hours=offset), label))


_STATE_TOKENS = {"wa", "us", "usa", "washington"}
_CITY_ZONES = {
    "kirkland": "kirkland_waterfront",
    "bellevue": "bellevue_core",
    "redmond": "redmond_downtown",
    "totem lake": "totem_lake",
    "woodinville": "woodinville_wine",
    "cottage lake": "cottage_lake",
    "sammamish": "sammamish",
    "issaquah": "issaquah",
    "bothell": "bothell",
    "kenmore": "kenmore",
    "seatac": "sea_airport",
    "sea tac": "sea_airport",
    "tukwila": "tukwila",
    "renton": "renton",
}


def _city_token(address: str) -> str:
    """City is the last token before WA/US so 'Redmond-Woodinville Rd, Woodinville' is Woodinville."""
    parts = [part.strip().lower() for part in (address or "").split(",") if part.strip()]
    filtered = [part for part in parts if part not in _STATE_TOKENS]
    if not filtered:
        return ""
    return filtered[-1] if len(filtered) > 1 else filtered[0]


def _zone(address: str) -> str:
    text = (address or "").lower()
    city = _city_token(address)
    # R22: Exclude Seattle streets like "Airport Way S" or Boeing Field from sea_airport
    is_sea_terminal = (
        city in {"seatac", "sea tac", "sea-tac"}
        or "seatac" in text
        or "sea-tac" in text
        or "seattle-tacoma international" in text
        or "17801 international" in text
        or ("perimeter rd" in text and "seatac" in text)
        or (
            "airport" in text
            and "airport way" not in text
            and "boeing field" not in text
            and "king county international" not in text
            and city not in {"seattle", "renton", "bellevue", "kirkland", "redmond"}
        )
    )
    if is_sea_terminal:
        return canonical_zone("sea_airport")
    if city in _CITY_ZONES:
        return canonical_zone(_CITY_ZONES[city])
    if city == "seattle" or "seattle" in city:
        if any(token in text for token in ("stone way", "wallingford", "nw 62nd")):
            return canonical_zone("fremont_ballard")
        if any(token in text for token in ("broadway", "nagle pl", "e union", "11th ave e")):
            return canonical_zone("seattle_capitol_hill")
        return canonical_zone("seattle_core")
    if "kirkland" in text:
        return canonical_zone("kirkland_waterfront")
    if "bellevue" in text:
        return canonical_zone("bellevue_core")
    if "woodinville" in text:
        return canonical_zone("woodinville_wine")
    if "cottage lake" in text:
        return canonical_zone("cottage_lake")
    if "redmond" in text:
        return canonical_zone("redmond_downtown")
    if "seattle" in text:
        return canonical_zone("seattle_core")
    return "unknown"


def _col(row: dict, *names: str) -> str:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return ""


def normalize_trip(row: dict, index: int = 1) -> dict | None:
    """Privacy-reduce one WA receipt row. Returns None for footnote lines."""
    try:
        began = _timestamp(row["Request Timestamp"])
    except (TypeError, ValueError, KeyError):
        return None
    duration = _number(row.get("Duration (minutes)", ""))
    ended = began + timedelta(minutes=duration)
    tip = _number(_col(row, "Your earnings.Tip", "Tips", "Your earnings.Tip "))
    uber_kept_raw = _number(row.get("Amount Uber kept", ""))
    return {
        "id": f"observed-{index:02d}",
        "requested_at": began.isoformat(),
        "ended_at": ended.isoformat(),
        "pickup_zone": _zone(row["Pickup Address (street, city, state)"]),
        "dropoff_zone": _zone(row["Dropoff Address (street, city, state)"]),
        "duration_minutes": round(duration, 2),
        "paid_miles": round(_number(row.get("Mileage", "")), 2),
        "seattle_miles": round(_number(row.get("City of Seattle - Distance", "")), 2),
        "washington_miles": round(_number(row.get("Washington State - Distance", "")), 2),
        "seattle_minutes": round(_number(row.get("City of Seattle - Time", "")), 2),
        "washington_minutes": round(
            _number(_col(row, "Washington State  - Time", "Washington State - Time")), 2
        ),
        "wait_minutes": round(_number(row.get("Wait Time at Pickup", "")), 2),
        "earnings": round(_number(row.get("Your earnings", "")), 2),
        "tip": round(tip, 2),
        "customer_fare": round(_number(row.get("Total customer fare", "")), 2),
        "uber_kept": round(abs(uber_kept_raw), 2),
        "minimum_fare_supplement": round(
            _number(row.get("Your earnings.Fare.Minimum Fare Supplement", "")), 2
        ),
        "airport_surcharge": round(
            abs(
                _number(
                    row.get(
                        "Government taxes, third-party fees, and regulatory-related charges.Airport Surcharge",
                        "",
                    )
                )
            ),
            2,
        ),
        "basis": "observed",
    }


def read_wa_trip_receipts(path: Path) -> list[dict]:
    """Read WA exports with or without the report preamble."""
    required = {
        "Request Timestamp",
        "Pickup Address (street, city, state)",
        "Dropoff Address (street, city, state)",
        "Duration (minutes)",
        "Mileage",
        "Your earnings",
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for index, header in enumerate(reader):
            if required.issubset(header):
                return list(csv.DictReader(handle, fieldnames=header))
            if index >= 10:
                break
    raise ValueError("not a recognized Washington trip receipt export")


def observed_shift(
    rows: list[dict],
    start_date: str,
    vehicle_cost_per_mile: float,
    committed_start: str | None = None,
    return_home_minutes: float | None = None,
) -> dict:
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TIME)
    end = start + timedelta(days=1, hours=4)
    selected = []
    for row in rows:
        try:
            requested_at = _timestamp(row["Request Timestamp"])
        except (TypeError, ValueError):
            continue  # Uber appends prose footnotes using the CSV's first column.
        if start <= requested_at < end:
            selected.append(row)
    selected.sort(key=lambda row: _timestamp(row["Request Timestamp"]))
    if not selected:
        raise ValueError(f"no trips found for shift beginning {start_date}")

    trips = []
    previous_end = None
    for index, row in enumerate(selected, 1):
        trip = normalize_trip(row, index)
        if trip is None:
            continue
        began = datetime.fromisoformat(trip["requested_at"])
        ended = datetime.fromisoformat(trip["ended_at"])
        gap = None if previous_end is None else max(0, (began - previous_end).total_seconds() / 60)
        trip["gap_since_previous_trip_minutes"] = None if gap is None else round(gap, 2)
        trips.append(trip)
        previous_end = ended

    first = _timestamp(selected[0]["Request Timestamp"])
    last_end = _timestamp(selected[-1]["Request Timestamp"]) + timedelta(
        minutes=_number(selected[-1]["Duration (minutes)"])
    )
    earnings = sum(trip["earnings"] for trip in trips)
    miles = sum(trip["paid_miles"] for trip in trips)
    duration = sum(trip["duration_minutes"] for trip in trips)
    observed_span = (last_end - first).total_seconds() / 60
    committed_started_at = datetime.fromisoformat(committed_start) if committed_start else first
    if committed_started_at.tzinfo is None:
        committed_started_at = committed_started_at.replace(tzinfo=LOCAL_TIME)
    committed_ended_at = last_end + timedelta(minutes=return_home_minutes or 0)
    committed_minutes = (committed_ended_at - committed_started_at).total_seconds() / 60
    net_paid_mile_lower_bound = earnings - miles * vehicle_cost_per_mile
    return {
        "name": f"Observed Uber trips for shift beginning {start_date}",
        "data_status": "actual",
        "source": "Washington trip receipt export",
        "privacy": "Street addresses reduced to named operating zones during ingest.",
        "limitations": [
            "The export does not contain leave-home, app-online, or return-home times.",
            "Off-app reposition and deadhead miles are not present.",
            "Gaps are unobserved intervals, not automatically classified as silence.",
            "Only the driver's chosen path is observed; alternative policies are counterfactual.",
        ],
        "observed_span": {
            "first_request_at": first.isoformat(),
            "last_trip_ended_at": last_end.isoformat(),
            "minutes": round(observed_span, 2),
        },
        "committed_window": {
            "started_at": committed_started_at.isoformat(),
            "ended_at": committed_ended_at.isoformat(),
            "minutes": round(committed_minutes, 2),
            "start_basis": "driver_reported" if committed_start else "first_request_proxy",
            "end_basis": "driver_reported_return_duration" if return_home_minutes is not None else "last_dropoff_proxy",
            "return_home_minutes": return_home_minutes,
        },
        "summary": {
            "trips": len(trips),
            "earnings": round(earnings, 2),
            "tips_included": round(sum(trip["tip"] for trip in trips), 2),
            "on_trip_minutes": round(duration, 2),
            "paid_miles": round(miles, 2),
            "paid_mile_vehicle_cost": round(miles * vehicle_cost_per_mile, 2),
            "net_after_paid_mile_cost_lower_bound": round(net_paid_mile_lower_bound, 2),
            "earnings_per_observed_span_hour": round(earnings * 60 / observed_span, 2),
            "net_per_observed_span_hour_lower_bound": round(
                net_paid_mile_lower_bound * 60 / observed_span, 2
            ),
            "net_per_committed_hour_lower_bound": round(
                net_paid_mile_lower_bound * 60 / committed_minutes, 2
            ),
        },
        "trips": trips,
    }


def parse_export(path: Path) -> list[dict]:
    """All privacy-reduced trips from one WA receipt CSV."""
    trips = []
    for index, row in enumerate(read_wa_trip_receipts(path), 1):
        trip = normalize_trip(row, index)
        if trip is None:
            continue
        trip["source_file"] = path.name
        trips.append(trip)
    trips.sort(key=lambda item: item["requested_at"])
    previous_end = None
    for index, trip in enumerate(trips, 1):
        trip["id"] = f"observed-{index:02d}"
        began = datetime.fromisoformat(trip["requested_at"])
        ended = datetime.fromisoformat(trip["ended_at"])
        gap = None if previous_end is None else max(0, (began - previous_end).total_seconds() / 60)
        trip["gap_since_previous_trip_minutes"] = None if gap is None else round(gap, 2)
        previous_end = ended
    return trips


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize an Uber WA trip receipt export")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--date", required=True, help="shift start date, YYYY-MM-DD")
    parser.add_argument("--vehicle-cost", type=float, default=0.45)
    parser.add_argument("--committed-start", help="local ISO timestamp, e.g. 2026-08-07T13:30:00")
    parser.add_argument("--return-home-minutes", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = observed_shift(
        read_wa_trip_receipts(args.csv),
        args.date,
        args.vehicle_cost,
        args.committed_start,
        args.return_home_minutes,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
