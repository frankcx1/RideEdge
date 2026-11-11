# Radar phone/car contract, version 1

The `/api/radar`, `/api/radar/context` and `/api/radar/preview` responses use integer
`schema_version: 1`. Pydantic validates outgoing responses; `RadarParser` is the
single Kotlin parser. Unknown additive fields are compatible. Missing required
fields and unsupported major versions produce explicit errors, never zero-valued
coordinates or an empty success state. Optional fields have documented null/false
defaults in the models.

`source_snapshot_id` identifies the source inputs. `snapshot_id` identifies the
candidate snapshot used by Ask. `decision_revision` identifies the selection
within that snapshot. `location_generation` tracks active-origin changes. A newer
GPS fix or runtime warning is not by itself a new decision. None of these fields
is a sufficient cache key for actionability: public responses re-evaluate expiry,
arrival timing and current-origin radius on every read.

Coordinates are WGS84 degrees; distances are miles; route durations are minutes.
`radius_miles` is straight-line distance, separate from road-route miles. A route
from a previous origin loses its live-traffic label and becomes a clearly marked
estimate until refreshed. Unknown provider measurement time stays null. Venue
busyness retains its provider basis and is not a rider count.

All wire timestamps carry UTC offsets. Plan contains six contiguous one-hour
elapsed intervals. Local presentation uses America/Los_Angeles and must label the
two 1 AM intervals distinctly on fall-back nights. The synthetic shared fixture
starts at 11 PM PDT October 31 and ends at 4 AM PST November 1, 2026.

`server_time` and `valid_until` let the client calculate remaining validity without
trusting the phone's wall clock. Each immediate place additionally has an
`actionable` flag and a potentially earlier `valid_until`. The client records
receipt with elapsedRealtime and boot identity; receipt is not persisted. Reboot,
elapsed-time rollback, stale evidence/location, and expired place deadlines block
navigation. Future Plan options remain inspectable but are not immediate actions.

Now and the first Plan selection share one authoritative ID. If that primary
expires or leaves the five-mile radius, the projection withholds it instead of
promoting a different destination while retaining the old first Plan choice.
Alternatives are rechecked independently. The next planning pass produces a new
validated selection; this contract does not force arbitrary destination changes.

Arrival assessment is shared by immediate ranking, algorithm sequence search,
Qwen sequence validation, and request-time action checks. A scheduled opportunity
must start no later than estimated arrival and leave at least ten minutes before
its end. This is a conservative planning rule, not an observed wait or measured
pickup probability. A shorter route can invalidate an opportunity by arriving
too early; merely arriving before the event window ends is insufficient.

Additive fields `arrival_at` and `arrival_eligible` explain the assessed leg.
Evidence retains its source window and adds `role` (opportunity or context),
`arrival_relevant`, and the algorithm's relative `activity_weight` contribution.
Only applicable opportunity contributions count, capped at 85 before applicable
area-context adjustments; context by itself cannot produce a recommendation.
These are heuristic weights, not counts or calibrated probabilities. Inactive
evidence remains inspectable and cannot boost a currently busy venue. Nearby
retains upcoming/ended opportunities without a Navigate action; the phone shows
their activity windows and explains excluded timing behind the detail disclosure.

Future legs are reassessed from the preceding choice for each method. Qwen gets
source basis, role, and both window boundaries, but no contribution weights,
algorithm selections, or arrival labels derived from the algorithm's sequence.
Phone/car summary reasons use relevant opportunity evidence; retained future
events and routine transit context cannot supply the immediate headline reason.
The existing source freshness and origin-expiry gates continue to apply. A timing
rule does not validate a provider's assumed event duration or passenger behavior.

Source health/detail responses now include `radar_participation`, separately
identified by radar `snapshot_id`, `source_snapshot_id`, review time and origin
label. The retained source cache may be newer than the decision; these identities
are not interchangeable. No decision or an obsolete location generation produces
`no_decision`. Expired evidence/location produces `stale`, with no current Now
support count while the saved Plan remains inspectable.

Participation reports enumerate immediate candidates, source-construction
exclusions, evidence attached to the selected Now opportunity/context, provider
route use and the displayed Plan intervals using that source. Counts are records
or candidate places, never people. They do not attribute causality to Qwen. The
full decision audit stays in memory; ordinary radar projections omit its candidate
table. Reading reports does not start model/provider work or extend the session.
Normal explicit source-refresh behavior and existing budgets are unchanged.

Candidate construction records timing, unknown area/kind, identity mismatch,
closed/quiet/missing BestTime readings, airport-context isolation, replaced
synthetic BestTime magnitudes and unattached area-context records. Exclusions are
for the immediate review; a future Plan interval may legitimately use the same
record. Candidate statuses separately explain arrival timing, radius/further
criteria and transport-only context. Current adapter source constants supplement
historical aliases; unmatched sources remain visible instead of disappearing.

BestTime retained reports preserve provider percentages, separate live/forecast
retrieval times, unknown measurement time, identity match and basic reading
eligibility. A stale retained reading is not labeled current crowd activity.

Curated BestTime identity is checked against retained provider ID, name, street
number/city and coordinates (within the existing 300-meter check), independently
of data availability. Live evidence additionally needs the same returned provider
ID and a successful identity check in its normalized receipt. Legacy live rows
without that metadata remain inspectable but cannot provide live support; a
matched weekly pattern can still support a typical-pattern recommendation.
Direct area-scan rows use their self-contained provider ID/name/address/location,
not a claim of independent curated-catalog matching. `identity_review` explains
the method and per-stream checks in source details. Raw cached receipts/reports
are not rewritten by read-time review.

Standing hospital/office/transit windows from `situational_waves` are unverified
local assumptions, not dated schedules. New signals use `assumed` and no passenger
magnitude. Retained records are corrected in memory with original labels/values
preserved under `assumption_review` in source details. Assumed-only opportunities
are labeled Best guess even when their heuristic windows have start/end times;
unverified last-train cutoffs cannot create destination recommendations. Qwen
receives the same corrected basis and explicit assumption text as the algorithm.

A Qwen fallback reason does not turn scheduled or typical support into a best
guess. If that reason conflicts with the selected place's evidence strength, the
display uses a neutral selection statement and `qwen_reason_review` preserves
the reported code and mismatch for inspection. No replacement model motive is
inferred. Actual Best guess choices explicitly say current activity is unverified.

`scheduler.next_review_at` reflects the actual scheduler deadline. A preview has
its own origin and no active review schedule; exploring an area does not mutate
the driving session. Runtime cleanup is independent from Qwen answer validity.

The internal Qwen request compacts the existing bounded evidence projection with
source/time dictionaries and named place columns. Each interval maps its allowed
place IDs to evidence IDs. Decoding preserves exact source labels, timestamp
offsets, unknown values and all six candidate pools. Algorithm scores and choices
remain absent. This internal encoding does not change the public radar schema or
remove the measured input ceiling; oversized requests still fail explicitly.

The Kotlin state store preserves the previous valid snapshot and original receipt
on schema errors, rejects late responses from an obsolete origin request, and
resolves navigation IDs against current state at tap time. Network failure does
not extend expiry. No networking or location collection occurs in these models.

`RadarRepository` now owns the application session and Compose observes it through
`RadarViewModel`. It polls every 30 seconds while active, or five seconds during
a bounded explicit review window, with offline backoff up to 120 seconds. Phone
fixes are requested at most once per minute; no coordinate history is persisted.
Nearby previews use a separate generation and never change the driving origin.
A failed GPS request cannot reload the last selected-area context as phone data.

Backend origin generations clear preceding snapshot/question history. Historical
snapshot and completed-answer payloads are pruned after 20 minutes. Six hours
without a context update clears the retained session, and reads do not renew it.
An expired backend returns the existing context-required error; the repository
backs off before resending context during a supported active session. Expiry or
shutdown invalidates late workers before they can restore cleared data, while
their resource cleanup still runs. The last view can remain inspectable during
an active session even after its evidence becomes too old for navigation.

The initial CarAppService consumes this repository. Car row identity is retained
between explicit refreshes while eligibility is always live; a stale captured
Navigate action cannot bypass the shared store. Host location delivery and
physical session behavior are not yet accepted. Deploy a compatible backend before
installing the production app that requires this contract. Only the separate
offline preview APK has been installed; it uses synthetic assets and blocks all
backend requests, GPS and navigation. The production API has not yet been
restarted; the acceptance ledger records that deployment gate.
