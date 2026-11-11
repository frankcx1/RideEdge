"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch]);
const money = (value) => `$${Number(value).toFixed(2)}`;
const zone = (value) => value ? value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Area unknown";
const clock = (value) => new Date(value).toLocaleTimeString("en-US", {timeZone:"America/Los_Angeles", hour:"numeric", minute:"2-digit"});
let latest, lastHere, voiceUI, askUI, askSpeech = false, brainTimer, brainPolls = 0, briefLoading = false, hereRequest = 0, lastPlace = "";
let lastDeviceLocation = null, gpsRequest = 0;
const demoMode = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "1";

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not update. Try again.");
  return body;
}
function routeLabel(route) {
  if (!route || route.traffic_minutes == null || !Number.isFinite(Number(route.traffic_minutes)) || Number(route.traffic_minutes) < 0) return "Drive time unknown";
  return `${route.basis === "assumed" ? "~" : ""}${Math.round(route.traffic_minutes)} min drive${route.basis === "assumed" ? " · estimated" : ""}`;
}
function opportunityGroups(brief) {
  const ranks = new Map((brief.ranked_opportunity_ids || []).map((id, i) => [id, i]));
  const ordered = [...(brief.opportunities || [])].sort((a, b) => (ranks.get(a.id) ?? 999) - (ranks.get(b.id) ?? 999));
  // Match the engine's minimum opportunity score; don't promote a weak WATCH.
  const featured = brief.shift_decision?.action === "NO CLEAR SIGNAL" ? []
    : ordered.filter((item) => item.action !== "AVOID" && Number(item.score) >= 5).slice(0, 3);
  return {featured, other:ordered.filter((item) => !featured.includes(item))};
}
function workingSummary(payload) {
  const {place, best, stay, action} = payload;
  if (place.zone === "sea_airport") return {title:"Check the airport queue", text:payload.nearby?.[0]?.headline || "No qualifying arrival wave in this check.", basis:"Airport arrivals only · driver queue unknown"};
  const sample = (action === "WAIT" ? stay?.thin : best?.thin) ? "Limited pickup history" : "Based on past pickups";
  if (action === "WAIT" && stay) return {title:`Stay near ${place.label}`, text:"Your pickup history favors staying in this area.", basis:`${sample} · wait time unknown`};
  if (best && best.zone !== place.zone) return {title:`Watch ${zone(best.zone)}`, text:best.reposition_minutes == null ? "Repositioning time unknown." : `~${Math.round(best.reposition_minutes)} min to reposition · estimate from this area.`, basis:`${sample} · choose a legal pickup spot`};
  if (best) return {title:`Watch ${place.label}`, text:"No stronger area in your pickup history for this hour.", basis:`${sample} · live demand unknown`};
  return {title:"No clear move yet", text:"Not enough pickup history for this location.", basis:"Check nearby events and places."};
}
function opportunityCard(item) {
  const facts = item.facts || [];
  const headline = item.venue_name || facts.find((f) => ["event_exit", "closing_wave"].includes(f.kind))?.text || zone(item.zone);
  const action = ({WAIT:"Stay nearby", WATCH:"Watch this area", MOVE:"Worth a look", AVOID:"Skip this window"})[item.action] || "Window to review";
  const mapsHref = item.navigation_available && item.anchor && Number.isFinite(Number(item.anchor.latitude)) && Number.isFinite(Number(item.anchor.longitude)) ? `https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=${Number(item.anchor.latitude).toFixed(6)},${Number(item.anchor.longitude).toFixed(6)}` : "";
  return `<article class="compact-card ${item.action === "AVOID" ? "subdued" : ""}"><div class="card-top"><span class="pill">${esc(action)}</span><span>${esc("Est. " + clock(item.starts_at))}–${esc(clock(item.ends_at))}</span></div><h3>${esc(headline)}</h3><p class="card-meta">${esc(zone(item.zone))} · ${esc(routeLabel(item.route))}</p><details><summary>Details</summary>${item.note ? `<p>${esc(item.note)}</p>` : ""}<ul class="detail-list">${facts.map((fact) => `<li>${esc(fact.text)}<small>${esc(fact.basis)} · ${esc(fact.source)}</small></li>`).join("")}</ul><p class="quiet-note">${esc(item.anchor?.safety_notes || "Pickup spot needs approval.")}</p><p class="quiet-note">Signal score ${Number(item.score).toFixed(1)} · hourly earnings unknown.</p>${item.navigation_available ? `<button class="send-route" data-id="${esc(item.id)}">Send to Volvo</button>${mapsHref ? ` <a class="open-maps" href="${esc(mapsHref)}" target="_blank" rel="noopener noreferrer">Open in Maps</a>` : ""}` : ""}</details></article>`;
}
function renderBrief(data) {
  latest = data;
  const decision = data.shift_decision;
  $("mode").textContent = data.mock_feeds ? "Demo data" : "Connected feeds";
  $("shift-action").textContent = ({"CHECK WINDOW":"A window worth a look", "NO CLEAR SIGNAL":"No clear signal yet"})[decision.action] || decision.action;
  $("shift-explanation").textContent = decision.best_window ? "Check the timing before heading out." : "No strong opportunity in the available feeds. That doesn’t mean it’s quiet.";
  $("decision-kicker").textContent = decision.signal_timing === "later" ? "LOOKING AHEAD" : "YOUR NEXT WINDOW";
  $("decision-window").classList.toggle("hidden", !decision.best_window);
  $("best-zone").textContent = zone(decision.best_zone);
  $("shift-window").textContent = decision.best_window ? `Est. ${clock(decision.best_window.starts_at)}–${clock(decision.best_window.ends_at)}` : "";
  $("earnings-explanation").textContent = decision.earnings_explanation || "Your goal is a preference, not an earnings forecast.";
  $("window-label").textContent = `Next ${$("hours").value} hours`;
  const {featured, other} = opportunityGroups(data);
  $("opportunities").innerHTML = featured.map(opportunityCard).join("") || '<p class="empty-state">No strong windows to highlight. Explore the area or check again later.</p>';
  $("more-opportunities").classList.toggle("hidden", !other.length);
  $("other-opportunities").innerHTML = other.map(opportunityCard).join("");
  document.querySelectorAll(".send-route").forEach((button) => button.addEventListener("click", () => sendRoute(button)));
  const brain = data.brain || {}, narration = data.narration;
  $("grok-panel").classList.toggle("hidden", !narration && brain.provider !== "local");
  $("brain-status").textContent = narration ? "Ready" : brain.mode === "warming" ? "Preparing…" : ["busy", "error"].includes(brain.mode) ? "Unavailable" : "";
  $("grok-headline").textContent = narration?.headline || (brain.mode === "warming" ? "Qwen is preparing your brief" : "Qwen is unavailable");
  $("grok-spoken").textContent = narration?.spoken || brain.detail || "";
  $("grok-risks").innerHTML = (narration?.risks || []).map((risk) => `<li>${esc(risk)}</li>`).join("");
  $("grok-meta").textContent = [brain.model, brain.detail].filter(Boolean).join(" · ");
  $("fixture-warning").textContent = (data.warnings || []).join(" ");
  $("feed-list").innerHTML = (data.feeds || []).map((feed) => `<li>${esc(feed.adapter.replaceAll("_", " "))} · ${esc(feed.mode)}<small>${esc(feed.detail)}${feed.fetched_at ? ` · ${clock(feed.fetched_at)}` : ""}</small></li>`).join("");
  $("updated-at").textContent = `${data.mock_feeds ? "Demo" : "Updated"} ${clock(data.as_of)} · Pacific`;
  renderHistory(data.personal || {});
}
function renderHistory(personal) {
  $("personal-panel").classList.toggle("hidden", !personal.trips);
  if (!personal.trips) return;
  $("personal-headline").textContent = `${personal.trips} trips · ${money(personal.earnings)} gross`;
  $("personal-note").textContent = personal.note || "";
  $("personal-facts").innerHTML = Object.entries(personal.by_pickup_cluster || {}).map(([name, bucket]) => `<p>${esc(zone(name))} · ${bucket.trips} pickups · ${money(bucket.mean_earnings)} average / trip</p>`).join("");
  $("history-rows").innerHTML = (personal.history?.sessions || []).map((row) => `<tr><td>${esc(row.date)}</td><td>${row.trips}</td><td>${money(row.gross_earnings)}</td><td>${Number(row.paid_miles).toFixed(1)}</td></tr>`).join("");
  $("history-note").textContent = personal.history?.note || "";
  $("venue-observations").innerHTML = (personal.venue_observations || []).map((row) => `<li>${esc(row.venue)} · ${esc(row.date)}<small>${esc(row.pattern)} ${esc(row.driver_interpretation)}</small></li>`).join("");
}
async function loadBrief() {
  if (briefLoading) return;
  briefLoading = true; $("refresh").disabled = true; clearTimeout(brainTimer);
  try {
    const params = new URLSearchParams({hours:$("hours").value, vehicle_cost:$("vehicle-cost").value, value_of_time:$("value-of-time").value});
    const data = await api(`/api/tonight?${params}`);
    renderBrief(data); $("app-error").classList.add("hidden");
    if (data.brain?.mode === "warming" && !document.hidden && brainPolls < 32) { brainPolls++; brainTimer = setTimeout(() => loadBrief().catch(showError), 15000); }
    else if (data.brain?.mode !== "warming") brainPolls = 0;
  } finally { briefLoading = false; $("refresh").disabled = false; }
}
function renderHere(payload) {
  lastHere = payload;
  askUI?.setArea(payload.place.zone);
  const summary = workingSummary(payload);
  $("here-place").textContent = `Near ${payload.place.label}`; $("here-action").textContent = summary.title;
  $("here-spoken").textContent = summary.text; $("here-basis").textContent = summary.basis;
  $("here-detail").textContent = payload.spoken;
  $("here-warnings").innerHTML = (payload.warnings || []).map((row) => `<li>${esc(row)}</li>`).join("");
  $("here-detail-panel").classList.remove("hidden");
  $("working-around").href = `/awareness?ui=20260919-rideedge1&area=${encodeURIComponent(payload.place.zone)}`;
  $("nav-around").href = $("working-around").href;
  const nearby = (payload.nearby || []).filter((row) => row.action !== "AVOID").slice(0, 3);
  $("here-nearby-section").classList.toggle("hidden", !nearby.length);
  $("here-nearby").innerHTML = nearby.map((row) => `<article class="compact-card"><span class="pill">${row.basis === "assumed" ? "Estimated window" : "Window to watch"}</span><h3>${esc(row.headline || row.title)}</h3><p class="card-meta">${esc("Est. " + clock(row.starts_at))}–${esc(clock(row.ends_at))} · ${esc(routeLabel({traffic_minutes:row.minutes_away, basis:row.route_basis}))}</p><details><summary>Details</summary><p>${esc(row.detail)}</p></details></article>`).join("");
}
function clearHere(message = "Choose a location") {
  lastHere = null; askUI?.clearArea();
  $("here-error").classList.add("hidden"); $("here-action").textContent = message;
  $("here-spoken").textContent = ""; $("here-place").textContent = "UPDATING LOCATION"; $("here-basis").textContent = "";
  $("here-nearby-section").classList.add("hidden"); $("here-detail-panel").classList.add("hidden");
  $("working-around").href = "/awareness?ui=20260919-rideedge1";
  $("nav-around").href = "/awareness?ui=20260919-rideedge1";
  if (window.isSecureContext) $("here-location-note").textContent = "Use device location or enter an area.";
}
function selectManualLocation() {
  gpsRequest++; hereRequest++; lastDeviceLocation = null; lastPlace = "";
  $("here-gps").disabled = false; $("here-submit").disabled = false;
  clearHere(); $("here-place").textContent = "LOCATION NEEDED";
}
function expireLocation() {
  if (!lastDeviceLocation || RideEdgeLocation.fresh(lastDeviceLocation)) return false;
  selectManualLocation(); clearHere("Update your location"); $("here-place").textContent = "LOCATION EXPIRED";
  $("here-location-note").textContent = "Location is over 5 minutes old. Tap Use my location again or enter an area.";
  return true;
}
async function sitHereNow(isCurrent = () => true, fix = null) {
  const at = $("here-at").value.trim(); if (!fix && !at) return false;
  if (fix && !RideEdgeLocation.fresh(fix)) { expireLocation(); return false; }
  if (!fix) selectManualLocation();
  const request = ++hereRequest;
  clearHere("Checking this area…"); $("here-submit").disabled = true;
  try {
    const query = new URLSearchParams({vehicle_cost:$("vehicle-cost").value, value_of_time:$("value-of-time").value});
    if (!fix) query.set("at", at);
    const options = fix ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(RideEdgeLocation.body(fix))} : {};
    const payload = await api(`/api/here?${query}`, options);
    if (request !== hereRequest || !isCurrent()) return false;
    lastPlace = fix ? "" : at; lastDeviceLocation = fix; renderHere(payload);
    if (window.isSecureContext) $("here-location-note").textContent = fix ? `${RideEdgeLocation.note(fix)} · tap location after moving` : `Selected area · ${payload.place.label}`;
    return true;
  } catch (error) {
    if (request !== hereRequest || !isCurrent()) return false;
    $("here-action").textContent = "Try another location"; $("here-spoken").textContent = "Enter a nearby area or cross street.";
    $("here-error").textContent = error.message; $("here-error").classList.remove("hidden");
    return false;
  } finally { if (request === hereRequest) $("here-submit").disabled = false; }
}
async function parkedHere() {
  const request = ++gpsRequest;
  hereRequest++; lastPlace = ""; lastDeviceLocation = null; $("here-at").value = "";
  clearHere("Getting device location…"); $("here-gps").disabled = true; $("here-submit").disabled = false;
  try {
    const fix = await RideEdgeLocation.get();
    if (request !== gpsRequest) return;
    await sitHereNow(() => request === gpsRequest, fix);
  } catch (error) {
    if (request !== gpsRequest) return;
    clearHere("Location unavailable"); $("here-place").textContent = "LOCATION NEEDED";
    $("here-error").textContent = error.message; $("here-error").classList.remove("hidden");
  } finally { if (request === gpsRequest) $("here-gps").disabled = false; }
}
async function sendRoute(button) {
  button.disabled = true;
  try { await api(`/api/navigation/opportunity/${encodeURIComponent(button.dataset.id)}?vehicle_cost=${$("vehicle-cost").value}`, {method:"POST"}); button.textContent = "Sent · confirm in car"; }
  catch (error) { button.disabled = false; showError(error); }
}
async function loadShift() {
  const state = await api("/api/shift"), phase = state.phase || "idle";
  $("shift-status").textContent = ({driving:"Qwen is ready for this app.", narrating:"Qwen is preparing a brief.", acquiring:"Loading Qwen…", restoring:"Releasing Qwen…", idle:"Qwen loads when needed."})[phase] || state.detail || "Model status unavailable";
  $("shift-start").disabled = ["driving", "acquiring", "restoring", "narrating"].includes(phase);
  $("shift-stop").disabled = !["driving", "error"].includes(phase);
}
function changeMode() {
  voiceUI?.cancel();
  const working = demoMode || location.hash === "#working";
  $("decide-view").classList.toggle("hidden", working); $("working-view").classList.toggle("hidden", !working);
  for (const [id, active] of [["nav-decide", !working], ["nav-working", working]]) { if (active) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current"); }
  document.title = `${window.RIDEEDGE_PRODUCT.name} · ${demoMode ? "Simulated scenario" : working ? "Working" : "Should I drive?"}`; window.scrollTo(0, 0);
}
function showError(error) {
  $("app-error").textContent = `Couldn’t refresh. ${error.message} ${latest ? "The displayed brief may be out of date." : ""}`; $("app-error").classList.remove("hidden");
}
function spokenAnswer(forceBrief = false) {
  if (demoMode) return "Simulated scenario. " + (askUI?.answer() || "The comparison is loading.");
  if (!forceBrief && location.hash === "#working") {
    expireLocation();
    if (!lastHere) return "Choose a location first, or tap Speak and say the area you are in.";
    const summary = workingSummary(lastHere);
    return `${summary.title}. ${summary.text} ${summary.basis}.`;
  }
  if (!latest) return "The brief has not loaded yet. Please try again shortly.";
  const decision = latest.shift_decision, demo = latest.mock_feeds ? "Demo data. " : "";
  const stale = !$("app-error").classList.contains("hidden") ? "The displayed brief may be out of date. " : "";
  const answer = latest.narration?.spoken || (decision.best_window
    ? `A window worth a look near ${zone(decision.best_zone)}, estimated ${clock(decision.best_window.starts_at)} to ${clock(decision.best_window.ends_at)}. Check the timing before heading out.`
    : "No clear signal yet. No strong opportunity in the available feeds. That does not mean it is quiet.");
  return `${demo}${stale}${answer.slice(0, 540)} Earnings are not predictable yet.`;
}
function initAssistants() {
  askUI = window.createRideEdgeAsk({demo:demoMode, onContext:(context, comparison) => {
    if (!demoMode) return;
    $("mode").textContent="Simulated scenario";
    $("here-place").textContent=`Bellevue · ${clock(context.as_of)} Pacific`;
    $("here-action").textContent=comparison.best_id ? comparison.answer.split(".")[0] : "No qualifying move";
    $("here-spoken").textContent=comparison.best_id ? comparison.answer.split(". ").slice(1).join(". ") : "Staying put remains an option.";
    $("here-basis").textContent="Fictional events and routes · real Python calculations.";
  }});
  $("voice-record").addEventListener("click", () => { if ($("voice-record").textContent === "Speak") askSpeech=false; });
  voiceUI = window.createFarolVoice({
    location: async (place, isCurrent) => { if (demoMode) return false; if (place) $("here-at").value = place; return sitHereNow(isCurrent, place ? null : lastDeviceLocation); },
    answer: spokenAnswer,
    nearby: () => { location.href = $("nav-around").href; },
    wantsQuestion: () => askSpeech,
    question: (text, current) => askUI.submit(text, {isCurrent:current}),
  });
  $("ask-voice").addEventListener("click", () => { askSpeech=true; voiceUI.record(); });
}
function init() {
  document.body.classList.toggle("demo-app", demoMode);
  changeMode(); window.addEventListener("hashchange", changeMode);
  initAssistants();
  if (demoMode) {
    $("nav-decide").href="/?ui=20260919-rideedge1#decide";
    $("nav-around").href="/awareness?ui=20260919-rideedge1";
    $("ask-question").value="I have 90 minutes. Keep reposition drives under 15 minutes, and I'd prefer to finish near Kirkland. Compare staying around Bellevue with heading toward Seattle.";
    $("mode").textContent="Simulated scenario";
    $("updated-at").textContent="Fixed scenario · September 19, 2026 · Pacific";
    return;
  }
  $("refresh").addEventListener("click", () => { voiceUI?.cancel(); brainPolls = 0; loadBrief().catch(showError); });
  $("apply-preferences").addEventListener("click", () => { if (!$("value-of-time").reportValidity()) return; voiceUI?.cancel(); brainPolls = 0; loadBrief().catch(showError); if (lastPlace || lastDeviceLocation) sitHereNow(() => true, lastDeviceLocation); });
  $("here-form").addEventListener("submit", (event) => { event.preventDefault(); voiceUI?.cancel(); sitHereNow(); });
  $("here-at").addEventListener("input", () => { voiceUI?.cancel(); selectManualLocation(); });
  $("here-gps").addEventListener("click", () => { voiceUI?.cancel(); parkedHere(); });
  $("here-sea").addEventListener("click", () => { voiceUI?.cancel(); $("here-at").value = "SEA"; sitHereNow(); });
  if (!window.isSecureContext) $("here-location-note").innerHTML = 'For phone GPS, <a href="https://rideedge.example.com/?ui=20260919-rideedge1#working">open the secure link</a>. Or enter an area.';
  for (const verb of ["start", "stop"]) $("shift-" + verb).addEventListener("click", async () => {
    $("shift-start").disabled = true; $("shift-stop").disabled = true;
    try { const result = await api(`/api/shift/${verb}`, {method:"POST"}); $("shift-status").textContent = result.detail; } catch (error) { showError(error); }
    setTimeout(() => loadShift().catch(() => {}), 2000);
  });
  loadBrief().catch(showError); loadShift().catch(() => {});
  setInterval(() => { if (!document.hidden) loadShift().catch(() => {}); }, 15000);
  setInterval(() => { if (!document.hidden) loadBrief().catch(showError); }, 15 * 60 * 1000);
  setInterval(() => { if (!document.hidden) expireLocation(); }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { expireLocation(); brainPolls = 0; loadBrief().catch(showError); } });
}
if (typeof module !== "undefined") module.exports = {opportunityGroups, workingSummary, routeLabel, opportunityCard};
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
