"""Small, source-specific readers for Seattle community calendars.

Only published facts become dates or hours. Unrecognized layouts fail visibly;
date-only listings remain useful context without pretending to know a let-out.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from farol.community_events import PACIFIC, safe_url, slug
from farol.zones import load_zones

MONTHS = {name: index for index, names in enumerate([
    (), ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
    ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
    ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"),
    ("december", "dec")]) for name in names}
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?"
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY = r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b"
CLOCK_RANGE = re.compile(r"(?<!\d)(\d{1,2}(?::\d{2})?)\s*(a\.?m\.?|p\.?m\.?)?\s*(?:-|–|—|to)\s*(\d{1,2}(?::\d{2})?)\s*(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE)
MARKETS = {"udfm": ("University District", "uw_district"), "wsfm": ("West Seattle", "west_seattle"),
           "chfm": ("Capitol Hill", "capitol_hill"), "ccfm": ("Columbia City", "columbia_city"),
           "lcfm": ("Lake City", "lake_city"), "pfm": ("Phinney", "phinney_greenwood"),
           "mfm": ("Magnolia", "magnolia")}
NEIGHBORHOODS = {
    "seattle center": "seattle_center", "queen anne": "seattle_center", "uptown": "seattle_center",
    "capitol hill": "capitol_hill", "university district": "uw_district", "montlake": "uw_district",
    "u district": "uw_district", "belltown": "belltown", "waterfront": "belltown",
    "ballard": "fremont_ballard", "fremont": "fremont_ballard", "wallingford": "fremont_ballard",
    "green lake": "phinney_greenwood", "phinney": "phinney_greenwood", "greenwood": "phinney_greenwood",
    "west seattle": "west_seattle", "delridge": "west_seattle", "columbia city": "columbia_city",
    "rainier beach": "rainier_beach", "seward park": "rainier_beach", "rainier valley": "columbia_city",
    "lake city": "lake_city", "northgate": "northgate", "licton springs": "northgate",
    "magnolia": "magnolia", "interbay": "interbay", "beacon hill": "beacon_hill",
    "central district": "central_district", "central area": "central_district",
    "georgetown": "georgetown", "south park": "georgetown", "sodo": "sodo_stadiums",
    "pioneer square": "seattle_core", "international district": "seattle_core",
    "downtown": "seattle_core", "pike place": "seattle_core", "south lake union": "seattle_core",
}


class ParseError(ValueError):
    pass


def clean(value) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)).strip()


def days(first: date, last: date):
    if not 0 <= (last - first).days <= 366:
        raise ParseError("Event date range is not bounded")
    while first <= last:
        yield first
        first += timedelta(days=1)


def date_span(text: str, *, year: int | None = None) -> tuple[date, date] | None:
    numeric = re.findall(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if numeric:
        parsed = [date(int(y), int(m), int(d)) for m, d, y in numeric]
        return parsed[0], parsed[-1]
    pattern = rf"\b({MONTH})\s+(\d{{1,2}})(?:\s*(?:-|–|—|through|to)\s*(?:({MONTH})\s+)?(\d{{1,2}}))?(?:,?\s+(20\d{{2}}))?"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match or not (match[5] or year):
        return None
    m1, d1, m2, d2, explicit = match.groups()
    first = date(int(explicit or year), MONTHS[m1.lower().rstrip(".")], int(d1))
    last = date(first.year, MONTHS[(m2 or m1).lower().rstrip(".")], int(d2 or d1))
    return first, last


def clock(text: str, marker: str) -> time:
    h, *m = text.split(":")
    hour, minute = int(h), int(m[0]) if m else 0
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise ParseError("Unrecognized event clock")
    return time(hour % 12 + (12 if marker.lower().startswith("p") else 0), minute)


def clock_range(text: str) -> tuple[time, time] | None:
    match = CLOCK_RANGE.search(text)
    if not match:
        return None
    left, marker, right, end_marker = match.groups()
    start, end = clock(left, marker or end_marker), clock(right, end_marker)
    if not marker and start >= end and start.hour >= 12:
        start = time(start.hour - 12, start.minute)
    if start == end:
        raise ParseError("Equal opening and closing times")
    return start, end


def timed(day: date, hours) -> tuple[str | None, str | None]:
    if not hours:
        return None, None
    start, end = (datetime.combine(day, value, PACIFIC) for value in hours)
    if end <= start:
        end += timedelta(days=1)
    return start.isoformat(), end.isoformat()


def location(venue: str, neighborhood="", *, coords=None) -> dict:
    # Venue names outrank calendar audience tags (some entries tag every city
    # neighborhood). Never let a long tag list move a Ballard venue to Phinney.
    venue_matches = [(label, zone) for label, zone in NEIGHBORHOODS.items() if label in venue.lower()]
    tags = [part.strip() for part in neighborhood.split(",") if part.strip()]
    tag_matches = [(label, zone) for tag in tags[:3] for label, zone in NEIGHBORHOODS.items()
                   if label in tag.lower()] if len(tags) <= 4 else []
    picked = max(venue_matches, key=lambda pair: len(pair[0]), default=None) or next(iter(tag_matches), None)
    zone = picked[1] if picked else None
    registry = load_zones().by_id
    point = registry.get(zone)
    if coords:
        lat, lon = coords
        precision = "venue"
    elif point:
        lat, lon, precision = point.latitude, point.longitude, "area"
    else:
        lat, lon, precision = None, None, "unknown"
    return {"city": "Seattle", "zone": zone,
            "neighborhood": picked[0].title() if picked else "Seattle · area unconfirmed",
            "lat": lat, "lon": lon, "location_precision": precision}


def occurrence(source: str, key: str, title: str, day: date, url: str, *, venue="",
               neighborhood="", hours=None, category="community", coords=None, **extra):
    starts, ends = timed(day, hours)
    return {"source_id": source, "source_key": key, "title": clean(title),
            "local_date": day.isoformat(), "starts_at": starts, "ends_at": ends,
            "status": "scheduled", "category": category, "source_url": url,
            "venue": venue, "venue_key": slug(venue),
            "timing_basis": "published daily hours" if hours else "published date; daily hours unknown",
            **location(venue, neighborhood, coords=coords), **extra}


def classify(text: str) -> str:
    text = text.lower()
    if "farmers market" in text or "farmers markets" in text:
        return "farmers_market"
    if "market" in text or "bazaar" in text:
        return "market"
    if any(word in text for word in ("festival", "festál", "festal", "fiesta", "fair")):
        return "festival"
    if any(word in text for word in ("run", "walk", "race")):
        return "community_activity"
    return "community"


def trumba_events(payload, first: date, last: date) -> list[dict]:
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ParseError("Neighborhood calendar did not return an event list")
    result = []
    for item in payload:
        if item.get("locationType", "").lower() in {"online", "virtual"}:
            continue
        fields = {field.get("label"): clean(field.get("value")) for field in item.get("customFields", [])}
        neighborhood = fields.get("Neighborhoods", "")
        venue = clean(item.get("location"))
        if not venue or ("seattle" not in venue.lower() and not any(n in neighborhood.lower() for n in NEIGHBORHOODS)):
            continue
        if re.search(r"\b(Bellevue|Redmond|Kirkland|Tacoma|Bothell|Everett)\b", venue, re.IGNORECASE):
            continue
        if re.search(r"(?:commission|council|board|committee).*\bmeeting\b", item["title"], re.IGNORECASE):
            continue
        if any(term in (fields.get("Event Types", "") + " " + venue).lower()
               for term in ("public meeting", "board meeting", "virtual meeting", "zoom.us", "webinar")):
            continue
        def stamp(key, offset, item=item):
            value = datetime.fromisoformat(item[key])
            if value.tzinfo is None:
                supplied = item.get(offset)
                value = datetime.fromisoformat(item[key] + supplied) if supplied else value.replace(tzinfo=PACIFIC)
            return value.astimezone(PACIFIC)
        begins = stamp("startDateTime", "startTimeZoneOffset")
        ends = stamp("endDateTime", "endTimeZoneOffset")
        if ends < begins:
            raise ParseError("Neighborhood calendar contains reversed hours")
        final_day = ends.date() - timedelta(days=1) if ends.time() == time() and ends.date() > begins.date() else ends.date()
        for index, day in enumerate(days(begins.date(), final_day)):
            if not first <= day <= last:
                continue
            all_day = item.get("allDay") or begins.date() != ends.date()
            row = occurrence("neighborhoods", str(item["eventID"]) + (f":{index}" if begins.date() != final_day else ""),
                             item["title"], day, item["permaLinkUrl"], venue=venue,
                             neighborhood=neighborhood, category=classify(item["title"] + " " + fields.get("Event Types", "")),
                             organizer=fields.get("Sponsoring Organization", ""),
                             evidence=item.get("dateTimeFormatted", ""),
                             organizer_url=safe_url(item.get("webLink")))
            if not all_day:
                row.update(starts_at=begins.isoformat(), ends_at=ends.isoformat(), timing_basis="published calendar hours")
            if item.get("canceled"):
                row["status"] = "canceled"
            result.append(row)
    return result


def festal_index(html: str, first: date, last: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".fifty-fifty")
    if not cards:
        raise ParseError("Seattle Center festival index layout changed")
    rows = []
    for card in cards:
        anchor = card.select_one("h2 a[href]")
        when = card.select_one(".fifty-fifty__content b")
        if not anchor or not when:
            continue
        span = date_span(when.get_text(" ", strip=True))
        if not span or span[1] < first or span[0] > last:
            continue
        rows.append({"title": anchor.get_text(" ", strip=True), "first": span[0], "last": span[1],
                     "url": urljoin("https://www.seattlecenter.com", anchor["href"]),
                     "evidence": when.get_text(" ", strip=True)})
    return rows


def festal_detail(item: dict, html: str, first: date, last: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    intro = next((p.get_text(" ", strip=True) for p in soup.find_all("p")
                  if item["title"].lower() in p.get_text(" ", strip=True).lower()
                  and re.search(r"\bis\b|\bwill take place\b|\btakes place\b", p.get_text(), re.IGNORECASE)), "")
    if not intro:
        raise ParseError("Festival page has no recognizable current introduction")
    result = []
    for day in days(max(first, item["first"]), min(last, item["last"])):
        # Per-day hours take precedence. Never reuse Saturday's close on Sunday.
        prefix = rf"{MONTH}\s+{day.day}(?!\d)\s*:"
        segment = re.search(prefix + rf"(.*?)(?=&\s*{MONTH}|\b{MONTH}\s+\d|$)", intro, re.IGNORECASE)
        hours = clock_range(segment[1]) if segment else None
        if hours is None and not re.search(rf"{MONTH}\s+\d{{1,2}}\s*:", intro, re.IGNORECASE):
            hours = clock_range(intro)
        row = occurrence("seattle_center", item["url"] + ":" + day.isoformat(), item["title"],
                         day, item["url"], venue="Seattle Center", neighborhood="Seattle Center",
                         hours=hours, category="festival", evidence=item["evidence"] + ". " + intro,
                         venue_key="seattlecenter")
        if re.search(r"\b(cancelled|canceled)\b", intro, re.IGNORECASE):
            row["status"] = "canceled"
        result.append(row)
    return result


def map_coordinates(soup) -> tuple[float, float] | None:
    for a in soup.select('a[href*="google.com/maps"]'):
        # @lat,lon is only a camera viewport. !3d,!4d identifies the venue pin.
        match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", a["href"])
        if match:
            return float(match[1]), float(match[2])
    return None


def market_events(key: str, html: str, first: date, last: date) -> list[dict]:
    name, zone = MARKETS[key]
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("main")
    if not body:
        raise ParseError("Market page layout changed")
    intro = body.get_text(" ", strip=True).split("Market Events", 1)[0]
    if name.lower() not in intro.lower() or len(intro) > 1400:
        raise ParseError("Market schedule heading is missing")
    segments = list(re.finditer(WEEKDAY, intro, re.IGNORECASE))
    if not segments:
        raise ParseError("Market schedule has no weekday")
    coords = map_coordinates(body)
    result, found = [], 0
    for index, match in enumerate(segments):
        segment = intro[match.start():segments[index + 1].start() if index + 1 < len(segments) else len(intro)]
        # Exclude separately advertised harvest dates from the regular season.
        segment = re.split(r"Fall Harvest|Harvest Market|Holiday Market", segment, flags=re.IGNORECASE)[0]
        hours = clock_range(segment)
        if not hours:
            continue
        weekday = DAY_NAMES.index(match[1].title())
        span = date_span(segment, year=first.year)
        year_round = bool(re.search(r"year[ -]round", segment, re.IGNORECASE))
        if not span and not year_round:
            continue
        if span and not re.search(r"\b20\d{2}\b", segment) and span[0].weekday() != weekday:
            raise ParseError("Undated seasonal schedule does not match this year's weekdays")
        found += 1
        for day in days(first, last):
            if day.weekday() != weekday or (span and not span[0] <= day <= span[1]):
                continue
            row = occurrence("farmers_markets", key + ":" + day.isoformat(), name + " Farmers Market", day,
                             "https://seattlefarmersmarkets.org/" + key, venue=name + " Farmers Market",
                             neighborhood=name, hours=hours, category="farmers_market", coords=coords,
                             zone=zone, evidence=intro,
                             timing_basis="recurring hours from market operator; exceptions may apply")
            result.append(row)
    if not found:
        raise ParseError("Market schedule could not be interpreted")
    return result


def visit_index(html: str) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(".event-title a[href], .container-event h4 a[href]")
    if not anchors and not re.search(r"no (?:results|events)|nothing found", soup.get_text(), re.IGNORECASE):
        raise ParseError("Visit Seattle event results layout changed")
    urls = list(dict.fromkeys(a["href"] for a in anchors if "/events/" in a["href"]))
    next_page = soup.select_one('a.next.page-numbers, a[rel="next"]')
    return urls, next_page.get("href") if next_page else None


def visit_detail(url: str, html: str, first: date, last: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    schedule = next((h for h in soup.find_all("h4") if "|" in h.get_text()), None)
    if not heading or not schedule:
        raise ParseError("Visit Seattle event page has no title/schedule")
    title = clean(heading.get_text())
    when, venue = (clean(value) for value in schedule.get_text(" ", strip=True).split("|", 1))
    # The detail block holds category, region and body without footer addresses.
    content = soup.select_one(".container-event-detail")
    if not content:
        raise ParseError("Visit Seattle event detail layout changed")
    text = content.get_text(" ", strip=True)
    category = classify(title)
    if category == "community" and not re.search(r"festival|community|fair|cultural", text, re.IGNORECASE):
        return []  # Permanent museum exhibits and general attractions are not gatherings.
    neighborhood = next((label.title() for label in sorted(NEIGHBORHOODS, key=len, reverse=True)
                         if label in (venue + " " + text).lower()), "")
    if re.search(r"\b(Bellevue|Redmond|Kirkland|Tacoma|Bothell|Everett|Puyallup)\b", venue, re.IGNORECASE):
        return []
    if not neighborhood and "seattle" not in venue.lower():
        return []  # Region remains unresolved; don't silently call an Eastside event Seattle.
    span = date_span(when)
    recurring = re.search(r"(?:every|held)\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?", text, re.IGNORECASE)
    if not recurring:
        recurring = re.search(r"(?:–|-|—)\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\s*$", title, re.IGNORECASE)
    if not recurring and re.search(r"year[ -]round", text, re.IGNORECASE):
        recurring = re.search(WEEKDAY, title, re.IGNORECASE)
    if not span and (not recurring or category not in {"farmers_market", "market"}):
        return []
    title = re.sub(r"\s*[–—-]\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\s*$", "", title, flags=re.IGNORECASE)
    links = [a.get("href") for a in content.select("a[href]") if safe_url(a.get("href"))
             and "visitseattle.org" not in a["href"]]
    result = []
    for day in days(first, last):
        if span and not span[0] <= day <= span[1]:
            continue
        if not span and day.weekday() != DAY_NAMES.index(recurring[1].title()):
            continue
        # Visit Seattle often publishes dates only. Do not invent a closing wave.
        result.append(occurrence("visit_seattle", url + ":" + day.isoformat(), title, day, url,
                                 venue=venue, neighborhood=neighborhood, category=category,
                                 evidence=when + " | " + venue, organizer_url=links[0] if links else None,
                                 notes="Recurring day listed; hours unconfirmed." if not span else ""))
    return result


def collect_source(source_id: str, fetch, first: date, last: date) -> tuple[list[dict], list[str]]:
    """fetch is a bounded, cached downloader; errors are isolated by page."""
    rows, errors = [], []
    if source_id in {"redmond_city", "king_county_parks"}:
        from farol.redmond_events import collect_redmond_source
        return collect_redmond_source(source_id, fetch, first, last)
    if source_id == "neighborhoods":
        url = "https://www.trumba.com/calendars/neighborhoods.json?" + urlencode(
            {"startdate": first.strftime("%Y%m%d"), "days": (last - first).days + 1, "maxevents": 500})
        payload = json.loads(fetch(url))
        rows = trumba_events(payload, first, last)
        return rows, ["Calendar reached its 500-event bound; coverage may be incomplete"] if len(payload) >= 500 else []
    if source_id == "farmers_markets":
        for key in MARKETS:
            try:
                rows.extend(market_events(key, fetch("https://seattlefarmersmarkets.org/" + key), first, last))
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(f"{key}: {type(error).__name__}: {str(error)[:160]}")
        return rows, errors
    if source_id == "seattle_center":
        url = "https://www.seattlecenter.com/events/featured-events/festal"
        items = festal_index(fetch(url), first, last)
        for item in items[:30]:
            try:
                rows.extend(festal_detail(item, fetch(item["url"]), first, last))
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(f"{item['title']}: {type(error).__name__}: {str(error)[:160]}")
        return rows, errors
    if source_id == "visit_seattle":
        url = "https://visitseattle.org/?" + urlencode({"frm": "events", "event_type": "festivals-special-events",
              "event_begin": first.isoformat(), "event_end": last.isoformat(), "s": ""})
        urls = []
        for _ in range(3):
            discovered, next_page = visit_index(fetch(url))
            urls.extend(u for u in discovered if u not in urls)
            if not next_page:
                break
            url = urljoin(url, next_page)
        else:
            if next_page:
                errors.append("More listing pages exist; this run reached its three-page bound")
        if len(urls) > 45:
            errors.append("More than 45 detail pages; this run reached its page bound")
        for url in urls[:45]:
            try:
                rows.extend(visit_detail(url, fetch(url), first, last))
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(f"{url.rsplit('/', 2)[-2]}: {type(error).__name__}: {str(error)[:160]}")
        return rows, errors
    raise ParseError("Unknown source")
