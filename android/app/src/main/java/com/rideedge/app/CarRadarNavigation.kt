package com.rideedge.app

import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.*
import androidx.core.graphics.drawable.IconCompat
import android.text.SpannableString
import android.text.SpannableStringBuilder
import android.text.Spanned
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal enum class CarRadarTab(val label: String, val icon: Int) {
    NOW("Now", R.drawable.ic_car_now), NEARBY("Nearby", R.drawable.ic_car_nearby), PLAN("Plan", R.drawable.ic_car_plan)
}

internal fun carTime(time: Instant): String = DateTimeFormatter.ofPattern("h:mm a z", Locale.US)
    .withZone(ZoneId.of("America/Los_Angeles")).format(time)

internal fun carHighlight(text: String, color: CarColor = CarColor.SECONDARY): CharSequence = SpannableString(text).apply {
    setSpan(ForegroundCarColorSpan.create(color), 0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
}

internal fun carRow(title: String, text: CharSequence, detail: String? = null, click: (() -> Unit)? = null): Row =
    Row.Builder().setTitle(title).addText(SpannableStringBuilder()
        .append(text.ifBlank { "Unavailable" })).apply {
        detail?.takeIf { it.isNotBlank() }?.let { addText(it) }
        if (click != null) setOnClickListener(click)
    }.build()

internal fun carList(title: String, rows: List<Row>, back: Boolean = true): ListTemplate =
    ListTemplate.Builder().setTitle(title).setHeaderAction(if (back) Action.BACK else Action.APP_ICON)
        .setSingleList(ItemList.Builder().apply { rows.forEach { addItem(it) } }.build()).build()

/** Stable row titles let live values change without consuming host task steps.
 * Actions capture the displayed ID; details and navigation resolve it against current state.
 */
class RadarCarHome(context: CarContext, repo: RadarRepository, private val legacyTab: String? = null, private val mapHome: Boolean = false) :
    ObservingRadarCarScreen(context, repo) {
    private var selected = CarRadarTab.entries.firstOrNull { it.name == legacyTab } ?: CarRadarTab.NOW
    private fun open(screen: Screen) = screenManager.push(screen)

    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, legacyTab != null) }
        // More is a drill-down from the map, so expose a visible Back action rather
        // than an already-selected Now tab that cannot be tapped to return.
        if (mapHome && legacyTab == CarRadarTab.NOW.name) return carList("Now details", nowRows())
        if (carContext.carAppApiLevel < 6 && legacyTab == null) return carList("RideEdge", CarRadarTab.entries.map { tab ->
            carRow(tab.label, when (tab) {
                CarRadarTab.NOW -> "Where should I go?"
                CarRadarTab.NEARBY -> "Places and activity around you"
                CarRadarTab.PLAN -> "Your next six hours"
            }) { open(RadarCarHome(carContext, repo, tab.name)) }
        }, false)
        val rows = when (selected) {
            CarRadarTab.NOW -> nowRows()
            CarRadarTab.NEARBY -> nearbyRows()
            CarRadarTab.PLAN -> planRows()
        }
        if (carContext.carAppApiLevel < 6) return carList(selected.label, rows)
        val content = ListTemplate.Builder().setSingleList(ItemList.Builder().apply { rows.forEach { addItem(it) } }.build()).build()
        return TabTemplate.Builder(object : TabTemplate.TabCallback {
            override fun onTabSelected(tabContentId: String) {
                if (mapHome && tabContentId == CarRadarTab.NOW.name) {
                    screenManager.popToRoot()
                    return
                }
                CarRadarTab.entries.firstOrNull { it.name == tabContentId }?.let { selected = it; invalidate() }
            }
        }).setHeaderAction(Action.APP_ICON).apply {
            CarRadarTab.entries.forEach { tab -> addTab(Tab.Builder().setTitle(tab.label).setContentId(tab.name)
                .setIcon(CarIcon.Builder(IconCompat.createWithResource(carContext, tab.icon)).build()).build()) }
        }.setActiveTabContentId(selected.name).setTabContents(TabContents.Builder(content).build()).build()
    }

    private fun refreshRow(label: String = "Refresh recommendations") = carRow(label,
        repo.session.value.notice ?: carReviewStatus(repo), "Request a new review; current evidence keeps its original expiry") {
        repo.refresh(); invalidate()
    }

    private fun nowRows(): List<Row> {
        val data = repo.state.value.received?.snapshot
        val best = repo.store.primary()
        return listOf(
            carRow("Best nearby option", best?.let { carHighlight(it.name, CarColor.PRIMARY) } ?: "No current recommendation",
                best?.let { "${carRouteText(it)} · ${it.qwenReason ?: it.supportingEvidence?.text ?: it.strength}" } ?: carReviewStatus(repo),
                best?.let { place -> { open(RadarCarPlace(carContext, repo, place.id)) } }),
            carRow("Other nearby options", "Within five miles · ${data?.origin?.label ?: "Location unavailable"}",
                if (data?.origin?.mode == "selected_area") "Selected area · navigation withheld" else carReviewStatus(repo)) {
                open(RadarCarPlaces(carContext, repo, CarPlaceGroup.NOW)) },
            carRow("A little further", "Compare the extra travel with the available evidence") {
                open(RadarCarPlaces(carContext, repo, CarPlaceGroup.FURTHER)) },
            carRow("View on map", "Numbered pins for current positioning options") {
                if (mapHome) screenManager.popToRoot() else open(RadarCarList(carContext, repo))
            },
            refreshRow(),
            carRow("Evidence and reports", carReviewStatus(repo), "SeaTac arrivals, source freshness and selection status") {
                open(RadarCarReports(carContext, repo)) }
        )
    }

    private fun nearbyRows(): List<Row> {
        val exploring = repo.exploration.value.area.isNotBlank()
        val receipt = if (exploring) repo.exploration.value.received else repo.state.value.received
        val data = receipt?.snapshot
        val places = data?.nearby.orEmpty()
        val rows = (0..1).map { index ->
            val place = places.getOrNull(index)
            carRow("Nearby option ${index + 1}", place?.let { carHighlight(it.name) } ?: when {
                exploring && repo.exploration.value.busy -> "Loading exploration area"
                exploring && repo.exploration.value.error != null -> repo.exploration.value.error!!
                else -> "No place in available coverage"
            },
                if (exploring) "Exploring ${repo.exploration.value.area} · navigation withheld" else place?.let(::carActivityLine),
                place?.let { p -> { open(RadarCarPlace(carContext, repo, p.id, if (exploring) p else null, exploring, retainedReceipt = receipt)) } })
        }
        return rows + listOf(
            carRow("All places and filters", "Places, events, activity and areas") { open(RadarCarCategories(carContext, repo)) },
            carRow("Explore another area", "${data?.origin?.label ?: "Unavailable"} · driving origin stays unchanged") {
                open(RadarCarAreaSearch(carContext, repo)) },
            carRow("Use my current area", "Return Nearby to the active driving origin") { repo.clearExploration(); invalidate() },
            carRow("Refresh nearby", if (exploring) "Reload ${repo.exploration.value.area}" else carReviewStatus(repo)) {
                if (exploring) repo.explore(repo.exploration.value.area) else repo.refresh()
                invalidate()
            }
        )
    }

    private fun planRows(): List<Row> {
        val plan = repo.state.value.received?.snapshot?.plan.orEmpty()
        return (0..2).map { index ->
            val slot = plan.getOrNull(index)
            carRow("Hour ${index + 1}", slot?.selected?.let { carHighlight(it.name) } ?: "No supported option",
                slot?.let { "${carTime(it.startsAt)} – ${carTime(it.endsAt)} · ${it.selectionBasis}" },
                slot?.let { { open(RadarCarPlanWindow(carContext, repo, it.startsAt)) } })
        } + listOf(
            carRow("Hours 4–6", "Later positioning windows and alternatives") { open(RadarCarLaterPlan(carContext, repo)) },
            carRow("Compare plans", "Qwen selection and evidence algorithm · ${carReviewStatus(repo)}") {
                open(RadarCarPlanComparison(carContext, repo)) },
            refreshRow("Re-plan now")
        )
    }
}

/** Gate all descendants too: back-stack screens must not bypass session/auth expiry. */
internal fun carSessionGate(repo: RadarRepository): Pair<String, String>? {
    if (!repo.hasActiveCarSession()) return "Start on your phone" to "While parked, open RideEdge and tap Start car session."
    val state = repo.state.value
    if (state.errorCode in setOf("access_required", "schema_mismatch", "invalid_contract"))
        return "Check RideEdge on your phone" to (state.message ?: "A compatible, authenticated connection is required.")
    if (state.changingOrigin) return "Updating location" to (repo.session.value.notice ?: "Waiting for a current car location.")
    if (state.received == null) return "Waiting for RideEdge" to (state.message ?: "No decision has been received. Check the phone connection.")
    return null
}

internal fun carReviewStatus(repo: RadarRepository): String {
    val state = repo.state.value
    val receipt = state.received ?: return state.message ?: "Waiting for evidence"
    if (state.changingOrigin) return "Location unavailable"
    return carReceiptStatus(receipt, repo.currentElapsedMs(), state.connected)
}

/** A retained detail must age its own receipt, never borrow a newer review's freshness. */
internal fun carReceiptStatus(receipt: ReceivedRadar?, elapsedNow: Long, connected: Boolean = true): String {
    if (receipt == null) return "Saved details · review time unavailable"
    val data = receipt.snapshot
    val elapsed = (elapsedNow - receipt.receivedElapsedMs).coerceAtLeast(0)
    val now = data.serverTime.plusMillis(elapsed)
    val age = java.time.Duration.between(data.generatedAt, now).toMinutes().coerceAtLeast(0)
    val freshness = when {
        elapsedNow < receipt.receivedElapsedMs -> "Saved review · clock unavailable"
        data.locationStale -> "Location unavailable"
        data.evidenceStale || now >= data.validUntil || elapsed >= 20*60*1000 -> "Saved review · expired"
        !connected -> "Offline · saved review"
        else -> "$age min old"
    }
    return "$freshness · ${if (data.qwen.state == "ready") "Local Qwen" else "Evidence ranking · Qwen ${data.qwen.state}"}"
}

internal fun carActivityLine(place: RadarPlace): String = listOfNotNull(place.busyness?.let {
    "${String.format(Locale.US, "%.0f", it)}% of own weekly peak"
}, place.evidence.firstOrNull { it.startsAt != null || it.endsAt != null }?.let {
    "${it.startsAt?.let(::carTime) ?: "Start unknown"} – ${it.endsAt?.let(::carTime) ?: "End unknown"}"
}, place.busynessBasis ?: place.strength, "${String.format(Locale.US, "%.1f", place.radiusMiles)} mi from origin").joinToString(" · ")
