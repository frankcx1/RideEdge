"use strict";
const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch]);
const stamp = (value) => value ? new Date(value).toLocaleString("en-US", {timeZone:"America/Los_Angeles", month:"short", day:"numeric", hour:"numeric", minute:"2-digit"}) : "time unknown";
const time = (value) => new Date(value).toLocaleTimeString("en-US", {timeZone:"America/Los_Angeles", hour:"numeric", minute:"2-digit"});
const age = (minutes) => minutes == null ? "Age unknown" : minutes < 1 ? "Just checked" : minutes < 60 ? `${Math.floor(minutes)}m ago` : `${Math.floor(minutes / 60)}h ago`;
const dayLabel = (value) => new Date(value).toLocaleDateString("en-US", {timeZone:"America/Los_Angeles", month:"short", day:"numeric"});
function sourceLink(url, label) {
  try { const link = new URL(url); if (!["https:", "http:"].includes(link.protocol) || link.username) return ""; }
  catch { return ""; }
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
}
let scope = "nearby", topic = "highlights", parked = null, requestNumber = 0, currentData = null;
let locationRequest = 0, locating = false, locationRequired = false;
let limits = {events:6, dining:6, access:6, other:6};

function groupObservations(rows) {
  return {events:rows.filter((r) => r.layer === "events"), dining:rows.filter((r) => r.layer === "dining"),
    access:rows.filter((r) => r.layer === "access"), other:rows.filter((r) => !["events", "dining", "access"].includes(r.layer))};
}
function venueLabel(row) {
  if (row.live_recent && row.live_value != null) {
    if (row.live_delta > 0) return {text:"Busier than usual", tone:"live"};
    if (row.live_delta < 0) return {text:"Quieter than usual", tone:"neutral"};
    return {text:row.live_delta === 0 ? "At its usual level" : "Recent activity reading", tone:"live"};
  }
  if (!row.profile_usable) return {text:"Activity unknown", tone:"neutral"};
  if (row.typically_closed_now) return {text:"Usually closed now", tone:"neutral"};
  return {text:"Typical pattern only", tone:"neutral"};
}
function rankedVenues(rows) {
  return [...rows].sort((a, b) => Number(Boolean(b.live_recent)) - Number(Boolean(a.live_recent))
    || (b.live_recent ? (b.live_delta ?? -999) - (a.live_delta ?? -999) : Number(Boolean(a.typically_closed_now)) - Number(Boolean(b.typically_closed_now)))
    || a.name.localeCompare(b.name));
}
function observationCard(row) {
  const old = ["old source data", "source refresh failed", "time unknown", "standing schedule", "demo", "not seen on latest check"].includes(row.freshness);
  const traffic = ["highway_alert", "travel_delay"].includes(row.kind);
  const label = row.community_event ? ({festival:"Festival", farmers_market:"Farmers market", market:"Market", community_activity:"Community event", community:"Community event"}[row.category] || "Community event")
    : row.kind === "event_exit" ? "Estimated let-out" : row.kind === "closing_wave" ? "Closing window"
    : row.kind === "highway_alert" ? "Road advisory" : row.kind === "precipitation" ? "Forecast" : row.timing_label;
  const hours = row.date_only ? "Hours unconfirmed" : row.end_unknown ? `${time(row.window_starts_at)} · end unconfirmed` : `${time(row.window_starts_at)}–${time(row.ends_at)}`;
  const timing = traffic ? row.timing_label : `${row.community_event ? `${dayLabel(row.window_starts_at)} · ` : ""}${hours}`;
  const place = row.location_label || row.zone_labels.join(" · ");
  const receipts = (row.receipts || []).map((receipt) => sourceLink(receipt.url, receipt.name)).filter(Boolean);
  const sourceText = receipts.length ? `<p class="event-sources">${receipts.join(" · ")}</p>` : "";
  const timingDetail = row.date_only ? `${dayLabel(row.window_starts_at)} · daily hours unconfirmed` : row.end_unknown ? `${stamp(row.window_starts_at)} · end unconfirmed` : `${stamp(row.window_starts_at)}–${stamp(row.ends_at)}`;
  return `<article class="compact-card" data-layer="${esc(row.layer)}"><div class="card-top"><span class="pill ${old ? "neutral" : ""}">${esc(label)}</span><span>${esc(traffic ? age(row.source_age_minutes) : timing)}</span></div><h3>${esc(row.title)}</h3><p class="card-meta">${esc(place)}${row.community_event ? ` · checked ${esc(age(row.source_age_minutes).toLowerCase())}` : ""}</p>${old ? `<p class="data-caution">${esc(row.freshness === "standing schedule" ? "Usual schedule · unverified today" : row.freshness)}</p>` : ""}${row.conflicts?.length ? '<p class="data-caution">Schedule needs confirmation</p>' : ""}<details><summary>Details</summary>${row.event_starts_at ? `<p>Event starts ${esc(stamp(row.event_starts_at))}</p>` : ""}<p>${esc(row.timing_label)}${traffic ? "" : ` · ${esc(timingDetail)}`}</p><p>${esc(row.detail)}</p>${row.community_event ? `<p>${esc(row.venue || "Venue unconfirmed")}${row.location_precision === "area" ? " · approximate neighborhood location" : row.location_precision === "unknown" ? " · location not mapped" : ""}</p>` : ""}${sourceText}<small>${esc(row.basis)} · ${esc(row.source)} · checked ${esc(stamp(row.fetched_at))}</small></details></article>`;
}
function venueCard(row) {
  const label = venueLabel(row), peak = row.window_peak;
  const supporting = row.live_recent && row.live_value != null ? `Checked ${age(row.live_age_minutes).toLowerCase()}`
    : peak && row.profile_usable ? `Typical peak ${time(peak.at)} · live unknown` : "No recent live reading";
  return `<article class="compact-card venue-card"><div class="card-top"><span class="pill ${label.tone}">${esc(label.text)}</span><span>${esc(row.area)}</span></div><h3>${esc(row.name)}</h3><p class="card-meta">${esc(supporting)}</p><details><summary>Activity details</summary><p>${esc(row.note || "")}</p>${row.live_value != null ? `<p>${row.live_recent ? "Latest" : "Earlier"} reading: ${esc(row.live_value)} · checked ${esc(stamp(row.live_retrieved_at))}</p>` : ""}<p>${row.profile_usable && row.typical_now != null ? `Typical at this hour: ${esc(row.typical_now)}` : "Typical activity unknown"}</p><small>Relative to this venue’s weekly peak of 100. Not a rider count. Historical profile checked ${esc(stamp(row.forecast_retrieved_at))} · BestTime.</small></details></article>`;
}
function error(message) { el("awareness-error").textContent = message; el("awareness-error").classList.toggle("hidden", !message); }
function section(id, visible) { el(id).classList.toggle("hidden", !visible); }
function renderContent(data) {
  const groups = groupObservations(data.observations), highlight = topic === "highlights";
  const venues = rankedVenues(data.venue_activity);
  section("events-section", highlight || topic === "events"); section("venue-section", highlight || topic === "dining");
  section("traffic-section", topic === "access"); section("other-context", highlight); section("metro-invite", scope === "nearby" && topic !== "access");
  section("all-events", highlight && groups.events.length > 3); section("all-places", highlight && venues.length + groups.dining.length > 3);
  el("traffic-count").textContent = groups.access.length ? String(groups.access.length) : "";
  el("traffic-total").textContent = `${groups.access.length} reports`;
  const eventLimit = highlight ? 3 : limits.events;
  const calendar = data.community_calendar;
  el("community-coverage").textContent = calendar ? `Community calendar · ${calendar.scheduled_count} dates through ${dayLabel(`${calendar.through_date}T12:00:00Z`)} · ${calendar.sources.filter((s) => s.state === "ready").length}/${calendar.sources.length} sources current` : "";
  el("awareness-observations").innerHTML = groups.events.slice(0, eventLimit).map(observationCard).join("") || '<p class="empty-state">No events in these feeds for this window. Try Metro or a later time.</p>';
  section("more-events", !highlight && groups.events.length > eventLimit);
  const placeLimit = highlight ? 3 : limits.dining;
  // A few venue cards first, then closing windows, without an unbounded wall of text.
  const venueSlots = Math.min(venues.length, groups.dining.length ? Math.ceil(placeLimit / 2) : placeLimit);
  const closingSlots = placeLimit - venueSlots;
  el("awareness-venues").innerHTML = venues.slice(0, venueSlots).map(venueCard).join("");
  el("closing-windows").innerHTML = groups.dining.slice(0, closingSlots).map(observationCard).join("");
  const coverage = data.busyness_coverage;
  el("venue-coverage").textContent = !venues.length && !groups.dining.length ? "No venue activity saved for this area yet."
    : coverage.recent_live ? `${coverage.recent_live} recent venue check${coverage.recent_live === 1 ? "" : "s"} · a small sample`
    : "Live activity unknown · saved patterns and hours only";
  section("more-places", !highlight && (venues.length > venueSlots || groups.dining.length > closingSlots));
  el("traffic-observations").innerHTML = groups.access.slice(0, limits.access).map(observationCard).join("") || '<p class="empty-state">No road reports in this selection. Conditions may still vary.</p>';
  section("more-traffic", groups.access.length > limits.access);
  el("other-count").textContent = String(groups.other.length);
  el("other-observations").innerHTML = groups.other.slice(0, limits.other).map(observationCard).join("") || '<p class="empty-state">No additional observations in this window.</p>';
  section("more-other", groups.other.length > limits.other);
}
function render(data) {
  currentData = data;
  const selected = data.area;
  el("awareness-area").innerHTML = data.areas.map((a) => `<option value="${esc(a.id)}">${esc(a.label)}</option>`).join("");
  el("awareness-area").value = selected;
  el("view-location").textContent = scope === "metro" ? "Across greater Seattle & the Eastside"
    : parked ? `~5 mi from device location · near ${data.location_label}` : `Selected area · ${data.location_label} · ~5 mi`;
  if (window.isSecureContext) el("location-note").textContent = parked ? `${RideEdgeLocation.note(parked)} · tap location after moving` : "Choose an area or use your device location.";
  section("location-note", scope === "nearby");
  const snap = data.snapshot;
  el("snapshot-status").textContent = snap.state === "demo" ? "Demo data" : snap.state === "missing" ? "Feeds unavailable" : snap.age_minutes < 1 ? "Just checked" : `${snap.state === "old" ? "Older snapshot · " : "Checked "}${age(snap.age_minutes).toLowerCase()}`;
  el("snapshot-status").classList.toggle("data-caution", ["old", "missing", "demo"].includes(snap.state));
  el("snapshot-detail").textContent = `Snapshot: ${stamp(snap.collected_at)}. ${data.period === "week" ? "Week view adds the saved Seattle and Redmond community calendar. Other feeds cover their existing shorter windows." : snap.full_window_covered ? "" : "The saved feeds may not cover the entire selected window."}`;
  el("awareness-feeds").innerHTML = data.feeds.map((feed) => `<li>${esc(feed.name)} · ${esc(feed.mode)}<small>${esc(feed.source)} · ${esc(stamp(feed.fetched_at))}</small></li>`).join("") || "<li>No source status available.</li>";
  renderContent(data);
}
async function load() {
  if (scope === "nearby" && locating) return;
  if (scope === "nearby" && locationRequired) { requireLocation("Tap location again or choose an area."); return; }
  if (scope === "nearby" && parked && !RideEdgeLocation.fresh(parked)) {
    requireLocation("Location is over 5 minutes old. Tap location again or choose an area."); return;
  }
  const request = ++requestNumber;
  error(""); el("awareness-refresh").disabled = true;
  // Clear the previous area's cards immediately; a failed fetch must not mislabel them.
  currentData = null; section("awareness-content", false);
  el("snapshot-status").textContent = "Updating…";
  const params = new URLSearchParams({scope, area:el("awareness-area").value, radius:"5", period:el("awareness-period").value, layer:"all"});
  const options = parked && scope === "nearby" ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(RideEdgeLocation.body(parked))} : {};
  try {
    const response = await fetch(`/api/awareness?${params}`, options), data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not read this area");
    if (request === requestNumber) { render(data); section("awareness-content", true); }
  } catch (err) { if (request === requestNumber) { currentData = null; error(`Couldn’t update this area. ${err.message}`); el("snapshot-status").textContent = "Update failed"; } }
  finally { if (request === requestNumber) el("awareness-refresh").disabled = false; }
}
function changeTopic(value) {
  if (value !== "events" && el("awareness-period").value === "week") {
    el("awareness-period").value = "all";
    load();
  }
  topic = value;
  document.querySelectorAll("[data-topic]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.topic === topic)));
  if (currentData) renderContent(currentData);
}
function changeScope(value) {
  if (locating) { cancelLocation(); locationRequired = true; }
  scope = value; limits = {events:6, dining:6, access:6, other:6};
  el("scope-metro").setAttribute("aria-pressed", String(scope === "metro"));
  el("scope-nearby").setAttribute("aria-pressed", String(scope === "nearby"));
  section("nearby-controls", scope === "nearby");
  section("location-note", false);
  load();
}
function cancelLocation() {
  locationRequest++; locating = false; el("awareness-gps").disabled = false;
}
function requireLocation(message) {
  requestNumber++; parked = null; currentData = null; locationRequired = true;
  section("awareness-content", false); el("awareness-area").value = "";
  el("view-location").textContent = "Choose an area or update device location";
  el("snapshot-status").textContent = "Location needed"; el("awareness-refresh").disabled = false;
  if (window.isSecureContext) el("location-note").textContent = "Device location is not current.";
  section("location-note", true); error(message);
}
function selectArea() {
  cancelLocation(); parked = null; locationRequired = false; load();
}
async function locate() {
  const request = ++locationRequest;
  requireLocation(""); locating = true; el("awareness-gps").disabled = true;
  el("view-location").textContent = "Getting device location…";
  try {
    const fix = await RideEdgeLocation.get();
    if (request !== locationRequest) return;
    parked = fix; locating = false; locationRequired = false; await load();
  } catch (err) { if (request === locationRequest) requireLocation(err.message); }
  finally { if (request === locationRequest) { locating = false; el("awareness-gps").disabled = false; } }
}
function init() {
  const params = new URLSearchParams(location.search), area = params.get("area");
  if (area) { const option = document.createElement("option"); option.value = area; option.textContent = area.replaceAll("_", " "); el("awareness-area").append(option); el("awareness-area").value = area; }
  if (!window.isSecureContext) el("location-note").innerHTML = 'For phone GPS, <a href="https://rideedge.example.com/awareness?ui=20260919-rideedge1">open the secure link</a>. Or choose an area.';
  el("scope-nearby").addEventListener("click", () => changeScope("nearby"));
  el("scope-metro").addEventListener("click", () => changeScope("metro"));
  el("awareness-refresh").addEventListener("click", () => scope === "nearby" && (parked || locationRequired) ? locate() : load());
  el("awareness-area").addEventListener("change", selectArea);
  el("awareness-period").addEventListener("change", () => { limits.events = 6; if (el("awareness-period").value === "week") changeTopic("events"); load(); });
  el("awareness-gps").addEventListener("click", locate);
  document.querySelectorAll("[data-topic]").forEach((button) => button.addEventListener("click", () => changeTopic(button.dataset.topic)));
  el("all-events").addEventListener("click", () => changeTopic("events")); el("all-places").addEventListener("click", () => changeTopic("dining"));
  for (const [id, key] of [["more-events", "events"], ["more-places", "dining"], ["more-traffic", "access"], ["more-other", "other"]]) el(id).addEventListener("click", () => { limits[key] += 6; if (currentData) renderContent(currentData); });
  if (params.get("period") === "week") { el("awareness-period").value = "week"; changeTopic("events"); }
  changeScope(params.get("scope") === "metro" ? "metro" : "nearby");
  setInterval(() => { if (!document.hidden) load(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
}
if (typeof module !== "undefined") module.exports = {groupObservations, venueLabel, rankedVenues, observationCard, venueCard};
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
