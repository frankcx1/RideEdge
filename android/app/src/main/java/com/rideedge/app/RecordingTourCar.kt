package com.rideedge.app

import androidx.car.app.Screen
import androidx.car.app.Session
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

/** Session-scoped, so drilling into a screen doesn't stop the Preview tour. */
internal fun Session.attachRecordingTour(root: Screen, app: RideEdgeApplication) {
    if (BuildConfig.BUILD_TYPE != "preview") return
    lifecycleScope.launch {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            app.recordingTour.state.map { it.revision }.distinctUntilChanged().collectLatest { revision ->
                val cue = app.recordingTour.state.value.cue ?: return@collectLatest
                if (app.previewScenario != "recording") return@collectLatest
                try {
                    val repo = app.radar
                    if (!repo.hasActiveCarSession()) return@collectLatest
                    val data = repo.state.value.received?.snapshot ?: return@collectLatest
                    val context = root.carContext
                    root.screenManager.popToRoot()
                    delay(200)
                    val next: Screen? = when (cue.shot) {
                        "now" -> null
                        "why", "ask" -> data.now.firstOrNull()?.let { RadarCarPlace(context, repo, it.id) }
                        "alternatives" -> RadarCarPlaces(context, repo, CarPlaceGroup.NOW)
                        "further" -> RadarCarPlaces(context, repo, CarPlaceGroup.FURTHER)
                        "nearby", "explore" -> RadarCarHome(context, repo, "NEARBY", mapHome = true)
                        "plan" -> RadarCarHome(context, repo, "PLAN", mapHome = true)
                        "plan_detail" -> data.plan.firstOrNull()?.let { RadarCarPlanWindow(context, repo, it.startsAt) }
                        "comparison" -> RadarCarPlanComparison(context, repo)
                        "sources", "source_detail" -> RadarCarSources(context, repo)
                        "seatac", "seatac_more" -> RadarCarSeaTac(context, repo)
                        else -> null
                    }
                    if (next != null) root.screenManager.push(next) else root.invalidate()
                    app.recordingTour.carRevision = revision
                    app.recordingTour.carError = null
                } catch (cancel: CancellationException) { throw cancel }
                catch (_: Exception) { app.recordingTour.carError = "Car host could not display this shot. Pause and check the DHU." }
            }
        }
    }
}
