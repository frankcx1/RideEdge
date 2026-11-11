package com.rideedge.app

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import java.time.Instant
import kotlin.math.*

data class RadarFix(val latitude: Double, val longitude: Double, val accuracyMeters: Double, val fixAt: Instant)
fun interface RadarLocationSource { suspend fun currentFix(): RadarFix? }
fun interface RadarTransport { suspend fun request(path: String, body: JSONObject?): JSONObject }
data class RadarSession(
    val area: String = "Home", val followPhone: Boolean = false, val phoneVisible: Boolean = false,
    val carConnected: Boolean = false, val carActive: Boolean = false,
    val busy: Boolean = false, val notice: String? = null,
)
data class RadarExploration(val received: ReceivedRadar? = null, val area: String = "", val busy: Boolean = false, val error: String? = null)
data class RadarAnswer(val question: String = "", val received: ReceivedRadar? = null, val busy: Boolean = false, val error: String? = null)

/** One repository per Application; UI and car rendering only observe it. */
class RadarRepository(
    private val scope: CoroutineScope,
    private val transport: RadarTransport,
    private val location: RadarLocationSource,
    private val elapsedMs: () -> Long,
    private val bootId: () -> Int,
    initialArea: String = "Home",
    followPhone: Boolean = false,
    private val savePreference: (String, Boolean) -> Unit = { _, _ -> },
) {
    val store = RadarStateStore(elapsedMs, bootId)
    val state = store.state
    private val mutableSession = MutableStateFlow(RadarSession(initialArea, followPhone))
    val session = mutableSession.asStateFlow()
    private val mutableExploration = MutableStateFlow(RadarExploration())
    val exploration = mutableExploration.asStateFlow()
    private val mutableAnswer = MutableStateFlow(RadarAnswer())
    val answer = mutableAnswer.asStateFlow()
    private val mutableClock = MutableStateFlow(elapsedMs())
    val clock = mutableClock.asStateFlow()
    private val activeRequest = Mutex()
    private var loop: Job? = null
    private var previewJob: Job? = null
    private var askJob: Job? = null
    private var refreshJob: Job? = null
    private var previewGeneration = 0L
    private var nextPoll = 0L
    private var nextFix = 0L
    private var pendingUntil = 0L
    private var carUntil = 0L
    private var failures = 0
    private var contextNeeded = true
    private val visiblePhoneOwners = mutableSetOf<Any>()

    fun setPhoneVisible(visible: Boolean, owner: Any = this) {
        if (visible) visiblePhoneOwners.add(owner) else visiblePhoneOwners.remove(owner)
        mutableSession.value = session.value.copy(phoneVisible = visiblePhoneOwners.isNotEmpty())
        updateLoop()
    }

    fun setCarConnected(connected: Boolean) {
        // Disconnect stops the location foreground service. A background reconnect
        // cannot restart its while-in-use permission: require a fresh phone start.
        if (!connected) carUntil = 0
        mutableSession.value = session.value.copy(carConnected = connected,
            carActive = connected && session.value.carActive && elapsedMs() < carUntil)
        updateLoop() // disconnected car-only subscriptions are cancelled immediately
    }

    /** Called only after a supported location/session start flow succeeds. */
    fun startCarSession() {
        if (!session.value.carConnected) return
        carUntil = elapsedMs() + 6*60*60*1000L
        mutableSession.value = session.value.copy(carActive = true)
        updateLoop()
    }

    fun endCarSession() {
        carUntil = 0
        mutableSession.value = session.value.copy(carActive = false)
        updateLoop()
    }

    fun chooseArea(area: String) {
        if (area.isBlank()) return
        changeOrigin(area.take(120), false)
    }

    fun usePhone() = changeOrigin(session.value.area, true)

    private fun changeOrigin(area: String, phone: Boolean) {
        store.beginOriginChange()
        askJob?.cancel()
        mutableAnswer.value = RadarAnswer()
        mutableSession.value = session.value.copy(area = area, followPhone = phone, notice = null)
        savePreference(area, phone) // no coordinates or fix history
        contextNeeded = true
        nextPoll = 0
        nextFix = 0
        updateLoop()
    }

    fun hasActiveCarSession(): Boolean = session.value.carConnected && session.value.carActive && elapsedMs() < carUntil

    // Rendering may occur between a response receipt and the next clock-flow tick.
    fun currentElapsedMs(): Long = elapsedMs()

    private fun active(): Boolean = session.value.phoneVisible || hasActiveCarSession()

    private fun updateLoop() {
        if (!active()) {
            loop?.cancel(); loop = null
            mutableSession.value = session.value.copy(busy = false)
            return
        }
        if (loop?.isActive == true) return
        loop = scope.launch {
            while (isActive) {
                val now = elapsedMs()
                mutableClock.value = now
                if (session.value.carActive && now >= carUntil) {
                    mutableSession.value = session.value.copy(carActive = false)
                }
                if (!active()) break
                if (now >= nextPoll) {
                    refreshCurrent()
                }
                delay(1000)
            }
        }
    }

    private suspend fun refreshCurrent() = activeRequest.withLock {
        if (!active()) return@withLock
        var generation = state.value.requestGeneration
        mutableSession.value = session.value.copy(busy = true)
        try {
            val body = if (session.value.followPhone && (contextNeeded || elapsedMs() >= nextFix)) {
                nextFix = elapsedMs() + 60000
                val fix = location.currentFix() ?: run {
                    mutableSession.value = session.value.copy(notice = "Could not get a precise location. Try again or choose an area.")
                    // Do not GET the previous area's context and relabel it as
                    // phone location while this origin change is unresolved.
                    nextPoll = nextFix
                    return@withLock
                }
                if (generation != state.value.requestGeneration || !active()) return@withLock
                val old = state.value.received?.snapshot?.origin
                if (old != null && distanceMiles(old.latitude, old.longitude, fix.latitude, fix.longitude) > .25) {
                    generation = store.beginOriginChange()
                    askJob?.cancel(); mutableAnswer.value = RadarAnswer()
                }
                JSONObject().put("latitude", fix.latitude).put("longitude", fix.longitude)
                    .put("accuracy_meters", fix.accuracyMeters).put("fix_at", fix.fixAt.toString())
            } else if (contextNeeded) JSONObject().put("area", session.value.area) else null
            val result = transport.request(if (body != null) "/context" else "", body)
            if (generation != state.value.requestGeneration) return@withLock
            val expectedMode = if (session.value.followPhone) "device" else "selected_area"
            check(result.optJSONObject("origin")?.optString("mode") == expectedMode) { "Origin mode changed" }
            contextNeeded = false
            if (store.accept(result, generation)) {
                mutableSession.value = session.value.copy(notice = null)
                failures = 0
            }
            nextPoll = elapsedMs() + if (elapsedMs() < pendingUntil) 5000 else 30000
        } catch (cancel: CancellationException) {
            throw cancel
        } catch (error: Exception) {
            if (error is AccessRequiredException) store.accessRequired(generation) else store.disconnected(generation)
            failures = (failures + 1).coerceAtMost(4)
            nextPoll = elapsedMs() + min(120000L, 15000L * (1L shl failures))
            // A restarted backend needs context again. Retrying observes normal backoff.
            contextNeeded = true
            nextFix = min(nextFix, nextPoll)
        } finally {
            mutableSession.value = session.value.copy(busy = false)
        }
    }

    fun refresh() {
        if (refreshJob?.isActive == true) return
        if (state.value.received == null) {
            contextNeeded = true; nextPoll = 0; nextFix = 0; updateLoop(); return
        }
        pendingUntil = elapsedMs() + 5*60*1000
        nextPoll = 0
        refreshJob = scope.launch {
            try {
                activeRequest.withLock { transport.request("/refresh", JSONObject()) }
                mutableSession.value = session.value.copy(notice = "Review requested. Current evidence remains available.")
            } catch (cancel: CancellationException) { throw cancel }
            catch (_: Exception) { mutableSession.value = session.value.copy(notice = "Could not request a review. Check Tailscale and try again.") }
        }
    }

    fun retryConnection() {
        contextNeeded = true; nextPoll = 0; nextFix = 0
        updateLoop()
    }

    fun explore(area: String) {
        if (area.isBlank()) return
        val generation = ++previewGeneration
        previewJob?.cancel()
        mutableExploration.value = RadarExploration(area = area, busy = true)
        previewJob = scope.launch {
            try {
                val result = transport.request("/preview", JSONObject().put("area", area.take(120)))
                val snapshot = RadarParser.parse(result)
                if (generation == previewGeneration) mutableExploration.value = RadarExploration(
                    ReceivedRadar(snapshot, elapsedMs(), bootId()), snapshot.origin.label)
            } catch (cancel: CancellationException) { throw cancel }
            catch (_: Exception) {
                if (generation == previewGeneration) mutableExploration.value = RadarExploration(area = area,
                    error = "This area could not be loaded. Your driving origin is unchanged.")
            }
        }
    }

    fun clearExploration() {
        previewGeneration++; previewJob?.cancel(); mutableExploration.value = RadarExploration()
    }

    fun ask(question: String) {
        if (question.isBlank() || askJob?.isActive == true) return
        val current = state.value.received?.snapshot ?: return
        val generation = state.value.requestGeneration
        mutableAnswer.value = RadarAnswer(question.take(700), busy = true)
        askJob = scope.launch {
            try {
                val job = transport.request("/ask", JSONObject().put("snapshot_id", current.snapshotId).put("question", question.take(700)))
                val jobId = job.getString("job_id")
                require(jobId.matches(Regex("[A-Za-z0-9-]{1,80}")))
                val deadline = elapsedMs() + 5*60*1000
                while (isActive && generation == state.value.requestGeneration && elapsedMs() < deadline) {
                    delay(5000)
                    val result = transport.request("/ask/jobs/$jobId", null)
                    when (result.getString("state")) {
                        "ready" -> {
                            val snapshot = RadarParser.parse(result.getJSONObject("answer"))
                            if (generation == state.value.requestGeneration) mutableAnswer.value = RadarAnswer(question,
                                ReceivedRadar(snapshot, elapsedMs(), bootId()))
                            return@launch
                        }
                        "failed" -> error("Model answer unavailable")
                    }
                }
                error("Question observation deadline reached")
            } catch (cancel: CancellationException) { throw cancel }
            catch (_: Exception) {
                if (generation == state.value.requestGeneration) mutableAnswer.value = RadarAnswer(question,
                    error = "Qwen has not returned a current, validated answer. Your activity options remain available.")
            }
        }
    }

    fun navigationTarget(id: String): RadarPlace? = store.navigationTarget(id).also {
        if (it == null) mutableSession.value = session.value.copy(notice = "This option is no longer current. Refresh before navigating.")
    }

    fun close() { loop?.cancel(); previewJob?.cancel(); askJob?.cancel(); refreshJob?.cancel() }
}

internal fun distanceMiles(lat: Double, lon: Double, otherLat: Double, otherLon: Double): Double {
    val a = Math.toRadians(lat); val b = Math.toRadians(otherLat)
    val d = sin((b-a)/2).pow(2) + cos(a)*cos(b)*sin(Math.toRadians(otherLon-lon)/2).pow(2)
    return 3958.8 * 2 * asin(sqrt(d.coerceIn(0.0, 1.0)))
}
