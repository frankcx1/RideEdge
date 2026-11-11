package com.rideedge.app

/** Presentation only: never grants eligibility or changes retry scheduling. */
internal data class RadarConnectionPresentation(val title: String, val detail: String,
    val action: String, val settingsRequired: Boolean, val retrying: Boolean = false)

internal fun radarConnectionPresentation(state: RadarViewState, accessNote: String?, busy: Boolean,
                                         active: Boolean): RadarConnectionPresentation? = when {
    state.errorCode == "access_required" || accessNote != null -> RadarConnectionPresentation(
        "Connection needs attention", accessNote ?: "The access key is missing or was rejected. Open Connection settings to reconnect.",
        "Connect", true)
    state.errorCode in setOf("schema_mismatch", "invalid_contract") -> RadarConnectionPresentation(
        "Data unavailable", "workstation responded, but its data is incompatible with this app. Saved details remain available for inspection.",
        "Retry connection", false)
    state.connected -> null
    busy -> RadarConnectionPresentation("Connecting", "Contacting workstation. Any saved review keeps its original expiry.", "Connecting", false)
    state.errorCode == "disconnected" -> RadarConnectionPresentation("Not connected",
        if (state.received != null) "workstation could not be reached. Rankings below are the last retained review."
        else "workstation could not be reached. No review is available yet.", "Connect", false, active)
    else -> RadarConnectionPresentation("Connect to workstation", "Connect to load your first review. No recommendation is available yet.", "Connect", true)
}
