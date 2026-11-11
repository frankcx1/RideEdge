const $ = (id) => document.getElementById(id);
const ACTIONS = ["WAIT", "ROAM", "MOVE", "GO_HOME"];
let latest;
let selectedDecision = null;
let fieldSession = null;
let fieldTimer = null;
let positionWatch = null;
let lastPresenceSent = 0;
let overrideRecorded = false;

function money(value) { return `$${Number(value).toFixed(2)}`; }
function zone(value) { return value.replaceAll("_", " ").toUpperCase(); }
function currentPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(resolve, () => resolve(null), {enableHighAccuracy:true, timeout:5000});
  });
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Request failed");
  }
  return response.json();
}

async function loadBrief() {
  const cost = $("vehicle-cost").value;
  const decision = selectedDecision === null ? "" : `&decision=${selectedDecision}`;
  latest = await api(`/api/brief?vehicle_cost=${cost}${decision}`);
  selectedDecision = latest.selected_decision_index;
  const recommendation = latest.recommendation;
  $("mode").textContent = latest.mode;
  $("action").textContent = recommendation.action === "STAY" ? "WAIT" : recommendation.action;
  $("zone").textContent = zone(recommendation.zone);
  $("return").textContent = `${money(recommendation.expected_dollars_per_hour)}/HR`;
  $("confidence").textContent = `${Math.round(recommendation.confidence * 100)}%`;
  $("cost").textContent = money(recommendation.reposition_cost);
  $("explanation").textContent = latest.explanation.replace("Stay in", "Wait in");
  $("position").textContent = `${selectedDecision + 1} OF ${latest.decision_count}`;
  $("decision-time").textContent = new Date(latest.decision.at).toLocaleString([], {weekday:"short", hour:"numeric", minute:"2-digit"});
  $("current-zone").textContent = `START: ${zone(latest.decision.current_zone)}`;
  $("gap").textContent = `OBSERVED GAP: ${latest.decision.observed_gap_minutes.toFixed(0)} MIN`;
  $("observed-next").textContent = `NEXT PICKUP: ${zone(latest.decision.next_observed_pickup_zone)}`;
  $("evidence").textContent = `${latest.evidence_label}. Not live advice.`;
  $("runner-zone").textContent = zone(latest.runner_up.zone);
  $("runner-return").textContent = `${money(latest.runner_up.expected_dollars_per_hour)}/hr`;
  $("home-credit").textContent = `Homeward credit: ${money(recommendation.homeward_credit)}`;
  $("stadium-wait").textContent = `${latest.stadium_finding.wait_minutes.toFixed(0)} MIN`;
  $("earnings").textContent = money(latest.observed_summary.earnings);
  $("trips").textContent = latest.observed_summary.trips;
  $("net-hour").textContent = `${money(latest.observed_summary.net_per_committed_hour_lower_bound)}/hr`;
  $("audit").textContent = JSON.stringify(latest.audit, null, 2);
  $("previous").disabled = selectedDecision === 0;
  $("next").disabled = selectedDecision === latest.decision_count - 1;
  renderTimeline(); renderWindowSplit();
}

function renderTimeline() {
  const container = $("timeline"); container.replaceChildren();
  latest.timeline.forEach((item) => {
    const button = document.createElement("button");
    button.className = `timeline-stop${item.index === selectedDecision ? " active" : ""}${item.annotated ? " annotated" : ""}`;
    const time = new Date(item.at).toLocaleTimeString([], {hour:"numeric", minute:"2-digit"});
    button.innerHTML = `<strong>${time}</strong><span>${item.observed_gap_minutes.toFixed(0)}m gap</span><small>${zone(item.recommendation_zone)}</small>`;
    button.addEventListener("click", () => { selectedDecision = item.index; loadBrief().catch(showError); });
    container.appendChild(button);
  });
}

function renderWindowSplit() {
  $("window-split").innerHTML = latest.window_split.map((item) => `<div class="split-row"><strong>${item.label}</strong><span>${money(item.net_per_committed_hour_lower_bound)}/hr</span><small>${item.trips} trips · ${item.committed_minutes.toFixed(0)} min</small></div>`).join("");
}

function makeActionButtons(selector, callback, prefix = "END AS") {
  const container = document.querySelector(selector); container.replaceChildren();
  ACTIONS.forEach((action) => {
    const button = document.createElement("button"); button.textContent = prefix ? `${prefix} ${action.replace("_", " ")}` : action.replace("_", " ");
    button.addEventListener("click", () => callback(action)); container.appendChild(button);
  });
}

async function startFieldTest() {
  const position = await currentPosition();
  const location = position ? {latitude:position.coords.latitude, longitude:position.coords.longitude} : {};
  fieldSession = await api("/api/field-tests", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({driver_zone:latest.decision.current_zone, vehicle_cost:Number($("vehicle-cost").value), decision_index:selectedDecision, ...location})});
  $("field-setup").classList.add("hidden"); $("field-choice").classList.remove("hidden");
  $("field-status").textContent = `${fieldSession.policy_version} frozen. Pick what you would do; ${window.RIDEEDGE_PRODUCT.name} is hidden.`;
}

async function chooseDriverAction(action) {
  fieldSession = await api(`/api/field-tests/${fieldSession.session_id}/choice`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action})});
  const recommendation = fieldSession.model_snapshot.recommendation;
  $("field-choice").classList.add("hidden"); $("field-active").classList.remove("hidden");
  $("driver-call").textContent = action.replace("_", " "); $("farol-call").textContent = recommendation.action.replace("_", " ");
  $("farol-zone").textContent = zone(recommendation.zone); $("field-explanation").textContent = fieldSession.model_snapshot.explanation.replace("Stay in", "Wait in");
  $("field-status").textContent = "Driver choice locked before reveal. Log only what actually happens.";
  startAutomaticWindow();
}

function startAutomaticWindow() {
  const expires = new Date(fieldSession.expires_at).getTime();
  const tick = () => {
    const remaining = Math.max(0, expires - Date.now());
    const seconds = Math.ceil(remaining / 1000);
    $("field-timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}`;
    if (remaining === 0) finishFieldTest(null).catch(showFieldError);
  };
  tick(); fieldTimer = setInterval(tick, 1000);
  if (navigator.geolocation) positionWatch = navigator.geolocation.watchPosition(sendPresence, () => {}, {enableHighAccuracy:true, maximumAge:30000});
}

async function sendPresence(position) {
  if (Date.now() - lastPresenceSent < 110000 || !fieldSession || fieldSession.status !== "ACTIVE") return;
  lastPresenceSent = Date.now();
  await api(`/api/field-tests/${fieldSession.session_id}/presence`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({latitude:position.coords.latitude, longitude:position.coords.longitude, accuracy_meters:position.coords.accuracy})}).catch(showFieldError);
}

async function addFieldEvent(eventType) {
  fieldSession = await api(`/api/field-tests/${fieldSession.session_id}/events`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({event_type:eventType})});
  $("field-status").textContent = `${eventType.replace("_", " ")} logged · ${fieldSession.events.length} event(s)`;
  if (eventType === "OVERRIDE") { overrideRecorded = true; $("override-actions").classList.remove("hidden"); $("end-field").classList.add("hidden"); }
}

async function finishFieldTest(actualAction) {
  if (overrideRecorded && !actualAction) { $("override-actions").classList.remove("hidden"); throw new Error("Choose what you actually did after changing plan."); }
  fieldSession = await api(`/api/field-tests/${fieldSession.session_id}/finish`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({actual_action:actualAction})});
  clearInterval(fieldTimer); if (positionWatch !== null) navigator.geolocation.clearWatch(positionWatch);
  $("field-active").classList.add("hidden"); $("field-result").classList.remove("hidden");
  const same = fieldSession.driver_choice.action === fieldSession.model_snapshot.recommendation.action;
  $("field-result").innerHTML = `<h3>Window recorded</h3><p>Driver and ${window.RIDEEDGE_PRODUCT.name} ${same ? "agreed" : "disagreed"}. Advice gradeable: <strong>${fieldSession.advice_gradeable ? "YES" : "NO"}</strong>. Observability: ${fieldSession.observability}.</p>`;
  $("field-status").textContent = "Saved locally. Learning remained off.";
}

$("vehicle-cost").addEventListener("change", () => loadBrief().catch(showError));
$("audit-toggle").addEventListener("click", () => $("audit").classList.toggle("hidden"));
$("volvo-demo").addEventListener("click", async () => { const command = await api(`/api/navigation/demo?vehicle_cost=${$("vehicle-cost").value}&decision=${selectedDecision}`, {method:"POST"}); $("volvo-status").textContent = `${command.destination.label} queued for 20 minutes. Demo only.`; });
$("previous").addEventListener("click", () => { selectedDecision -= 1; loadBrief().catch(showError); });
$("next").addEventListener("click", () => { selectedDecision += 1; loadBrief().catch(showError); });
$("start-field").addEventListener("click", () => startFieldTest().catch(showFieldError));
$("end-field").addEventListener("click", () => finishFieldTest(null).catch(showFieldError));
document.querySelectorAll("[data-event]").forEach((button) => button.addEventListener("click", () => addFieldEvent(button.dataset.event).catch(showFieldError)));
function showError(error) { $("evidence").textContent = error.message; }
function showFieldError(error) { $("field-status").textContent = error.message; }
makeActionButtons("[data-choice-buttons]", (action) => chooseDriverAction(action).catch(showFieldError), "");
makeActionButtons("[data-finish-buttons]", (action) => finishFieldTest(action).catch(showFieldError));
loadBrief().catch(showError);
