"""BestTime normalization, retained identity review, and bounded evaluation client.

The evaluation client persists attempts before sending and never retries
automatically: a timeout may still have been charged by the provider. Pure
normalization and identity helpers are also used by the production collector.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from calendar import day_name
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://besttime.app/api/v1"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize(value: object, secrets: tuple[str, ...] = ()) -> object:
    text = json.dumps(value, ensure_ascii=False)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "REDACTED")
    text = re.sub(r"(?:pri|pub)_[a-zA-Z0-9_-]+", "REDACTED", text)
    return json.loads(text)


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class BudgetExceeded(RuntimeError):
    pass


class BestTimeClient:
    def __init__(self, private: str, public: str, directory: Path, budget: int = 24):
        if not private or not public:
            raise ValueError("Set BESTTIME_API_KEY_PRIVATE and BESTTIME_API_KEY_PUBLIC in .env")
        if not 1 <= budget <= 24:
            raise ValueError("Pilot budget must be between 1 and 24 forecast credits")
        self.private, self.public = private, public
        self.directory, self.budget = directory, budget

    def _request(self, method: str, endpoint: str, params: dict | None = None) -> dict:
        from farol.besttime_control import reserve_request
        reserve_request()
        url = API + endpoint
        if params is not None:
            url += "?" + urlencode({"api_key_private": self.private, **params})
        request = Request(url, method=method, headers={"User-Agent": "farol-besttime-pilot/1"})
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.load(response)
                code = response.status
        except HTTPError as error:
            code = error.code
            try:
                payload = json.loads(error.read())
            except (ValueError, OSError):
                payload = {"status": "Error", "message": "Non-JSON HTTP error"}
        except (URLError, OSError, ValueError):
            # Exception strings may contain the credential-bearing URL.
            return {"http_status": None, "payload": {}, "error": "Transport or JSON error"}
        if not isinstance(payload, dict):
            return {"http_status": code, "payload": {}, "error": "Unexpected response schema"}
        return sanitize({"http_status": code, "payload": payload}, (self.private, self.public))

    def key_status(self) -> dict:
        # Never persist this URL or the raw key-validation response.
        result = self._request("GET", "/keys/" + self.private)
        payload = result["payload"]
        return {"retrieved_at": now(), "http_status": result["http_status"], **{
            key: payload.get(key)
            for key in ("status", "valid", "active", "credits_forecast", "credits_query")
        }}

    def attempts(self) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((self.directory / "requests").glob("*.json"))]

    def fetch(self, venue_key: str, kind: str, params: dict) -> dict:
        if kind not in {"forecast", "live"} or not re.fullmatch(r"[a-z0-9_]+", venue_key):
            raise ValueError("Invalid pilot request")
        path = self.directory / "requests" / f"{venue_key}.{kind}.json"
        if path.exists():
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt["parameters"] != params:
                raise ValueError("Existing receipt belongs to different request parameters")
            return receipt
        reserve = 2 if kind == "forecast" else 1
        if sum(item["reserved_credits"] for item in self.attempts()) + reserve > self.budget:
            raise BudgetExceeded("Pilot forecast-credit cap reached")
        receipt = {"venue_key": venue_key, "kind": kind, "parameters": params,
                   "reserved_credits": reserve, "requested_at": now(), "state": "pending"}
        save(path, receipt)
        result = self._request("POST", "/forecasts" + ("/live" if kind == "live" else ""), params)
        receipt.update(result)
        receipt.update(retrieved_at=now(), state="completed")
        save(path, receipt)
        return receipt


def number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def successful(receipt: dict) -> bool:
    return (receipt.get("http_status") == 200
            and str(receipt.get("payload", {}).get("status", "")).lower() == "ok")


def venue_match(requested: dict, info: dict) -> bool:
    """Conservative identity check: name tokens, street number, and city/coordinates."""
    def tokens(value):
        return set(re.findall(r"[a-z0-9]+", value.lower())) - {"the", "and", "bar", "cafe"}

    if not all(isinstance(requested.get(k), str) and requested[k].strip() for k in ("name", "address", "city")):
        return False
    names = tokens(requested["name"])
    matched_names = tokens(str(info.get("venue_name", "")))
    address = str(info.get("venue_address", ""))
    street = re.match(r"\d+", requested["address"])
    if not names.intersection(matched_names) or not street:
        return False
    if re.match(r"\d+", address) is None or not address.startswith(street.group() + " "):
        return False
    if requested["city"].lower() not in address.lower():
        return False
    if "latitude" in requested:
        if number(requested.get("latitude")) is None or number(requested.get("longitude")) is None:
            return False
        lat, lon = number(info.get("venue_lat")), number(info.get("venue_lon"))
        if lon is None:
            lon = number(info.get("venue_lng"))
        if lat is None or lon is None:
            return False
        distance = math.hypot((lat - requested["latitude"]) * 111_000,
                              (lon - requested["longitude"]) * 75_000)
        if distance > 300:
            return False
    return True


def review_entry(entry: dict) -> dict:
    """Revalidate retained venue identity without rewriting raw reports or readings."""
    import copy

    checked = copy.deepcopy(entry)
    requested = checked.get("requested") or {}
    forecast = checked.get("forecast") or {}
    live = checked.get("live") or {}
    info = forecast.get("venue") or {}
    provider_id = info.get("venue_id")
    direct = forecast.get("basis") == "BestTime area radar scan (/venues/filter)"
    if direct:
        # Area results are self-contained provider places, not matches to our curated catalog.
        matched = bool(provider_id and requested.get("id") == "radar_" + str(provider_id)[:28]
                       and requested.get("name")
                       and requested.get("name") == info.get("venue_name")
                       and requested.get("address") == info.get("venue_address")
                       and number(requested.get("latitude")) is not None
                       and number(requested.get("longitude")) is not None
                       and 47 <= requested["latitude"] <= 48.2
                       and -123 <= requested["longitude"] <= -121.5)
        live_matched = matched  # Reading and location came from the same provider row.
        method = "provider-area-row"
    else:
        matched = bool(provider_id and venue_match(requested, info))
        live_matched = bool(matched and live.get("venue_id") == provider_id
                            and live.get("identity_matched") is True)
        method = "curated-name-address-coordinates-and-provider-id"
    previous = checked.get("identity_review") or {}
    checked["identity_review"] = {
        "method": method, "reported_identity_matched": previous.get("reported_identity_matched", entry.get("identity_matched")),
        "forecast_matched": matched, "live_matched": live_matched,
        "note": ("Identity checked against retained provider metadata."
                 if matched and live_matched else "Live venue identity is unverified; only a matched weekly pattern may be used."
                 if matched else "Venue identity is unverified; excluded from recommendations."),
    }
    checked["identity_matched"] = matched
    return checked


def normalize_forecast(receipt: dict) -> dict:
    payload = receipt.get("payload", {})
    info = payload.get("venue_info") or {}
    days = []
    analysis = payload.get("analysis")
    if successful(receipt) and isinstance(analysis, list):
        for day in analysis:
            details = day.get("day_info") or {}
            weekday = details.get("day_int")
            raw = day.get("day_raw")
            if type(weekday) is not int or not 0 <= weekday <= 6:
                continue
            if not isinstance(raw, list) or len(raw) != 24:
                continue
            intensities = {item.get("hour"): item for item in day.get("hour_analysis", [])}
            hours = []
            for index, value in enumerate(raw):
                hour = (index + 6) % 24
                calendar_day = (weekday + (index + 6) // 24) % 7
                intensity = intensities.get(hour, {})
                value = number(value)
                hours.append({
                    "hour": hour, "weekday": calendar_day,
                    "label": f"{day_name[calendar_day]} {hour:02d}:00",
                    "typical_busyness": value if value is not None and 0 <= value <= 100 else None,
                    "closed": (intensity["intensity_nr"] == 999
                               if "intensity_nr" in intensity else None),
                })
            days.append({"weekday": weekday, "day": day_name[weekday], "hours": hours,
                         "opening_hours": details.get("venue_open_close_v2"),
                         "estimated_surge_hours": day.get("surge_hours")})
    return {"available": bool(days), "days_available": len(days), "days": days,
            "venue": info, "retrieved_at": receipt.get("retrieved_at"),
            "provider_analysis_time": payload.get("epoch_analysis"),
            "provider_message": payload.get("message"),
            "basis": "historical typical week; not a prediction of this specific date"}


def normalize_live(receipt: dict, expected_id: str) -> dict:
    payload = receipt.get("payload", {})
    analysis = payload.get("analysis") or {}
    if not isinstance(analysis, dict):
        analysis = {}
    info = payload.get("venue_info") or {}
    identity = bool(expected_id) and info.get("venue_id") == expected_id
    # Observed API behavior: HTTP 200 / status Error for an ordinary missing
    # live reading, with valid opening hours and an explicitly available baseline.
    no_live = (receipt.get("http_status") == 200 and identity
               and payload.get("message") == "No live data available."
               and analysis.get("venue_live_busyness_available") is False)
    valid = successful(receipt) and identity
    metadata_valid = valid or no_live
    live = number(analysis.get("venue_live_busyness"))
    forecast = number(analysis.get("venue_forecasted_busyness"))
    live_available = (valid and analysis.get("venue_live_busyness_available") is True
                      and live is not None and live >= 0)
    baseline_available = (metadata_valid
                          and analysis.get("venue_forecast_busyness_available") is True
                          and forecast is not None and 0 <= forecast <= 100)
    return {
        "venue_id": info.get("venue_id"), "identity_matched": identity,
        "available": live_available,
        "busyness": live if live_available else None,
        "typical_this_hour": forecast if baseline_available else None,
        "delta_percentage_points": live - forecast if live_available and baseline_available else None,
        "open_status": info.get("venue_open") if metadata_valid else None,
        "hour_start": analysis.get("hour_start") if metadata_valid else None,
        "timezone": info.get("venue_timezone"),
        "provider_current_localtime": info.get("venue_current_localtime"),
        "retrieved_at": receipt.get("retrieved_at"),
        "measurement_time": None,
        "note": "Provider current time is not a documented measurement timestamp.",
        "state": ("available" if live_available else "unavailable"
                  if metadata_valid else "request_failed"),
    }
