package com.rideedge.app

import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant

/** Versioned shared phone/car data. Rendering does not parse JSON or perform I/O. */
data class RadarOrigin(
    val label: String, val zone: String, val mode: String,
    val latitude: Double, val longitude: Double, val fixAt: Instant?,
)
data class RadarEvidence(
    val id: String, val source: String, val basis: String, val text: String,
    val fetchedAt: Instant?, val measurementTime: Instant?, val timingNote: String?,
    val arrivalRelevant: Boolean = true, val startsAt: Instant? = null, val endsAt: Instant? = null,
    val role: String? = null,
)
data class RadarRoute(val minutes: Double, val miles: Double, val basis: String, val fetchedAt: Instant?)
data class RadarPlace(
    val id: String, val name: String, val zone: String, val latitude: Double, val longitude: Double,
    val radiusMiles: Double, val withinNowRadius: Boolean, val route: RadarRoute,
    val evidence: List<RadarEvidence>, val strength: String, val category: String,
    val pinBasis: String, val navigationNote: String, val busyness: Double?, val busynessBasis: String?,
    val actionable: Boolean, val validUntil: Instant?, val unavailableReason: String?,
    val contextOnly: Boolean, val qwenReason: String?,
    val reachable: Boolean = true,
    val activityCoverage: String = "",
    val decisionClass: String = "",
    val hoursStatus: String = "",
) {
    val isPositioningFallback: Boolean get() = decisionClass == "contextual_fallback"
    val supportingEvidence: RadarEvidence? get() = evidence.firstOrNull { it.arrivalRelevant && it.role != "context" }
}
data class RadarInterval(
    val startsAt: Instant, val endsAt: Instant, val selectedId: String?,
    val selectionBasis: String, val options: List<RadarPlace>, val repeatArea: Boolean, val note: String,
    val routeReference: String = "prior_area",
) {
    val selected: RadarPlace? get() = options.firstOrNull { it.id == selectedId }
}
data class RadarModelStatus(val state: String, val detail: String, val code: String?)
data class RadarSchedule(val state: String, val nextReviewAt: Instant?, val sessionExpiresAt: Instant?)
data class RadarFeed(val adapter: String, val mode: String, val fetchedAt: Instant?, val count: Int?)
data class RadarSnapshot(
    val schemaVersion: Int, val snapshotId: String, val sourceSnapshotId: String,
    val decisionRevision: String, val locationGeneration: Long,
    val generatedAt: Instant, val serverTime: Instant, val validUntil: Instant,
    val origin: RadarOrigin, val now: List<RadarPlace>, val nearby: List<RadarPlace>,
    val further: List<RadarPlace>, val plan: List<RadarInterval>, val algorithmPlan: List<RadarInterval>,
    val qwen: RadarModelStatus, val scheduler: RadarSchedule, val cleanup: RadarModelStatus?,
    val evidenceStale: Boolean, val locationStale: Boolean, val refreshing: Boolean,
    val feeds: List<RadarFeed> = emptyList(), val excludedCount: Int = 0,
    val limits: String = "Activity signals do not reveal Uber requests or guarantee a rider.",
    val airportNote: String = "Airport rematch and queue wait are unknown.",
    val locationNote: String = "",
    val activityCoverage: String = "",
    val decisionPolicy: String = "",
    val decisionState: String = "",
    val decisionMessage: String = "",
)

class RadarContractException(val code: String, message: String) : IllegalArgumentException(message)

object RadarParser {
    fun parse(json: JSONObject): RadarSnapshot {
        try {
            val version = json.get("schema_version")
            if (version !is Int && version !is Long) invalid("schema_version must be an integer")
            if ((version as Number).toLong() != 1L)
                throw RadarContractException("schema_mismatch", "RideEdge needs a compatible app/backend version.")
            val origin = json.obj("origin")
            val mode = origin.text("mode")
            require(mode in setOf("device", "selected_area"))
            val runtime = json.optJSONObject("runtime")
            val cleanup = runtime?.optJSONObject("cleanup")?.let(::modelStatus)
            val schedule = json.obj("scheduler")
            val generation = json.get("location_generation")
            require(generation is Int || generation is Long)
            val snapshot = RadarSnapshot(
                1, json.text("snapshot_id"), json.text("source_snapshot_id"), json.text("decision_revision"),
                (generation as Number).toLong(), json.time("generated_at"), json.time("server_time"),
                json.time("valid_until"), RadarOrigin(origin.text("label"), origin.text("zone"), mode,
                    origin.coordinate("latitude", 47.0, 48.2), origin.coordinate("longitude", -123.0, -121.5),
                    origin.optionalTime("fix_at")),
                json.array("now").mapObjects(::place), json.array("nearby").mapObjects(::place),
                json.array("further").mapObjects(::place), json.array("plan").mapObjects(::interval),
                json.array("algorithm_plan").mapObjects(::interval), modelStatus(json.obj("qwen")),
                RadarSchedule(schedule.text("state"), schedule.optionalTime("next_review_at"),
                    schedule.optionalTime("session_expires_at")), cleanup,
                json.flag("evidence_stale"), json.flag("location_stale"), json.optionalFlag("refreshing"),
                json.optJSONArray("feeds")?.mapObjects { feed -> RadarFeed(feed.text("adapter"),
                    feed.optionalText("mode") ?: "unknown", feed.optionalTime("fetched_at"),
                    feed.optionalNumber("signal_count")?.toInt()) } ?: emptyList(),
                json.optionalNumber("excluded_count")?.toInt() ?: 0,
                json.optionalText("limits") ?: "Activity signals do not reveal Uber requests or guarantee a rider.",
                json.optionalText("airport_note") ?: "Airport rematch and queue wait are unknown.",
                json.optionalText("location_note") ?: "",
                json.optionalText("activity_coverage") ?: "",
                json.optionalText("decision_policy") ?: "",
                json.optionalText("decision_state") ?: "",
                json.optionalText("decision_message") ?: "",
            )
            listOf(snapshot.plan, snapshot.algorithmPlan).forEach { plan ->
                require(plan.size == 6)
                require(plan.all { Duration.between(it.startsAt, it.endsAt).seconds == 3600L })
                require(plan.zipWithNext().all { (a, b) -> a.endsAt == b.startsAt })
            }
            require(snapshot.now.isEmpty() || snapshot.now.first().id == snapshot.plan.first().selectedId)
            return snapshot
        } catch (error: RadarContractException) {
            throw error
        } catch (_: Exception) {
            // Never echo malformed payloads containing origin/account details.
            invalid("RideEdge returned an incomplete or invalid decision.")
        }
    }

    private fun modelStatus(json: JSONObject) = RadarModelStatus(
        json.text("state"), json.optionalText("detail") ?: "", json.optionalText("code"))

    private fun place(json: JSONObject): RadarPlace {
        val route = json.obj("route")
        return RadarPlace(json.text("id"), json.text("name"), json.text("zone"),
            json.coordinate("latitude", 47.0, 48.2), json.coordinate("longitude", -123.0, -121.5),
            json.nonnegative("radius_miles"), json.flag("within_now_radius"),
            RadarRoute(route.nonnegative("minutes"), route.nonnegative("miles"), route.text("basis"),
                route.optionalTime("fetched_at")),
            json.array("evidence").mapObjects { e -> RadarEvidence(e.text("id"), e.text("source"),
                e.text("basis"), e.text("text"), e.optionalTime("fetched_at"),
                e.optionalTime("measurement_time"), e.optionalText("timing_note"),
                if (e.isNull("arrival_relevant")) true else e.flag("arrival_relevant"),
                e.optionalTime("starts_at"), e.optionalTime("ends_at"), e.optionalText("role")) },
            json.text("strength"), json.text("category"), json.text("pin_basis"), json.text("navigation_note"),
            json.optionalNumber("busyness"), json.optionalText("busyness_basis"),
            json.optionalFlag("actionable"), json.optionalTime("valid_until"), json.optionalText("unavailable_reason"),
            json.optionalFlag("context_only"), json.optionalText("qwen_reason"),
            if (json.isNull("reachable")) true else json.flag("reachable"),
            json.optionalText("activity_coverage") ?: "",
            json.optionalText("decision_class") ?: "",
            json.optionalText("hours_status") ?: "")
    }

    private fun interval(json: JSONObject): RadarInterval {
        val result = RadarInterval(json.time("starts_at"), json.time("ends_at"), json.optionalText("selected_id"),
            json.text("selection_basis"), json.array("options").mapObjects(::place),
            json.optionalFlag("repeat_area"), json.optionalText("outlook_note") ?: "",
            json.optionalText("route_reference") ?: "prior_area")
        require(result.endsAt > result.startsAt)
        require(result.selectedId == null || result.selected != null)
        return result
    }

    private fun invalid(message: String): Nothing = throw RadarContractException("invalid_contract", message)
    private fun JSONObject.text(key: String): String = (get(key) as? String)?.takeIf { it.isNotBlank() }
        ?: invalid("Required text missing")
    private fun JSONObject.optionalText(key: String): String? = if (isNull(key)) null else
        get(key) as? String ?: invalid("Invalid optional text")
    private fun JSONObject.obj(key: String): JSONObject = get(key) as? JSONObject ?: invalid("Required object missing")
    private fun JSONObject.array(key: String): JSONArray = get(key) as? JSONArray ?: invalid("Required list missing")
    private fun JSONObject.flag(key: String): Boolean = get(key) as? Boolean ?: invalid("Required flag missing")
    private fun JSONObject.optionalFlag(key: String): Boolean = if (isNull(key)) false else flag(key)
    private fun JSONObject.number(key: String): Double = (get(key) as? Number)?.toDouble()?.takeIf { it.isFinite() }
        ?: invalid("Invalid number")
    private fun JSONObject.nonnegative(key: String): Double = number(key).also { require(it >= 0) }
    private fun JSONObject.coordinate(key: String, min: Double, max: Double): Double = number(key).also { require(it in min..max) }
    private fun JSONObject.optionalNumber(key: String): Double? = if (isNull(key)) null else number(key)
    private fun JSONObject.time(key: String): Instant = Instant.parse(text(key))
    private fun JSONObject.optionalTime(key: String): Instant? = optionalText(key)?.let(Instant::parse)
    private fun <T> JSONArray.mapObjects(parse: (JSONObject) -> T): List<T> = (0 until length()).map { index ->
        parse(get(index) as? JSONObject ?: invalid("Invalid list item"))
    }
}

/** Receipt time is elapsedRealtime, never the phone's wall clock. Not persisted. */
data class ReceivedRadar(val snapshot: RadarSnapshot, val receivedElapsedMs: Long, val bootId: Int) {
    fun eligible(place: RadarPlace, elapsedMs: Long, currentBootId: Int): Boolean {
        if (bootId != currentBootId || elapsedMs < receivedElapsedMs || !place.actionable ||
            snapshot.evidenceStale || snapshot.locationStale || place.contextOnly) return false
        val deadline = minOf(snapshot.validUntil, place.validUntil ?: return false)
        val remaining = Duration.between(snapshot.serverTime, deadline).toMillis().coerceIn(0L, 20 * 60 * 1000L)
        return elapsedMs - receivedElapsedMs < remaining
    }

    fun primary(elapsedMs: Long, currentBootId: Int): RadarPlace? = snapshot.now.firstOrNull()?.takeIf {
        it.withinNowRadius && it.radiusMiles <= 5.0 && eligible(it, elapsedMs, currentBootId)
    }
}
