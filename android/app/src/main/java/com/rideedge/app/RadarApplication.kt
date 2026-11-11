package com.rideedge.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.location.Location
import android.os.CancellationSignal
import android.os.SystemClock
import android.provider.Settings
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.car.app.connection.CarConnection
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import kotlin.coroutines.resume

class RideEdgeApplication : Application() {
    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    var previewScenario: String = "fallback"
        set(value) {
            if (field != value) {
                previewEpoch = null
                previewRevision = 0
                previewResponses = 0
            }
            field = value
        }
    var previewAccessCheck: String? = null
    internal val recordingStep = MutableStateFlow(0)
    internal val recordingDemo by lazy { RecordingDemo(this) }
    internal val recordingTour by lazy { RecordingTour(applicationScope,
        { BuildConfig.BUILD_TYPE == "preview" && previewScenario == "recording" },
        { recordingDemo.cues }) { cue ->
        selectRecordingStep(cue.scene)
        val expected = recordingDemo.scene(cue.scene).getJSONObject("radar").getString("snapshot_id")
        radar.state.first { it.received?.snapshot?.snapshotId == expected && !it.changingOrigin }
        if (radar.session.value.carConnected && !radar.hasActiveCarSession()) radar.startCarSession()
    } }
    internal fun selectRecordingStep(step: Int) {
        if (BuildConfig.BUILD_TYPE != "preview" || previewScenario != "recording") return
        recordingStep.value = step.coerceIn(0, recordingDemo.sceneCount - 1)
        radar.clearExploration()
        radar.refresh()
    }
    private var previewResponses = 0
    private var previewEpoch: Instant? = null
    private var previewRevision = 0
    private var previewElapsedOffsetMs = 0L
    /** Deterministic DHU expiry test; never changes Android's clock or normal-app time. */
    internal fun advancePreviewSessionClock() {
        if (BuildConfig.BUILD_TYPE == "preview") previewElapsedOffsetMs += 6 * 60 * 60 * 1000L
    }
    internal fun radarElapsedMs(): Long = if (BuildConfig.BUILD_TYPE == "preview" && previewScenario == "recording")
        100000L else SystemClock.elapsedRealtime() + if (BuildConfig.BUILD_TYPE == "preview") previewElapsedOffsetMs else 0L
    val carLocation = CarRadarLocation()
    val phoneLocation by lazy { PhoneRadarLocation(this) }
    var phoneLocationServiceRunning = false
    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.BUILD_TYPE != "preview") RideEdgeClient.initializeAccess(AndroidAccessKeyStore(this))
        // Only connection state is observed; this does not start GPS or polling.
        CarConnection(this).type.observeForever { type ->
            radar.setCarConnected(type == CarConnection.CONNECTION_TYPE_PROJECTION)
        }
        if (BuildConfig.BUILD_TYPE != "preview") applicationScope.launch {
            radar.session.map { carPhoneLocationSessionActive(it) to it.phoneVisible }.distinctUntilChanged().collect { (active, visible) ->
                val intent = Intent(this@RideEdgeApplication, CarSessionLocationService::class.java)
                if (!active) stopService(intent)
                else if (visible && !phoneLocationServiceRunning) {
                    // Start only while the phone UI is visible: Android's while-in-use
                    // permission rules prohibit assuming background start eligibility.
                    runCatching { ContextCompat.startForegroundService(this@RideEdgeApplication, intent) }
                        .onFailure { radar.endCarSession() }
                }
            }
        }
    }
    val radar: RadarRepository by lazy {
        val preferences = getSharedPreferences("activity_radar", Context.MODE_PRIVATE)
        RadarRepository(applicationScope,
            RadarTransport { path, body -> withContext(Dispatchers.IO) {
                if (BuildConfig.BUILD_TYPE == "preview") previewResponse(path, body)
                else RideEdgeClient.request("/api/radar$path", if (body == null) "GET" else "POST", body, 15000)
            } }, RadarLocationSource {
                val session = radar.session.value
                if (phoneLocationAllowed(session, phoneLocationServiceRunning)) phoneLocation.currentFix()
                else null
            }, ::radarElapsedMs,
            { Settings.Global.getInt(contentResolver, Settings.Global.BOOT_COUNT, -1) },
            preferences.getString("area", "Home") ?: "Home", preferences.getBoolean("follow_phone", false),
        ) { area, phone -> preferences.edit().putString("area", area).putBoolean("follow_phone", phone).apply() }
    }

    private fun previewResponse(path: String, body: JSONObject? = null): JSONObject {
        if (previewScenario == "recording") return recordingDemo.request(recordingStep.value, path, body)
        if (previewScenario == "offline") error("Offline fixture")
        if (previewScenario == "unauthorized") throw AccessRequiredException("Synthetic fixture: the access key was rejected.")
        if (previewScenario == "saved" && previewResponses > 0) error("Synthetic connection loss")
        if (path == "/refresh") {
            previewEpoch = Instant.now()
            previewRevision++
            return JSONObject().put("queued", true)
        }
        if (path.startsWith("/ask")) error("Local model requests are disabled in the offline preview")
        val json = assets.open("radar-v1.json").bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
        json.put("synthetic", true).put("limits", "SYNTHETIC PREVIEW · no live data, location collection or model requests.")
        json.getJSONObject("scheduler").put("state", "preview").put("next_review_at", JSONObject.NULL)
        json.getJSONObject("qwen").put("state", "fixture").put("detail", "Offline design fixture")
        if (previewScenario in setOf("design", "saved", "expired", "incompatible", "stress", "positioning", "no_options")) {
            // Polls observe one review; only explicit refresh creates a new plan epoch.
            val epoch = previewEpoch ?: Instant.now().also { previewEpoch = it }
            val delta = java.time.Duration.between(Instant.parse(json.getString("server_time")), epoch)
            fun rebase(value: Any?) {
                when (value) {
                    is JSONObject -> value.keys().asSequence().toList().forEach { key ->
                        val child = value.get(key)
                        if (child is String && child.matches(Regex("\\d{4}-\\d{2}-\\d{2}T.*Z"))) {
                            runCatching { Instant.parse(child).plus(delta).toString() }.getOrNull()?.let { value.put(key, it) }
                        } else rebase(child)
                    }
                    is JSONArray -> for (i in 0 until value.length()) rebase(value.get(i))
                }
            }
            rebase(json)
            json.put("server_time", Instant.now().toString())
            json.put("decision_revision", "synthetic-review-$previewRevision")
            json.getJSONObject("origin").put("label", "Totem Lake / Kingsgate")
            json.getJSONObject("qwen").put("state", "pending")
            val names = listOf("Moss Bay Hall", "Matador Redmond", "Flatstick Pub · Kirkland")
            val distances = listOf(2.2, 2.7, 4.1)
            val minutes = listOf(8.1, 10.0, 15.0)
            val choices = json.getJSONArray("now")
            for (i in 0 until minOf(choices.length(), 3)) {
                val place = choices.getJSONObject(i)
                place.put("name", names[i]).put("radius_miles", distances[i]).put("qwen_reason", JSONObject.NULL)
                    .put("busyness", if (i == 0) 55 else if (i == 1) 65 else JSONObject.NULL)
                    .put("busyness_basis", if (i < 2) "typical weekly pattern" else JSONObject.NULL)
                place.getJSONObject("route").put("minutes", minutes[i])
                place.getJSONArray("evidence").getJSONObject(0)
                    .put("source", "Synthetic design fixture").put("basis", "typical weekly pattern")
                    .put("text", "Fictional activity for visual review. Not a real observation or destination recommendation.")
            }
            if (previewScenario == "expired") json.put("valid_until", json.getString("server_time"))
            if (previewScenario == "incompatible") json.put("schema_version", 999)
        }
        if (previewScenario in setOf("positioning", "no_options")) {
            json.put("activity_coverage", "Venue activity: no usable readings. BestTime collection paused.")
            json.put("decision_state", if (previewScenario == "positioning") "contextual_fallback" else "none_supported")
            if (previewScenario == "no_options") {
                json.put("now", JSONArray()).put("further", JSONArray())
                    .put("decision_message", "No supported immediate move. Nearby, Plan and reports remain available.")
                json.getJSONArray("plan").getJSONObject(0).put("selected_id", JSONObject.NULL)
            } else {
                json.put("decision_message", "Area to consider · current activity and opening hours unverified.")
                val collections = listOf(json.getJSONArray("now"), json.getJSONArray("nearby"), json.getJSONArray("further"),
                    json.getJSONArray("plan").getJSONObject(0).getJSONArray("options"))
                collections.forEach { rows -> for (i in 0 until rows.length()) rows.getJSONObject(i).apply {
                    put("decision_class", "contextual_fallback").put("hours_status", "unknown")
                    put("strength", "Area to consider · current activity unverified").put("busyness", JSONObject.NULL)
                    put("busyness_basis", JSONObject.NULL).put("qwen_reason", JSONObject.NULL)
                    put("activity_coverage", json.getString("activity_coverage"))
                    getJSONArray("evidence").getJSONObject(0).put("role", "context").put("basis", "best guess")
                        .put("text", "Offline test of a catalogued area; current activity and opening hours unverified.")
                } }
            }
        }
        if (previewScenario == "stress") {
            val nearby = json.getJSONArray("nearby")
            for (i in 0 until nearby.length()) nearby.getJSONObject(i).apply {
                put("name", "Synthetic long neighborhood and restaurant name · option ${i+1}")
                put("busyness", when(i) { 0 -> 0; 1 -> 125; else -> JSONObject.NULL })
                put("busyness_basis", "typical weekly pattern")
                put("category", listOf("Places", "Events", "Activity")[i % 3])
            }
            val plan = json.getJSONArray("plan")
            plan.getJSONObject(plan.length()-1).put("selected_id", JSONObject.NULL).put("options", JSONArray())
        }
        if (previewScenario == "cleanup") {
            json.getJSONObject("qwen").put("state", "ready")
            json.put("runtime", JSONObject().put("cleanup", JSONObject().put("state", "restoration_failed")
                .put("detail", "Fixture: the answer completed, but GPU restoration is unresolved. New AI reviews are blocked.")))
        }
        if (previewScenario == "stale") {
            json.put("location_stale", true).put("now", JSONArray()).put("further", JSONArray())
        }
        if (previewScenario == "arrival") {
            val upcoming = JSONObject(json.getJSONArray("nearby").getJSONObject(0).toString())
            upcoming.put("id", "fixture:upcoming-exit").put("name", "Synthetic concert exit")
                .put("strength", "Upcoming / ended activity").put("category", "Events")
                .put("actionable", false).put("unavailable_reason", "opportunity_not_active_on_arrival")
                .put("qwen_reason", JSONObject.NULL).put("busyness", JSONObject.NULL)
            upcoming.put("evidence", JSONArray().put(JSONObject()
                .put("id", "fixture:exit-window").put("source", "Synthetic event fixture")
                .put("basis", "scheduled").put("text", "An estimated exit window later tonight.")
                .put("role", "opportunity").put("arrival_relevant", false)
                .put("starts_at", "2026-11-01T06:30:00Z").put("ends_at", "2026-11-01T07:15:00Z")
                .put("timing_note", "Fictional timing for UI review; not a live event.")))
            val nearby = JSONArray().put(upcoming)
            val existing = json.getJSONArray("nearby")
            for (i in 0 until existing.length()) nearby.put(existing.getJSONObject(i))
            json.put("nearby", nearby)
        }
        previewResponses++
        return json
    }
}

class RadarViewModel(application: Application) : AndroidViewModel(application) {
    val repository = (application as RideEdgeApplication).radar
    private var initialized = false
    fun initialize(area: String?) {
        if (initialized) return
        initialized = true
        if (!area.isNullOrBlank()) repository.chooseArea(area)
    }
}

class PhoneRadarLocation(private val context: Context) : RadarLocationSource {
    var status = "Waiting for phone location"
        private set
    @SuppressLint("MissingPermission")
    override suspend fun currentFix(): RadarFix? {
        if (BuildConfig.BUILD_TYPE == "preview") return null
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            status = "Precise phone location permission required"; return null
        }
        status = "Waiting for phone location"
        val result = withTimeoutOrNull(15000) {
            suspendCancellableCoroutine { continuation ->
                val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
                val providers = listOf(LocationManager.FUSED_PROVIDER, LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                    .filter { runCatching { manager.isProviderEnabled(it) }.getOrDefault(false) }
                if (providers.isEmpty()) { continuation.resume(null); return@suspendCancellableCoroutine }
                val cancellations = providers.map { CancellationSignal() }
                continuation.invokeOnCancellation { cancellations.forEach { it.cancel() } }
                var pending = providers.size
                fun received(loc: Location?) {
                    if (!continuation.isActive) return
                    val fix = loc?.toRadarFix(maxAgeMs = 60000)
                    pending--
                    if (fix != null || pending == 0) {
                        cancellations.forEach { it.cancel() }
                        continuation.resume(fix)
                    }
                }
                providers.forEachIndexed { index, provider ->
                    if (continuation.isActive) runCatching {
                        manager.getCurrentLocation(provider, cancellations[index], context.mainExecutor) { loc ->
                            received(loc)
                        }
                    }.onFailure { received(null) }
                }
            }
        }
        status = if (result != null) "Phone location available" else "Phone location unavailable or not precise enough"
        return result
    }
}

internal fun Location.toRadarFix(maxAgeMs: Long = 300000): RadarFix? {
    val ageMs = (SystemClock.elapsedRealtimeNanos() - elapsedRealtimeNanos) / 1_000_000
    return if (ageMs in 0..maxAgeMs && hasAccuracy() && accuracy.isFinite() && accuracy in 0f..200f &&
        latitude in 47.0..48.2 && longitude in -123.0..-121.5)
        RadarFix(latitude, longitude, accuracy.toDouble(), Instant.ofEpochMilli(time)) else null
}
