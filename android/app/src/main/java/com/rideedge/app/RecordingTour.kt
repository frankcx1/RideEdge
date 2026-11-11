package com.rideedge.app

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/** UI choreography only. Never authorizes live requests, GPS or navigation. */
internal data class RecordingCue(val scene: Int, val shot: String, val title: String, val seconds: Int = 24)
internal val recordingCues = listOf(
    RecordingCue(0, "now", "Kirkland: the next move"),
    RecordingCue(0, "why", "Inspect the supporting evidence"),
    RecordingCue(0, "alternatives", "Compare nearby options"),
    RecordingCue(0, "nearby", "Explore the activity around us"),
    RecordingCue(0, "explore", "Explore Capitol Hill without moving the driver"),
    RecordingCue(0, "sources", "Inspect the source inventory"),
    RecordingCue(0, "source_detail", "Open a source report"),
    RecordingCue(0, "ask", "Ask Qwen: prepared recording answer"),
    RecordingCue(0, "plan", "Look ahead across six hours"),
    RecordingCue(1, "now", "SeaTac: after the airport drop-off"),
    RecordingCue(1, "seatac", "Hour-by-hour airport arrivals"),
    RecordingCue(1, "seatac_more", "Inspect later arrival windows"),
    RecordingCue(1, "plan", "The story continues with a Seattle rematch"),
    RecordingCue(2, "now", "Downtown Seattle drop-off"),
    RecordingCue(2, "nearby", "Dinner activity around Seattle"),
    RecordingCue(2, "plan_detail", "Inspect an outlook window and alternatives"),
    RecordingCue(3, "now", "Belltown: dinner departures"),
    RecordingCue(3, "further", "Compare a little further away"),
    RecordingCue(4, "now", "Paramount: theater departure window"),
    RecordingCue(4, "why", "Inspect timing and travel evidence"),
    RecordingCue(4, "plan", "Reassess the remaining evening"),
    RecordingCue(4, "comparison", "Compare the prepared model and algorithm choices"),
    RecordingCue(5, "now", "WAMU: the next departure wave"),
    RecordingCue(5, "why", "Review the WAMU recommendation"),
    RecordingCue(5, "nearby", "Compare activity nearby"),
    RecordingCue(6, "now", "Capitol Hill: after midnight"),
    RecordingCue(6, "plan_detail", "Review the late-night outlook"),
    RecordingCue(7, "now", "Back to the Eastside"),
    RecordingCue(7, "nearby", "Kirkland and Redmond alternatives"),
    RecordingCue(7, "plan", "The final outlook")
)
internal data class RecordingTourState(val index: Int = -1, val playing: Boolean = false,
    val revision: Int = 0, val remaining: Int = 0, val error: String? = null,
    val cue: RecordingCue? = recordingCues.getOrNull(index))

internal class RecordingTour(private val scope: CoroutineScope, private val allowed: () -> Boolean,
    private val cueSource: () -> List<RecordingCue> = { recordingCues },
    private val prepare: suspend (RecordingCue) -> Unit) {
    val cues: List<RecordingCue> get() = cueSource()
    private val mutable = MutableStateFlow(RecordingTourState())
    val state = mutable.asStateFlow()
    val clean = MutableStateFlow(false)
    private var job: Job? = null
    var phoneRevision = -1
    var carRevision = -1
    var carError: String? = null
    fun seek(index: Int, play: Boolean = false) {
        if (!allowed() || index !in cues.indices) return
        job?.cancel()
        job = scope.launch {
            try {
                var current = index
                while (true) {
                    withTimeout(10000) { prepare(cues[current]) }
                    mutable.value = RecordingTourState(current, play, mutable.value.revision + 1, cues[current].seconds, cue = cues[current])
                    if (!play) break
                    countdown()
                    if (current == cues.lastIndex) { pause(); break }
                    current++
                }
            } catch (_: TimeoutCancellationException) {
                mutable.value = mutable.value.copy(playing = false, error = "Replay load timed out; retry this shot.")
            } catch (cancel: CancellationException) { throw cancel }
            catch (_: Exception) { mutable.value = mutable.value.copy(playing = false, error = "Replay could not load. Pause and retry this shot.") }
        }
    }
    private suspend fun countdown() {
        while (mutable.value.remaining > 0) {
            delay(1000)
            mutable.value = mutable.value.copy(remaining = mutable.value.remaining - 1)
        }
    }
    fun pause() { job?.cancel(); mutable.value = mutable.value.copy(playing = false) }
    fun resume() {
        if (!allowed() || state.value.playing) return
        if (state.value.index < 0) { seek(0, true); return }
        job?.cancel()
        mutable.value = mutable.value.copy(playing = true)
        job = scope.launch {
            countdown()
            if (state.value.index < cues.lastIndex) seek(state.value.index + 1, true) else pause()
        }
    }
    fun stop() { job?.cancel(); mutable.value = RecordingTourState(revision = mutable.value.revision + 1) }
}
