package com.rideedge.app

import android.os.SystemClock
import android.provider.Settings
import androidx.car.app.CarContext
import androidx.car.app.model.*
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

internal class RadarCarReports(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val data = repo.state.value.received!!.snapshot
        val recording = BuildConfig.BUILD_TYPE == "preview" &&
            (carContext.applicationContext as? RideEdgeApplication)?.previewScenario == "recording"
        return carList("Evidence and reports", listOf(
            if (recording) carRow("About this recording",
                if ((carContext.applicationContext as RideEdgeApplication).recordingDemo.isCaptured) "Captured evidence and validated Qwen review" else "Prepared Friday-night replay",
                "Navigate opens a real route from your phone; area pins are not verified pickup curbs.")
                else carRow("Selection status", carReviewStatus(repo), data.qwen.detail),
            carRow("Data sources", "${data.feeds.size} sources in this decision snapshot") { pushScreen(RadarCarSources(carContext, repo)) },
            carRow("SeaTac arrivals", "Saved hourly report · opening does not refresh the provider") { pushScreen(RadarCarSeaTac(carContext, repo)) },
            carRow("Airport guidance", data.airportNote),
            if (BuildConfig.BUILD_TYPE == "preview" &&
                (carContext.applicationContext as RideEdgeApplication).previewScenario == "recording")
                carRow("Maps handoff demonstration", "Fixed public Paramount Theatre reference · starts real navigation") {
                    pushScreen(RadarCarDemoMaps(carContext, repo))
                } else carRow("What these signals mean", data.limits),
            carRow("Ask Qwen and detailed reports", "Use RideEdge on your phone while parked", "Car details show retained reasoning; no extra model request")
        ))
    }
}

/** Fixed public destination only; synthetic candidate navigation remains blocked. */
internal class RadarCarDemoMaps(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    private var launchError: String? = null
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        if (BuildConfig.BUILD_TYPE != "preview" ||
            (carContext.applicationContext as RideEdgeApplication).previewScenario != "recording")
            return message("Demo unavailable", "Use the recording Preview.", true)
        return MessageTemplate.Builder(launchError ?: "Real route from your phone to the Paramount Theatre. Demo destination.")
            .setTitle("Maps demonstration").setHeaderAction(Action.BACK)
            .addAction(Action.Builder().setTitle("Open Maps").setOnClickListener {
                if (repo.hasActiveCarSession() && BuildConfig.BUILD_TYPE == "preview" &&
                    (carContext.applicationContext as RideEdgeApplication).previewScenario == "recording") runCatching {
                    carContext.startCarApp(android.content.Intent(CarContext.ACTION_NAVIGATE,
                        android.net.Uri.parse("geo:0,0?q=$RECORDING_MAP_QUERY")))
                }.onFailure {
                    launchError = "Navigation could not open. Open Google Maps on the phone, then retry this fixed public destination."
                    invalidate()
                }
            }.build()).build()
    }
}

internal class RadarCarSources(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    private var page = 0
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val feeds = repo.state.value.received!!.snapshot.feeds
        page = page.coerceAtMost(((feeds.size-1)/4).coerceAtLeast(0))
        return carList("Sources in saved review", (0..3).map { index ->
            val feed = feeds.getOrNull(page*4+index)
            carRow("Source ${index+1}", feed?.let { "${it.adapter} · ${it.mode}" } ?: "No further source",
                feed?.let { "Fetched ${it.fetchedAt?.let(::carTime) ?: "unknown"} · ${it.count?.toString() ?: "Unknown"} signals; availability is not decision use" })
        } + listOf(
            carRow("Previous page", "Page ${page+1}", click = if (page > 0) ({ page--; invalidate() }) else null),
            carRow("Next page", "Detailed participation report on phone", click = if ((page+1)*4 < feeds.size) ({ page++; invalidate() }) else null)
        ))
    }
}

/** Fetch only on explicit entry/reload, never during template rendering or provider refresh. */
internal class RadarCarSeaTac(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    private var receipt: SeaTacReceipt? = null
    private var error: String? = null
    private var job: Job? = null
    private var page = 0
    private val boot: Int get() = Settings.Global.getInt(carContext.contentResolver, Settings.Global.BOOT_COUNT, -1)
    init { load() }
    private fun load() {
        if (job?.isActive == true || !repo.hasActiveCarSession()) return
        job = lifecycleScope.launch {
            error = null
            try { receipt = SeaTacReceipt(SeaTacParser.parse(reportRequest(carContext, "/api/seatac/forecast")), SystemClock.elapsedRealtime(), boot) }
            catch (cancel: CancellationException) { throw cancel }
            catch (failure: Exception) { error = if (failure is AccessRequiredException) "Reconnect using Connection on your phone." else "Saved SeaTac report unavailable. Retry or inspect the phone report." }
            finally { invalidate() }
        }
    }
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val current = receipt
        if (current == null && error == null) return ListTemplate.Builder().setTitle("SeaTac arrivals").setHeaderAction(Action.BACK).setLoading(true).build()
        val elapsed = SystemClock.elapsedRealtime()
        val peak = current?.peak(elapsed, boot)
        val hours = current?.report?.hours.orEmpty()
        val rows = listOf(carRow("Strongest usable arrival window", error ?: peak?.let { "${carTime(it.startsAt)} · ${it.estimated} ${if (it.extrapolated) "estimated" else "counted"} planes" } ?: "No current usable peak",
            "Arrivals are not ride requests; queue and rematch unknown")) + (0..2).map { index ->
            val h = hours.getOrNull(page*3+index)
            val usable = h != null && current?.usable(h, elapsed, boot) == true
            carRow("Arrival window ${index+1}", h?.let { "${carTime(it.startsAt)} – ${carTime(it.endsAt)}" } ?: "No window available",
                h?.let { if (usable) "${it.estimated} ${if (it.extrapolated) "estimated" else "counted"} planes · ${it.coverage}${if (it.partialHour) " · partial hour" else ""}" else "Unavailable / stale · ${it.coverage}" },
                h?.let { hour -> { pushScreen(RadarCarSeaTacHour(carContext, repo, current!!, hour)) } })
        } + listOf(
            carRow("Other hours", "${if (page == 0) "Later" else "Earlier"} three windows") { page = 1-page; invalidate() },
            carRow("Reload saved report", "Reads retained data; use the phone for provider refresh") { load(); invalidate() }
        )
        return carList("SeaTac arrivals", rows)
    }
}

internal class RadarCarSeaTacHour(context: CarContext, repo: RadarRepository, private val receipt: SeaTacReceipt,
    private val hour: SeaTacHour) : ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val usable = receipt.usable(hour, SystemClock.elapsedRealtime(), Settings.Global.getInt(carContext.contentResolver, Settings.Global.BOOT_COUNT, -1))
        return PaneTemplate.Builder(Pane.Builder()
            .addRow(carRow("Arrival count", if (usable) "${hour.estimated} ${if (hour.extrapolated) "estimated" else "counted"} planes" else "Unavailable or stale",
                "${hour.coverage} · ${hour.mode} · ${hour.sampled?.toString() ?: "Unknown"} sampled flights"))
            .addRow(carRow("Passenger-ready estimate", if (usable && hour.readinessStart != null && hour.readinessEnd != null)
                "${carTime(hour.readinessStart)} – ${carTime(hour.readinessEnd)}" else "Unavailable", hour.readinessBasis))
            .addRow(carRow("Evidence timing", hour.fetchedAt?.let(::carTime) ?: "Unknown", receipt.report.timingNote))
            .addRow(carRow("Limits", receipt.report.coverageNote, "No known queue wait or guaranteed rematch"))
            .build()).setTitle(carTime(hour.startsAt)).setHeaderAction(Action.BACK).build()
    }
}
