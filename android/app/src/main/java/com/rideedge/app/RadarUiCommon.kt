package com.rideedge.app

import androidx.compose.ui.graphics.Color
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal val RadarBg = Edge.Paper
internal val RadarCard = Edge.Card
// Compatibility names while individual renderers migrate to explicit semantic roles.
internal val RadarMint = Edge.Blue
internal val RadarMuted = Edge.Soft
internal val RadarAmber = Edge.Pressed // Small text on cards needs the lighter palette tone for contrast.
internal fun JSONObject.countText(key: String): String = when (val value = opt(key)) {
    is Number -> value.toString()
    else -> "unknown"
}
internal fun JSONObject.rows(key: String): List<JSONObject> = optJSONArray(key).objects()
private fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else
    (0 until length()).mapNotNull { optJSONObject(it) }
internal fun radarSameOrigin(current: JSONObject?, asked: JSONObject?): Boolean {
    if (current == null || asked == null || current.optString("mode") != asked.optString("mode")) return false
    return kotlin.math.abs(current.optDouble("latitude") - asked.optDouble("latitude")) <= .001 &&
        kotlin.math.abs(current.optDouble("longitude") - asked.optDouble("longitude")) <= .001
}
internal fun clockTime(value: String): String = runCatching {
    DateTimeFormatter.ofPattern("h:mm a", Locale.US).withZone(ZoneId.of("America/Los_Angeles")).format(Instant.parse(value))
}.getOrDefault("Unknown")
