"""Published Redmond community calendars, with venue and daily date boundaries."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup

from farol.community_events import PACIFIC, SOURCES, safe_url
from farol.event_sources import (
    ParseError,
    classify,
    clean,
    clock_range,
    date_span,
    days,
    occurrence,
)
from farol.zones import load_zones

PARK_FIELDS = ":id,event_name,start_time,end_time,location_name,location,location_address,location_city,location_state,event_description_details,url"


def redmond_location(venue: str, address="", *, coords=None) -> dict:
    # Marymoor Village's community center is a different venue from Marymoor Park.
    park = bool(re.search(r"\bmarymoor park\b", venue, re.IGNORECASE))
    zone = "marymoor" if park else "redmond_downtown"
    center = load_zones().by_id[zone]
    mapped = park or bool(address) or venue.lower() not in {"", "redmond", "event location", "tbd", "tba"}
    lat, lon = coords if coords else (center.latitude, center.longitude) if mapped else (None, None)
    return {"city": "Redmond", "zone": zone if mapped else None,
            "neighborhood": "Marymoor Park · Redmond" if park else "Redmond",
            "lat": lat, "lon": lon, "location_precision": "venue" if coords else "area" if mapped else "unknown"}


def local_stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    return stamp.replace(tzinfo=PACIFIC) if stamp.tzinfo is None else stamp.astimezone(PACIFIC)


def city_events(html: str, first: date, last: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select('[itemtype="http://schema.org/Event"], [itemtype="https://schema.org/Event"]')
    if not blocks and not soup.select_one('input[name="chkCalendarID"][value="22"]'):
        raise ParseError("Redmond community calendar layout changed")
    output = []
    for block in blocks:
        parent = block.find_parent("li")
        anchor = parent.select_one('h3 a[href*="EID="]') if parent else None
        start_tag = block.select_one('[itemprop="startDate"]')
        title_tag = block.select_one('[itemprop="name"]')
        if not anchor or not start_tag or not title_tag:
            raise ParseError("Redmond event is missing identity or date")
        ident = parse_qs(urlsplit(anchor["href"]).query)["EID"][0]
        start = local_stamp(start_tag.get("content") or start_tag.get_text(strip=True))
        day = start.date()
        if not first <= day <= last:
            continue
        place = block.select_one('[itemprop="location"]')
        def field(name, place=place):
            tag = place.select_one(f'[itemprop="{name}"]') if place else None
            return clean(tag.get_text(" ", strip=True)) if tag else ""
        if field("addressLocality").lower() != "redmond":
            continue
        title, venue, address = clean(title_tag.get_text()), field("name"), field("streetAddress")
        if re.search(r"\b(online|virtual|webinar)\b", venue, re.IGNORECASE):
            continue
        visible_date = parent.select_one(".date")
        published = clean(visible_date.get_text()) if visible_date else ""
        hours = clock_range(published)
        row = occurrence("redmond_city", ident, title, day,
                         "https://www.redmond.gov/Calendar.aspx?EID=" + ident,
                         venue=venue, address=address, hours=hours, category=classify(title),
                         evidence=published)
        row.update(redmond_location(venue, address))
        # Preserve a published start with an unknown end; midnight has no implied
        # meaning if the source has not given hours in its visible schedule.
        if hours and datetime.fromisoformat(row["starts_at"]) != start:
            row.update(starts_at=None, ends_at=None,
                       schedule_warnings=["Calendar start and displayed hours disagree; verify with the city."])
        elif not hours and start.time() != time():
            row.update(starts_at=start.isoformat(), timing_basis="published start; end unknown")
        if re.search(r"\bcancel(?:l)?ed\b", title, re.IGNORECASE):
            row["status"] = "canceled"
        output.append(row)
    return output


def park_events(payload, first: date, last: date) -> list[dict]:
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ParseError("King County parks calendar did not return an event list")
    output = []
    for item in payload:
        venue, city = clean(item.get("location_name")), clean(item.get("location_city"))
        if city.lower() != "redmond" or not venue:
            continue  # This extension is Redmond/Marymoor, not every county service.
        start, end = local_stamp(item["start_time"]), local_stamp(item["end_time"])
        if end < start:
            raise ParseError("King County event contains reversed dates")
        description = clean(item.get("event_description_details"))
        final_day = end.date() - timedelta(days=1) if end.time() == time() and end.date() > start.date() else end.date()
        described = date_span(description, year=start.year)
        warnings = []
        # A date range explicitly starting on this occurrence's first day may
        # identify additional days missing from the calendar timestamp. Preserve
        # that evidence with a warning and no invented daily opening/closing time.
        if described and described[0] == start.date() and described[1] > final_day:
            warnings.append("Calendar end date differs from the published description; verify daily hours.")
            final_day = described[1]
        coords = None
        geometry = item.get("location") or {}
        if geometry.get("type") == "Point" and len(geometry.get("coordinates", [])) == 2:
            lon, lat = geometry["coordinates"]
            coords = float(lat), float(lon)
        title = clean(item["event_name"])
        ident = item[":id"]
        # The source row ID survives time changes. Daily suffixes remain stable
        # within a multi-day occurrence, including when its final day changes.
        for index, day in enumerate(days(start.date(), final_day)):
            if not first <= day <= last:
                continue
            row = occurrence("king_county_parks", f"{ident}:{index}", title, day,
                             SOURCES["king_county_parks"]["url"], venue=venue,
                             address=clean(item.get("location_address")), category=classify(title),
                             organizer_url=safe_url(item.get("url")), evidence=description,
                             schedule_warnings=warnings,
                             notes="Multi-day listing; daily hours unconfirmed." if start.date() != final_day else "")
            row.update(redmond_location(venue, item.get("location_address", ""), coords=coords))
            if start.date() == final_day and not warnings and end > start and not (start.time() == end.time() == time()):
                row.update(starts_at=start.isoformat(), ends_at=end.isoformat(), timing_basis="published calendar hours")
            if re.search(r"\bcancel(?:l)?ed\b", title, re.IGNORECASE):
                row["status"] = "canceled"
            output.append(row)
    return output


def collect_redmond_source(source: str, fetch, first: date, last: date):
    if source == "king_county_parks":
        # A lookback includes multi-day gatherings that began before today's
        # date, including records whose end timestamp disagrees with their text.
        query = {"$select": PARK_FIELDS, "$where":
                 f"parks=true AND start_time >= '{first - timedelta(days=31)}T00:00:00' "
                 f"AND start_time < '{last + timedelta(days=1)}T00:00:00'",
                 "$order": "start_time,:id", "$limit": 500}
        payload = json.loads(fetch("https://data.kingcounty.gov/resource/grxi-zqg2.json?" + urlencode(query)))
        rows = park_events(payload, first, last)
        return rows, ["Parks calendar reached its 500-event bound"] if len(payload) >= 500 else []
    if source != "redmond_city":
        raise ParseError("Unknown Redmond source")
    rows, errors = [], []
    for year, month in sorted({(day.year, day.month) for day in days(first, last)}):
        for category in (22, 39):  # Community Events and Welcoming Week, not council meetings.
            url = "https://www.redmond.gov/calendar.aspx?" + urlencode(
                {"CID": category, "month": month, "year": year, "view": "list"})
            try:
                rows.extend(city_events(fetch(url), first, last))
            except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                errors.append(f"{year}-{month:02d} category {category}: {type(error).__name__}: {str(error)[:150]}")
    # The same event can be published under both calendar categories.
    return list({row["source_key"]: row for row in rows}.values()), errors
