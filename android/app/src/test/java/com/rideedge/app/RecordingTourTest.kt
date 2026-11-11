package com.rideedge.app

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class RecordingTourTest {
    @Test fun capturedCuesReplaceTheFridayStoryAndStopAtTheirOwnEnd() = runTest {
        val cue = RecordingCue(0, "now", "Captured session", 5)
        val prepared = mutableListOf<RecordingCue>()
        val tour = RecordingTour(backgroundScope, { true }, { listOf(cue) }) { prepared += it }
        tour.seek(0, true); runCurrent()
        assertEquals(cue, tour.state.value.cue)
        advanceTimeBy(5000); runCurrent()
        assertFalse(tour.state.value.playing)
        assertEquals(listOf(cue), prepared)
        tour.seek(1); runCurrent()
        assertEquals(0, tour.state.value.index)
    }
    @Test fun completeTourIsTwelveMinutesAndNeverOpensExternalNavigation() {
        assertEquals(720, recordingCues.sumOf { it.seconds })
        assertEquals((0..7).toSet(), recordingCues.map { it.scene }.toSet())
        assertFalse(recordingCues.any { "maps" in it.shot || "navigate" in it.shot })
    }
    @Test fun disabledControllerCannotRunOrPrepare() = runTest {
        val tour = RecordingTour(backgroundScope, { false }) { error("Must not prepare") }
        tour.seek(0, true); tour.resume(); runCurrent()
        assertEquals(-1, tour.state.value.index)
    }
    @Test fun pausePreservesRemainingTimeAndResumeAdvancesOnce() = runTest {
        val prepared = mutableListOf<String>()
        val tour = RecordingTour(backgroundScope, { true }) { prepared += it.shot }
        tour.seek(0, true); runCurrent()
        advanceTimeBy(5000); runCurrent(); tour.pause()
        assertEquals(19, tour.state.value.remaining)
        advanceTimeBy(50000); runCurrent()
        assertEquals(0, tour.state.value.index)
        tour.resume(); advanceTimeBy(19000); runCurrent()
        assertEquals(1, tour.state.value.index)
        assertEquals(listOf("now", "why"), prepared)
    }
    @Test fun retakeAndStopCancelPendingTransitions() = runTest {
        val tour = RecordingTour(backgroundScope, { true }) { }
        tour.seek(0, true); runCurrent(); tour.seek(15); runCurrent()
        advanceTimeBy(60000); runCurrent()
        assertEquals(15, tour.state.value.index)
        assertFalse(tour.state.value.playing)
        tour.stop(); advanceTimeBy(60000); runCurrent()
        assertEquals(-1, tour.state.value.index)
    }
    @Test fun sceneLoadFailureStopsInsteadOfClaimingTheNextShot() = runTest {
        val tour = RecordingTour(backgroundScope, { true }) { error("Missing fixture") }
        tour.seek(0, true); runCurrent()
        assertNotNull(tour.state.value.error)
        assertFalse(tour.state.value.playing)
        assertEquals(-1, tour.state.value.index)
    }
}
