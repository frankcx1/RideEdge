package com.rideedge.app

import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.UUID
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

data class HereDecisionView(
    val stateCode: String,
    val badgeLabel: String,
    val headline: String,
    val whyText: String,
    val evidenceChipLabel: String,
    val isLocalLive: Boolean,
    val remoteContextNote: String? = null,
    val spokenSummary: String,
)

/**
 * Pure Kotlin state machine for Working-tab location provenance, request-generation
 * ordering, GPS expiry, and recommendation-outcome attribution (F06, F07, G03, G04).
 */
class WorkingLocationController(
    initialArea: String = "Bellevue",
) {
    var hereState: HereState? = null
        private set
    var hereLoadedAtMs: Long? = null
        private set
    var hereFromGps: Boolean = false
        private set
    var originSelectionMode: String = "manual"
        private set
    var lastGpsLat: Double? = null
        private set
    var lastGpsLon: Double? = null
        private set
    var lastGpsFixAtMs: Long? = null
        private set
    var awarenessUseGps: Boolean = false
        private set
    var areaQuery: String = initialArea
    var awarenessArea: String = initialArea
    var lastCompletedManualQuery: String? = null
        private set
    var lastCompletedPlaceId: String? = null
        private set
    var lastCompletedLabel: String? = null
        private set
    var lastCompletedOriginKind: String? = null
        private set
    var statusBanner: String? = null
    var hereReqGen: Int = 0
        private set

    var driverMode: String = "active_working"
        private set
    var repositionLimitMinutes: Int = 20
        private set
    var planMinutesAvailable: Int = 360
        private set

    var positioningTargetId: String? = null
        private set
    var positioningTargetLabel: String? = null
        private set
    var positioningTargetZone: String? = null
        private set
    var positioningTargetLat: Double? = null
        private set
    var positioningTargetLon: Double? = null
        private set
    var positioningState: String = "none"
        private set
    var arrivedAtEpochMs: Long? = null
        private set

    var activeEpisodeId: String? = null
        private set
    var activeEpisodeRecommendationId: String? = null
        private set
    var activeEpisodeEvidenceVersion: String? = null
        private set
    var activeEpisodeZone: String? = null
        private set
    var activeEpisodeState: String = "none"
        private set
    var activeEpisodeStartedAtMs: Long? = null
        private set
    var activeEpisodeFirstRequestWaitMinutes: Double? = null
        private set
    var lastSubmittedEpisodeId: String? = null
        private set
    var lastSubmittedFirstRequestWaitMinutes: Double? = null
        private set
    var lastSubmittedEventAtMs: Long? = null
        private set
    val lastSubmittedEventAtIso: String?
        get() = lastSubmittedEventAtMs?.let { java.time.Instant.ofEpochMilli(it).toString() }
    var lastSubmittedZone: String? = null
        private set
    var lastSubmittedRecommendedAction: String? = null
        private set
    var lastSubmittedRecommendationId: String? = null
        private set
    var lastSubmittedEvidenceVersion: String? = null
        private set

    var pendingOutcomeStatus: String? = null
        private set
    var lastOutcomeDeliveryState: String = "idle"
        private set
    var lastOutcomeMessage: String = ""
        private set
    var failedOutcomeRetryKey: String? = null
        private set
    var failedOutcomeStatus: String? = null
        private set
    var failedOutcomeNote: String? = null
        private set
    var failedOutcomeEventAtMs: Long? = null
        private set
    var failedOutcomeWaitMinutes: Double? = null
        private set
    var failedOutcomeEpisodeId: String? = null
        private set
    var failedOutcomeEpisodeStartedAtMs: Long? = null
        private set
    var failedOutcomeRecommendationId: String? = null
        private set
    var failedOutcomeEvidenceVersion: String? = null
        private set
    var failedOutcomeZone: String? = null
        private set
    var failedOutcomeZoneLabel: String? = null
        private set
    var failedOutcomeRecommendedAction: String? = null
        private set
    val queuedFailedOutcomes: MutableList<JSONObject> = mutableListOf()

    private var preAttemptEpisodeId: String? = null
    private var preAttemptEpisodeState: String = "none"
    private var preAttemptStartedAtMs: Long? = null
    private var preAttemptFirstReqWaitMin: Double? = null
    private var preAttemptRecId: String? = null
    private var preAttemptEvVer: String? = null
    private var preAttemptZone: String? = null

    fun setDriverPosture(mode: String) {
        val norm = mode.trim().lowercase(Locale.US)
        driverMode = if (norm in setOf("active_working", "wait_at_home", "break", "offline")) {
            norm
        } else {
            "active_working"
        }
    }

    fun setRepositionLimit(minutes: Int) {
        repositionLimitMinutes = minutes.coerceIn(5, 45)
    }

    fun setPlanDurationMinutes(minutes: Int) {
        planMinutesAvailable = minutes.coerceIn(30, 360)
    }

    fun markPositioningNavigationOpened() {
        if (!positioningTargetId.isNullOrBlank() && positioningState != "arrived") {
            positioningState = "en_route"
        }
    }

    fun confirmArrivalAtDestination(nowMs: Long = System.currentTimeMillis()): String? {
        val targetLabel = positioningTargetLabel?.takeIf { it.isNotBlank() }
            ?: hereState?.destinationLabel?.takeIf { it.isNotBlank() }
            ?: return null
        val targetId = positioningTargetId?.takeIf { it.isNotBlank() }
            ?: hereState?.destinationId?.takeIf { it.isNotBlank() }
        positioningTargetId = targetId
        positioningTargetLabel = targetLabel
        positioningState = "arrived"
        arrivedAtEpochMs = nowMs
        return targetLabel
    }

    fun toJson(): JSONObject {
        val persistedGpsIntent = hereFromGps || originSelectionMode == "gps"
        return JSONObject()
            .put("originSelectionMode", if (persistedGpsIntent) "gps" else "manual")
            .put("hereFromGps", persistedGpsIntent)
            .put("areaQuery", areaQuery)
            .put("awarenessArea", awarenessArea)
            .put("lastCompletedManualQuery", lastCompletedManualQuery ?: JSONObject.NULL)
            .put("lastCompletedPlaceId", lastCompletedPlaceId ?: JSONObject.NULL)
            .put("lastCompletedLabel", lastCompletedLabel ?: JSONObject.NULL)
            .put("lastCompletedOriginKind", lastCompletedOriginKind ?: JSONObject.NULL)
            .put("driverMode", driverMode)
            .put("repositionLimitMinutes", repositionLimitMinutes)
            .put("planMinutesAvailable", planMinutesAvailable)
            .put("positioningTargetId", positioningTargetId ?: JSONObject.NULL)
            .put("positioningTargetLabel", positioningTargetLabel ?: JSONObject.NULL)
            .put("positioningTargetZone", positioningTargetZone ?: JSONObject.NULL)
            .put("positioningTargetLat", positioningTargetLat ?: JSONObject.NULL)
            .put("positioningTargetLon", positioningTargetLon ?: JSONObject.NULL)
            .put("positioningState", positioningState)
            .put("arrivedAtEpochMs", arrivedAtEpochMs ?: JSONObject.NULL)
            .put("activeEpisodeId", activeEpisodeId ?: JSONObject.NULL)
            .put("activeEpisodeRecommendationId", activeEpisodeRecommendationId ?: JSONObject.NULL)
            .put("activeEpisodeEvidenceVersion", activeEpisodeEvidenceVersion ?: JSONObject.NULL)
            .put("activeEpisodeZone", activeEpisodeZone ?: JSONObject.NULL)
            .put("activeEpisodeState", activeEpisodeState)
            .put("activeEpisodeStartedAtMs", activeEpisodeStartedAtMs ?: JSONObject.NULL)
            .put("activeEpisodeFirstRequestWaitMinutes", activeEpisodeFirstRequestWaitMinutes ?: JSONObject.NULL)
            .put("lastSubmittedEpisodeId", lastSubmittedEpisodeId ?: JSONObject.NULL)
            .put("lastSubmittedFirstRequestWaitMinutes", lastSubmittedFirstRequestWaitMinutes ?: JSONObject.NULL)
            .put("lastSubmittedEventAtMs", lastSubmittedEventAtMs ?: JSONObject.NULL)
            .put("lastSubmittedZone", lastSubmittedZone ?: JSONObject.NULL)
            .put("lastSubmittedRecommendedAction", lastSubmittedRecommendedAction ?: JSONObject.NULL)
            .put("lastSubmittedRecommendationId", lastSubmittedRecommendationId ?: JSONObject.NULL)
            .put("lastSubmittedEvidenceVersion", lastSubmittedEvidenceVersion ?: JSONObject.NULL)
            .put("pendingOutcomeStatus", pendingOutcomeStatus ?: JSONObject.NULL)
            .put("lastOutcomeDeliveryState", lastOutcomeDeliveryState)
            .put("lastOutcomeMessage", lastOutcomeMessage)
            .put("failedOutcomeRetryKey", failedOutcomeRetryKey ?: JSONObject.NULL)
            .put("failedOutcomeStatus", failedOutcomeStatus ?: JSONObject.NULL)
            .put("failedOutcomeNote", failedOutcomeNote ?: JSONObject.NULL)
            .put("failedOutcomeEventAtMs", failedOutcomeEventAtMs ?: JSONObject.NULL)
            .put("failedOutcomeWaitMinutes", failedOutcomeWaitMinutes ?: JSONObject.NULL)
            .put("failedOutcomeEpisodeId", failedOutcomeEpisodeId ?: JSONObject.NULL)
            .put("failedOutcomeEpisodeStartedAtMs", failedOutcomeEpisodeStartedAtMs ?: JSONObject.NULL)
            .put("failedOutcomeRecommendationId", failedOutcomeRecommendationId ?: JSONObject.NULL)
            .put("failedOutcomeEvidenceVersion", failedOutcomeEvidenceVersion ?: JSONObject.NULL)
            .put("failedOutcomeZone", failedOutcomeZone ?: JSONObject.NULL)
            .put("failedOutcomeZoneLabel", failedOutcomeZoneLabel ?: JSONObject.NULL)
            .put("failedOutcomeRecommendedAction", failedOutcomeRecommendedAction ?: JSONObject.NULL)
            .put("preAttemptEpisodeId", preAttemptEpisodeId ?: JSONObject.NULL)
            .put("preAttemptEpisodeState", preAttemptEpisodeState)
            .put("preAttemptStartedAtMs", preAttemptStartedAtMs ?: JSONObject.NULL)
            .put("preAttemptFirstReqWaitMin", preAttemptFirstReqWaitMin ?: JSONObject.NULL)
            .put("preAttemptRecId", preAttemptRecId ?: JSONObject.NULL)
            .put("preAttemptEvVer", preAttemptEvVer ?: JSONObject.NULL)
            .put("preAttemptZone", preAttemptZone ?: JSONObject.NULL)
            .put("queuedFailedOutcomes", JSONArray(queuedFailedOutcomes))
    }

    fun restoreFromJson(json: JSONObject) {
        val restoredMode = json.optString(
            "originSelectionMode",
            if (json.optBoolean("hereFromGps", false)) "gps" else "manual"
        ).trim().lowercase(Locale.US)
        originSelectionMode = if (restoredMode == "gps") "gps" else "manual"
        hereFromGps = originSelectionMode == "gps" || json.optBoolean("hereFromGps", false)
        hereState = null
        hereLoadedAtMs = null
        lastGpsLat = null
        lastGpsLon = null
        lastGpsFixAtMs = null
        awarenessUseGps = originSelectionMode == "gps"
        areaQuery = json.optString("areaQuery", areaQuery).ifBlank { areaQuery }
        awarenessArea = json.optString("awarenessArea", awarenessArea).ifBlank { awarenessArea }
        lastCompletedManualQuery = if (json.isNull("lastCompletedManualQuery")) null else json.optString("lastCompletedManualQuery").takeIf { it.isNotBlank() }
        lastCompletedPlaceId = if (json.isNull("lastCompletedPlaceId")) null else json.optString("lastCompletedPlaceId").takeIf { it.isNotBlank() }
        lastCompletedLabel = if (json.isNull("lastCompletedLabel")) null else json.optString("lastCompletedLabel").takeIf { it.isNotBlank() }
        lastCompletedOriginKind = if (json.isNull("lastCompletedOriginKind")) null else json.optString("lastCompletedOriginKind").takeIf { it.isNotBlank() }
        setDriverPosture(json.optString("driverMode", driverMode))
        setRepositionLimit(json.optInt("repositionLimitMinutes", repositionLimitMinutes))
        setPlanDurationMinutes(json.optInt("planMinutesAvailable", 360))
        positioningTargetId = if (json.isNull("positioningTargetId")) null else json.optString("positioningTargetId").takeIf { it.isNotBlank() }
        positioningTargetLabel = if (json.isNull("positioningTargetLabel")) null else json.optString("positioningTargetLabel").takeIf { it.isNotBlank() }
        positioningTargetZone = if (json.isNull("positioningTargetZone")) null else json.optString("positioningTargetZone").takeIf { it.isNotBlank() }
        positioningTargetLat = if (json.isNull("positioningTargetLat")) null else json.optDouble("positioningTargetLat")
        positioningTargetLon = if (json.isNull("positioningTargetLon")) null else json.optDouble("positioningTargetLon")
        positioningState = json.optString("positioningState", "none")
        arrivedAtEpochMs = if (json.isNull("arrivedAtEpochMs")) null else json.optLong("arrivedAtEpochMs")
        activeEpisodeId = if (json.isNull("activeEpisodeId")) null else json.optString("activeEpisodeId").takeIf { it.isNotBlank() }
        activeEpisodeRecommendationId = if (json.isNull("activeEpisodeRecommendationId")) null else json.optString("activeEpisodeRecommendationId").takeIf { it.isNotBlank() }
        activeEpisodeEvidenceVersion = if (json.isNull("activeEpisodeEvidenceVersion")) null else json.optString("activeEpisodeEvidenceVersion").takeIf { it.isNotBlank() }
        activeEpisodeZone = if (json.isNull("activeEpisodeZone")) null else json.optString("activeEpisodeZone").takeIf { it.isNotBlank() }
        activeEpisodeState = json.optString("activeEpisodeState", "none").ifBlank { "none" }
        activeEpisodeStartedAtMs = if (json.isNull("activeEpisodeStartedAtMs")) null else json.optLong("activeEpisodeStartedAtMs")
        activeEpisodeFirstRequestWaitMinutes = if (json.isNull("activeEpisodeFirstRequestWaitMinutes")) null else json.optDouble("activeEpisodeFirstRequestWaitMinutes")
        lastSubmittedEpisodeId = if (json.isNull("lastSubmittedEpisodeId")) null else json.optString("lastSubmittedEpisodeId").takeIf { it.isNotBlank() }
        lastSubmittedFirstRequestWaitMinutes = if (json.isNull("lastSubmittedFirstRequestWaitMinutes")) null else json.optDouble("lastSubmittedFirstRequestWaitMinutes")
        lastSubmittedEventAtMs = if (json.isNull("lastSubmittedEventAtMs")) null else json.optLong("lastSubmittedEventAtMs")
        lastSubmittedZone = if (json.isNull("lastSubmittedZone")) null else json.optString("lastSubmittedZone").takeIf { it.isNotBlank() }
        lastSubmittedRecommendedAction = if (json.isNull("lastSubmittedRecommendedAction")) null else json.optString("lastSubmittedRecommendedAction").takeIf { it.isNotBlank() }
        lastSubmittedRecommendationId = if (json.isNull("lastSubmittedRecommendationId")) null else json.optString("lastSubmittedRecommendationId").takeIf { it.isNotBlank() }
        lastSubmittedEvidenceVersion = if (json.isNull("lastSubmittedEvidenceVersion")) null else json.optString("lastSubmittedEvidenceVersion").takeIf { it.isNotBlank() }
        pendingOutcomeStatus = if (json.isNull("pendingOutcomeStatus")) null else json.optString("pendingOutcomeStatus").takeIf { it.isNotBlank() }
        lastOutcomeDeliveryState = json.optString("lastOutcomeDeliveryState", "idle").ifBlank { "idle" }
        lastOutcomeMessage = json.optString("lastOutcomeMessage", "")
        failedOutcomeRetryKey = if (json.isNull("failedOutcomeRetryKey")) null else json.optString("failedOutcomeRetryKey").takeIf { it.isNotBlank() }
        failedOutcomeStatus = if (json.isNull("failedOutcomeStatus")) null else json.optString("failedOutcomeStatus").takeIf { it.isNotBlank() }
        failedOutcomeNote = if (json.isNull("failedOutcomeNote")) null else json.optString("failedOutcomeNote")
        failedOutcomeEventAtMs = if (json.isNull("failedOutcomeEventAtMs")) null else json.optLong("failedOutcomeEventAtMs")
        failedOutcomeWaitMinutes = if (json.isNull("failedOutcomeWaitMinutes")) null else json.optDouble("failedOutcomeWaitMinutes")
        failedOutcomeEpisodeId = if (json.isNull("failedOutcomeEpisodeId")) null else json.optString("failedOutcomeEpisodeId").takeIf { it.isNotBlank() }
        failedOutcomeEpisodeStartedAtMs = if (json.isNull("failedOutcomeEpisodeStartedAtMs")) null else json.optLong("failedOutcomeEpisodeStartedAtMs")
        failedOutcomeRecommendationId = if (json.isNull("failedOutcomeRecommendationId")) null else json.optString("failedOutcomeRecommendationId").takeIf { it.isNotBlank() }
        failedOutcomeEvidenceVersion = if (json.isNull("failedOutcomeEvidenceVersion")) null else json.optString("failedOutcomeEvidenceVersion").takeIf { it.isNotBlank() }
        failedOutcomeZone = if (json.isNull("failedOutcomeZone")) null else json.optString("failedOutcomeZone").takeIf { it.isNotBlank() }
        failedOutcomeZoneLabel = if (json.isNull("failedOutcomeZoneLabel")) null else json.optString("failedOutcomeZoneLabel").takeIf { it.isNotBlank() }
        failedOutcomeRecommendedAction = if (json.isNull("failedOutcomeRecommendedAction")) null else json.optString("failedOutcomeRecommendedAction").takeIf { it.isNotBlank() }
        preAttemptEpisodeId = if (json.isNull("preAttemptEpisodeId")) null else json.optString("preAttemptEpisodeId").takeIf { it.isNotBlank() }
        preAttemptEpisodeState = json.optString("preAttemptEpisodeState", "none").ifBlank { "none" }
        preAttemptStartedAtMs = if (json.isNull("preAttemptStartedAtMs")) null else json.optLong("preAttemptStartedAtMs")
        preAttemptFirstReqWaitMin = if (json.isNull("preAttemptFirstReqWaitMin")) null else json.optDouble("preAttemptFirstReqWaitMin")
        preAttemptRecId = if (json.isNull("preAttemptRecId")) null else json.optString("preAttemptRecId").takeIf { it.isNotBlank() }
        preAttemptEvVer = if (json.isNull("preAttemptEvVer")) null else json.optString("preAttemptEvVer").takeIf { it.isNotBlank() }
        preAttemptZone = if (json.isNull("preAttemptZone")) null else json.optString("preAttemptZone").takeIf { it.isNotBlank() }
        queuedFailedOutcomes.clear()
        val queuedArr = json.optJSONArray("queuedFailedOutcomes")
        if (queuedArr != null) {
            for (i in 0 until queuedArr.length()) {
                val item = queuedArr.optJSONObject(i) ?: continue
                queuedFailedOutcomes.add(item)
            }
        }

        // R4-01: No network coroutine survives process recreation. If an outcome save was in-flight
        // ("pending") when serialized, roll back optimistic episode state to preAttempt* and surface
        // an actionable failed/retry state so controls are never stuck disabled in "Saving…".
        if (lastOutcomeDeliveryState == "pending") {
            failOutcomeSubmission("Save interrupted before confirmation")
        }
    }

    /**
     * G04 / R3-01 / R3-02: Starting a manual area load immediately clears any previous guidance card
     * alongside GPS provenance so a slow or failed area switch can never leave stale
     * GPS guidance visible without GPS expiry protection. When refreshing the same manual
     * location (e.g., 'home' or the currently selected area), open wait episodes are preserved.
     */
    fun beginManualAreaLoad(place: String): Int {
        val reqId = ++hereReqGen
        val trimmedPlace = place.trim()
        val isSameLocationRefresh = !hereFromGps && trimmedPlace.isNotBlank() && (
            trimmedPlace.equals(areaQuery.trim(), ignoreCase = true) ||
                (lastCompletedManualQuery != null && trimmedPlace.equals(lastCompletedManualQuery, ignoreCase = true)) ||
                (lastCompletedPlaceId != null && trimmedPlace.equals(lastCompletedPlaceId, ignoreCase = true)) ||
                (
                    lastCompletedOriginKind?.startsWith("residential", ignoreCase = true) != true &&
                        lastCompletedLabel != null &&
                        trimmedPlace.equals(lastCompletedLabel, ignoreCase = true)
                    )
            )
        originSelectionMode = "manual"
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        awarenessUseGps = false
        lastGpsLat = null
        lastGpsLon = null
        lastGpsFixAtMs = null
        statusBanner = null
        if (!isSameLocationRefresh) {
            activeEpisodeId = null
            activeEpisodeRecommendationId = null
            activeEpisodeEvidenceVersion = null
            activeEpisodeZone = null
            activeEpisodeState = "none"
            activeEpisodeStartedAtMs = null
            activeEpisodeFirstRequestWaitMinutes = null
        }
        return reqId
    }

    fun completeManualAreaLoad(
        reqId: Int,
        state: HereState,
        place: String,
        nowMs: Long = System.currentTimeMillis(),
    ): Boolean {
        if (reqId != hereReqGen) return false
        originSelectionMode = "manual"
        hereState = state
        hereLoadedAtMs = nowMs
        hereFromGps = false
        val requestedPlace = place.trim()
        areaQuery = requestedPlace.ifBlank { state.originPlaceId.ifBlank { state.label } }
        awarenessArea = state.zone.ifBlank { requestedPlace.ifBlank { state.label } }
        lastCompletedManualQuery = areaQuery
        lastCompletedPlaceId = state.originPlaceId.takeIf { it.isNotBlank() }
        lastCompletedLabel = state.label.takeIf { it.isNotBlank() }
        lastCompletedOriginKind = state.originKind.takeIf { it.isNotBlank() }
        awarenessUseGps = false
        lastGpsLat = null
        lastGpsLon = null
        lastGpsFixAtMs = null
        updatePositioningTracking(state, null, null, nowMs)
        captureEpisodeAttributionIfNeeded(state)
        return true
    }

    fun failManualAreaLoad(reqId: Int, errorMessage: String?): Boolean {
        if (reqId != hereReqGen) return false
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        statusBanner = errorMessage ?: "Failed to load area"
        return true
    }

    fun beginGpsLoad(): Int {
        val reqId = ++hereReqGen
        originSelectionMode = "gps"
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        statusBanner = "Reading Pixel 10 Pro GPS…"
        return reqId
    }

    /**
     * F06: Validates request generation immediately after awaiting a GPS fix so a delayed
     * GPS callback cannot restore coordinates after a newer manual selection.
     */
    fun onGpsFixAcquired(
        reqId: Int,
        lat: Double,
        lon: Double,
        fixTimeMs: Long,
        nowMs: Long = System.currentTimeMillis(),
        accuracyMeters: Float? = null,
    ): Boolean {
        if (reqId != hereReqGen) return false
        val ageMs = nowMs - fixTimeMs
        val validFix = ageMs in -5_000L..120_000L &&
            (accuracyMeters == null || (accuracyMeters > 0f && accuracyMeters <= 250f))
        if (!validFix) {
            failGpsLoad(reqId, "Fresh GPS fix unavailable (>2m old or >250m accuracy); select an area chip.")
            return false
        }
        lastGpsLat = lat
        lastGpsLon = lon
        lastGpsFixAtMs = fixTimeMs
        awarenessUseGps = true
        return true
    }

    fun completeGpsLoad(
        reqId: Int,
        state: HereState,
        lat: Double,
        lon: Double,
        nowMs: Long = System.currentTimeMillis(),
    ): Boolean {
        if (reqId != hereReqGen) return false
        originSelectionMode = "gps"
        hereState = state
        hereLoadedAtMs = nowMs
        hereFromGps = true
        awarenessArea = state.label
        statusBanner = "Updated phone location (${state.label})"
        updatePositioningTracking(state, lat, lon, nowMs)
        captureEpisodeAttributionIfNeeded(state)
        return true
    }

    private fun updatePositioningTracking(
        state: HereState,
        lat: Double?,
        lon: Double?,
        nowMs: Long,
    ) {
        val isPosHeuristic = state.recommendationBasis.equals("positioning_heuristic", ignoreCase = true)
        val isPositionedCenter = state.recommendationBasis.equals("positioned_pickup_center", ignoreCase = true)
        val isResidentialOrigin = state.originKind.startsWith("residential", ignoreCase = true) ||
            state.originPlaceId.equals("home", ignoreCase = true)
        val originMatchesTarget = !isResidentialOrigin &&
            !positioningTargetId.isNullOrBlank() &&
            state.originPlaceId.isNotBlank() &&
            state.originPlaceId.equals(positioningTargetId, ignoreCase = true)
        val withinQuarterMileOfTarget = if (
            !isResidentialOrigin &&
            lat != null && lon != null &&
            positioningTargetLat != null && positioningTargetLon != null
        ) {
            haversineMiles(lat, lon, positioningTargetLat!!, positioningTargetLon!!) <= 0.25
        } else {
            false
        }

        if (!isPosHeuristic && !isResidentialOrigin && (isPositionedCenter || originMatchesTarget || withinQuarterMileOfTarget)) {
            if (state.originPlaceId.isNotBlank()) {
                positioningTargetId = state.originPlaceId
            }
            val centerLabel = state.destinationLabel.ifBlank { state.label }
            if (centerLabel.isNotBlank()) {
                positioningTargetLabel = centerLabel
            }
            positioningTargetZone = state.zone
            positioningState = "arrived"
            if (arrivedAtEpochMs == null) {
                arrivedAtEpochMs = nowMs
            }
            return
        }

        if (isPosHeuristic && state.destinationId.isNotBlank()) {
            val changedTarget = !state.destinationId.equals(positioningTargetId, ignoreCase = true)
            positioningTargetId = state.destinationId
            positioningTargetLabel = state.destinationLabel.ifBlank { state.bestRow?.zone ?: state.zone }
            positioningTargetZone = state.bestRow?.zone ?: state.zone
            val coords = parseDestinationCoordsFromMapsUrl(state.bestRow?.mapsUrl.orEmpty())
            positioningTargetLat = coords?.first
            positioningTargetLon = coords?.second
            if (changedTarget || positioningState == "none" || positioningState == "arrived") {
                positioningState = "suggested"
                arrivedAtEpochMs = null
            }
        } else {
            positioningState = "none"
            positioningTargetId = null
            positioningTargetLabel = null
            positioningTargetZone = null
            positioningTargetLat = null
            positioningTargetLon = null
            arrivedAtEpochMs = null
        }
    }

    private fun parseDestinationCoordsFromMapsUrl(mapsUrl: String): Pair<Double, Double>? {
        val m = Regex("""destination=([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)""").find(mapsUrl)
            ?: return null
        val lat = m.groupValues[1].toDoubleOrNull() ?: return null
        val lon = m.groupValues[2].toDoubleOrNull() ?: return null
        return lat to lon
    }

    private fun haversineMiles(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 3958.8
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2).pow(2) +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLon / 2).pow(2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }

    fun failGpsLoad(reqId: Int, errorMessage: String?): Boolean {
        if (reqId != hereReqGen) return false
        lastGpsLat = null
        lastGpsLon = null
        lastGpsFixAtMs = null
        awarenessUseGps = false
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        statusBanner = errorMessage ?: "Fresh GPS fix unavailable (>2m old or >250m accuracy); select an area chip."
        return true
    }

    fun currentFreshGps(nowMs: Long = System.currentTimeMillis()): Pair<Double, Double>? {
        val lat = lastGpsLat
        val lon = lastGpsLon
        val fixMs = lastGpsFixAtMs
        if (lat == null || lon == null || fixMs == null) return null
        if (nowMs - fixMs > 300_000L) {
            lastGpsLat = null
            lastGpsLon = null
            lastGpsFixAtMs = null
            awarenessUseGps = false
            if (hereFromGps) {
                hereState = null
                hereLoadedAtMs = null
                hereFromGps = false
                statusBanner = "GPS fix expired (>5m old); refresh GPS or choose an area chip."
            }
            return null
        }
        return lat to lon
    }

    /**
     * G03 / H02: Explicit client episode state machine (`none` -> `waiting` -> `pinged` -> `accepted`).
     * Retains the recommendation_id and evidence_version that initiated an active waiting/pinged
     * episode across background refreshes and repeated `Waiting` taps, attaches that ID to the
     * accepted ride, and transitions to `accepted` so the next `Waiting` tap after a ride starts
     * a new episode with the newly displayed recommendation.
     */
    fun resolveOutcomeAttribution(
        status: String,
        currentHere: HereState? = hereState,
    ): Pair<String, String> {
        val normStatus = status.trim().lowercase()
        val curRecId = currentHere?.recommendationId?.trim().orEmpty()
        val curEvVer = currentHere?.evidenceVersion?.trim()?.ifBlank { "v2" } ?: "v2"
        val curZone = currentHere?.zone?.trim().orEmpty()
        val sameZone = activeEpisodeZone == null || curZone.isBlank() || activeEpisodeZone == curZone

        if (normStatus == "waiting") {
            val isContinuousWaitInSameZone =
                activeEpisodeState == "waiting" &&
                    sameZone &&
                    !activeEpisodeRecommendationId.isNullOrBlank()
            if (!isContinuousWaitInSameZone) {
                val nowMs = System.currentTimeMillis()
                activeEpisodeRecommendationId = curRecId.ifBlank { null }
                activeEpisodeEvidenceVersion = curEvVer
                activeEpisodeZone = curZone
                activeEpisodeState = "waiting"
                activeEpisodeStartedAtMs = nowMs
                activeEpisodeFirstRequestWaitMinutes = null
                activeEpisodeId = "ep-${(activeEpisodeRecommendationId ?: curRecId).ifBlank { "now" }}-$nowMs"
            }
            return (activeEpisodeRecommendationId ?: curRecId) to (activeEpisodeEvidenceVersion ?: curEvVer)
        }

        if (normStatus == "request_received") {
            val hasOpenWaitOrPing =
                activeEpisodeState in setOf("waiting", "pinged") &&
                    sameZone &&
                    !activeEpisodeRecommendationId.isNullOrBlank()
            val finalId: String
            val finalVer: String
            if (hasOpenWaitOrPing) {
                finalId = activeEpisodeRecommendationId!!
                finalVer = activeEpisodeEvidenceVersion ?: curEvVer
            } else {
                val nowMs = System.currentTimeMillis()
                finalId = curRecId
                finalVer = curEvVer
                activeEpisodeRecommendationId = curRecId.ifBlank { null }
                activeEpisodeEvidenceVersion = curEvVer
                activeEpisodeZone = curZone
                if (activeEpisodeId.isNullOrBlank()) {
                    activeEpisodeId = "ep-${finalId.ifBlank { "now" }}-$nowMs"
                }
            }
            activeEpisodeState = "pinged"
            return finalId to finalVer
        }

        if (normStatus == "accepted_ride") {
            val hasOpenWaitOrPing =
                activeEpisodeState in setOf("waiting", "pinged") &&
                    sameZone &&
                    !activeEpisodeRecommendationId.isNullOrBlank()
            val finalId = if (hasOpenWaitOrPing) activeEpisodeRecommendationId!! else curRecId
            val finalVer = if (hasOpenWaitOrPing) (activeEpisodeEvidenceVersion ?: curEvVer) else curEvVer
            if (!hasOpenWaitOrPing || activeEpisodeId.isNullOrBlank()) {
                activeEpisodeId = "ep-${finalId.ifBlank { "now" }}-${System.currentTimeMillis()}"
            }
            activeEpisodeRecommendationId = finalId.ifBlank { null }
            activeEpisodeEvidenceVersion = finalVer
            activeEpisodeZone = curZone
            activeEpisodeState = "accepted"
            activeEpisodeStartedAtMs = null
            return finalId to finalVer
        }

        if (normStatus in setOf(
                "break",
                "offline",
                "repositioned",
                "no_request",
                "no_request_after_15m",
                "observed_15m_no_request",
                "dry_wait_15m",
                "left_area",
            )
        ) {
            val hasOpenWaitOrPing =
                activeEpisodeState in setOf("waiting", "pinged") &&
                    sameZone &&
                    !activeEpisodeRecommendationId.isNullOrBlank()
            val finalId = if (hasOpenWaitOrPing) activeEpisodeRecommendationId!! else curRecId
            val finalVer = if (hasOpenWaitOrPing) (activeEpisodeEvidenceVersion ?: curEvVer) else curEvVer
            if (!hasOpenWaitOrPing || activeEpisodeId.isNullOrBlank()) {
                activeEpisodeId = "ep-${finalId.ifBlank { "now" }}-${System.currentTimeMillis()}"
            }
            activeEpisodeRecommendationId = null
            activeEpisodeEvidenceVersion = null
            activeEpisodeZone = null
            activeEpisodeState = "none"
            activeEpisodeStartedAtMs = null
            activeEpisodeFirstRequestWaitMinutes = null
            return finalId to finalVer
        }

        return (activeEpisodeRecommendationId ?: curRecId) to (activeEpisodeEvidenceVersion ?: curEvVer)
    }

    private fun captureEpisodeAttributionIfNeeded(state: HereState) {
        val zoneChanged = !activeEpisodeZone.isNullOrBlank() &&
            state.zone.isNotBlank() &&
            !activeEpisodeZone.equals(state.zone, ignoreCase = true)
        if (activeEpisodeState !in setOf("waiting", "pinged") || zoneChanged) {
            activeEpisodeRecommendationId = state.recommendationId.ifBlank { null }
            activeEpisodeEvidenceVersion = state.evidenceVersion.ifBlank { "v2" }
            activeEpisodeZone = state.zone
            if (zoneChanged) {
                activeEpisodeId = null
                activeEpisodeState = "none"
                activeEpisodeStartedAtMs = null
                activeEpisodeFirstRequestWaitMinutes = null
            }
        } else if (activeEpisodeZone.isNullOrBlank()) {
            activeEpisodeZone = state.zone
        }
    }

    /**
     * N04: Begins an async driver-outcome submission with pending state, rollback snapshot,
     * and stable idempotency key across retries of a failed write.
     */
    fun beginOutcomeSubmission(
        status: String,
        note: String = "",
        currentHere: HereState? = hereState,
        nowMs: Long = System.currentTimeMillis(),
    ): Triple<String, String, String> {
        val normStatus = status.trim().lowercase()
        val isRetry = lastOutcomeDeliveryState == "failed" &&
            failedOutcomeStatus == normStatus &&
            !failedOutcomeRetryKey.isNullOrBlank()

        if (!isRetry && lastOutcomeDeliveryState == "failed" && !failedOutcomeRetryKey.isNullOrBlank() && !failedOutcomeStatus.isNullOrBlank()) {
            val priorKey = failedOutcomeRetryKey!!
            if (queuedFailedOutcomes.none { it.optString("retryKey") == priorKey }) {
                queuedFailedOutcomes.add(
                    JSONObject()
                        .put("retryKey", priorKey)
                        .put("status", failedOutcomeStatus)
                        .put("note", failedOutcomeNote ?: "")
                        .put("eventAtMs", failedOutcomeEventAtMs ?: nowMs)
                        .put("waitMinutes", failedOutcomeWaitMinutes ?: JSONObject.NULL)
                        .put("episodeId", failedOutcomeEpisodeId ?: JSONObject.NULL)
                        .put("episodeStartedAtMs", failedOutcomeEpisodeStartedAtMs ?: JSONObject.NULL)
                        .put("recommendationId", failedOutcomeRecommendationId ?: "")
                        .put("evidenceVersion", failedOutcomeEvidenceVersion ?: "v2")
                        .put("zone", failedOutcomeZone ?: "")
                        .put("zoneLabel", failedOutcomeZoneLabel ?: "")
                        .put("recommendedAction", failedOutcomeRecommendedAction ?: "WAIT")
                )
            }
        }

        preAttemptEpisodeId = activeEpisodeId
        preAttemptEpisodeState = activeEpisodeState
        preAttemptStartedAtMs = activeEpisodeStartedAtMs
        preAttemptFirstReqWaitMin = activeEpisodeFirstRequestWaitMinutes
        preAttemptRecId = activeEpisodeRecommendationId
        preAttemptEvVer = activeEpisodeEvidenceVersion
        preAttemptZone = activeEpisodeZone

        val eventAtMs = if (isRetry && failedOutcomeEventAtMs != null) {
            failedOutcomeEventAtMs!!
        } else {
            nowMs
        }
        val elapsedWaitMinutes = if (isRetry && failedOutcomeWaitMinutes != null) {
            failedOutcomeWaitMinutes
        } else {
            activeEpisodeStartedAtMs?.let {
                ((eventAtMs - it) / 60_000.0).coerceAtLeast(0.0)
            }
        }

        val reuseIdem = if (isRetry) {
            failedOutcomeRetryKey!!
        } else {
            UUID.randomUUID().toString()
        }

        val recId: String
        val evVer: String
        val targetZone: String
        val targetZoneLabel: String
        val targetAction: String

        if (isRetry) {
            recId = failedOutcomeRecommendationId
                ?: activeEpisodeRecommendationId
                ?: currentHere?.recommendationId.orEmpty()
            evVer = failedOutcomeEvidenceVersion?.takeIf { it.isNotBlank() }
                ?: activeEpisodeEvidenceVersion
                ?: currentHere?.evidenceVersion?.ifBlank { "v2" }
                ?: "v2"
            targetZone = failedOutcomeZone ?: preAttemptZone ?: currentHere?.zone.orEmpty()
            targetZoneLabel = failedOutcomeZoneLabel ?: cleanZoneDisplayName(targetZone)
            targetAction = failedOutcomeRecommendedAction ?: currentHere?.action?.ifBlank { "WAIT" } ?: "WAIT"
            when (normStatus) {
                "waiting" -> {
                    val startedMs = failedOutcomeEpisodeStartedAtMs ?: eventAtMs
                    activeEpisodeStartedAtMs = startedMs
                    activeEpisodeId = failedOutcomeEpisodeId?.takeIf { it.isNotBlank() }
                        ?: "ep-${recId.ifBlank { "now" }}-$startedMs"
                    activeEpisodeRecommendationId = recId.ifBlank { null }
                    activeEpisodeEvidenceVersion = evVer
                    activeEpisodeZone = targetZone
                    activeEpisodeState = "waiting"
                    activeEpisodeFirstRequestWaitMinutes = null
                }
                "request_received" -> {
                    activeEpisodeId = failedOutcomeEpisodeId?.takeIf { it.isNotBlank() }
                        ?: "ep-${recId.ifBlank { "now" }}-$eventAtMs"
                    activeEpisodeRecommendationId = recId.ifBlank { null }
                    activeEpisodeEvidenceVersion = evVer
                    activeEpisodeZone = targetZone
                    activeEpisodeState = "pinged"
                    if (activeEpisodeFirstRequestWaitMinutes == null && elapsedWaitMinutes != null) {
                        activeEpisodeFirstRequestWaitMinutes = elapsedWaitMinutes
                    }
                }
                "accepted_ride" -> {
                    activeEpisodeId = failedOutcomeEpisodeId?.takeIf { it.isNotBlank() }
                        ?: "ep-${recId.ifBlank { "now" }}-$eventAtMs"
                    activeEpisodeRecommendationId = recId.ifBlank { null }
                    activeEpisodeEvidenceVersion = evVer
                    activeEpisodeZone = targetZone
                    activeEpisodeState = "accepted"
                    activeEpisodeStartedAtMs = null
                    if (activeEpisodeFirstRequestWaitMinutes == null && elapsedWaitMinutes != null) {
                        activeEpisodeFirstRequestWaitMinutes = elapsedWaitMinutes
                    }
                }
                else -> {
                    activeEpisodeId = failedOutcomeEpisodeId
                    activeEpisodeRecommendationId = null
                    activeEpisodeEvidenceVersion = null
                    activeEpisodeZone = null
                    activeEpisodeState = "none"
                    activeEpisodeStartedAtMs = null
                    activeEpisodeFirstRequestWaitMinutes = null
                }
            }
        } else {
            val resolved = resolveOutcomeAttribution(normStatus, currentHere)
            recId = resolved.first
            evVer = resolved.second
            targetZone = activeEpisodeZone?.takeIf { it.isNotBlank() }
                ?: preAttemptZone?.takeIf { it.isNotBlank() }
                ?: currentHere?.zone.orEmpty()
            targetZoneLabel = cleanZoneDisplayName(targetZone.ifBlank { currentHere?.label.orEmpty() })
            targetAction = currentHere?.action?.ifBlank { "WAIT" } ?: "WAIT"
            if (normStatus == "waiting" && preAttemptEpisodeState != "waiting") {
                activeEpisodeStartedAtMs = eventAtMs
                activeEpisodeId = "ep-${recId.ifBlank { "now" }}-$eventAtMs"
                activeEpisodeFirstRequestWaitMinutes = null
            } else if (normStatus == "request_received" && activeEpisodeFirstRequestWaitMinutes == null && elapsedWaitMinutes != null) {
                activeEpisodeFirstRequestWaitMinutes = elapsedWaitMinutes
            } else if (normStatus == "accepted_ride" && activeEpisodeFirstRequestWaitMinutes == null && elapsedWaitMinutes != null) {
                activeEpisodeFirstRequestWaitMinutes = elapsedWaitMinutes
            }
        }
        lastSubmittedEpisodeId = if (isRetry && !failedOutcomeEpisodeId.isNullOrBlank()) {
            failedOutcomeEpisodeId
        } else {
            activeEpisodeId
                ?: preAttemptEpisodeId
                ?: "ep-${recId.ifBlank { "now" }}-$eventAtMs"
        }
        lastSubmittedFirstRequestWaitMinutes = when (normStatus) {
            "request_received" -> if (isRetry && failedOutcomeWaitMinutes != null) failedOutcomeWaitMinutes else (activeEpisodeFirstRequestWaitMinutes ?: elapsedWaitMinutes)
            "accepted_ride" -> if (isRetry && failedOutcomeWaitMinutes != null) failedOutcomeWaitMinutes else (preAttemptFirstReqWaitMin ?: activeEpisodeFirstRequestWaitMinutes ?: elapsedWaitMinutes)
            "no_request", "no_request_after_15m", "observed_15m_no_request", "dry_wait_15m" -> elapsedWaitMinutes
            else -> activeEpisodeFirstRequestWaitMinutes
        }
        lastSubmittedEventAtMs = eventAtMs
        lastSubmittedZone = targetZone
        lastSubmittedRecommendedAction = targetAction
        lastSubmittedRecommendationId = recId
        lastSubmittedEvidenceVersion = evVer
        pendingOutcomeStatus = normStatus
        lastOutcomeDeliveryState = "pending"
        lastOutcomeMessage = "Saving to RideEdge…"
        failedOutcomeStatus = normStatus
        failedOutcomeNote = note
        failedOutcomeRetryKey = reuseIdem
        failedOutcomeEventAtMs = eventAtMs
        failedOutcomeWaitMinutes = lastSubmittedFirstRequestWaitMinutes ?: elapsedWaitMinutes
        failedOutcomeEpisodeId = lastSubmittedEpisodeId
        failedOutcomeEpisodeStartedAtMs = if (normStatus == "waiting") activeEpisodeStartedAtMs else (failedOutcomeEpisodeStartedAtMs ?: preAttemptStartedAtMs)
        failedOutcomeRecommendationId = recId
        failedOutcomeEvidenceVersion = evVer
        failedOutcomeZone = targetZone
        failedOutcomeZoneLabel = targetZoneLabel
        failedOutcomeRecommendedAction = targetAction
        return Triple(recId, evVer, reuseIdem)
    }

    fun completeOutcomeSubmission(status: String) {
        val normStatus = status.trim().lowercase()
        val completedKey = failedOutcomeRetryKey
        if (!completedKey.isNullOrBlank()) {
            queuedFailedOutcomes.removeAll { it.optString("retryKey") == completedKey }
        }
        preAttemptEpisodeId = null
        preAttemptEpisodeState = "none"
        preAttemptStartedAtMs = null
        preAttemptFirstReqWaitMin = null
        preAttemptRecId = null
        preAttemptEvVer = "v2"
        preAttemptZone = null
        if (queuedFailedOutcomes.isNotEmpty()) {
            val nextQueued = queuedFailedOutcomes.removeAt(0)
            failedOutcomeRetryKey = nextQueued.optString("retryKey").takeIf { it.isNotBlank() }
            failedOutcomeStatus = nextQueued.optString("status").takeIf { it.isNotBlank() }
            failedOutcomeNote = nextQueued.optString("note")
            failedOutcomeEventAtMs = if (nextQueued.isNull("eventAtMs")) null else nextQueued.optLong("eventAtMs")
            failedOutcomeWaitMinutes = if (nextQueued.isNull("waitMinutes")) null else nextQueued.optDouble("waitMinutes")
            failedOutcomeEpisodeId = if (nextQueued.isNull("episodeId")) null else nextQueued.optString("episodeId").takeIf { it.isNotBlank() }
            failedOutcomeEpisodeStartedAtMs = if (nextQueued.isNull("episodeStartedAtMs")) null else nextQueued.optLong("episodeStartedAtMs")
            failedOutcomeRecommendationId = nextQueued.optString("recommendationId").takeIf { it.isNotBlank() }
            failedOutcomeEvidenceVersion = nextQueued.optString("evidenceVersion").takeIf { it.isNotBlank() }
            failedOutcomeZone = nextQueued.optString("zone").takeIf { it.isNotBlank() }
            failedOutcomeZoneLabel = nextQueued.optString("zoneLabel").takeIf { it.isNotBlank() }
            failedOutcomeRecommendedAction = nextQueued.optString("recommendedAction").takeIf { it.isNotBlank() }
            pendingOutcomeStatus = if (failedOutcomeStatus == "waiting") null else failedOutcomeStatus
            lastOutcomeDeliveryState = "failed"
            lastOutcomeMessage = "Earlier ${failedOutcomeStatus ?: "action"} still unsent. Tap Retry to resend without duplicating."
            return
        }
        pendingOutcomeStatus = null
        failedOutcomeRetryKey = null
        failedOutcomeStatus = null
        failedOutcomeNote = null
        failedOutcomeEventAtMs = null
        failedOutcomeWaitMinutes = null
        failedOutcomeEpisodeId = null
        failedOutcomeEpisodeStartedAtMs = null
        failedOutcomeRecommendationId = null
        failedOutcomeEvidenceVersion = null
        failedOutcomeZone = null
        failedOutcomeZoneLabel = null
        failedOutcomeRecommendedAction = null
        lastOutcomeDeliveryState = "saved"
        lastOutcomeMessage = when (normStatus) {
            "waiting" -> "Tracking wait in RideEdge (does not change Uber status)."
            "request_received" -> "Saved in RideEdge: ride request received."
            "accepted_ride" -> "Saved in RideEdge: ride accepted."
            "repositioned" -> "Saved in RideEdge: ended wait to move elsewhere."
            "no_request", "no_request_after_15m", "observed_15m_no_request", "dry_wait_15m" -> "Saved in RideEdge: ended wait with no ride request."
            "left_area" -> "Saved in RideEdge: ended wait after leaving area."
            "offline" -> "Saved in RideEdge: ended wait (going offline)."
            else -> "Saved in RideEdge: taking a break."
        }
    }

    fun failOutcomeSubmission(errorMessage: String?) {
        activeEpisodeId = preAttemptEpisodeId
        activeEpisodeState = preAttemptEpisodeState
        activeEpisodeStartedAtMs = preAttemptStartedAtMs
        activeEpisodeFirstRequestWaitMinutes = if (failedOutcomeStatus == "request_received" && failedOutcomeWaitMinutes != null) {
            failedOutcomeWaitMinutes
        } else {
            preAttemptFirstReqWaitMin
        }
        activeEpisodeRecommendationId = preAttemptRecId
        activeEpisodeEvidenceVersion = preAttemptEvVer
        activeEpisodeZone = preAttemptZone
        pendingOutcomeStatus = if (failedOutcomeStatus == "waiting") null else failedOutcomeStatus
        lastOutcomeDeliveryState = "failed"
        val cleanErr = errorMessage?.trim()?.takeIf { it.isNotBlank() } ?: "connection error"
        lastOutcomeMessage = "Not saved ($cleanErr). Tap Retry to resend without duplicating."
    }

    companion object {
        fun cleanZoneDisplayName(raw: String): String {
            val trimmed = raw.trim()
            if (trimmed.isBlank()) return "Nearby area"
            return when (trimmed.lowercase()) {
                "bellevue_core", "bellevue core" -> "Bellevue Core"
                "kirkland_waterfront", "kirkland waterfront" -> "Kirkland Waterfront"
                "totem_lake", "totem lake", "totem lake / kingsgate" -> "Totem Lake / Kingsgate"
                "redmond_downtown", "redmond downtown" -> "Redmond Downtown"
                "seattle_core", "seattle core" -> "Seattle Core"
                "capitol_hill", "capitol hill" -> "Capitol Hill"
                "seattle_center", "seattle center" -> "Seattle Center / Queen Anne"
                "fremont_ballard", "fremont / ballard" -> "Fremont / Ballard"
                "sodo_stadiums", "sodo stadiums" -> "SoDo Stadiums"
                "uw_district", "u district" -> "University District"
                "sea_airport", "seatac airport" -> "Sea-Tac Airport"
                else -> trimmed.replace("_", " ").replaceFirstChar {
                    if (it.isLowerCase()) it.titlecase(Locale.US) else it.toString()
                }
            }
        }

        fun normalizePlainDriverCopy(raw: String): String {
            if (raw.isBlank()) return ""
            return raw
                .replace(Regex("(?i)\\bdischarge wave\\b"), "offices usually finish around this time")
                .replace(Regex("(?i)\\bRTO\\b"), "weekday office schedule")
                .replace(Regex("(?i)\\bspillout\\b"), "crowd leaving")
                .replace(Regex("(?i)\\bmid-shift pivot\\b"), "next stage")
                .replace(Regex("(?i)\\bPython Comparison\\b"), "Compare areas")
                .replace(Regex("(?i)\\bcalibrated ledger\\b"), "shift log")
                .replace(Regex("(?i)\\boutside constraints\\b"), "outside your settings")
                .replace(Regex("(?i)Score\\s+[0-9.]+\\s*[—-]\\s*[^.]+\\.?"), "")
                .replace(Regex("\\s{2,}"), " ")
                .trim()
        }

        /**
         * N01 & N02: Binds reasons strictly to the current zone vs remote areas, separates
         * WAIT, WATCH, MOVE, and UNAVAILABLE, and never promotes a scheduled or remote
         * opportunity to "Live local" based on score.
         */
        fun resolveHereDecision(
            here: HereState?,
            repositionLimitMinutes: Int? = null,
        ): HereDecisionView {
            if (here == null) {
                return HereDecisionView(
                    stateCode = "UNAVAILABLE",
                    badgeLabel = "LOCATION NEEDED",
                    headline = "Guidance unavailable until location loads",
                    whyText = "Choose an area or use phone location to check current pickup conditions.",
                    evidenceChipLabel = "No location loaded",
                    isLocalLive = false,
                    remoteContextNote = null,
                    spokenSummary = "Guidance unavailable until location loads.",
                )
            }

            fun isRoutineTransitInventory(w: NearbyWindow): Boolean {
                val h = w.headline.lowercase(Locale.US)
                val d = w.detail.lowercase(Locale.US)
                return "link light rail arriving" in h ||
                    "trains arriving" in h ||
                    "ferry arrival" in h ||
                    "ferry arriving" in h ||
                    "station arrival" in h ||
                    "onebusaway" in d ||
                    "colman dock ferry" in h
            }

            val nonRoutineNearby = here.nearby.filterNot { isRoutineTransitInventory(it) }
            val sameZoneWindows = nonRoutineNearby.filter { w ->
                val sameZoneMatch = w.isSameZone ||
                    (w.zone.isNotBlank() && here.zone.isNotBlank() && w.zone.equals(here.zone, ignoreCase = true))
                val withinArrival = w.isAlreadyHere || here.localLiveEvidence || here.localScheduledEvidence ||
                    ((w.minutesAway == null || w.minutesAway <= 2.0) && (w.milesAway == null || w.milesAway <= 0.25))
                w.score > 0.0 && sameZoneMatch && withinArrival
            }
            val remotePositiveWindows = nonRoutineNearby.filter { w ->
                w.score > 0.0 && !sameZoneWindows.contains(w)
            }

            val isLocalLive = here.localLiveEvidence || sameZoneWindows.any {
                it.sourceType.equals("live", ignoreCase = true)
            }
            val hasLocalScheduled = here.localScheduledEvidence || sameZoneWindows.any {
                !it.sourceType.equals("live", ignoreCase = true)
            }
            val localTrips = here.stayRow?.sampleTrips ?: 0

            val evidenceChipLabel = when {
                isLocalLive -> "Live local reading"
                hasLocalScheduled -> "Scheduled local pattern (not live)"
                localTrips >= 2 -> "Past trip history ($localTrips trips)"
                remotePositiveWindows.isNotEmpty() -> {
                    val topRem = remotePositiveWindows.first()
                    val remArea = cleanZoneDisplayName(topRem.zone)
                    val remMins = topRem.minutesAway?.toInt()
                    if (remMins != null && remMins > 0) {
                        "Other area activity ($remArea · ~${remMins}m away)"
                    } else {
                        "Other area activity ($remArea)"
                    }
                }
                else -> "No verified local signal"
            }

            val rawDecision = here.decisionState.ifBlank { here.action }.trim().uppercase(Locale.US)
            val remoteNote = remotePositiveWindows.firstOrNull()?.let { rem ->
                val remArea = cleanZoneDisplayName(rem.zone)
                val remMins = rem.minutesAway?.toInt()
                val distClause = if (remMins != null && remMins > 0) "about $remMins minutes away" else "in another area"
                val limitClause = if (repositionLimitMinutes != null && remMins != null && remMins > repositionLimitMinutes) {
                    " (beyond your $repositionLimitMinutes-minute driving limit)"
                } else {
                    ""
                }
                "Activity in $remArea (${normalizePlainDriverCopy(rem.headline)}) is $distClause$limitClause and does not establish stronger pickup demand here in ${here.label}."
            }

            if (rawDecision == "MOVE") {
                val destLabel = here.destinationLabel.ifBlank { cleanZoneDisplayName(here.bestRow?.zone ?: "") }
                val isPositioning = here.recommendationBasis.equals("positioning_heuristic", ignoreCase = true)
                val mins = here.bestRow?.repositionMinutes?.toInt() ?: 0
                if (isPositioning) {
                    val headline = "Position near $destLabel"
                    val why = buildString {
                        append("You're starting from a residential area. This is a nearby pickup center to try; current rider demand is unverified.")
                        if (mins > 0) append(" About $mins min drive")
                        if (here.costNote.isNotBlank()) append(" · ${here.costNote}")
                        if (!here.stagingApproved) append(" · Staging curb not yet verified")
                        append(" · Recheck after arrival.")
                    }
                    return HereDecisionView(
                        stateCode = "MOVE",
                        badgeLabel = "POSITIONING SUGGESTION",
                        headline = headline,
                        whyText = why,
                        evidenceChipLabel = "Positioning heuristic · demand unverified",
                        isLocalLive = false,
                        remoteContextNote = remoteNote,
                        spokenSummary = "$headline. $why",
                    )
                }
                val headline = if (
                    here.actionPlain.isNotBlank() &&
                    !here.actionPlain.equals("Worth the drive", ignoreCase = true)
                ) {
                    normalizePlainDriverCopy(here.actionPlain)
                } else {
                    "Move to $destLabel"
                }
                val why = normalizePlainDriverCopy(
                    here.stayOrMoveReason.ifBlank {
                        here.advantageNote.ifBlank {
                            "Another area has a verified advantage after driving time and vehicle cost."
                        }
                    }
                )
                return HereDecisionView(
                    stateCode = "MOVE",
                    badgeLabel = "RECOMMENDED MOVE",
                    headline = headline,
                    whyText = why,
                    evidenceChipLabel = evidenceChipLabel,
                    isLocalLive = isLocalLive,
                    remoteContextNote = remoteNote,
                    spokenSummary = "$headline. $why Next check in ${here.recheckMinutes} minutes.",
                )
            }

            if (rawDecision.contains("AIRPORT")) {
                val headline = "Check Sea-Tac lot conditions before moving"
                val why = normalizePlainDriverCopy(
                    here.stayOrMoveReason.ifBlank {
                        "Airport arrivals are active, but Uber FIFO lot wait time is unknown."
                    }
                )
                return HereDecisionView(
                    stateCode = "CHECK_AIRPORT",
                    badgeLabel = "CHECK AIRPORT",
                    headline = headline,
                    whyText = why,
                    evidenceChipLabel = evidenceChipLabel,
                    isLocalLive = isLocalLive,
                    remoteContextNote = remoteNote,
                    spokenSummary = "$headline. $why",
                )
            }

            val isPositionedPickupCenter = here.recommendationBasis.equals("positioned_pickup_center", ignoreCase = true)
            if ((rawDecision == "WAIT" || rawDecision == "STAY") && isPositionedPickupCenter) {
                val centerName = here.destinationLabel.ifBlank { here.label }
                val headline = "Hold at $centerName for ${here.recheckMinutes} minutes"
                val why = normalizePlainDriverCopy(
                    here.stayOrMoveReason.ifBlank {
                        "You are positioned at $centerName, an active commercial pickup center. Current rider demand is unverified; hold here for up to ${here.recheckMinutes} minutes before repositioning again."
                    }
                )
                return HereDecisionView(
                    stateCode = "WAIT",
                    badgeLabel = "POSITIONED AT PICKUP CENTER · HOLD ${here.recheckMinutes}M",
                    headline = headline,
                    whyText = why,
                    evidenceChipLabel = "Positioned pickup center · demand unverified",
                    isLocalLive = false,
                    remoteContextNote = remoteNote,
                    spokenSummary = "$headline. $why",
                )
            }

            val isDriverModeHold = here.recommendationBasis.equals("driver_mode_hold", ignoreCase = true)
            if ((rawDecision == "WAIT" || rawDecision == "STAY") && isDriverModeHold) {
                val headline = normalizePlainDriverCopy(here.actionPlain.ifBlank { "Hold at ${here.label}" })
                val why = normalizePlainDriverCopy(
                    here.stayOrMoveReason.ifBlank {
                        "Driver mode is set to hold at your current location without suggesting a reposition."
                    }
                )
                return HereDecisionView(
                    stateCode = "WAIT",
                    badgeLabel = "HOLDING AT CURRENT LOCATION",
                    headline = headline,
                    whyText = why,
                    evidenceChipLabel = "Driver mode hold",
                    isLocalLive = false,
                    remoteContextNote = null,
                    spokenSummary = "$headline. $why",
                )
            }

            val hasLocalStaySupport = isLocalLive || hasLocalScheduled || localTrips >= 2
            if ((rawDecision == "WAIT" || rawDecision == "STAY") && hasLocalStaySupport) {
                val headline = "Stay in ${here.label} for now"
                val why = when {
                    sameZoneWindows.isNotEmpty() -> {
                        val localWin = sameZoneWindows.first()
                        val basisPrefix = if (localWin.sourceType.equals("live", ignoreCase = true)) {
                            "Live local activity"
                        } else {
                            "Usual local schedule"
                        }
                        "$basisPrefix in ${here.label}: ${normalizePlainDriverCopy(localWin.headline)}. Staying here avoids empty driving miles."
                    }
                    localTrips >= 2 && here.stayRow != null -> {
                        "Past trips in ${here.label} averaged $${here.stayRow.netPerHour.toInt()}/hr during paid rides ($localTrips trips), and no nearby area beats staying after driving cost."
                    }
                    else -> normalizePlainDriverCopy(here.stayOrMoveReason)
                }
                return HereDecisionView(
                    stateCode = "WAIT",
                    badgeLabel = "STAY FOR NOW",
                    headline = headline,
                    whyText = why,
                    evidenceChipLabel = evidenceChipLabel,
                    isLocalLive = isLocalLive,
                    remoteContextNote = remoteNote,
                    spokenSummary = "$headline. $why Next check in ${here.recheckMinutes} minutes.",
                )
            }

            // Unresolved WATCH (or WAIT without local evidence)
            val headline = "No clear recommendation to move yet"
            val why = if (remotePositiveWindows.isNotEmpty()) {
                val rem = remotePositiveWindows.first()
                val remArea = cleanZoneDisplayName(rem.zone)
                val remMins = rem.minutesAway?.toInt()
                val distClause = if (remMins != null && remMins > 0) {
                    " is about $remMins minutes away"
                } else {
                    " is in another area"
                }
                val limitClause = if (repositionLimitMinutes != null && remMins != null && remMins > repositionLimitMinutes) {
                    " and exceeds your $repositionLimitMinutes-minute driving limit"
                } else {
                    ""
                }
                "The activity listed in $remArea (${normalizePlainDriverCopy(rem.headline)})$distClause$limitClause. It does not establish stronger pickup demand here in ${here.label}. Check again in ${here.recheckMinutes} minutes."
            } else {
                "RideEdge does not have enough live or past-trip evidence in ${here.label} right now to confirm staying or moving. Check again in ${here.recheckMinutes} minutes."
            }
            return HereDecisionView(
                stateCode = "WATCH",
                badgeLabel = "NO CLEAR MOVE YET",
                headline = headline,
                whyText = why,
                evidenceChipLabel = evidenceChipLabel,
                isLocalLive = false,
                remoteContextNote = null,
                spokenSummary = "$headline. $why",
            )
        }

        /**
         * N06: Truthful completion message for venue crowd checks.
         */
        fun formatVenuePollStatus(
            polledCount: Int,
            refreshedAwareness: AwarenessState?,
        ): Pair<String, Boolean> {
            if (refreshedAwareness == null) {
                return "Checked $polledCount venues, but refreshing the screen failed. Previous readings are still shown." to true
            }
            val freshLiveCount = refreshedAwareness.venueActivity.count { it.liveRecent && it.liveValue != null }
            return if (freshLiveCount > 0) {
                val suffix = if (freshLiveCount == 1) "" else "s"
                "Checked $polledCount venues; $freshLiveCount fresh live reading$suffix available." to false
            } else {
                "Checked $polledCount venues; no fresh live readings available." to false
            }
        }

        /**
         * N10: Specific exclusion badge and explanation for Compare options.
         */
        fun formatCompareExclusion(
            option: AskOptionRow,
            maxDriveMinutes: Int,
        ): Pair<String, String> {
            val reasonsLower = option.reasons.joinToString(" ") { it.lowercase(Locale.US) }
            val routeUnknown = option.routeMinutes == null ||
                option.routeStatus.lowercase(Locale.US) in setOf("unavailable", "unknown", "missing") ||
                "route time is unknown" in reasonsLower ||
                "route unavailable" in reasonsLower
            if (routeUnknown) {
                return "Route unavailable" to "No current route estimate is available for ${option.area}."
            }
            val driveMins = option.routeMinutes?.toInt()
            if (
                (driveMins != null && driveMins > maxDriveMinutes) ||
                "under $maxDriveMinutes" in reasonsLower ||
                "reposition" in reasonsLower ||
                "drive limit" in reasonsLower
            ) {
                val detail = if (driveMins != null) {
                    "${option.area} is about $driveMins minutes away (your limit is $maxDriveMinutes minutes)."
                } else {
                    "Estimated drive exceeds your $maxDriveMinutes-minute driving limit."
                }
                return "Exceeds your $maxDriveMinutes-minute drive limit" to detail
            }
            if ("window" in reasonsLower || "ends" in reasonsLower || "after" in reasonsLower) {
                return "Arrives after the useful window" to "Estimated arrival is too close to the end of the active window."
            }
            val fallback = option.reasons.firstOrNull()?.let { normalizePlainDriverCopy(it) }
                ?: "Does not beat staying in your current area."
            return "Not recommended right now" to fallback
        }
    }
}
