# Architecture and evidence boundaries

## Application layers

| Layer | Main source | Responsibility |
|---|---|---|
| Collection | `farol/adapters/`, `farol/collect.py` | Provider requests, normalization, caching, freshness and failures |
| Guidance | `farol/radar.py`, `farol/decision_engine.py` | Candidate evidence, arrival eligibility, deterministic ranking and alternatives |
| Model policy | `farol/decision_policy.yaml`, `farol/decision_policy.py` | Review cadence, bounded model instructions and feature policy |
| Local inference | `farol/local.py`, `farol/local_runtime.py`, `farol/model_queue.py` | Local model requests, admission, timeouts and resource ownership |
| API | `farol/api.py`, `farol/radar_api.py`, `farol/access.py` | Authenticated client access and bounded active planning sessions |
| Monitoring | `farol/studio.py`, `farol/studio_monitor.py`, `farol/model_metrics.py` | Runtime/source state, evaluation metrics and provenance |
| Phone and car | `android/app/src/main/java/com/rideedge/app/` | Now/Nearby/Plan, location context, source details and navigation handoff |

## Decision process

The engine evaluates event departures, closing windows, ongoing venue activity, travel and evidence coverage. Repeated choices are allowed: variety is not evidence. A future event is not automatically an immediate opportunity. Missing data is unknown, not zero demand. A contextual fallback is labeled as unverified positioning context.

Qwen receives bounded candidate evidence rather than an instruction to echo the deterministic winner. Python validates allowed choices and support references, including the `none_supported` response. YAML instructions do not replace application-side validation. Authored rules, experimental imports, historic research and observed provider records retain distinct roles.

The Plan outlook revisits opportunities across six hours; it is not a promise that the driver will follow a continuous route or remain free after a passenger ride. Provider and model failures remain visible. Agreement between Qwen and the algorithm is inspectable, but is not proof of faster pickups.

## Sources and limits

Event adapters include Ticketmaster, SeatGeek and public schedules. Place/hour context can come from Google Places; venue activity can come from BestTime when configured and permitted. Weather, roads, transport and airport arrivals add context. Census and neighborhood research are static context, not live rider observations; their presence must not be described as proof of pickup demand.

BestTime percentages are relative to an individual venue's typical peak, not comparable headcounts. Flight arrivals are not queue length, guaranteed rematches, or airport-bound passenger requests. External provider text is untrusted data. Historical trip-derived ranking and experimental Uber Assistant text imports remain separate from the modern activity-radar path.

## Privacy boundary

The model processes prompts on the configured local server. Provider APIs receive the requests made to them, and navigation destinations are handed to Google Maps. Local processing therefore reduces cloud-model exposure; it does not imply that all app/network activity is offline.

Credentials are configured locally. This source snapshot contains public geography and labeled test/demo fixtures, not private driving records or recorded model sessions. The monitoring UI should distinguish available integrations from configured, fresh, decision-active sources.
