package com.rideedge.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.UUID

data class OpportunityItem(
    val id: String,
    val zone: String,
    val venueName: String,
    val action: String,
    val score: Double,
    val startsAt: String,
    val endsAt: String,
    val trafficMinutes: Double?,
    val distanceMiles: Double?,
    val routeBasis: String,
    val anchorId: String,
    val anchorLabel: String,
    val anchorLat: Double?,
    val anchorLon: Double?,
    val anchorApproved: Boolean,
    val safetyNotes: String,
    val navigationAvailable: Boolean,
    val note: String,
    val facts: List<String>,
)

data class SitHereRow(
    val zone: String,
    val hour: Int,
    val weekday: String,
    val score: Double,
    val meanEarnings: Double,
    val netPerHour: Double,
    val sampleTrips: Int,
    val grain: String,
    val repositionMinutes: Double,
    val repositionMiles: Double,
    val routeBasis: String,
    val thin: Boolean,
    val mapsUrl: String = "",
)

data class NearbyWindow(
    val id: String,
    val zone: String,
    val action: String,
    val actionPlain: String,
    val score: Double,
    val headline: String,
    val detail: String,
    val startsAt: String,
    val endsAt: String,
    val minutesAway: Double?,
    val milesAway: Double?,
    val routeBasis: String,
    val mapsUrl: String = "",
    val isSameZone: Boolean = false,
    val isAlreadyHere: Boolean = false,
    val sourceType: String = "scheduled",
    val windowLabel: String = "",
)

data class StationTrainArrival(
    val line: String,
    val headsign: String,
    val etaMinutes: Int,
    val arrivalClock: String,
    val status: String,
)

data class NearbyTrainStation(
    val id: String,
    val name: String,
    val distanceMiles: Double,
    val lines: List<String>,
    val mapsUrl: String,
    val nextEtaMinutes: Int?,
    val trains: List<StationTrainArrival>,
)

data class HereState(
    val zone: String,
    val label: String,
    val matched: String,
    val note: String,
    val action: String,
    val actionPlain: String,
    val spoken: String,
    val stayRow: SitHereRow?,
    val bestRow: SitHereRow?,
    val rankedHours: List<SitHereRow>,
    val nearby: List<NearbyWindow>,
    val nearbyStations: List<NearbyTrainStation> = emptyList(),
    val warnings: List<String>,
    val asOf: String = "",
    val recheckMinutes: Int = 15,
    val costNote: String = "",
    val crossesLake: Boolean = false,
    val sr520TollDollars: Double = 0.0,
    val recommendationId: String = "",
    val evidenceVersion: String = "v2",
    val stayEvidence: String = "",
    val advantageKnown: Boolean = false,
    val advantageNote: String = "Pickup advantage unverified",
    val stayOrMoveAction: String = "",
    val stayOrMoveReason: String = "",
    val stayOrMoveMoveCostDollars: Double = 0.0,
    val decisionState: String = "",
    val localLiveEvidence: Boolean = false,
    val localScheduledEvidence: Boolean = false,
    val originKind: String = "zone_centroid",
    val originPlaceId: String = "",
    val recommendationBasis: String = "",
    val destinationId: String = "",
    val destinationLabel: String = "",
    val suitabilityReason: String = "",
    val stagingApproved: Boolean = false,
    val navigationAvailable: Boolean = false,
)

data class TonightState(
    val shiftAction: String,
    val bestZone: String,
    val windowStartsAt: String,
    val windowEndsAt: String,
    val explanation: String,
    val narratorHeadline: String,
    val narratorSpoken: String,
    val narratorMode: String,
    val narratorModel: String,
    val risks: List<String>,
    val opportunities: List<OpportunityItem>,
)

data class AskOptionRow(
    val id: String,
    val area: String,
    val venue: String,
    val score: Double,
    val routeMinutes: Double?,
    val routeStatus: String,
    val eligible: Boolean,
    val reasons: List<String>,
)

data class AskChangeRow(
    val id: String,
    val kind: String,
    val before: String,
    val now: String,
    val why: String,
)

data class AskState(
    val snapshotId: String,
    val origin: String,
    val mode: String,
    val answerState: String,
    val answer: String,
    val bestId: String?,
    val generationSeconds: Double?,
    val explanationBullets: List<String>,
    val options: List<AskOptionRow>,
    val changes: List<AskChangeRow>,
    val limits: String,
)

data class ShiftSessionRow(
    val date: String,
    val weekday: String,
    val trips: Int,
    val grossEarnings: Double,
    val paidMiles: Double,
    val totalMiles: Double?,
    val deadheadMiles: Double?,
    val committedMinutes: Double?,
    val netPerCommittedHour: Double?,
)

data class ShiftLedgerState(
    val activeShiftId: String?,
    val activeStartedAt: String?,
    val activeStartOdometer: Double?,
    val activeNote: String,
    val activeElapsedMinutes: Double = 0.0,
    val activeTripCount: Int = 0,
    val activeRunningGross: Double = 0.0,
    val activeRunningMiles: Double = 0.0,
    val activeRunningGrossPerHour: Double = 0.0,
    val activeRunningNetPerHour: Double = 0.0,
    val earningsStatus: String,
    val calibratedMedianNetPerHour: Double?,
    val fridayMedianGross: Double?,
    val sessions: List<ShiftSessionRow>,
)

data class SeatacHourBucket(
    val hourIndex: Int,
    val hourLabel: String,
    val estimatedPlanes: Int,
    val sampledFlights: Int,
    val longHaulCount: Int,
    val lotArrivalTarget: String,
    val sampleFlights: List<String>,
    val isPeak: Boolean,
)

data class SeatacForecastState(
    val state: String,
    val cached: Boolean,
    val fetchedAt: String?,
    val bestHourLabel: String,
    val bestLotArrivalTime: String,
    val summary: String,
    val hours: List<SeatacHourBucket>,
)

data class ShiftCourseHotspot(
    val name: String,
    val area: String,
    val busynessPct: Int,
    val nextHourPct: Int?,
    val spilloutDrop: Int,
    val mapsUrl: String,
)

data class ShiftCourseStop(
    val hourIndex: Int,
    val windowLabel: String,
    val zone: String,
    val zoneLabel: String,
    val score: Double,
    val stagingSpot: String,
    val navigationAvailable: Boolean = false,
    val mapsUrl: String,
    val primaryTrigger: String,
    val hotVenues: List<String>,
    val spilloutVenues: List<String>,
    val events: List<String>,
    val flightArrivals: Int,
    val repositionLabel: String,
    val expectedNetPerHour: Double?,
    val sampleTrips: Int = 0,
    val rateBasis: String = "unknown",
    val driveMinutesFromPrev: Int = 0,
    val action: String = "",
    val decisionState: String = "",
    val recommendationBasis: String = "",
    val recheckMinutes: Int = 10,
)

data class ShiftCourseState(
    val isLiveBlast: Boolean,
    val generatedAt: String,
    val pollReceipt: String,
    val originLabel: String,
    val blastElapsedMs: Int,
    val totalFeedsOnline: Int,
    val totalFeedsCatalog: Int,
    val besttimeVenuesScanned: Int,
    val besttimeHotspotsActive: Int,
    val flightaware6hPlanes: Int,
    val flightawarePeakWindow: String,
    val nearbyTrainStations: Int,
    val aiModel: String,
    val aiBriefing: String,
    val planHeadline: String,
    val planImmediateMove: String,
    val planMidShiftPivot: String,
    val planAirportAndLate: String,
    val planWatchouts: String,
    val topHotspotsNow: List<ShiftCourseHotspot>,
    val stops: List<ShiftCourseStop>,
    val minutesAvailable: Int? = null,
    val repositionUnderMinutes: Int? = null,
    val finishNearLabel: String = "",
)

data class FeedHealthItem(
    val adapter: String,
    val label: String,
    val category: String,
    val stoplight: String,
    val mode: String,
    val enabled: Boolean = true,
    val healthy: Boolean = true,
    val signalCount: Int,
    val fetchedAt: String? = null,
    val ageMinutes: Double?,
    val detail: String,
    val plainSummary: String = detail,
)

data class HealthState(
    val connectedUrl: String,
    val shiftPhase: String,
    val shiftDetail: String,
    val shiftModel: String,
    val mockFeeds: Boolean,
    val snapshotId: String = "",
    val snapshotState: String = "ready",
    val snapshotAgeMinutes: Double? = null,
    val serviceHealthNote: String = "Shows API source availability and freshness — not whether sources agree with a recommendation.",
    val overallStoplight: String = "green",
    val greenCount: Int = 0,
    val amberCount: Int = 0,
    val redCount: Int = 0,
    val totalCount: Int = 0,
    val enabledCount: Int = 0,
    val disabledCount: Int = 0,
    val healthyCount: Int = 0,
    val degradedCount: Int = 0,
    val feeds: List<FeedHealthItem> = emptyList(),
)

data class TicketmasterQuerySummary(
    val label: String,
    val mode: String,
    val fetchedAt: String?,
    val totalElements: Int?,
    val fetchedCount: Int,
    val duplicateIdsInQuery: Int,
    val truncated: Boolean,
)

data class TicketmasterEventRecord(
    val eventId: String,
    val title: String,
    val venue: String,
    val city: String,
    val provider: String,
    val segment: String,
    val status: String,
    val localDate: String,
    val localTime: String,
    val timezone: String,
    val sourceStartTime: String,
    val sourceEndTime: String?,
    val sourceEndBasis: String,
    val estimatedDepartureStart: String?,
    val estimatedDepartureEnd: String?,
    val exitTimingBasis: String,
    val zone: String?,
    val zoneLabel: String,
    val mappingStatus: String,
    val signalId: String?,
    val exclusionReason: String?,
    val mappingExplanation: String,
    val url: String,
)

data class FeedDetailRecord(
    val id: String,
    val recordType: String,
    val title: String,
    val subtitle: String,
    val zoneLabel: String,
    val timeLabel: String,
    val basis: String,
    val detail: String,
    val alertText: String? = null,
)

data class FeedDetailState(
    val adapter: String,
    val label: String,
    val category: String,
    val kind: String,
    val snapshotId: String,
    val collectedAt: String?,
    val fetchedAt: String?,
    val ageMinutes: Double?,
    val mode: String,
    val stoplight: String,
    val detailState: String,
    val statusMessage: String,
    val summary: String,
    val plainSummary: String,
    val mappingNote: String? = null,
    val windowStart: String? = null,
    val windowEnd: String? = null,
    val uniqueEventsCount: Int = 0,
    val mappedSignalsCount: Int = 0,
    val excludedEventsCount: Int = 0,
    val duplicateCollapsedCount: Int = 0,
    val multiQueryDuplicates: Int = 0,
    val truncated: Boolean = false,
    val queries: List<TicketmasterQuerySummary> = emptyList(),
    val ticketmasterEvents: List<TicketmasterEventRecord> = emptyList(),
    val records: List<FeedDetailRecord> = emptyList(),
    val snapshotTransitionNotice: String? = null,
    val snapshotTransitionDiagnostic: String? = null,
)

data class AwarenessLayerCount(
    val id: String,
    val label: String,
    val count: Int,
)

data class AwarenessObservation(
    val id: String,
    val layer: String,
    val kind: String,
    val title: String,
    val detail: String,
    val zoneLabels: List<String>,
    val state: String,
    val freshness: String,
    val venue: String,
    val priority: String,
    val distanceMiles: Double?,
    val timingLabel: String,
    val startsAt: String,
    val endsAt: String,
)

data class AwarenessVenueActivity(
    val id: String,
    val name: String,
    val area: String,
    val typicalNow: Int?,
    val liveValue: Int?,
    val liveDelta: Int?,
    val liveRecent: Boolean = false,
    val note: String,
)

data class AwarenessState(
    val scope: String,
    val area: String,
    val locationLabel: String,
    val locationSource: String,
    val snapshotState: String,
    val snapshotAgeMinutes: Double?,
    val layers: List<AwarenessLayerCount>,
    val observations: List<AwarenessObservation>,
    val venueActivity: List<AwarenessVenueActivity>,
    val emptyNote: String,
)

object RideEdgeClient {
    val CANDIDATE_URLS = listOf(RideEdgeConnection.origin)
    val baseUrl: String = RideEdgeConnection.origin
    private var accessStore: AccessKeyStore? = null
    private val mutableAccessNote = kotlinx.coroutines.flow.MutableStateFlow<String?>(null)
    val accessNote: kotlinx.coroutines.flow.StateFlow<String?> = mutableAccessNote

    internal fun initializeAccess(store: AccessKeyStore) {
        accessStore = store
        mutableAccessNote.value = runCatching { store.read() }.fold(
            onSuccess = { if (it == null) "Connect to workstation with your RideEdge access key." else null },
            onFailure = { "The saved access key could not be read. Connect again." })
    }

    internal fun connect(key: String) {
        require(RideEdgeConnection.validKey(key))
        check(request("/auth/check", accessKey = key).optBoolean("authenticated"))
        checkNotNull(accessStore).write(key)
        mutableAccessNote.value = null
    }

    internal fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        timeoutMs: Int = 12000,
        accessKey: String? = null,
    ): JSONObject {
        check(BuildConfig.BUILD_TYPE != "preview") { "Network requests are disabled in the offline preview." }
        val key = accessKey ?: runCatching { accessStore?.read() }.getOrNull()
        if (key == null || !RideEdgeConnection.validKey(key)) {
            mutableAccessNote.value = "Connect to workstation with your RideEdge access key."
            throw AccessRequiredException(mutableAccessNote.value!!)
        }
        return try {
            RideEdgeHttpTransport().request(path, method, body, timeoutMs, key)
        } catch (error: AccessRequiredException) {
            mutableAccessNote.value = error.message
            throw error
        }
    }

    suspend fun fetchHealth(): HealthState = withContext(Dispatchers.IO) {
        val json = request("/api/health")
        val shift = json.optJSONObject("shift") ?: JSONObject()
        val fh = json.optJSONObject("feeds_health") ?: JSONObject()
        val feedsArr = fh.optJSONArray("feeds") ?: JSONArray()
        val feedItems = mutableListOf<FeedHealthItem>()
        for (i in 0 until feedsArr.length()) {
            val item = feedsArr.optJSONObject(i) ?: continue
            val mode = item.optString("mode", "live")
            val stoplight = item.optString("stoplight", "green")
            val enabled = if (item.has("enabled")) item.optBoolean("enabled", true) else mode !in setOf("needs_key", "disabled")
            val healthy = if (item.has("healthy")) item.optBoolean("healthy", stoplight == "green") else (enabled && stoplight == "green")
            val detail = item.optString("detail", "")
            feedItems += FeedHealthItem(
                adapter = item.optString("adapter", ""),
                label = item.optString("label", ""),
                category = item.optString("category", "Feeds"),
                stoplight = stoplight,
                mode = mode,
                enabled = enabled,
                healthy = healthy,
                signalCount = item.optInt("signal_count", 0),
                fetchedAt = if (item.isNull("fetched_at")) null else item.optString("fetched_at"),
                ageMinutes = if (item.isNull("age_minutes")) null else item.optDouble("age_minutes"),
                detail = detail,
                plainSummary = item.optString("plain_summary", detail).ifBlank { detail },
            )
        }
        val enabledCnt = if (fh.has("enabled_count")) fh.optInt("enabled_count") else feedItems.count { it.enabled }
        val disabledCnt = if (fh.has("disabled_count")) fh.optInt("disabled_count") else feedItems.count { !it.enabled }
        val healthyCnt = if (fh.has("healthy_count")) fh.optInt("healthy_count") else feedItems.count { it.healthy }
        val degradedCnt = if (fh.has("degraded_count")) fh.optInt("degraded_count") else feedItems.count { it.enabled && !it.healthy }
        HealthState(
            connectedUrl = baseUrl,
            shiftPhase = shift.optString("phase", "idle"),
            shiftDetail = shift.optString("detail", "Qwen loads when needed."),
            shiftModel = shift.optString("model", ""),
            mockFeeds = json.optBoolean("mock_feeds", false),
            snapshotId = fh.optString("snapshot_id", ""),
            snapshotState = fh.optString("snapshot_state", if (feedItems.isEmpty()) "missing" else "ready"),
            snapshotAgeMinutes = if (fh.isNull("snapshot_age_minutes")) null else fh.optDouble("snapshot_age_minutes"),
            serviceHealthNote = fh.optString(
                "service_health_note",
                "Shows API source availability and freshness — not whether sources agree with a recommendation."
            ),
            overallStoplight = fh.optString("overall_stoplight", "green"),
            greenCount = fh.optInt("green_count", 0),
            amberCount = fh.optInt("amber_count", 0),
            redCount = fh.optInt("red_count", 0),
            totalCount = fh.optInt("total_count", feedItems.size),
            enabledCount = enabledCnt,
            disabledCount = disabledCnt,
            healthyCount = healthyCnt,
            degradedCount = degradedCnt,
            feeds = feedItems,
        )
    }

    suspend fun fetchFeedDetail(adapter: String, snapshotId: String? = null): FeedDetailState = withContext(Dispatchers.IO) {
        val enc = URLEncoder.encode(adapter.trim(), "UTF-8")
        val trimmedSnap = snapshotId?.trim()?.takeIf { it.isNotBlank() }
        val snapQuery = trimmedSnap?.let {
            "?snapshot_id=${URLEncoder.encode(it, "UTF-8")}"
        } ?: ""
        try {
            val json = request("/api/feeds/$enc/detail$snapQuery", method = "GET")
            parseFeedDetail(json)
        } catch (e: IllegalStateException) {
            val msg = e.message.orEmpty()
            if (trimmedSnap != null && (msg.contains("snapshot_changed", ignoreCase = true) || msg.contains("HTTP 409", ignoreCase = true))) {
                val latestJson = request("/api/feeds/$enc/detail", method = "GET")
                val parsed = parseFeedDetail(latestJson)
                parsed.copy(
                    snapshotTransitionNotice = "Updated to the latest data",
                    snapshotTransitionDiagnostic = "Snapshot changed ($trimmedSnap → ${parsed.snapshotId.ifBlank { "latest" }}); HTTP 409 snapshot_changed.",
                )
            } else {
                throw e
            }
        }
    }

    internal fun parseFeedDetail(json: JSONObject): FeedDetailState {
        val kind = json.optString("kind", "general")
        val queriesArr = json.optJSONArray("queries") ?: JSONArray()
        val queries = mutableListOf<TicketmasterQuerySummary>()
        for (i in 0 until queriesArr.length()) {
            val q = queriesArr.optJSONObject(i) ?: continue
            queries += TicketmasterQuerySummary(
                label = q.optString("label", "query-$i"),
                mode = q.optString("mode", "cache"),
                fetchedAt = if (q.isNull("fetched_at")) null else q.optString("fetched_at"),
                totalElements = if (q.isNull("total_elements")) null else q.optInt("total_elements"),
                fetchedCount = q.optInt("fetched_count", 0),
                duplicateIdsInQuery = q.optInt("duplicate_ids_in_query", 0),
                truncated = q.optBoolean("truncated", false),
            )
        }
        val tmEventsArr = json.optJSONArray("events") ?: JSONArray()
        val tmEvents = mutableListOf<TicketmasterEventRecord>()
        for (i in 0 until tmEventsArr.length()) {
            val ev = tmEventsArr.optJSONObject(i) ?: continue
            tmEvents += TicketmasterEventRecord(
                eventId = ev.optString("event_id", "tm-$i"),
                title = ev.optString("title", "Ticketed event"),
                venue = ev.optString("venue", "unknown"),
                city = ev.optString("city", "unknown"),
                provider = ev.optString("provider", "Ticketmaster Discovery v2"),
                segment = ev.optString("segment", "unknown"),
                status = ev.optString("status", "unknown"),
                localDate = ev.optString("local_date", "unknown"),
                localTime = ev.optString("local_time", "unknown"),
                timezone = ev.optString("timezone", "America/Los_Angeles"),
                sourceStartTime = ev.optString("source_start_time", "unknown"),
                sourceEndTime = if (ev.isNull("source_end_time")) null else ev.optString("source_end_time").takeIf { it.isNotBlank() },
                sourceEndBasis = ev.optString("source_end_basis", "not_reported_by_provider"),
                estimatedDepartureStart = if (ev.isNull("estimated_departure_start")) null else ev.optString("estimated_departure_start"),
                estimatedDepartureEnd = if (ev.isNull("estimated_departure_end")) null else ev.optString("estimated_departure_end"),
                exitTimingBasis = ev.optString("exit_timing_basis", ""),
                zone = if (ev.isNull("zone")) null else ev.optString("zone"),
                zoneLabel = ev.optString("zone_label", "Unmapped area"),
                mappingStatus = ev.optString("mapping_status", "excluded"),
                signalId = if (ev.isNull("signal_id")) null else ev.optString("signal_id"),
                exclusionReason = if (ev.isNull("exclusion_reason")) null else ev.optString("exclusion_reason"),
                mappingExplanation = ev.optString("mapping_explanation", ""),
                url = ev.optString("url", ""),
            )
        }
        val recArr = json.optJSONArray("records") ?: JSONArray()
        val records = mutableListOf<FeedDetailRecord>()
        if (tmEvents.isEmpty()) {
            for (i in 0 until recArr.length()) {
                val r = recArr.optJSONObject(i) ?: continue
                val rType = r.optString("record_type", r.optString("kind", kind))
                val title = when {
                    r.optString("station").isNotBlank() && r.optString("route_line").isNotBlank() ->
                        "${r.optString("route_line")} · ${r.optString("station")}"
                    r.optString("vessel").isNotBlank() ->
                        "WSF ${r.optString("vessel")} · ${r.optString("route")}"
                    else -> r.optString("title", "Record ${i + 1}")
                }
                val subtitle = when {
                    r.optString("direction_headsign").isNotBlank() -> r.optString("direction_headsign")
                    r.optString("terminal").isNotBlank() -> r.optString("terminal")
                    r.optString("venue").isNotBlank() -> r.optString("venue")
                    else -> ""
                }
                val timeLabel = when {
                    r.optString("arrival_time").isNotBlank() -> {
                        val eta = if (!r.isNull("eta_minutes")) " (~${r.optInt("eta_minutes")}m)" else ""
                        "Arrival: ${r.optString("arrival_time")}$eta"
                    }
                    r.optString("starts_at").isNotBlank() -> {
                        val endPart = r.optString("ends_at").takeIf { it.isNotBlank() }?.let { " → $it" } ?: ""
                        "${r.optString("starts_at")}$endPart"
                    }
                    r.optString("retrieved_at").isNotBlank() -> "Checked: ${r.optString("retrieved_at")}"
                    else -> ""
                }
                val detail = when {
                    r.optString("time_meaning").isNotBlank() -> {
                        val delay = r.optInt("delay_minutes", 0)
                        val delayNote = if (delay > 0) " · ${delay}m delay" else ""
                        "${r.optString("time_meaning")}$delayNote"
                    }
                    r.optString("detail").isNotBlank() -> r.optString("detail")
                    else -> ""
                }
                records += FeedDetailRecord(
                    id = r.optString("id", "rec-$i"),
                    recordType = rType,
                    title = title,
                    subtitle = subtitle,
                    zoneLabel = r.optString("zone_label", ""),
                    timeLabel = timeLabel,
                    basis = r.optString("basis", "unknown"),
                    detail = detail,
                    alertText = if (r.isNull("service_alert")) null else r.optString("service_alert").takeIf { it.isNotBlank() },
                )
            }
        }
        val detailText = json.optString("summary", "")
        return FeedDetailState(
            adapter = json.optString("adapter", ""),
            label = json.optString("label", ""),
            category = json.optString("category", ""),
            kind = kind,
            snapshotId = json.optString("snapshot_id", ""),
            collectedAt = if (json.isNull("collected_at")) null else json.optString("collected_at"),
            fetchedAt = if (json.isNull("fetched_at")) null else json.optString("fetched_at"),
            ageMinutes = if (json.isNull("age_minutes")) null else json.optDouble("age_minutes"),
            mode = json.optString("mode", "unknown"),
            stoplight = json.optString("stoplight", "amber"),
            detailState = json.optString("detail_state", "ready"),
            statusMessage = json.optString("status_message", ""),
            summary = detailText,
            plainSummary = json.optString("plain_summary", detailText).ifBlank { detailText },
            mappingNote = if (json.isNull("mapping_note")) null else json.optString("mapping_note"),
            windowStart = if (json.isNull("window_start")) null else json.optString("window_start"),
            windowEnd = if (json.isNull("window_end")) null else json.optString("window_end"),
            uniqueEventsCount = json.optInt("unique_events_count", tmEvents.size),
            mappedSignalsCount = json.optInt("mapped_signals_count", 0),
            excludedEventsCount = json.optInt("excluded_events_count", 0),
            duplicateCollapsedCount = json.optInt("duplicate_collapsed_count", 0),
            multiQueryDuplicates = json.optInt("multi_query_duplicates", 0),
            truncated = json.optBoolean("truncated", false),
            queries = queries,
            ticketmasterEvents = tmEvents,
            records = records,
        )
    }

    suspend fun refreshAllFeeds(): Unit = withContext(Dispatchers.IO) {
        request("/api/feeds/refresh", method = "POST", body = JSONObject(), timeoutMs = 25000)
    }

    suspend fun fetchSeatacForecast(pull: Boolean = false): SeatacForecastState = withContext(Dispatchers.IO) {
        val json = if (pull) {
            request("/api/seatac/forecast", method = "POST", body = JSONObject(), timeoutMs = 25000)
        } else {
            request("/api/seatac/forecast", method = "GET")
        }
        val hoursArr = json.optJSONArray("hours") ?: JSONArray()
        val hours = mutableListOf<SeatacHourBucket>()
        for (i in 0 until hoursArr.length()) {
            val h = hoursArr.optJSONObject(i) ?: continue
            val samplesArr = h.optJSONArray("sample_flights") ?: JSONArray()
            val samples = mutableListOf<String>()
            for (j in 0 until samplesArr.length()) {
                val s = samplesArr.optString(j)
                if (s.isNotBlank()) samples += s
            }
            hours += SeatacHourBucket(
                hourIndex = h.optInt("hour_index", i),
                hourLabel = h.optString("hour_label", ""),
                estimatedPlanes = h.optInt("estimated_planes", 0),
                sampledFlights = h.optInt("sampled_flights", 0),
                longHaulCount = h.optInt("long_haul_count", 0),
                lotArrivalTarget = h.optString("lot_arrival_target", ""),
                sampleFlights = samples,
                isPeak = h.optBoolean("is_peak", false),
            )
        }
        SeatacForecastState(
            state = json.optString("state", "not_pulled_yet"),
            cached = json.optBoolean("cached", false),
            fetchedAt = if (json.isNull("fetched_at")) null else json.optString("fetched_at"),
            bestHourLabel = json.optString("best_hour_label", ""),
            bestLotArrivalTime = json.optString("best_lot_arrival_time", ""),
            summary = json.optString("summary", ""),
            hours = hours,
        )
    }

    suspend fun toggleGpuShift(start: Boolean): String = withContext(Dispatchers.IO) {
        val verb = if (start) "start" else "stop"
        val json = request("/api/shift/$verb", method = "POST", body = JSONObject())
        json.optString("detail", if (start) "Requesting GPU1 lease…" else "Releasing GPU1 lease…")
    }

    suspend fun fetchHereByText(
        at: String,
        vehicleCost: Double = 0.45,
        valueOfTime: Double = 25.0,
        driverMode: String = "active_working",
        maxRepositionMinutes: Int = 20,
    ): HereState = withContext(Dispatchers.IO) {
        val enc = URLEncoder.encode(at.trim(), "UTF-8")
        val encMode = URLEncoder.encode(driverMode.trim(), "UTF-8")
        val json = request(
            "/api/here?at=$enc&vehicle_cost=$vehicleCost&value_of_time=$valueOfTime&driver_mode=$encMode&max_reposition_minutes=$maxRepositionMinutes"
        )
        parseHere(json)
    }

    suspend fun fetchHereByGps(
        latitude: Double,
        longitude: Double,
        vehicleCost: Double = 0.45,
        valueOfTime: Double = 25.0,
        driverMode: String = "active_working",
        maxRepositionMinutes: Int = 20,
    ): HereState = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("latitude", latitude)
            .put("longitude", longitude)
        val encMode = URLEncoder.encode(driverMode.trim(), "UTF-8")
        val json = request(
            "/api/here?vehicle_cost=$vehicleCost&value_of_time=$valueOfTime&driver_mode=$encMode&max_reposition_minutes=$maxRepositionMinutes",
            method = "POST",
            body = body,
        )
        parseHere(json)
    }

    private fun parseSitRow(obj: JSONObject?): SitHereRow? {
        if (obj == null) return null
        return SitHereRow(
            zone = obj.optString("zone", ""),
            hour = obj.optInt("hour", 0),
            weekday = obj.optString("weekday", ""),
            score = obj.optDouble("score", 0.0),
            meanEarnings = obj.optDouble("historical_mean_earnings", 0.0),
            netPerHour = obj.optDouble("historical_net_per_hour", 0.0),
            sampleTrips = obj.optInt("sample_trips", 0),
            grain = obj.optString("grain", "none"),
            repositionMinutes = obj.optDouble("reposition_minutes", 0.0),
            repositionMiles = obj.optDouble("reposition_miles", 0.0),
            routeBasis = obj.optString("route_basis", "assumed"),
            thin = obj.optBoolean("thin", true),
            mapsUrl = obj.optString("maps_url", ""),
        )
    }

    internal fun parseHere(json: JSONObject): HereState {
        val place = json.optJSONObject("place") ?: JSONObject()
        val sitHere = json.optJSONObject("sit_here") ?: JSONObject()
        val rankedArr = sitHere.optJSONArray("ranked") ?: JSONArray()
        val ranked = mutableListOf<SitHereRow>()
        for (i in 0 until rankedArr.length()) {
            parseSitRow(rankedArr.optJSONObject(i))?.let { ranked.add(it) }
        }
        val placeZone = place.optString("zone", "")
        val nearbyArr = json.optJSONArray("nearby") ?: JSONArray()
        val nearby = mutableListOf<NearbyWindow>()
        for (i in 0 until nearbyArr.length()) {
            val row = nearbyArr.optJSONObject(i) ?: continue
            val rowZone = row.optString("zone", "")
            val isSameZone = if (row.has("is_same_zone")) {
                row.optBoolean("is_same_zone", false)
            } else {
                rowZone.isNotBlank() && rowZone.equals(placeZone, ignoreCase = true)
            }
            val minsAway = if (row.isNull("minutes_away")) null else row.optDouble("minutes_away")
            val milesAway = if (row.isNull("miles_away")) null else row.optDouble("miles_away")
            val isAlreadyHere = if (row.has("is_already_here")) {
                row.optBoolean("is_already_here", false)
            } else {
                isSameZone && (minsAway == null || minsAway <= 2.0) && (milesAway == null || milesAway <= 0.25)
            }
            val rawSourceType = row.optString("source_type", "").trim().lowercase()
            val detailLow = row.optString("detail", "").lowercase()
            val sourceType = when {
                rawSourceType in setOf("live", "scheduled", "estimated") -> rawSourceType
                "live" in detailLow || "real-time" in detailLow || "realtime" in detailLow -> "live"
                else -> "scheduled"
            }
            nearby.add(
                NearbyWindow(
                    id = row.optString("id", "near-$i"),
                    zone = rowZone,
                    action = row.optString("action", "WATCH"),
                    actionPlain = row.optString("action_plain", "Watch"),
                    score = row.optDouble("score", 0.0),
                    headline = row.optString("headline", row.optString("title", "")),
                    detail = row.optString("detail", ""),
                    startsAt = row.optString("starts_at", ""),
                    endsAt = row.optString("ends_at", ""),
                    minutesAway = minsAway,
                    milesAway = milesAway,
                    routeBasis = row.optString("route_basis", "assumed"),
                    mapsUrl = row.optString("maps_url", ""),
                    isSameZone = isSameZone,
                    isAlreadyHere = isAlreadyHere,
                    sourceType = sourceType,
                    windowLabel = row.optString("window_label", ""),
                )
            )
        }
        val stationsArr = json.optJSONArray("nearby_stations") ?: JSONArray()
        val stations = mutableListOf<NearbyTrainStation>()
        for (i in 0 until stationsArr.length()) {
            val st = stationsArr.optJSONObject(i) ?: continue
            val linesArr = st.optJSONArray("lines") ?: JSONArray()
            val lines = (0 until linesArr.length()).mapNotNull { linesArr.optString(it) }
            val trainsArr = st.optJSONArray("trains") ?: JSONArray()
            val trains = mutableListOf<StationTrainArrival>()
            for (j in 0 until trainsArr.length()) {
                val tr = trainsArr.optJSONObject(j) ?: continue
                trains += StationTrainArrival(
                    line = tr.optString("line", "Link"),
                    headsign = tr.optString("headsign", ""),
                    etaMinutes = tr.optInt("eta_minutes", 1),
                    arrivalClock = tr.optString("arrival_clock", ""),
                    status = tr.optString("status", "live"),
                )
            }
            stations += NearbyTrainStation(
                id = st.optString("id", "st-$i"),
                name = st.optString("name", ""),
                distanceMiles = st.optDouble("distance_miles", 0.0),
                lines = lines,
                mapsUrl = st.optString("maps_url", ""),
                nextEtaMinutes = if (st.isNull("next_eta_minutes")) null else st.optInt("next_eta_minutes"),
                trains = trains,
            )
        }
        val warnArr = json.optJSONArray("warnings") ?: JSONArray()
        val warnings = (0 until warnArr.length()).mapNotNull { warnArr.optString(it) }
        val roadCost = json.optJSONObject("road_cost") ?: JSONObject()
        val som = json.optJSONObject("stay_or_move_card") ?: json.optJSONObject("stay_or_move") ?: JSONObject()
        val bestJson = json.optJSONObject("best") ?: sitHere.optJSONObject("best") ?: JSONObject()
        val rawAction = json.optString("action", som.optString("action", "WATCH"))
        val normAction = if (rawAction.equals("STAY", ignoreCase = true)) "WAIT" else rawAction
        return HereState(
            zone = place.optString("zone", ""),
            label = place.optString("label", "Selected area"),
            matched = place.optString("matched", ""),
            note = place.optString("note", ""),
            action = normAction,
            actionPlain = json.optString("action_plain", som.optString("action_plain", "Watch this area")),
            spoken = json.optString("spoken", som.optString("spoken", "")),
            stayRow = parseSitRow(json.optJSONObject("stay") ?: sitHere.optJSONObject("stay")),
            bestRow = parseSitRow(json.optJSONObject("best") ?: sitHere.optJSONObject("best")),
            rankedHours = ranked,
            nearby = nearby,
            nearbyStations = stations,
            warnings = warnings,
            asOf = json.optString("as_of", ""),
            recheckMinutes = json.optInt("recheck_minutes", 15),
            costNote = roadCost.optString("cost_note", ""),
            crossesLake = roadCost.optBoolean("crosses_lake", false),
            sr520TollDollars = roadCost.optDouble("sr520_toll_dollars", 0.0),
            recommendationId = json.optString("recommendation_id", ""),
            evidenceVersion = json.optString("evidence_version", "v2"),
            stayEvidence = som.optString("stay_evidence", ""),
            advantageKnown = som.optBoolean("advantage_known", false),
            advantageNote = som.optString("advantage_note", "Pickup advantage unverified"),
            stayOrMoveAction = som.optString("action", ""),
            stayOrMoveReason = som.optString("reason", ""),
            stayOrMoveMoveCostDollars = som.optDouble("move_cost_dollars", 0.0),
            decisionState = som.optString("decision_state", json.optString("action", "WATCH")),
            localLiveEvidence = som.optBoolean("local_live_evidence", false),
            localScheduledEvidence = som.optBoolean("local_scheduled_evidence", false),
            originKind = place.optString("origin_kind", som.optString("origin_kind", "zone_centroid")),
            originPlaceId = place.optString("place_id", som.optString("origin_place_id", "")),
            recommendationBasis = som.optString("recommendation_basis", bestJson.optString("recommendation_basis", "")),
            destinationId = som.optString("destination_id", bestJson.optString("destination_id", "")),
            destinationLabel = som.optString("destination_label", bestJson.optString("destination_label", "")),
            suitabilityReason = som.optString("suitability_reason", bestJson.optString("suitability_reason", "")),
            stagingApproved = som.optBoolean("staging_approved", bestJson.optBoolean("staging_approved", false)),
            navigationAvailable = som.optBoolean("navigation_available", bestJson.optBoolean("navigation_available", false)),
        )
    }

    suspend fun pollBestTimeArea(area: String, forceLive: Boolean = true): Int = withContext(Dispatchers.IO) {
        val enc = URLEncoder.encode(area.trim(), "UTF-8")
        val json = request("/api/besttime/poll?area=$enc&max_venues=5&force_live=$forceLive", method = "POST", body = JSONObject(), timeoutMs = 45000)
        json.optInt("polled_venues", 0)
    }

    suspend fun fetchTonight(
        hours: Int = 12,
        vehicleCost: Double = 0.45,
        valueOfTime: Double = 22.0,
    ): TonightState = withContext(Dispatchers.IO) {
        val json = request(
            "/api/tonight?hours=$hours&vehicle_cost=$vehicleCost&value_of_time=$valueOfTime",
            timeoutMs = 20000,
        )
        val decision = json.optJSONObject("shift_decision") ?: JSONObject()
        val bestWindow = decision.optJSONObject("best_window") ?: JSONObject()
        val narration = json.optJSONObject("narration") ?: JSONObject()
        val brain = json.optJSONObject("brain") ?: JSONObject()
        val risksArr = narration.optJSONArray("risks") ?: JSONArray()
        val risks = (0 until risksArr.length()).mapNotNull { risksArr.optString(it) }

        val oppArr = json.optJSONArray("opportunities") ?: JSONArray()
        val opps = mutableListOf<OpportunityItem>()
        for (i in 0 until oppArr.length()) {
            val item = oppArr.optJSONObject(i) ?: continue
            val route = item.optJSONObject("route") ?: JSONObject()
            val anchor = item.optJSONObject("anchor") ?: JSONObject()
            val factsArr = item.optJSONArray("facts") ?: JSONArray()
            val facts = mutableListOf<String>()
            for (j in 0 until factsArr.length()) {
                val f = factsArr.optJSONObject(j) ?: continue
                facts.add("${f.optString("text")} (${f.optString("basis")})")
            }
            opps.add(
                OpportunityItem(
                    id = item.optString("id", "opp-$i"),
                    zone = item.optString("zone", ""),
                    venueName = item.optString("venue_name", ""),
                    action = item.optString("action", "WATCH"),
                    score = item.optDouble("score", 0.0),
                    startsAt = item.optString("starts_at", ""),
                    endsAt = item.optString("ends_at", ""),
                    trafficMinutes = if (route.isNull("traffic_minutes")) null else route.optDouble("traffic_minutes"),
                    distanceMiles = if (route.isNull("distance_miles")) null else route.optDouble("distance_miles"),
                    routeBasis = route.optString("basis", "assumed"),
                    anchorId = anchor.optString("id", ""),
                    anchorLabel = anchor.optString("label", ""),
                    anchorLat = if (anchor.isNull("latitude")) null else anchor.optDouble("latitude"),
                    anchorLon = if (anchor.isNull("longitude")) null else anchor.optDouble("longitude"),
                    anchorApproved = anchor.optString("approval_status") == "approved",
                    safetyNotes = anchor.optString("safety_notes", ""),
                    navigationAvailable = item.optBoolean("navigation_available", false),
                    note = item.optString("note", ""),
                    facts = facts,
                )
            )
        }
        val sortedOpps = opps.sortedWith(
            compareBy<OpportunityItem> { it.action.equals("AVOID", ignoreCase = true) }
                .thenByDescending { it.score }
        )
        TonightState(
            shiftAction = decision.optString("action", "CHECK WINDOW"),
            bestZone = decision.optString("best_zone", ""),
            windowStartsAt = bestWindow.optString("starts_at", ""),
            windowEndsAt = bestWindow.optString("ends_at", ""),
            explanation = decision.optString("explanation", ""),
            narratorHeadline = narration.optString("headline", ""),
            narratorSpoken = narration.optString("spoken", brain.optString("detail", "")),
            narratorMode = brain.optString("mode", "idle"),
            narratorModel = brain.optString("model", "qwen3.8-27b"),
            risks = risks,
            opportunities = sortedOpps,
        )
    }

    suspend fun approveAnchor(anchorId: String, notes: String = "Driver-approved curb on Pixel."): JSONObject =
        withContext(Dispatchers.IO) {
            val body = JSONObject()
                .put("approval_status", "approved")
                .put("safety_notes", notes)
            request("/api/anchors/${URLEncoder.encode(anchorId, "UTF-8")}/approve", method = "POST", body = body)
        }

    suspend fun saveCustomParkedSpot(
        latitude: Double,
        longitude: Double,
        label: String,
        zone: String = "",
    ): JSONObject = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("zone", zone)
            .put("label", label)
            .put("latitude", latitude)
            .put("longitude", longitude)
            .put("action", "WAIT")
            .put("approval_status", "approved")
            .put("safety_notes", "Saved while parked from Pixel 10 Pro XL.")
        request("/api/anchors/custom", method = "POST", body = body)
    }

    suspend fun sendToVolvo(opportunityId: String, vehicleCost: Double = 0.45): JSONObject =
        withContext(Dispatchers.IO) {
            request(
                "/api/navigation/opportunity/${URLEncoder.encode(opportunityId, "UTF-8")}?vehicle_cost=$vehicleCost",
                method = "POST",
                body = JSONObject(),
            )
        }

    suspend fun fetchAskContext(area: String): AskState = withContext(Dispatchers.IO) {
        val resolvedArea = canonicalAwarenessArea(area)
        val enc = URLEncoder.encode(resolvedArea, "UTF-8")
        val json = try {
            request("/api/ask/context?mode=live&area=$enc")
        } catch (_: Exception) {
            request("/api/ask/context?mode=demo&step=0")
        }
        val ctx = json.optJSONObject("context") ?: JSONObject()
        val comp = json.optJSONObject("comparison") ?: JSONObject()
        parseAskComparison(
            snapshotId = ctx.optString("snapshot_id", ""),
            origin = ctx.optString("origin", resolvedArea),
            mode = ctx.optString("mode", "live"),
            answerState = "Python comparison",
            comp = comp,
            explanation = emptyList(),
            genSeconds = null,
        )
    }

    suspend fun updateAskConstraints(
        snapshotId: String,
        origin: String,
        mode: String,
        minutesAvailable: Int,
        repositionUnderMinutes: Int,
        finishNear: String,
    ): AskState = withContext(Dispatchers.IO) {
        val constraints = JSONObject()
            .put("minutes_available", minutesAvailable)
            .put("reposition_under_minutes", repositionUnderMinutes)
            .put("finish_near", finishNear)
        val body = JSONObject()
            .put("snapshot_id", snapshotId)
            .put("constraints", constraints)
        val comp = request("/api/ask/compare", method = "POST", body = body)
        parseAskComparison(
            snapshotId = snapshotId,
            origin = origin,
            mode = mode,
            answerState = "Python comparison · updated constraints",
            comp = comp,
            explanation = emptyList(),
            genSeconds = null,
        )
    }

    suspend fun askQwen(
        current: AskState,
        question: String,
        minutesAvailable: Int,
        repositionUnderMinutes: Int,
        finishNear: String,
        fresh: Boolean = false,
    ): AskState = withContext(Dispatchers.IO) {
        val constraints = JSONObject()
            .put("minutes_available", minutesAvailable)
            .put("reposition_under_minutes", repositionUnderMinutes)
            .put("finish_near", finishNear)
        val body = JSONObject()
            .put("snapshot_id", current.snapshotId)
            .put("question", question)
            .put("constraints", constraints)
            .put("fresh", fresh)
        var job = request("/api/ask", method = "POST", body = body)
        val requestId = job.optString("request_id", "")
        var polls = 0
        while (job.optString("state") == "working" && polls < 120) {
            delay(650)
            job = request("/api/ask/jobs/$requestId")
            polls++
        }
        val state = job.optString("state", "error")
        if (state != "ready") {
            val detail = job.optString("detail", "Qwen is currently unavailable; Python comparison remains active.")
            return@withContext current.copy(
                answerState = "Local model $state",
                answer = detail,
            )
        }
        val comp = job.optJSONObject("comparison") ?: JSONObject()
        val expArr = job.optJSONArray("explanation") ?: JSONArray()
        val bullets = (0 until expArr.length()).mapNotNull {
            expArr.optJSONObject(it)?.optString("text")
        }
        val exec = job.optJSONObject("execution")
        val genSeconds = if (exec != null && !exec.isNull("generation_seconds")) {
            exec.optDouble("generation_seconds")
        } else null
        parseAskComparison(
            snapshotId = current.snapshotId,
            origin = current.origin,
            mode = current.mode,
            answerState = job.optString("answer_state", "Fresh local inference"),
            comp = comp,
            explanation = bullets,
            genSeconds = genSeconds,
            overrideAnswer = job.optString("answer", ""),
        )
    }

    private fun parseAskComparison(
        snapshotId: String,
        origin: String,
        mode: String,
        answerState: String,
        comp: JSONObject,
        explanation: List<String>,
        genSeconds: Double?,
        overrideAnswer: String? = null,
    ): AskState {
        val optArr = comp.optJSONArray("options") ?: JSONArray()
        val options = mutableListOf<AskOptionRow>()
        for (i in 0 until optArr.length()) {
            val o = optArr.optJSONObject(i) ?: continue
            val rArr = o.optJSONArray("reasons") ?: JSONArray()
            val reasons = (0 until rArr.length()).mapNotNull { rArr.optString(it) }
            options.add(
                AskOptionRow(
                    id = o.optString("id", "opt-$i"),
                    area = o.optString("area", ""),
                    venue = o.optString("venue", ""),
                    score = o.optDouble("score", 0.0),
                    routeMinutes = if (o.isNull("route_minutes")) null else o.optDouble("route_minutes"),
                    routeStatus = o.optString("route_status", ""),
                    eligible = o.optBoolean("eligible", false),
                    reasons = reasons,
                )
            )
        }
        val chgArr = comp.optJSONArray("changes") ?: JSONArray()
        val changes = mutableListOf<AskChangeRow>()
        for (i in 0 until chgArr.length()) {
            val c = chgArr.optJSONObject(i) ?: continue
            changes.add(
                AskChangeRow(
                    id = c.optString("id", "chg-$i"),
                    kind = c.optString("kind", ""),
                    before = c.optString("before", ""),
                    now = c.optString("now", ""),
                    why = c.optString("why", ""),
                )
            )
        }
        return AskState(
            snapshotId = snapshotId,
            origin = origin,
            mode = mode,
            answerState = answerState,
            answer = if (!overrideAnswer.isNullOrBlank()) overrideAnswer else comp.optString("answer", ""),
            bestId = if (comp.isNull("best_id")) null else comp.optString("best_id"),
            generationSeconds = genSeconds,
            explanationBullets = explanation,
            options = options,
            changes = changes,
            limits = comp.optString("limits", ""),
        )
    }

    suspend fun fetchShiftLedger(vehicleCost: Double = 0.45): ShiftLedgerState = withContext(Dispatchers.IO) {
        val hist = request("/api/history?vehicle_cost=$vehicleCost")
        val shifts = request("/api/history/shifts")
        val active = shifts.optJSONObject("active")
        val sessArr = hist.optJSONArray("sessions") ?: JSONArray()
        val sessions = mutableListOf<ShiftSessionRow>()
        for (i in 0 until minOf(sessArr.length(), 10)) {
            val s = sessArr.optJSONObject(i) ?: continue
            sessions.add(
                ShiftSessionRow(
                    date = s.optString("date", ""),
                    weekday = s.optString("weekday", ""),
                    trips = s.optInt("trips", 0),
                    grossEarnings = s.optDouble("gross_earnings", 0.0),
                    paidMiles = s.optDouble("paid_miles", 0.0),
                    totalMiles = if (s.isNull("total_miles")) null else s.optDouble("total_miles"),
                    deadheadMiles = if (s.isNull("deadhead_miles")) null else s.optDouble("deadhead_miles"),
                    committedMinutes = if (s.isNull("committed_minutes")) null else s.optDouble("committed_minutes"),
                    netPerCommittedHour = if (s.isNull("net_per_committed_hour")) null else s.optDouble("net_per_committed_hour"),
                )
            )
        }
        ShiftLedgerState(
            activeShiftId = active?.optString("shift_id"),
            activeStartedAt = active?.optString("started_at"),
            activeStartOdometer = if (active != null && !active.isNull("start_odometer_miles")) active.optDouble("start_odometer_miles") else null,
            activeNote = active?.optString("note", "") ?: "",
            activeElapsedMinutes = active?.optDouble("elapsed_minutes", 0.0) ?: 0.0,
            activeTripCount = active?.optInt("running_trip_count", 0) ?: 0,
            activeRunningGross = active?.optDouble("running_gross_earnings", 0.0) ?: 0.0,
            activeRunningMiles = active?.optDouble("running_paid_miles", 0.0) ?: 0.0,
            activeRunningGrossPerHour = active?.optDouble("running_gross_per_hour", 0.0) ?: 0.0,
            activeRunningNetPerHour = active?.optDouble("running_net_per_hour", 0.0) ?: 0.0,
            earningsStatus = hist.optString("earnings_status", "uncalibrated"),
            calibratedMedianNetPerHour = if (hist.isNull("calibrated_median_net_per_hour")) null else hist.optDouble("calibrated_median_net_per_hour"),
            fridayMedianGross = if (hist.isNull("friday_median_gross")) null else hist.optDouble("friday_median_gross"),
            sessions = sessions,
        )
    }

    suspend fun startOdometerShift(odometerMiles: Double, note: String): Unit = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("odometer_miles", odometerMiles)
            .put("note", note)
            .put("idempotency_key", UUID.randomUUID().toString())
        request("/api/history/shifts/start", method = "POST", body = body)
    }

    suspend fun endOdometerShift(odometerMiles: Double, note: String): Unit = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("odometer_miles", odometerMiles)
            .put("note", note)
            .put("idempotency_key", UUID.randomUUID().toString())
        request("/api/history/shifts/end", method = "POST", body = body)
    }

    suspend fun logShiftTrip(grossFare: Double, miles: Double, note: String = ""): Unit = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("gross_fare", grossFare)
            .put("miles", miles)
            .put("note", note)
            .put("idempotency_key", UUID.randomUUID().toString())
        request("/api/history/shifts/trip", method = "POST", body = body)
    }

    internal fun buildDriverOutcomePayload(
        status: String,
        zone: String,
        recommendedAction: String = "",
        recommendationId: String = "",
        evidenceVersion: String = "v2",
        note: String = "",
        idempotencyKey: String = UUID.randomUUID().toString(),
        recordedAt: String? = null,
    ): JSONObject {
        val obj = JSONObject()
            .put("status", status)
            .put("zone", zone)
            .put("recommended_action", recommendedAction)
            .put("recommendation_id", recommendationId)
            .put("evidence_version", evidenceVersion.ifBlank { "v2" })
            .put("note", note)
            .put("idempotency_key", idempotencyKey)
        if (!recordedAt.isNullOrBlank()) {
            obj.put("recorded_at", recordedAt)
        }
        return obj
    }

    suspend fun logDriverOutcome(
        status: String,
        zone: String,
        recommendedAction: String = "",
        recommendationId: String = "",
        evidenceVersion: String = "v2",
        note: String = "",
        idempotencyKey: String = UUID.randomUUID().toString(),
        recordedAt: String? = null,
    ): Unit = withContext(Dispatchers.IO) {
        val body = buildDriverOutcomePayload(
            status = status,
            zone = zone,
            recommendedAction = recommendedAction,
            recommendationId = recommendationId,
            evidenceVersion = evidenceVersion,
            note = note,
            idempotencyKey = idempotencyKey,
            recordedAt = recordedAt,
        )
        request("/api/history/outcomes", method = "POST", body = body)
    }

    fun canonicalAwarenessArea(raw: String): String {
        return when (raw.trim().lowercase()) {
            "bellevue", "bellevue core", "bellevue_core", "downtown bellevue" -> "bellevue_core"
            "kirkland", "kirkland waterfront", "kirkland_waterfront", "downtown kirkland waterfront", "kirkland_downtown" -> "kirkland_waterfront"
            "totem lake", "totem_lake", "kingsgate", "home", "example_public_origin", "home (kingsgate)", "home · kingsgate", "kingsgate / totem lake", "totem lake / kingsgate", "village at totem lake", "totem_lake_village", "village_at_totem_lake" -> "totem_lake"
            "redmond", "redmond downtown", "redmond_downtown", "downtown redmond / town center", "redmond town center" -> "redmond_downtown"
            "bothell", "downtown bothell" -> "bothell"
            "woodinville", "woodinville wine country", "woodinville_wine" -> "woodinville_wine"
            "seattle", "downtown seattle", "seattle core", "seattle_core", "slu", "south lake union", "downtown / slu" -> "seattle_core"
            "capitol hill", "capitol_hill", "capitol hill / pike-pine" -> "capitol_hill"
            "seattle center", "seattle_center", "queen anne", "climate pledge", "seattle center / lower queen anne" -> "seattle_center"
            "ballard", "fremont", "fremont / ballard", "fremont_ballard" -> "fremont_ballard"
            "sodo", "sodo stadiums", "sodo_stadiums", "lumen field", "sodo / stadium district" -> "sodo_stadiums"
            "uw", "u district", "university district", "uw_district" -> "uw_district"
            "seatac", "seatac airport", "sea airport", "sea_airport", "sea airport (seatac)" -> "sea_airport"
            "central district", "central_district", "central district / madison" -> "central_district"
            "columbia city", "columbia_city", "columbia city / rainier" -> "columbia_city"
            "west seattle", "west_seattle", "west seattle junction" -> "west_seattle"
            else -> raw.trim().ifBlank { "bellevue_core" }
        }
    }

    suspend fun fetchAwarenessByArea(
        scope: String = "nearby",
        area: String = "bellevue_core",
        radius: Double = 8.0,
        period: String = "all",
        layer: String = "all",
    ): AwarenessState = withContext(Dispatchers.IO) {
        val resolvedArea = canonicalAwarenessArea(area)
        val effectiveScope = if (layer == "airport") "metro" else scope
        val encArea = URLEncoder.encode(resolvedArea, "UTF-8")
        val json = request("/api/awareness?scope=$effectiveScope&area=$encArea&radius=$radius&period=$period&layer=$layer")
        parseAwareness(json)
    }

    suspend fun fetchAwarenessByGps(
        latitude: Double,
        longitude: Double,
        radius: Double = 8.0,
        period: String = "all",
        layer: String = "all",
    ): AwarenessState = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("latitude", latitude)
            .put("longitude", longitude)
        val json = request(
            "/api/awareness?radius=$radius&period=$period&layer=$layer",
            method = "POST",
            body = body,
        )
        parseAwareness(json)
    }

    private fun parseAwareness(json: JSONObject): AwarenessState {
        val snap = json.optJSONObject("snapshot") ?: JSONObject()
        val layersArr = json.optJSONArray("layers") ?: JSONArray()
        val layers = mutableListOf<AwarenessLayerCount>()
        for (i in 0 until layersArr.length()) {
            val l = layersArr.optJSONObject(i) ?: continue
            layers.add(
                AwarenessLayerCount(
                    id = l.optString("id", ""),
                    label = l.optString("label", ""),
                    count = l.optInt("count", 0),
                )
            )
        }
        val obsArr = json.optJSONArray("observations") ?: JSONArray()
        val observations = mutableListOf<AwarenessObservation>()
        for (i in 0 until obsArr.length()) {
            val o = obsArr.optJSONObject(i) ?: continue
            val zArr = o.optJSONArray("zone_labels") ?: JSONArray()
            val zoneLabels = (0 until zArr.length()).mapNotNull { zArr.optString(it) }
            observations.add(
                AwarenessObservation(
                    id = o.optString("id", "obs-$i"),
                    layer = o.optString("layer", ""),
                    kind = o.optString("kind", ""),
                    title = o.optString("title", ""),
                    detail = o.optString("detail", ""),
                    zoneLabels = zoneLabels,
                    state = o.optString("state", ""),
                    freshness = o.optString("freshness", ""),
                    venue = if (o.isNull("venue")) "" else o.optString("venue", ""),
                    priority = if (o.isNull("priority")) "" else o.optString("priority", ""),
                    distanceMiles = if (o.isNull("distance_miles")) null else o.optDouble("distance_miles"),
                    timingLabel = o.optString("timing_label", ""),
                    startsAt = o.optString("starts_at", ""),
                    endsAt = o.optString("ends_at", ""),
                )
            )
        }
        val actArr = json.optJSONArray("venue_activity") ?: JSONArray()
        val activities = mutableListOf<AwarenessVenueActivity>()
        for (i in 0 until actArr.length()) {
            val a = actArr.optJSONObject(i) ?: continue
            activities.add(
                AwarenessVenueActivity(
                    id = a.optString("id", "act-$i"),
                    name = a.optString("name", ""),
                    area = a.optString("area", ""),
                    typicalNow = if (a.isNull("typical_now")) null else a.optInt("typical_now"),
                    liveValue = if (a.isNull("live_value")) null else a.optInt("live_value"),
                    liveDelta = if (a.isNull("live_delta")) null else a.optInt("live_delta"),
                    liveRecent = a.optBoolean("live_recent", false),
                    note = a.optString("note", ""),
                )
            )
        }
        return AwarenessState(
            scope = json.optString("scope", "nearby"),
            area = json.optString("area", ""),
            locationLabel = json.optString("location_label", "Metro"),
            locationSource = json.optString("location_source", "selected_area"),
            snapshotState = snap.optString("state", "ready"),
            snapshotAgeMinutes = if (snap.isNull("age_minutes")) null else snap.optDouble("age_minutes"),
            layers = layers,
            observations = observations,
            venueActivity = activities,
            emptyNote = json.optString("empty_note", "No active signals match this filter."),
        )
    }

    suspend fun fetchShiftCourse(
        area: String = "Bellevue",
        latitude: Double? = null,
        longitude: Double? = null,
        pullAll: Boolean = true,
        minutesAvailable: Int? = null,
        repositionUnderMinutes: Int? = null,
        finishNear: String? = null,
    ): ShiftCourseState = withContext(Dispatchers.IO) {
        val encArea = URLEncoder.encode(area.trim(), "UTF-8")
        val queryParts = mutableListOf("area=$encArea", "pull_all=$pullAll")
        if (minutesAvailable != null && minutesAvailable > 0) {
            queryParts += "minutes_available=$minutesAvailable"
        }
        if (repositionUnderMinutes != null && repositionUnderMinutes > 0) {
            queryParts += "reposition_under_minutes=$repositionUnderMinutes"
        }
        if (!finishNear.isNullOrBlank()) {
            queryParts += "finish_near=${URLEncoder.encode(finishNear.trim(), "UTF-8")}"
        }
        val queryString = queryParts.joinToString("&")
        // R06/R07: Send device coordinates in the POST JSON body rather than URL query parameters
        val hasCoords = latitude != null && longitude != null
        val json = if (pullAll || hasCoords) {
            val body = JSONObject()
                .put("area", area.trim())
                .put("pull_all", pullAll)
            if (latitude != null && longitude != null) {
                body.put("latitude", latitude).put("longitude", longitude)
            }
            if (minutesAvailable != null && minutesAvailable > 0) {
                body.put("minutes_available", minutesAvailable)
            }
            if (repositionUnderMinutes != null && repositionUnderMinutes > 0) {
                body.put("reposition_under_minutes", repositionUnderMinutes)
            }
            if (!finishNear.isNullOrBlank()) {
                body.put("finish_near", finishNear.trim())
            }
            request(
                "/api/ask/course?$queryString",
                method = "POST",
                body = body,
                timeoutMs = if (pullAll) 90000 else 25000,
            )
        } else {
            request("/api/ask/course?$queryString", method = "GET", timeoutMs = 25000)
        }
        val apis = json.optJSONObject("apis_fired") ?: JSONObject()
        val hsArr = json.optJSONArray("top_hotspots_now") ?: JSONArray()
        val hotspots = mutableListOf<ShiftCourseHotspot>()
        for (i in 0 until hsArr.length()) {
            val h = hsArr.optJSONObject(i) ?: continue
            hotspots += ShiftCourseHotspot(
                name = h.optString("name", ""),
                area = h.optString("area", ""),
                busynessPct = h.optInt("busyness_pct", 0),
                nextHourPct = if (h.isNull("next_hour_pct")) null else h.optInt("next_hour_pct"),
                spilloutDrop = h.optInt("spillout_drop", 0),
                mapsUrl = h.optString("maps_url", ""),
            )
        }
        val stopsArr = json.optJSONArray("stops") ?: JSONArray()
        val stops = mutableListOf<ShiftCourseStop>()
        for (i in 0 until stopsArr.length()) {
            val s = stopsArr.optJSONObject(i) ?: continue
            val hvArr = s.optJSONArray("hot_venues") ?: JSONArray()
            val spArr = s.optJSONArray("spillout_venues") ?: JSONArray()
            val evArr = s.optJSONArray("events") ?: JSONArray()
            val netVal = if (s.isNull("expected_net_per_hour")) {
                null
            } else {
                s.optDouble("expected_net_per_hour", Double.NaN).takeIf { !it.isNaN() && !it.isInfinite() }
            }
            stops += ShiftCourseStop(
                hourIndex = s.optInt("hour_index", i + 1),
                windowLabel = s.optString("window_label", ""),
                zone = s.optString("zone", ""),
                zoneLabel = s.optString("zone_label", ""),
                score = s.optDouble("score", 0.0),
                stagingSpot = s.optString("staging_spot", ""),
                navigationAvailable = s.optBoolean("navigation_available", false),
                mapsUrl = s.optString("maps_url", ""),
                primaryTrigger = s.optString("primary_trigger", ""),
                hotVenues = (0 until hvArr.length()).mapNotNull { hvArr.optString(it) },
                spilloutVenues = (0 until spArr.length()).mapNotNull { spArr.optString(it) },
                events = (0 until evArr.length()).mapNotNull { evArr.optString(it) },
                flightArrivals = s.optInt("flight_arrivals", 0),
                repositionLabel = s.optString("reposition_label", ""),
                expectedNetPerHour = netVal,
                sampleTrips = s.optInt("sample_trips", 0),
                rateBasis = s.optString("rate_basis", "unknown"),
                driveMinutesFromPrev = s.optInt("drive_minutes_from_prev", 0),
                action = s.optString("action", ""),
                decisionState = s.optString("decision_state", ""),
                recommendationBasis = s.optString("recommendation_basis", ""),
                recheckMinutes = s.optInt("recheck_minutes", 10),
            )
        }
        val ap = json.optJSONObject("action_plan") ?: JSONObject()
        val ca = json.optJSONObject("constraints_applied") ?: JSONObject()
        ShiftCourseState(
            isLiveBlast = json.optBoolean("is_live_blast", pullAll),
            generatedAt = json.optString("generated_at", ""),
            pollReceipt = json.optString("poll_receipt", ""),
            originLabel = json.optString("origin_label", area),
            blastElapsedMs = json.optInt("blast_elapsed_ms", 0),
            totalFeedsOnline = apis.optInt("total_feeds_online", 20),
            totalFeedsCatalog = apis.optInt("total_feeds_catalog", 23),
            besttimeVenuesScanned = apis.optInt("besttime_venues_scanned", 0),
            besttimeHotspotsActive = apis.optInt("besttime_hotspots_active", 0),
            flightaware6hPlanes = apis.optInt("flightaware_6h_planes", 0),
            flightawarePeakWindow = apis.optString("flightaware_peak_window", ""),
            nearbyTrainStations = apis.optInt("nearby_train_stations", 0),
            aiModel = json.optString("ai_model", "Qwen 3.5 Shift Commander"),
            aiBriefing = json.optString("ai_briefing", ""),
            planHeadline = ap.optString("headline", ""),
            planImmediateMove = ap.optString("immediate_move", ""),
            planMidShiftPivot = ap.optString("mid_shift_pivot", ""),
            planAirportAndLate = ap.optString("airport_and_late_bank", ""),
            planWatchouts = ap.optString("tactical_watchouts", ""),
            topHotspotsNow = hotspots,
            stops = stops,
            minutesAvailable = if (ca.isNull("minutes_available") || !ca.has("minutes_available")) minutesAvailable else ca.optInt("minutes_available"),
            repositionUnderMinutes = if (ca.isNull("reposition_under_minutes") || !ca.has("reposition_under_minutes")) repositionUnderMinutes else ca.optInt("reposition_under_minutes"),
            finishNearLabel = ca.optString("finish_near_label", finishNear ?: ""),
        )
    }
}
