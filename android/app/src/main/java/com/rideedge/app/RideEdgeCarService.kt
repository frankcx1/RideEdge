package com.rideedge.app

import android.content.Intent
import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.IconCompat
import android.text.SpannableString
import android.text.Spanned
import androidx.car.app.CarAppService
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.Session
import androidx.car.app.constraints.ConstraintManager
import androidx.car.app.model.*
import androidx.car.app.validation.HostValidator
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class RideEdgeCarService : CarAppService() {
    override fun createHostValidator(): HostValidator = HostValidator.Builder(this)
        .addAllowedHosts(androidx.car.app.R.array.hosts_allowlist_sample).build()

    override fun onCreateSession(): Session = object : Session() {
        override fun onCreateScreen(intent: Intent): Screen {
            val app = application as RideEdgeApplication
            app.carLocation.attach(carContext)
            lifecycle.addObserver(object : DefaultLifecycleObserver {
                override fun onDestroy(owner: LifecycleOwner) { app.carLocation.detach(carContext) }
            })
            val root = RadarCarList(carContext, app.radar, isHome = true)
            attachRecordingTour(root, app)
            return root
        }
    }
}

abstract class ObservingRadarCarScreen(context: CarContext, protected val repo: RadarRepository) : Screen(context) {
    /** Flatten the deepest drill-down on older hosts instead of exceeding the five-step task. */
    protected fun pushScreen(screen: Screen) {
        if (screenManager.stackSize >= 5) screenManager.pop()
        screenManager.push(screen)
    }
    init {
        lifecycleScope.launch {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(repo.state, repo.session, repo.clock, repo.exploration) { state, session, tick, exploration ->
                    carRefreshKey(state, session, exploration, tick, repo.hasActiveCarSession())
                }
                    .distinctUntilChanged()
                    // A response updates state and session together. Coalesce that
                    // burst instead of sending duplicate templates to the host.
                    .collectLatest { delay(150); invalidate() }
            }
        }
    }
    protected fun message(title: String, text: String, back: Boolean = false): Template = MessageTemplate.Builder(text)
        .setTitle(title).setHeaderAction(if (back) Action.BACK else Action.APP_ICON).build()
}

/** Poll receipts are not new decisions. Keep transport timestamps out of the
 * render identity, but retain current eligibility, status, location and content.
 * The repository continues polling independently of this presentation filter.
 */
internal fun carRefreshKey(state: RadarViewState, session: RadarSession,
    exploration: RadarExploration, tick: Long, active: Boolean): List<Any?> {
    val receipt = state.received
    val normalized = receipt?.copy(receivedElapsedMs = 0,
        snapshot = receipt.snapshot.copy(serverTime = java.time.Instant.EPOCH))
    val eligible = receipt?.let { r -> (r.snapshot.now + r.snapshot.further)
        .filter { r.eligible(it, tick, r.bootId) }.map { it.id } }
    return listOf(state.copy(received = normalized, lastContactAt = null),
        session.copy(busy = false), exploration, active, eligible,
        carReceiptStatus(receipt, tick, state.connected),
        carReceiptStatus(exploration.received, tick, state.connected))
}

class RadarCarList(context: CarContext, repo: RadarRepository, private val isHome: Boolean = false) : ObservingRadarCarScreen(context, repo) {
    // Stable slot titles/count satisfy host refresh rules while destinations and
    // pins follow the latest shared review, rather than retaining old identities.
    private var refreshRevision: String? = null
    private var refreshUntil = 0L
    private var navigationError: String? = null

    private fun requestRefresh() {
        refreshRevision = repo.state.value.received?.snapshot?.decisionRevision
        refreshUntil = repo.clock.value + 120000
        repo.refresh()
        invalidate()
    }

    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let {
            refreshRevision = null
            return message(it.first, it.second, !isHome)
        }
        val view = carRadarView(repo)
        if (!repo.hasActiveCarSession()) {
            refreshRevision = null
            return message(view.title, view.message ?: view.status)
        }
        if (refreshRevision != null) {
            val state = repo.state.value
            if (state.connected && repo.clock.value < refreshUntil &&
                state.received?.snapshot?.decisionRevision == refreshRevision) {
                return PlaceListMapTemplate.Builder().setTitle("RideEdge · Reviewing")
                    .setHeaderAction(Action.APP_ICON).setLoading(true).build()
            }
            refreshRevision = null
        }
        val limit = carContext.getCarService(ConstraintManager::class.java)
            .getContentLimit(ConstraintManager.CONTENT_LIMIT_TYPE_PLACE_LIST).coerceIn(1, 4)
        val items = ItemList.Builder()
        repeat(limit) { index ->
            val current = view.places.getOrNull(index)
            val row = Row.Builder().setTitle("Option ${index + 1}")
            if (current == null) {
                // A browsable coverage row has no marker, fabricated distance or
                // navigation action. Keep its slot to avoid changing task structure.
                val data = repo.state.value.received?.snapshot
                val explanation = when (index) {
                    0 -> if (data?.decisionState == "none_supported" &&
                        view.message == data.decisionMessage) "No supported move" else view.message ?: "No additional destination"
                    1 -> carCoverageText(data?.activityCoverage.orEmpty())
                    2 -> "Explore Nearby"
                    else -> "Open Plan"
                }
                row.addText(explanation)
                    .addText(carReviewStatus(repo))
                    .setBrowsable(true)
                    .setOnClickListener { pushScreen(when (index) {
                        2 -> RadarCarHome(carContext, repo, "NEARBY", mapHome = isHome)
                        3 -> RadarCarHome(carContext, repo, "PLAN", mapHome = isHome)
                        else -> RadarCarReports(carContext, repo)
                    }) }
            } else {
                val primary = repo.store.primary()?.id == current.id
                val status = if (!repo.state.value.connected) "Offline" else if (repo.state.value.received?.snapshot?.qwen?.state == "ready") "Qwen" else "Evidence"
                val prefix = (if (BuildConfig.BUILD_TYPE != "preview") "Navigate · " else "") +
                    (if (current.isPositioningFallback) "Unverified area" else status) +
                    (if (!current.withinNowRadius) " · Further" else "") + " · "
                val distance = SpannableString(prefix + "  · ${kotlin.math.ceil(current.route.minutes).toInt()} min " +
                    (if (current.route.basis == "live traffic") "traffic" else "estimate"))
                distance.setSpan(DistanceSpan.create(Distance.create(current.radiusMiles, Distance.UNIT_MILES)),
                    prefix.length, prefix.length + 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                row.addText(carHighlight(current.name, if (primary) CarColor.PRIMARY else CarColor.SECONDARY))
                    .addText(navigationError ?: distance)
                    .setMetadata(Metadata.Builder().setPlace(Place.Builder(CarLocation.create(current.latitude, current.longitude))
                        .setMarker(PlaceMarker.Builder().setLabel((index + 1).toString())
                            .setColor(if (primary) CarColor.PRIMARY else CarColor.SECONDARY).build()).build()).build())
                    .setOnClickListener {
                        if (BuildConfig.BUILD_TYPE == "preview") pushScreen(RadarCarPlace(carContext, repo, current.id))
                        else {
                            navigationError = navigateCarDestination(carContext, repo, current.id)
                            invalidate()
                        }
                    }
            }
            items.addItem(row.build())
        }
        // Four actions share this header on compact hosts; the app icon already
        // identifies RideEdge. Keep the title short enough to remain visible.
        val recording = BuildConfig.BUILD_TYPE == "preview" &&
            (carContext.applicationContext as? RideEdgeApplication)?.previewScenario == "recording"
        val builder = PlaceListMapTemplate.Builder().setTitle(if (BuildConfig.BUILD_TYPE == "preview" && !recording) "Replay" else "Now")
            .setHeaderAction(if (isHome) Action.APP_ICON else Action.BACK).setItemList(items.build())
            // Use the shared phone-location origin below. A separate host dot could
            // disagree with it (particularly in DHU, whose car sensor is simulated).
            .setCurrentLocationEnabled(false)
        if (carMapLocationEnabled(carContext)) carMapOrigin(repo)?.let { origin ->
            // Including the recent driving origin in the host's camera bounds keeps
            // the location indicator from sitting behind the recommendation panel.
            builder.setAnchor(Place.Builder(CarLocation.create(origin.latitude, origin.longitude))
                .setMarker(PlaceMarker.Builder().setIcon(CarIcon.Builder(
                    IconCompat.createWithResource(carContext, R.drawable.ic_rideedge_sedan)).build(), PlaceMarker.TYPE_ICON)
                    .setColor(CarColor.BLUE).build()).build())
        }
        if (carContext.carAppApiLevel >= 5) builder.setOnContentRefreshListener {
            requestRefresh()
        }
        // Keep Refresh visible even on hosts that hide the API 5 content-refresh affordance.
        builder.setActionStrip(ActionStrip.Builder().apply {
            if (isHome) {
                addAction(Action.Builder().setTitle("Nearby").setOnClickListener {
                    pushScreen(RadarCarHome(carContext, repo, "NEARBY", mapHome = true))
                }.build())
                addAction(Action.Builder().setTitle("Plan").setOnClickListener {
                    pushScreen(RadarCarHome(carContext, repo, "PLAN", mapHome = true))
                }.build())
                addAction(Action.Builder().setTitle("More").setOnClickListener {
                    pushScreen(RadarCarHome(carContext, repo, "NOW", mapHome = true))
                }.build())
            }
            addAction(Action.Builder().setTitle("Refresh").setOnClickListener { requestRefresh() }.build())
        }.build())
        return builder.build()
    }
}

internal fun carMapLocationEnabled(context: CarContext, preview: Boolean = BuildConfig.BUILD_TYPE == "preview"): Boolean =
    !preview && (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED)

/** A camera anchor is a recent driving fix, never a searched area's center. */
internal fun carMapOrigin(repo: RadarRepository, preview: Boolean = BuildConfig.BUILD_TYPE == "preview"): RadarOrigin? {
    val state = repo.state.value
    if (preview || !state.connected || state.changingOrigin) return null
    val receipt = state.received ?: return null
    val data = receipt.snapshot
    val elapsed = repo.currentElapsedMs() - receipt.receivedElapsedMs
    val fix = data.origin.fixAt ?: return null
    val age = java.time.Duration.between(fix, data.serverTime.plusMillis(elapsed)).toMillis()
    return data.origin.takeIf { elapsed >= 0 && it.mode == "device" && !data.locationStale && age in 0..60000 }
}
