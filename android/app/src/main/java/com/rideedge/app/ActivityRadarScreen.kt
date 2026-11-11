package com.rideedge.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun ActivityRadarApp(initialArea: String? = null, initialTab: Int = 0, model: RadarViewModel = viewModel()) {
    val repo = model.repository
    val state by repo.state.collectAsState()
    val session by repo.session.collectAsState()
    val exploration by repo.exploration.collectAsState()
    val answer by repo.answer.collectAsState()
    val elapsed by repo.clock.collectAsState()
    val context = LocalContext.current
    val app = context.applicationContext as RideEdgeApplication
    val recordingStep by app.recordingStep.collectAsState()
    val tour by app.recordingTour.state.collectAsState()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val phoneOwner = remember(lifecycle) { Any() }
    var tab by rememberSaveable { mutableIntStateOf(initialTab) }
    val tabState = rememberSaveableStateHolder()
    val nowScroll = rememberLazyListState()
    val nearbyScroll = rememberLazyListState()
    val planScroll = rememberLazyListState()
    var report by rememberSaveable { mutableStateOf<String?>(null) }
    var connectionOpen by rememberSaveable { mutableStateOf(false) }
    val accessNote by RideEdgeClient.accessNote.collectAsState()
    var locationOpen by rememberSaveable { mutableStateOf(false) }
    var areaInput by rememberSaveable { mutableStateOf(initialArea ?: session.area) }
    var exploreInput by rememberSaveable { mutableStateOf("") }
    var exploreOpen by rememberSaveable { mutableStateOf(false) }
    var category by rememberSaveable { mutableStateOf("All") }
    var notice by remember { mutableStateOf<String?>(null) }
    var askOpen by rememberSaveable { mutableStateOf(false) }
    var startingCar by remember { mutableStateOf(false) }
    var demoMapsOpen by remember { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants[Manifest.permission.ACCESS_FINE_LOCATION] == true) {
            notice = null; repo.usePhone(); locationOpen = false
            if (startingCar) repo.startCarSession()
        }
        else { notice = "Precise location is unavailable. Choose an area or enable it in Android settings."; locationOpen = true }
        startingCar = false
    }
    fun usePhone() {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            notice = null; repo.usePhone(); locationOpen = false
        } else permission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    }
    fun navigate(id: String) {
        val destination = if (BuildConfig.BUILD_TYPE == "preview") {
            if (app.previewScenario != "recording" || !app.recordingDemo.isCaptured) {
                notice = "Navigation is disabled for synthetic preview destinations."; return
            }
            repo.store.navigationTarget(id)?.let { app.recordingDemo.navigationTarget(app.recordingStep.value, it) }
        } else repo.navigationTarget(id)
        destination?.let { place ->
            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=${place.latitude},${place.longitude}"))) }
                .onFailure { notice = "No navigation app could open this destination." }
        }
    }
    LaunchedEffect(model) { model.initialize(initialArea) }
    LaunchedEffect(tour.revision) {
        val cue = tour.cue ?: return@LaunchedEffect
        if (BuildConfig.BUILD_TYPE != "preview" || app.previewScenario != "recording") return@LaunchedEffect
        connectionOpen = false; locationOpen = false; exploreOpen = false; demoMapsOpen = false
        category = "All"
        report = when (cue.shot) { "sources", "source_detail" -> "sources"; "seatac", "seatac_more" -> "seatac"; else -> null }
        askOpen = cue.shot == "ask"
        tab = when (cue.shot) { "nearby", "explore" -> 1; "plan", "plan_detail", "comparison" -> 2; else -> 0 }
        if (cue.shot == "explore") { exploreInput = "Capitol Hill"; repo.explore(exploreInput) }
        if (askOpen) repo.ask("Why is this option preferable right now?")
        kotlinx.coroutines.delay(500)
        val scroll = when (tab) { 1 -> nearbyScroll; 2 -> planScroll; else -> nowScroll }
        val target = when (cue.shot) {
            "alternatives" -> 3
            "further" -> scroll.layoutInfo.totalItemsCount - 2
            "comparison" -> 8
            "plan_detail" -> 2
            "nearby", "explore" -> 1
            "plan" -> 1
            else -> 1
        }
        if (report == null && !askOpen) scroll.animateScrollToItem(target.coerceIn(0, (scroll.layoutInfo.totalItemsCount - 1).coerceAtLeast(0)))
        app.recordingTour.phoneRevision = tour.revision
    }
    DisposableEffect(lifecycle, repo, phoneOwner) {
        val observer = LifecycleEventObserver { _, _ -> repo.setPhoneVisible(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED), phoneOwner) }
        lifecycle.addObserver(observer)
        repo.setPhoneVisible(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED), phoneOwner)
        onDispose { lifecycle.removeObserver(observer); repo.setPhoneVisible(false, phoneOwner) }
    }
    if (report != null) { RadarReportsScreen(report!!, onBack = { report = null }); return }
    if (connectionOpen) {
        ConnectionScreen(onBack = { connectionOpen = false }, onConnected = { repo.retryConnection() })
        return
    }
    if (askOpen) AlertDialog(onDismissRequest = { askOpen = false }, confirmButton = {
        EdgeButton("Close", { askOpen = false }, kind = EdgeButtonKind.Link)
    }, text = { Column(Modifier.imePadding().verticalScroll(rememberScrollState())) {
        RadarAsk(answer, elapsed, repo::ask, initiallyExpanded = true)
    } }, containerColor = RadarCard, shape = androidx.compose.ui.graphics.RectangleShape)
    if (demoMapsOpen && BuildConfig.BUILD_TYPE == "preview" && app.previewScenario == "recording") {
        AlertDialog(onDismissRequest = { demoMapsOpen = false }, title = { Text("Maps handoff demonstration") },
            text = { Text("Open a real route to the fixed public Paramount Theatre reference from your phone's current location. This is separate from the synthetic recommendations.") },
            confirmButton = { TextButton(onClick = {
                demoMapsOpen = false
                runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=$RECORDING_MAP_QUERY"))) }
                    .onFailure { notice = "No navigation app could open this demonstration." }
            }) { Text("Open Maps") } }, dismissButton = { TextButton(onClick = { demoMapsOpen = false }) { Text("Cancel") } })
    }
    val data = state.received?.snapshot
    val savedReview = !state.connected || state.errorCode != null || state.changingOrigin
    val primary = repo.store.primary()
    val expired = state.received?.let { elapsed - it.receivedElapsedMs >=
        java.time.Duration.between(it.snapshot.serverTime, it.snapshot.validUntil).toMillis().coerceIn(0L, 20 * 60 * 1000L) } ?: false
    Scaffold(containerColor = RadarBg, bottomBar = {
        Column { RecordingTourControls(); EdgeTabBar(tab) { app.recordingTour.pause(); tab = it } }
    }) { padding ->
        tabState.SaveableStateProvider(tab) {
        LazyColumn(Modifier.fillMaxSize().padding(padding), state = when (tab) {
            1 -> nearbyScroll
            2 -> planScroll
            else -> nowScroll
        }, contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            item {
                if (BuildConfig.BUILD_TYPE == "preview" && app.previewScenario != "recording") Text("OFFLINE PREVIEW · SYNTHETIC DATA", color = RadarAmber, fontSize = 11.sp)
                if (BuildConfig.BUILD_TYPE == "preview" && app.previewScenario == "recording") {
                    Text("${if (app.recordingDemo.isCaptured) "RECORDED SESSION" else "DEMO REPLAY"} · ${app.recordingDemo.scene(recordingStep).getString("short_title")}", color = RadarAmber, fontSize = 12.sp)
                    RecordingTourControls(startOnly = true)
                    if (tour.index < 0 && !app.recordingDemo.isCaptured) Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        EdgeButton("Reset", { app.selectRecordingStep(0) }, kind = EdgeButtonKind.Link)
                        EdgeButton("Previous", { app.selectRecordingStep(recordingStep - 1) }, enabled = recordingStep > 0, kind = EdgeButtonKind.Link)
                        EdgeButton("Next scene", { app.selectRecordingStep(recordingStep + 1) }, enabled = recordingStep < app.recordingDemo.sceneCount - 1, kind = EdgeButtonKind.Link)
                    }
                    if (tour.index < 0 && !app.recordingDemo.isCaptured) EdgeButton("Maps handoff demo", { demoMapsOpen = true }, kind = EdgeButtonKind.Link)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("RIDEEDGE · ${listOf("NOW", "NEARBY", "PLAN")[tab]}", Modifier.weight(1f), style = Edge.Eyebrow)
                    EdgeButton("Location", { locationOpen = !locationOpen }, kind = EdgeButtonKind.Link)
                }
                EdgeHeading(data?.origin?.label ?: session.area, size = 23)
                EdgeMeta(if (session.followPhone) "PHONE LOCATION · WITHIN 5 MI" else "SELECTED AREA · WITHIN 5 MI")
                EdgeActions {
                    EdgeButton("Data sources", { report = "sources" }, kind = EdgeButtonKind.Link)
                    EdgeButton("SeaTac report", { report = "seatac" }, kind = EdgeButtonKind.Link)
                    EdgeButton("Refresh", repo::refresh, enabled = !session.busy, kind = EdgeButtonKind.Outline)
                }
                if (session.busy) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Edge.Orange)
                HorizontalDivider(thickness = 2.dp, color = Edge.Ink)
            }
            radarConnectionPresentation(state, accessNote, session.busy,
                session.phoneVisible || (session.carActive && session.carConnected))?.let { connection -> item {
                RadarConnectionBanner(connection, state.lastContactAt, session.busy,
                    connect = { if (connection.settingsRequired) connectionOpen = true else repo.retryConnection() },
                    settings = { connectionOpen = true })
            } }

            if (locationOpen || state.changingOrigin) item {
                RadarPanel {
                    EdgeHeading("Choose your starting point.", size = 21)
                    EdgeButton("Use my location", { usePhone() }, enabled = !session.busy && BuildConfig.BUILD_TYPE != "preview", kind = EdgeButtonKind.Primary)
                    OutlinedTextField(areaInput, { areaInput = it.take(120) }, label = { Text("Area or neighborhood") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    EdgeButton("Use this area", { repo.chooseArea(areaInput); locationOpen = false }, enabled = areaInput.isNotBlank())
                }
            }
            listOfNotNull(notice, session.notice).distinct().forEach { message -> item { EdgeCaveat(message) } }
            if (data != null) {
                if (expired || data.locationStale || data.evidenceStale) item {
                    RadarPanel {
                        Text(if (data.locationStale) "Update your location" else "Saved outlook · refresh before acting", color = RadarAmber)
                        Text("Details remain available for inspection. Current eligibility is checked again when you navigate.", color = RadarMuted, fontSize = 12.sp)
                        EdgeButton("Update now", { if (session.followPhone) usePhone() else repo.refresh() })
                    }
                }
                when (tab) {
                    0 -> {
                        val retained = data.now.firstOrNull()
                        if (retained == null) item { EdgePanel {
                            EdgeHeading("No current nearby recommendation.")
                            Text(radarEmptyMessage(state, repo.currentElapsedMs()), style = Edge.Prose)
                            if (data.activityCoverage.isNotBlank()) EdgeCaveat(data.activityCoverage)
                            EdgeMeta("Last review ${edgeTime(data.generatedAt)} · source freshness is shown separately")
                            EdgeActions {
                                EdgeButton("Nearby", { tab = 1 })
                                EdgeButton("Plan", { tab = 2 })
                                EdgeButton("Refresh", { repo.refresh() })
                            }
                            EdgeButton("Ask Qwen", { askOpen = true })
                        } } else item {
                            RadarNowHero(retained, saved = savedReview,
                                expired = expired || data.locationStale || data.evidenceStale,
                                eligible = primary?.id == retained.id, navigate = { navigate(retained.id) }, ask = { askOpen = true })
                        }
                        item { RadarStatus(data, saved = savedReview) }
                        if (data.now.size > 1) item { EdgeHeading("Also nearby.", size = 20) }
                        items(data.now.drop(1), key = { "now:${it.id}" }) { place -> RadarAlternative(place,
                            navigate = if (repo.store.navigationTarget(place.id) != null) ({ navigate(place.id) }) else null) }
                        if (session.carConnected) item {
                RadarPanel {
                    Text(if (session.carActive) "Car session active" else "Android Auto connected", color = RadarMint)
                    Text(if (BuildConfig.BUILD_TYPE == "preview" && app.previewScenario == "recording" && app.recordingDemo.isCaptured)
                        "Showing a recorded evaluation from a selected public area. No phone GPS is being replayed."
                        else if (session.carActive) "Uses phone location for up to six hours, including with the screen off. Disconnecting ends this session; start again here after reconnecting."
                        else "While parked, start a session to use phone location in Android Auto. No trip history is stored.", color = RadarMuted, fontSize = 12.sp)
                    EdgeButton(if (session.carActive) "End car session" else "Start car session", onClick = {
                        if (session.carActive) repo.endCarSession()
                        else if (BuildConfig.BUILD_TYPE == "preview") repo.startCarSession()
                        else if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                            repo.usePhone(); repo.startCarSession()
                        } else {
                            startingCar = true
                            permission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
                        }
                    })
                    if (session.carActive && BuildConfig.BUILD_TYPE != "preview") Text(
                        (context.applicationContext as RideEdgeApplication).phoneLocation.status, color = RadarMuted, fontSize = 11.sp)
                }
            }
                        if (data.further.isNotEmpty()) item {
                            var expanded by rememberEdgeExpansion("further")
                            EdgeButton("A little further · ${data.further.size} options ${if (expanded) "▴" else "▾"}", { expanded = !expanded }, kind = EdgeButtonKind.Link)
                            Text("Outside five miles, up to twenty. Compare travel and timing before going.", color = RadarMuted, fontSize = 12.sp)
                            if (expanded) data.further.forEach { place -> RadarPlaceCard(place,
                                onNavigate = if (repo.store.navigationTarget(place.id) != null) ({ navigate(place.id) }) else null) }
                        }
                        item { Text(data.limits, color = RadarMuted, fontSize = 11.sp) }
                    }
                    1 -> {
                        val exploring = exploration.area.isNotBlank()
                        val local = if (exploring) exploration.received?.snapshot else data
                        item {
                            EdgeHeading("Around ${if (exploring) exploration.area else data.origin.label}.")
                            Text(if (exploring) "Distances are from this exploration area. Your driving origin is unchanged." else "Distances are from your active starting point.", style = Edge.Prose)
                            Text("Percentages are relative to each venue's own peak, not comparable crowd counts.", style = Edge.Prose)
                        }
                        item { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            EdgeButton("Explore another area ${if (exploreOpen) "▴" else "▾"}", { exploreOpen = !exploreOpen }, modifier = Modifier.fillMaxWidth(), kind = EdgeButtonKind.Outline)
                            if (exploreOpen) {
                            OutlinedTextField(exploreInput, { exploreInput = it.take(120) }, label = { Text("Area or neighborhood") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                            EdgeActions {
                                EdgeButton("Explore", { repo.explore(exploreInput); exploreOpen = false }, enabled = exploreInput.isNotBlank() && !exploration.busy, kind = EdgeButtonKind.Primary)
                                EdgeButton("My area", { repo.clearExploration(); exploreInput = "" })
                            }
                            } else if (exploration.area.isNotBlank()) EdgeButton("Back to my area", { repo.clearExploration(); exploreInput = "" })
                            if (exploration.busy) LinearProgressIndicator(Modifier.fillMaxWidth(), color = RadarMint)
                            exploration.error?.let { Text(it, color = RadarAmber, fontSize = 12.sp) }
                        } }
                        item { RadarCategoryFilter(category) { category = it } }
                        val rows = local?.nearby.orEmpty().filter { category == "All" || it.category == category }
                        if (rows.isEmpty() && !exploration.busy) item { Text("No matching places in the available coverage.", color = RadarMuted) }
                        items(rows, key = { "near:${it.id}" }) { place -> RadarPlaceCard(place,
                            onNavigate = if (!exploring && repo.store.navigationTarget(place.id) != null) ({ navigate(place.id) }) else null,
                            distanceLabel = if (exploring) "from exploration center" else if (data.origin.mode == "device") "from you" else "from selected area") }
                        if (local != null) item { RadarSources(local) }
                    }
                    2 -> {
                        item {
                            EdgeHeading("Your next six hours.")
                            Text("Provisional areas to reassess after each ride. Repeating a place is not an instruction to wait there all night.", style = Edge.Prose)
                            RadarStatus(data, saved = savedReview)
                            EdgeButton("Re-plan now", repo::refresh, enabled = !session.busy, kind = EdgeButtonKind.Outline)
                        }
                        items(data.plan, key = { it.startsAt.toString() }) { slot ->
                            val serverNow = data.serverTime.plusMillis((elapsed - (state.received?.receivedElapsedMs ?: elapsed)).coerceAtLeast(0))
                            RadarTimelineSlot(slot, slot == data.plan.firstOrNull(), serverNow)
                        }
                        item { RadarComparison(data) }
                        item { RadarAsk(answer, elapsed, repo::ask) }
                        item { EdgeCaveat(data.airportNote) }
                        item { EdgeMeta("Fri/Sat · 6 PM–3 AM · $200 target / $100 minimum goal, not a forecast") }
                        item { RadarSources(data) }
                    }
                }
            }
        }
    }
}
}

@Composable internal fun RadarPanel(content: @Composable ColumnScope.() -> Unit) {
    EdgePanel(content = content)
}
private fun preciseClock(value: Instant): String = DateTimeFormatter.ofPattern("h:mm a z", Locale.US).withZone(ZoneId.of("America/Los_Angeles")).format(value)
private fun decimal(value: Double): String = String.format(Locale.US, "%.1f", value)

@Composable private fun RadarPlaceCard(place: RadarPlace, onNavigate: (() -> Unit)? = null,
                                      distanceLabel: String = "away", onAsk: (() -> Unit)? = null) {
    RadarPlaceRow(place, onNavigate, distanceLabel, onAsk)
}

@Composable private fun RadarStatus(data: RadarSnapshot, saved: Boolean = false) {
    EdgeMeta(if (BuildConfig.BUILD_TYPE == "preview" && data.qwen.state == "demo") "Prepared review" else if (data.qwen.state == "ready") "Local Qwen selection" else "Evidence ranking · Qwen ${data.qwen.state}", color = Edge.Ink)
    val schedule = data.scheduler
    EdgeMeta(if (saved) "No newer review · saved outlook" else when (schedule.state) {
        "reviewing" -> "Review in progress on workstation"
        "blocked" -> "AI review blocked while model recovery is unresolved"
        "expired" -> "Session expired · update your location to resume"
        "preview" -> "Replay scene ready"
        "scheduled" -> "Next review ${schedule.nextReviewAt?.let(::preciseClock) ?: "pending"}"
        else -> "No active review schedule"
    }, color = RadarMuted)
    EdgeMeta("Evidence reviewed ${preciseClock(data.generatedAt)}", color = RadarMuted)
    if (data.activityCoverage.isNotBlank()) EdgeCaveat(data.activityCoverage)
    if (data.decisionPolicy.isNotBlank()) EdgeMeta("Policy ${data.decisionPolicy} · local evaluation · Python-validated output")
    if (data.qwen.state in setOf("unavailable", "blocked", "stale")) EdgeMeta(data.qwen.detail, color = RadarAmber)
    data.cleanup?.takeIf { it.state == "restoration_failed" }?.let { EdgeMeta(it.detail, color = RadarAmber) }
}

@Composable private fun RadarComparison(data: RadarSnapshot) {
    var expanded by rememberEdgeExpansion("comparison")
    val demo = BuildConfig.BUILD_TYPE == "preview" && data.qwen.state == "demo"
    RadarPanel {
        EdgeButton("Qwen / algorithm comparison ${if (expanded) "▴" else "▾"}", { expanded = !expanded }, kind = EdgeButtonKind.Link)
        if (expanded) {
            Text("Same eligible evidence, two methods. Agreement is not proof of demand.", color = RadarMuted, fontSize = 12.sp)
            data.plan.zip(data.algorithmPlan).forEach { (ai, algorithm) ->
                EdgeMeta(preciseClock(ai.startsAt), color = Edge.Blue)
                Text("Qwen: ${if (data.qwen.state == "ready" || demo) ai.selected?.name ?: "No option" else "No current validated selection"}", color = Edge.Ink, fontSize = 12.sp)
                Text("Algorithm: ${algorithm.selected?.name ?: "No option"}", color = RadarMuted, fontSize = 12.sp)
                if (data.qwen.state == "ready" || demo) Text(if (ai.selectedId == algorithm.selectedId) "Same choice" else "Different choices · inspect evidence and travel", color = RadarAmber, fontSize = 11.sp)
            }
        }
    }
}

@Composable private fun RadarAsk(answer: RadarAnswer, elapsed: Long, ask: (String) -> Unit, initiallyExpanded: Boolean = false) {
    var expanded by rememberSaveable { mutableStateOf(initiallyExpanded) }
    var question by rememberSaveable { mutableStateOf("") }
    RadarPanel {
        EdgeButton("Ask local Qwen ${if (expanded) "▴" else "▾"}", { expanded = !expanded }, kind = EdgeButtonKind.Link)
        if (expanded) {
            Text("Compare the current options or ask about the six-hour plan.", color = RadarMuted, fontSize = 12.sp)
            OutlinedTextField(question, { question = it.take(700) }, label = { Text("What would you like to know?") }, modifier = Modifier.fillMaxWidth())
            EdgeButton(if (answer.busy) "Qwen is reviewing…" else "Ask Qwen", { ask(question) }, enabled = question.isNotBlank() && !answer.busy, kind = EdgeButtonKind.Primary)
            answer.error?.let { Text(it, color = RadarAmber, fontSize = 12.sp) }
            answer.received?.snapshot?.let { response ->
                val receipt = answer.received
                if (elapsed - receipt.receivedElapsedMs >= java.time.Duration.between(response.serverTime, response.validUntil).toMillis())
                    Text("Saved answer · refresh before acting", color = RadarAmber, fontSize = 12.sp)
                EdgeMeta("Comparison using evidence from ${preciseClock(response.generatedAt)}")
                response.now.firstOrNull()?.let { Text(it.name, color = Edge.Ink); Text(it.qwenReason ?: it.supportingEvidence?.text.orEmpty(), color = RadarMint, fontSize = 12.sp) }
                if (response.now.isEmpty()) Text("No current choice in this response. Refresh before asking again.", color = RadarAmber, fontSize = 12.sp)
            }
        }
    }
}

@Composable private fun RadarSources(data: RadarSnapshot) {
    var expanded by rememberEdgeExpansion("coverage")
    RadarPanel {
        EdgeButton("Coverage · ${data.feeds.size} source reports ${if (expanded) "▴" else "▾"}", { expanded = !expanded }, kind = EdgeButtonKind.Link)
        if (expanded) {
            EdgeMeta("${data.excludedCount} records excluded while building immediate options. Open Data sources for reasons and future Plan use.")
            data.feeds.forEach { EdgeMeta("${it.adapter.replace('_', ' ')} · ${it.mode} · ${it.fetchedAt?.let(::preciseClock) ?: "time unknown"}") }
        }
    }
}
