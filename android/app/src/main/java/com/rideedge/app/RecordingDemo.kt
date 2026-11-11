package com.rideedge.app

import android.content.Context
import org.json.JSONObject

internal const val RECORDING_MAP_QUERY = "Paramount+Theatre+911+Pine+Street+Seattle+WA"

/** Static recording data exists only in the separate Preview APK's assets. */
internal class RecordingDemo(private val context: Context) {
    private val refreshRevision = java.util.concurrent.atomic.AtomicInteger()
    private val data by lazy {
        check(BuildConfig.BUILD_TYPE == "preview")
        val captured = java.io.File(context.filesDir, "captured-session.json")
        if (captured.exists()) JSONObject(captured.readText()).also {
            check(it.getString("kind") == "captured_session" && it.getInt("schema_version") == 1)
            check(it.getJSONArray("stages").length() == 1)
            RadarParser.parse(it.getJSONArray("stages").getJSONObject(0).getJSONObject("radar"))
        } else context.assets.open("recording-demo.json").bufferedReader().use { JSONObject(it.readText()) }
    }
    val isCaptured: Boolean get() = data.optString("kind") == "captured_session"
    val captureId: String? get() = if (isCaptured) data.getString("capture_id") else null
    val cues: List<RecordingCue> get() = if (!isCaptured) recordingCues else
        data.getJSONArray("cues").let { rows -> (0 until rows.length()).map { i ->
            val row = rows.getJSONObject(i)
            check(row.getInt("scene") == 0 && row.getInt("seconds") in 5..60)
            check(row.getString("shot") in setOf("now", "why", "alternatives", "nearby", "plan", "comparison", "sources", "source_detail", "seatac"))
            RecordingCue(0, row.getString("shot"), row.getString("title"), row.getInt("seconds"))
        } }
    val sceneCount: Int get() = data.getJSONArray("stages").length()
    fun scene(step: Int): JSONObject = data.getJSONArray("stages").getJSONObject(step.coerceIn(0, sceneCount - 1))
    /** Resolve only a public area reference from the bundled scene, never provider text. */
    fun navigationTarget(step: Int, displayed: RadarPlace): RadarPlace? {
        val snapshot = RadarParser.parse(scene(step).getJSONObject("radar"))
        return (snapshot.now + snapshot.further + snapshot.nearby).firstOrNull {
            it.actionable && it.id == displayed.id && it.name == displayed.name &&
                it.latitude == displayed.latitude && it.longitude == displayed.longitude
        }
    }
    fun request(step: Int, path: String, body: JSONObject? = null): JSONObject {
        val scene = scene(step)
        val radar = JSONObject(scene.getJSONObject("radar").toString())
        if (isCaptured) return when {
            path == "/refresh" -> JSONObject().put("queued", false)
            path == "/preview" -> error("This area was not captured. Use the live app to explore another location.")
            path == "/ask" || path.startsWith("/ask/jobs/") -> error("This recording retains the actual Qwen review. New questions require the live app.")
            else -> radar
        }
        radar.put("decision_revision", "recording-$step-${refreshRevision.get()}")
        if (path == "/preview") {
            val area = body?.optString("area").orEmpty()
            val center = when {
                area.contains("kirkland", true) -> 47.6769 to -122.206
                area.contains("redmond", true) -> 47.674 to -122.1215
                area.contains("totem", true) -> 47.712 to -122.18
                area.contains("capitol", true) -> 47.614 to -122.319
                area.contains("seattle", true) -> 47.6205 to -122.3509
                area.contains("bellevue", true) -> 47.615 to -122.201
                else -> error("Choose Seattle, Capitol Hill, Bellevue, Kirkland, Totem Lake or Redmond for this recording")
            }
            radar.getJSONObject("origin").put("label", "$area · demo exploration")
                .put("latitude", center.first).put("longitude", center.second)
            val nearby = radar.getJSONArray("nearby")
            for (i in 0 until nearby.length()) {
                val p = nearby.getJSONObject(i)
                val miles = distanceMiles(center.first, center.second, p.getDouble("latitude"), p.getDouble("longitude"))
                p.put("radius_miles", miles).put("within_now_radius", miles <= 5).put("actionable", false)
                p.getJSONObject("route").put("minutes", miles * 3).put("miles", miles * 1.3).put("basis", "estimated")
            }
        }
        return when {
            path == "/refresh" -> {
                refreshRevision.incrementAndGet()
                JSONObject().put("queued", true)
            }
            path == "/ask" -> JSONObject().put("job_id", "scripted-demo-$step")
            path.startsWith("/ask/jobs/") -> JSONObject().put("state", "ready").put("answer", radar)
            else -> radar
        }
    }
    fun report(step: Int, path: String): JSONObject {
        val scene = scene(step)
        val key = when (path) {
            "/api/seatac/forecast" -> "seatac"
            "/api/feeds/health", "/api/feeds/refresh" -> "health"
            "/api/radar/status" -> "status"
            else -> null
        }
        if (key != null) return JSONObject(scene.getJSONObject(key).toString())
        val adapter = path.removePrefix("/api/feeds/").removeSuffix("/detail")
        if (isCaptured) return JSONObject(scene.getJSONObject("source_details").getJSONObject(adapter).toString())
        val feeds = scene.getJSONObject("health").getJSONArray("feeds")
        val feed = (0 until feeds.length()).map(feeds::getJSONObject).firstOrNull { it.optString("adapter") == adapter }
            ?: error("No demo source")
        return JSONObject(feed.toString()).put("synthetic", true)
            .put("status_message", "Demo replay")
            .put("records", org.json.JSONArray().put(JSONObject().put("title", feed.getString("label"))
                .put("basis", "Replay").put("detail", feed.getString("detail"))))
    }
}
