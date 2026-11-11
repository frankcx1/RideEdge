package com.rideedge.app

import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable internal fun RecordingTourControls(startOnly: Boolean = false) {
    if (BuildConfig.BUILD_TYPE != "preview") return
    val app = LocalContext.current.applicationContext as RideEdgeApplication
    if (app.previewScenario != "recording") return
    val tour by app.recordingTour.state.collectAsState()
    val clean by app.recordingTour.clean.collectAsState()
    if (startOnly) {
        if (tour.index < 0) EdgeButton(if (app.recordingDemo.isCaptured) "Play feature walkthrough" else "Play 12-minute guided tour", { app.recordingTour.seek(0, true) }, kind = EdgeButtonKind.Primary)
        return
    }
    if (tour.index < 0 || clean) return
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
        EdgeMeta("SHOT ${tour.index+1}/${app.recordingTour.cues.size} · ${tour.remaining}s · ${tour.cue?.title}")
        tour.error?.let { Text(it) }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            EdgeButton(if (tour.playing) "Pause" else "Resume", { if (tour.playing) app.recordingTour.pause() else app.recordingTour.resume() }, kind = EdgeButtonKind.Link)
            EdgeButton("Back", { app.recordingTour.seek((tour.index-1).coerceAtLeast(0)) }, kind = EdgeButtonKind.Link)
            EdgeButton("Next", { app.recordingTour.seek((tour.index+1).coerceAtMost(app.recordingTour.cues.lastIndex)) }, kind = EdgeButtonKind.Link)
            EdgeButton("Stop", { app.recordingTour.stop() }, kind = EdgeButtonKind.Link)
        }
    }
}
