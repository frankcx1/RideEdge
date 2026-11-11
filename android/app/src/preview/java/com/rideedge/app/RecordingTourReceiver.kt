package com.rideedge.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import org.json.JSONArray
import org.json.JSONObject

/** Explicit ADB recording controls. This component is absent from the normal APK. */
class RecordingTourReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext as RideEdgeApplication
        if (BuildConfig.BUILD_TYPE != "preview" || app.previewScenario != "recording") {
            resultCode = 1; resultData = "Open the recording Preview first"; return
        }
        val tour = app.recordingTour
        if (intent.hasExtra("clean")) tour.clean.value = intent.getBooleanExtra("clean", false)
        when (intent.getStringExtra("command")) {
            "start" -> tour.seek(intent.getIntExtra("shot", 0), true)
            "seek" -> tour.seek(intent.getIntExtra("shot", 0))
            "pause" -> tour.pause()
            "resume" -> tour.resume()
            "stop" -> tour.stop()
            "status", "cues" -> Unit
            else -> { resultCode = 1; resultData = "Unknown recording command"; return }
        }
        val state = tour.state.value
        resultCode = 0
        resultData = JSONObject().put("index", state.index).put("playing", state.playing)
            .put("revision", state.revision).put("remaining", state.remaining)
            .put("phone_revision", tour.phoneRevision).put("car_revision", tour.carRevision)
            .put("car_connected", app.radar.session.value.carConnected)
            .put("error", state.error ?: tour.carError ?: JSONObject.NULL)
            .put("capture_id", app.recordingDemo.captureId ?: JSONObject.NULL)
            .put("snapshot_id", app.radar.state.value.received?.snapshot?.snapshotId ?: JSONObject.NULL)
            .put("cues", JSONArray().apply { tour.cues.forEach { cue -> put(JSONObject()
                .put("scene", cue.scene).put("shot", cue.shot).put("title", cue.title).put("seconds", cue.seconds)) } })
            .toString()
    }
}
