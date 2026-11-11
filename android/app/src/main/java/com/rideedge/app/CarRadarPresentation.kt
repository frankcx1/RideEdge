package com.rideedge.app

import java.util.Locale
import java.time.Duration

data class CarRadarView(val title: String, val message: String?, val places: List<RadarPlace>, val status: String)

internal fun carCoverageText(coverage: String): String = when {
    "paused" in coverage.lowercase() -> "Venue feed paused · cached only"
    "no usable" in coverage.lowercase() -> "Venue readings unavailable"
    coverage.isBlank() -> "Activity coverage unknown"
    else -> coverage
}

/** Shared eligibility, never a second scoring engine. Safe to call during rendering. */
fun carRadarView(repo: RadarRepository): CarRadarView {
    if (!repo.hasActiveCarSession()) return CarRadarView("Start on your phone",
        "While parked, open RideEdge on your phone and tap Start car session.", emptyList(), "No active car session")
    val state = repo.state.value
    if (state.errorCode == "access_required") return CarRadarView("Reconnect on your phone",
        state.message, emptyList(), "Access key required")
    if (state.changingOrigin) return CarRadarView("Updating location", "Waiting for a current location. Check RideEdge on your phone if this persists.", emptyList(), "Location pending")
    val data = state.received?.snapshot ?: return CarRadarView("Waiting for RideEdge",
        state.message ?: "Loading current activity. Check Tailscale on your phone if this persists.", emptyList(), "No current decision")
    if (data.origin.mode != "device" && BuildConfig.BUILD_TYPE != "preview") return CarRadarView("Use current location",
        "A selected area's distances are not distances from your car. Choose Use my location on your phone.",
        emptyList(), "Selected area · navigation withheld")
    val places = (data.now + data.further).distinctBy { it.id }.mapNotNull { repo.store.navigationTarget(it.id) }.take(4)
    val status = when {
        data.cleanup?.state == "restoration_failed" -> "Answer retained · AI recovery needed"
        !state.connected -> "Offline · saved evidence"
        places.firstOrNull()?.isPositioningFallback == true -> "Area to consider · activity unverified"
        data.qwen.state == "ready" -> "Local Qwen · reviewed"
        else -> "Evidence ranking · AI ${data.qwen.state}"
    }
    val ageMs = Duration.between(data.generatedAt, data.serverTime).toMillis() +
        (repo.clock.value - state.received.receivedElapsedMs).coerceAtLeast(0)
    return CarRadarView(if (repo.store.primary() != null) "RideEdge · Now" else "RideEdge · Alternatives",
        if (places.isEmpty()) radarEmptyMessage(state, repo.currentElapsedMs()) else null, places,
        "${(ageMs / 60000).coerceAtLeast(0)} min old · $status")
}

fun carRouteText(place: RadarPlace): String = String.format(Locale.US, "%.1f mi radius · %.0f min %s",
    place.radiusMiles, place.route.minutes, if (place.route.basis == "live traffic") "with traffic" else "estimate")

fun carEvidenceText(place: RadarPlace): String = (place.supportingEvidence?.text
    ?: if (place.isPositioningFallback) "Catalogued commercial area. Current activity and opening hours unverified; shorter travel preferred."
    else "No supporting observation available").take(180)

/** Shared explanation; a fresh review timestamp is not fresh provider evidence. */
internal fun radarEmptyMessage(state: RadarViewState, elapsedNow: Long): String {
    val receipt = state.received
    val data = receipt?.snapshot
    return when {
        state.errorCode == "access_required" -> "Reconnect in Connection on your phone while parked."
        state.changingOrigin || data?.locationStale == true -> "Waiting for a current location. Update location on your phone while parked."
        !state.connected -> "Connection lost. Reconnecting automatically; saved details remain available."
        data == null -> "Waiting for the first review."
        data.evidenceStale || elapsedNow < receipt.receivedElapsedMs ||
            data.serverTime.plusMillis(elapsedNow-receipt.receivedElapsedMs) >= data.validUntil ->
            "This review expired. Refresh to check current options."
        data.refreshing || data.scheduler.state == "reviewing" -> "Review in progress. Nearby and Plan remain available."
        else -> data.decisionMessage.ifBlank { "No supported immediate move. Explore Nearby, Plan or reports." }
    }
}
