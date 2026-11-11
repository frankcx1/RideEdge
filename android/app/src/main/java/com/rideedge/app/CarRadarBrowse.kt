package com.rideedge.app

import android.content.Intent
import android.net.Uri
import androidx.car.app.CarContext
import androidx.car.app.model.*
import java.time.Instant

internal enum class CarPlaceGroup { NOW, FURTHER, NEARBY, EVENTS, ACTIVITY, AREAS, PLACES }

internal fun carPlaces(repo: RadarRepository, group: CarPlaceGroup): List<RadarPlace> {
    val active = repo.state.value.received?.snapshot ?: return emptyList()
    val nearby = if (repo.exploration.value.area.isNotBlank()) repo.exploration.value.received?.snapshot?.nearby.orEmpty() else active.nearby
    return when (group) {
        CarPlaceGroup.NOW -> active.now.filter { it.id != repo.store.primary()?.id }
        CarPlaceGroup.FURTHER -> active.further
        CarPlaceGroup.NEARBY -> nearby
        else -> nearby.filter { it.category.equals(group.name, true) }
    }.distinctBy { it.id }
}

/** Fixed slots preserve template structure on updates and page changes. Names are the first
 * secondary line, not fabricated persistent identities; every tap uses the displayed place ID.
 */
internal class RadarCarPlaces(context: CarContext, repo: RadarRepository, private val group: CarPlaceGroup) :
    ObservingRadarCarScreen(context, repo) {
    private var page = 0
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val places = carPlaces(repo, group)
        page = page.coerceAtMost(((places.size - 1) / 4).coerceAtLeast(0))
        val exploring = group !in setOf(CarPlaceGroup.NOW, CarPlaceGroup.FURTHER) && repo.exploration.value.area.isNotBlank()
        val receipt = if (exploring) repo.exploration.value.received else repo.state.value.received
        val rows = (0..3).map { offset ->
            val place = places.getOrNull(page * 4 + offset)
            carRow("Option ${offset + 1}", place?.let { carHighlight(it.name) } ?: "No further option",
                place?.let { if (exploring) "From ${repo.exploration.value.area} · ${carActivityLine(it)}" else carActivityLine(it) },
                place?.let { p -> { pushScreen(RadarCarPlace(carContext, repo, p.id, if (exploring) p else null, exploring, retainedReceipt = receipt)) } })
        } + listOf(
            carRow("Previous page", "Page ${page + 1}", click = if (page > 0) ({ page--; invalidate() }) else null),
            carRow("Next page", "${places.size} places in available coverage", click = if ((page + 1)*4 < places.size) ({ page++; invalidate() }) else null)
        )
        return ListTemplate.Builder().setTitle(if (exploring) "Exploring · ${repo.exploration.value.area}" else group.name.lowercase().replaceFirstChar { it.uppercase() })
            .setHeaderAction(Action.BACK).setSingleList(ItemList.Builder().apply { rows.forEach { addItem(it) } }.build())
            .setActionStrip(ActionStrip.Builder().addAction(Action.Builder().setTitle("Refresh").setOnClickListener {
                if (exploring) repo.explore(repo.exploration.value.area) else repo.refresh()
                invalidate()
            }.build()).build()).build()
    }
}

internal class RadarCarCategories(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        return carList("Nearby filters", listOf(CarPlaceGroup.NEARBY, CarPlaceGroup.PLACES, CarPlaceGroup.EVENTS,
            CarPlaceGroup.ACTIVITY, CarPlaceGroup.AREAS).map { group ->
            carRow(if (group == CarPlaceGroup.NEARBY) "All nearby" else group.name.lowercase().replaceFirstChar { it.uppercase() },
                "${carPlaces(repo, group).size} places in available coverage") { pushScreen(RadarCarPlaces(carContext, repo, group)) }
        })
    }
}

internal class RadarCarAreaSearch(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    private fun explore(area: String) {
        if (area.isBlank() || !repo.hasActiveCarSession()) return
        repo.explore(area)
        pushScreen(RadarCarExploration(carContext, repo))
    }
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        return SearchTemplate.Builder(object : SearchTemplate.SearchCallback {
            override fun onSearchSubmitted(searchText: String) = explore(searchText.take(120))
        }).setHeaderAction(Action.BACK).setSearchHint("Area or neighborhood")
            .setItemList(ItemList.Builder().apply {
                listOf("Downtown Kirkland", "Totem Lake", "Downtown Redmond", "Capitol Hill", "Seattle Center", "SeaTac").forEach { area ->
                    addItem(carRow(area, "Explore only · driving origin unchanged") { explore(area) })
                }
            }.build()).build()
    }
}

internal class RadarCarExploration(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    private var page = 0
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val exploration = repo.exploration.value
        if (exploration.busy) return ListTemplate.Builder().setTitle("Exploring area").setHeaderAction(Action.BACK).setLoading(true).build()
        exploration.error?.let { return message("Area unavailable", it, true) }
        val data = exploration.received?.snapshot ?: return message("Choose an area", "Your driving origin is unchanged.", true)
        val places = data.nearby
        page = page.coerceAtMost(((places.size-1)/4).coerceAtLeast(0))
        return carList("Explore · ${data.origin.label}", (0..3).map { index ->
            val place = places.getOrNull(page*4 + index)
            carRow("Option ${index+1}", place?.let { carHighlight(it.name) } ?: "No further place", "From exploration center · navigation withheld",
                place?.let { p -> { pushScreen(RadarCarPlace(carContext, repo, p.id, p, true, retainedReceipt = exploration.received)) } })
        } + listOf(
            carRow("Previous page", "Page ${page+1}", click = if (page > 0) ({ page--; invalidate() }) else null),
            carRow("Next page", "${places.size} places", click = if ((page+1)*4 < places.size) ({ page++; invalidate() }) else null)
        ))
    }
}

internal fun carNavigationUri(place: RadarPlace): Uri = Uri.parse("geo:${place.latitude},${place.longitude}")

/** Official host handoff, always resolve the displayed ID again at action time. */
internal fun navigateCarDestination(context: CarContext, repo: RadarRepository, id: String): String? {
    val destination = if (repo.hasActiveCarSession() && repo.state.value.received?.snapshot?.origin?.mode == "device")
        repo.navigationTarget(id) else null
    if (destination == null) return "This option expired or location changed. Refresh before navigating."
    return runCatching { context.startCarApp(Intent(CarContext.ACTION_NAVIGATE, carNavigationUri(destination))) }
        .fold({
            android.util.Log.i("RideEdgeCarNav", "Navigation intent handed to host; api=${context.carAppApiLevel}")
            null
        }, { error ->
            android.util.Log.w("RideEdgeCarNav", "Navigation handoff rejected; api=${context.carAppApiLevel}; type=${error.javaClass.simpleName}")
            "The car host could not open navigation. Retry from the latest option when permitted."
        })
}

/** Retained/exploration/plan places are inspectable, but never authorize navigation. */
internal class RadarCarPlace(context: CarContext, repo: RadarRepository, private val id: String,
    private val retained: RadarPlace? = null, private val inspectOnly: Boolean = false,
    private val contextLabel: String = "Exploration · distances from selected area",
    private val preview: Boolean = BuildConfig.BUILD_TYPE == "preview",
    private val retainedReceipt: ReceivedRadar? = null) : ObservingRadarCarScreen(context, repo) {
    private var navigationError: String? = null
    private fun recordingTarget(): RadarPlace? {
        if (!preview || BuildConfig.BUILD_TYPE != "preview" || inspectOnly || !repo.hasActiveCarSession()) return null
        val app = carContext.applicationContext as? RideEdgeApplication ?: return null
        if (app.previewScenario != "recording") return null
        val current = repo.store.navigationTarget(id) ?: return null
        return app.recordingDemo.navigationTarget(app.recordingStep.value, current)
    }
    private fun place(): RadarPlace? {
        if (inspectOnly) return retained
        val data = repo.state.value.received?.snapshot ?: return null
        return (data.now + data.further + data.nearby).firstOrNull { it.id == id }
    }
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val place = place() ?: return message("Option no longer current", "Go back to the latest options or refresh the review.", true)
        val receipt = if (inspectOnly) retainedReceipt else repo.state.value.received
        val recordingDestination = recordingTarget()
        val status = if (inspectOnly) "$contextLabel · ${carReceiptStatus(receipt, repo.currentElapsedMs())} · navigation withheld"
            else "${if (repo.store.navigationTarget(id) == null) "Option not eligible · " else ""}${carReviewStatus(repo)}"
        val pane = Pane.Builder()
            .addRow(carRow("Travel and area", "${carRouteText(place)} · ${place.zone}",
                if (recordingDestination != null) "Google Maps routes from your phone to this public area reference." else place.navigationNote))
            .addRow(carRow("Why this place", place.qwenReason ?: carEvidenceText(place), place.busynessBasis ?: place.strength))
            .addRow(carRow("Review status", navigationError ?: status, "${place.pinBasis} · activity does not reveal Uber requests"))
        if (!inspectOnly && repo.store.navigationTarget(id) != null &&
            (repo.state.value.received?.snapshot?.origin?.mode == "device" || preview)) {
            pane.addAction(Action.Builder().setTitle(if (preview && recordingDestination == null) "Preview only" else "Navigate")
                .setBackgroundColor(CarColor.PRIMARY)
                .apply { if (carContext.carAppApiLevel >= 4) setFlags(Action.FLAG_PRIMARY) }
                .setOnClickListener {
                    val destination = if (preview) recordingTarget() else null
                    navigationError = when {
                        !preview -> navigateCarDestination(carContext, repo, id)
                        preview && destination == null -> "This option is not available · navigation disabled"
                        destination == null -> "This option expired. Refresh before navigating."
                        else -> runCatching { carContext.startCarApp(Intent(CarContext.ACTION_NAVIGATE, carNavigationUri(destination))) }
                            .fold({ null }, { "The car host could not open navigation." })
                    }
                    invalidate()
                }.build())
        }
        if (screenManager.stackSize < 5) pane.addAction(Action.Builder().setTitle("Evidence").setOnClickListener {
            pushScreen(RadarCarEvidence(carContext, repo, place, receipt, if (inspectOnly) contextLabel else "Saved evidence"))
        }.build())
        return PaneTemplate.Builder(pane.build()).setTitle(place.name).setHeaderAction(Action.BACK).build()
    }
}

internal class RadarCarEvidence(context: CarContext, repo: RadarRepository, private val place: RadarPlace,
    private val receipt: ReceivedRadar?, private val contextLabel: String) : ObservingRadarCarScreen(context, repo) {
    private var page = 0
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val observations = place.evidence
        val rows = (0..3).map { index ->
            val e = observations.getOrNull(page*4 + index)
            carRow("Observation ${index+1}", e?.let { "${it.source} · ${it.basis} · ${it.text}" } ?: "No additional observation",
                e?.let { "${it.role ?: "Evidence"} · ${it.measurementTime?.let(::carTime) ?: "Measurement time unknown"}${it.timingNote?.let { note -> " · $note" } ?: ""}" })
        } + listOf(carRow("Previous page", "$contextLabel · ${carReceiptStatus(receipt, repo.currentElapsedMs(), repo.state.value.connected)}", click = if (page > 0) ({ page--; invalidate() }) else null),
            carRow("Next page", "${observations.size} observations · full report on phone", click = if ((page+1)*4 < observations.size) ({ page++; invalidate() }) else null))
        return carList("Evidence · ${place.name}", rows)
    }
}
