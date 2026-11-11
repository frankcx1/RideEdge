package com.rideedge.app

import android.content.Context
import android.os.SystemClock
import android.provider.Settings
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.CancellationException
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal suspend fun reportRequest(context: Context, path: String, refresh: Boolean = false): JSONObject = withContext(Dispatchers.IO) {
    if (BuildConfig.BUILD_TYPE == "preview") {
        val scenario = (context.applicationContext as RideEdgeApplication).previewScenario
        if (scenario == "recording") {
            val app = context.applicationContext as RideEdgeApplication
            return@withContext app.recordingDemo.report(app.recordingStep.value, path)
        }
        if (scenario == "unauthorized") throw AccessRequiredException("Synthetic rejected credentials")
        if (scenario == "offline") error("Synthetic report connection failure")
        val asset = when (path) {
            "/api/seatac/forecast" -> "seatac-v1.json"
            "/api/feeds/health", "/api/feeds/refresh" -> "source-health-v1.json"
            "/api/feeds/flightaware_sea/detail" -> "source-detail-v1.json"
            "/api/radar/status" -> "radar-status-v1.json"
            else -> error("No preview fixture for this report")
        }
        return@withContext context.assets.open(asset).bufferedReader().use { JSONObject(it.readText()) }.also { json ->
            if (scenario == "stress" && asset == "source-detail-v1.json") {
                val records = JSONArray()
                repeat(25) { i -> records.put(JSONObject().put("title", "Synthetic pagination record ${i + 1}")
                    .put("basis", "offline fixture").put("detail", "Long retained detail for layout verification. No provider request.")) }
                json.put("records", records)
            }
        }
    }
    RideEdgeClient.request(path, if (refresh) "POST" else "GET", if (refresh) JSONObject() else null, if (refresh) 120000 else 20000)
}

private fun reportTime(value: String): String = runCatching {
    DateTimeFormatter.ofPattern("EEE MMM d, h:mm a z").withZone(ZoneId.of("America/Los_Angeles")).format(Instant.parse(value))
}.getOrDefault("Unknown")

@Composable
internal fun RadarReportsScreen(report: String, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val bootId = Settings.Global.getInt(context.contentResolver, Settings.Global.BOOT_COUNT, -1)
    var airportReceipt by remember { mutableStateOf<SeaTacReceipt?>(null) }
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var status by remember { mutableStateOf<JSONObject?>(null) }
    var adapter by rememberSaveable { mutableStateOf<String?>(null) }
    val app = context.applicationContext as RideEdgeApplication
    val tour by app.recordingTour.state.collectAsState()
    val tourScroll = androidx.compose.foundation.lazy.rememberLazyListState()
    LaunchedEffect(tour.revision) {
        if (BuildConfig.BUILD_TYPE != "preview" || app.previewScenario != "recording" || tour.cue == null) return@LaunchedEffect
        adapter = if (tour.cue?.shot == "source_detail") "besttime_busyness" else null
        kotlinx.coroutines.delay(1200)
        tourScroll.animateScrollToItem((if (tour.cue?.shot == "seatac_more") 3 else 1)
            .coerceIn(0, (tourScroll.layoutInfo.totalItemsCount-1).coerceAtLeast(0)))
    }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var accessRequired by remember { mutableStateOf(false) }
    var connectionOpen by rememberSaveable { mutableStateOf(false) }
    var loadGeneration by remember { mutableLongStateOf(0) }
    var visibleRecords by rememberSaveable(adapter) { mutableIntStateOf(20) }
    var elapsed by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    LaunchedEffect(Unit) { while (true) { elapsed = SystemClock.elapsedRealtime(); delay(1000) } }
    fun back() { if (adapter != null) adapter = null else onBack() }
    BackHandler { back() }
    suspend fun load(refresh: Boolean = false) {
        val requestedAdapter = adapter
        val requestId = ++loadGeneration
        busy = true; error = null; accessRequired = false
        runCatching {
            when {
                report == "seatac" -> reportRequest(context, "/api/seatac/forecast", refresh)
                adapter != null -> reportRequest(context, "/api/feeds/${adapter}/detail")
                refresh -> reportRequest(context, "/api/feeds/refresh", true)
                else -> reportRequest(context, "/api/feeds/health")
            }
        }.onSuccess {
            if (adapter == requestedAdapter && requestId == loadGeneration) {
                if (report == "seatac") {
                    runCatching { SeaTacParser.parse(it) }.onSuccess { parsed ->
                        airportReceipt = SeaTacReceipt(parsed, SystemClock.elapsedRealtime(), bootId)
                    }.onFailure { error = "Could not read this saved SeaTac report. Refresh it; if this persists, check the app/backend versions." }
                }
                data = it
            }
        }.onFailure {
            if (it is CancellationException) {
                if (requestId == loadGeneration) busy = false
                throw it
            }
            if (adapter == requestedAdapter && requestId == loadGeneration) {
                accessRequired = it is AccessRequiredException
                error = if (accessRequired) "Open Connection to reconnect to workstation."
                    else "Report unavailable. Check the connection and try again."
            }
        }
        if (report == "sources" && adapter == null) runCatching { reportRequest(context, "/api/radar/status") }
            .onSuccess { if (requestId == loadGeneration) status = it }
            .onFailure {
                if (it is CancellationException) throw it
                if (requestId == loadGeneration && it is AccessRequiredException) {
                    accessRequired = true; error = "Open Connection to reconnect to workstation."
                }
            }
        if (requestId == loadGeneration) busy = false
    }
    LaunchedEffect(report, adapter) { data = null; load() }
    if (connectionOpen) {
        ConnectionScreen(onBack = { connectionOpen = false }, onConnected = {
            connectionOpen = false
            (context.applicationContext as RideEdgeApplication).radar.retryConnection()
            scope.launch { load() }
        })
        return
    }
    Scaffold(containerColor = RadarBg, bottomBar = { RecordingTourControls() }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), state = tourScroll,
            contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            item {
                EdgeButton(if (adapter != null) "← All sources" else "← Back to RideEdge", { back() }, kind = EdgeButtonKind.Link)
                if (BuildConfig.BUILD_TYPE == "preview") EdgeMeta(if ((context.applicationContext as RideEdgeApplication).previewScenario == "recording") "DEMO REPLAY" else "OFFLINE PREVIEW · SYNTHETIC DATA", color = RadarAmber)
                EdgeHeading(if (report == "seatac") "SeaTac arrivals." else data?.optString("label")?.takeIf { it.isNotBlank() } ?: "Data sources.", size = 30)
                EdgeMeta(if (report == "seatac") "SIX HOURLY WINDOWS · PACIFIC TIME · FLIGHTAWARE" else "SOURCE COVERAGE AND RETAINED EVIDENCE")
                Spacer(Modifier.height(16.dp))
                HorizontalDivider(thickness = 2.dp, color = Edge.Ink)
                Spacer(Modifier.height(12.dp))
                EdgeButton(if (report == "seatac") "Refresh six-hour arrivals" else if (adapter == null) "Refresh source feeds" else "Reload report",
                    { if (!busy) scope.launch { load(refresh = adapter == null) } }, enabled = !busy, kind = EdgeButtonKind.Primary)
                if (report == "seatac") EdgeMeta(if (BuildConfig.BUILD_TYPE == "preview")
                    "Reloads this replay report."
                    else "Refresh uses up to six provider requests. This report is fetched on demand.", color = RadarMuted)
            }
            if (busy) item { LinearProgressIndicator(Modifier.fillMaxWidth(), color = RadarMint) }
            error?.let { item {
                EdgeCaveat(it)
                if (accessRequired) EdgeButton("Connection settings", { connectionOpen = true })
                else EdgeButton("Retry report", { scope.launch { load() } }, enabled = !busy)
            } }
            data?.let { result ->
                if (report == "seatac") {
                    airportReceipt?.let { seatacReportContent(it, elapsed, bootId) }
                } else if (adapter == null) {
                    status?.let { health -> item {
                        EdgePanel(cap = Edge.Ink) {
                            val recorded = BuildConfig.BUILD_TYPE == "preview" && health.has("recorded_at")
                            EdgeMeta(if (recorded) "CAPTURED EVALUATION" else "workstation SERVICES")
                            if (recorded) EdgeMeta("Recorded Qwen review · ${health.optJSONObject("qwen")?.optString("state") ?: "unknown"}", color = RadarAmber)
                            else if (BuildConfig.BUILD_TYPE == "preview" && health.optBoolean("synthetic"))
                                EdgeMeta("Demo replay · prepared review", color = RadarAmber)
                            else RadarServiceGrid(health)
                            EdgeButton("Connection settings", { connectionOpen = true }, kind = EdgeButtonKind.Link)
                            EdgeMeta("Last Qwen result: ${health.optJSONObject("qwen")?.optString("state") ?: "none"} · ${reportTime(health.optString("evidence_generated_at"))}", color = RadarMuted)
                            val cleanup = health.optJSONObject("cleanup")
                            if (cleanup?.optString("state") == "restoration_failed") Text(
                                "GPU restoration needs recovery. New model work is blocked; a retained answer can remain valid separately.", color = RadarAmber, fontSize = 12.sp)
                            val usage = health.optJSONObject("collector")?.optJSONObject("last_run_usage")
                            if (usage != null) {
                                var expanded by rememberSaveable { mutableStateOf(false) }
                                EdgeButton("Last collector request usage ${if (expanded) "▴" else "▾"}", { expanded = !expanded }, kind = EdgeButtonKind.Link)
                                if (expanded) {
                                    EdgeMeta(usage.optString("scope"), color = RadarMuted)
                                    val providers = usage.optJSONObject("providers")
                                    providers?.keys()?.asSequence()?.sorted()?.forEach { provider ->
                                        val counts = providers.optJSONObject(provider)
                                        EdgeMeta("$provider: ${counts?.countText("http_attempts")} attempts · ${counts?.countText("cache_hits")} cache hits · ${counts?.countText("http_failures")} failures", color = RadarMuted)
                                    }
                                    EdgeMeta("Request counts are not billed credits or a complete account total.", color = RadarMuted)
                                }
                            }
                        }
                    } }
                    item { EdgeMeta(result.optString("service_health_note"), color = RadarMuted) }
                    item { RadarPanel { RadarParticipation(result.optJSONObject("radar_participation")) } }
                    item {
                        EdgeActions {
                            Text(result.countText("healthy_count"), style = Edge.Meta.copy(fontSize = 30.sp, lineHeight = 38.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink)
                            EdgeMeta("healthy / ${result.countText("enabled_count")} enabled · ${result.countText("total_count")} sources")
                        }
                        EdgeMeta("Snapshot ${reportTime(result.optString("collected_at"))}")
                    }
                    items(result.rows("feeds"), key = { it.optString("adapter") }) { feed ->
                        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            HorizontalDivider(color = Edge.Rule)
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                EdgeHeading(feed.optString("label"), Modifier.weight(1f), size = 17)
                                RadarSourceTag(feed.optString("mode"))
                            }
                            EdgeMeta("${feed.optString("mode")} · ${feed.countText("signal_count")} ${feed.optString("count_unit", "signals")} · ${reportTime(feed.optString("fetched_at"))}")
                            Text(feed.optString("plain_summary").ifBlank { feed.optString("detail") }, color = RadarMuted, fontSize = 13.sp)
                            val participation = result.optJSONObject("radar_participation")
                            participation?.rows("sources")?.firstOrNull { it.optString("adapter") == feed.optString("adapter") }?.let {
                                RadarParticipation(participation, it)
                            }
                            EdgeButton("Open detailed report", { adapter = feed.optString("adapter") }, enabled = !busy, kind = EdgeButtonKind.Link)
                        }
                    }
                    val otherSources = result.optJSONObject("radar_participation")?.rows("sources").orEmpty()
                        .filter { it.optString("adapter") in setOf("local_catalogs", "unmapped_sources") &&
                            (it.optInt("candidate_count") > 0 || it.optInt("exclusion_count") > 0 || it.optInt("plan_interval_count") > 0) }
                    items(otherSources) { source -> RadarPanel {
                        Text(source.optString("label"), color = Edge.Ink, fontSize = 18.sp)
                        RadarParticipation(result.optJSONObject("radar_participation"), source)
                    } }
                } else {
                    item { RadarPanel {
                        Text(result.optString("status_message"), color = Edge.Ink)
                        Text(result.optString("plain_summary").ifBlank { result.optString("summary") }, color = RadarMuted, fontSize = 13.sp)
                        EdgeMeta("${result.optString("mode")} · retrieved ${reportTime(result.optString("fetched_at"))}", color = RadarMint)
                        if (!result.isNull("mapping_note")) EdgeMeta(result.optString("mapping_note"), color = RadarAmber)
                        EdgeMeta("Retained source records, which may include stale or contextual data excluded from Plan.", color = RadarMuted)
                    } }
                    item { RadarPanel {
                        val participation = result.optJSONObject("radar_participation")
                        RadarParticipation(participation)
                        participation?.optJSONObject("source")?.let { RadarParticipation(participation, it) }
                    } }
                    val records = result.rows("records")
                    items(records.take(visibleRecords)) { RadarSourceRecord(it) }
                    if (records.size > visibleRecords) item { EdgeButton("Show more (${records.size - visibleRecords} remaining)", { visibleRecords += 20 }, kind = EdgeButtonKind.Link) }
                    if (records.isEmpty()) item { Text("No retained records available for this source.", color = RadarMuted) }
                }
            }
        }
    }
}

@Composable
private fun RadarParticipation(report: JSONObject?, source: JSONObject? = null) {
    if (report == null) {
        EdgeMeta("This backend has not supplied decision participation details.", color = RadarMuted)
        return
    }
    if (source == null) {
        EdgeHeading("Radar review.", size = 21)
        RadarSourceTag(report.optString("state"))
        if (!report.isNull("reviewed_at")) EdgeMeta("${report.optString("origin_label")} · ${reportTime(report.optString("reviewed_at"))}", color = RadarMuted)
        EdgeMeta(report.optString("note"), color = RadarMuted)
        if (!report.isNull("exclusion_scope")) EdgeMeta(report.optString("exclusion_scope"), color = RadarMuted)
        return
    }
    var expanded by rememberSaveable(report.optString("snapshot_id"), source.optString("adapter")) { mutableStateOf(false) }
    var visible by rememberSaveable(report.optString("snapshot_id"), source.optString("adapter")) { mutableIntStateOf(20) }
    EdgeMeta("Now: ${source.countText("now_opportunity_count")} supporting records · ${source.countText("now_context_count")} context records", color = RadarMint)
    if (source.optInt("now_travel_count") > 0) EdgeMeta("${source.countText("now_travel_count")} provider route used for Now travel time", color = RadarMint)
    EdgeMeta("${source.countText("plan_interval_count")} Plan intervals · ${source.countText("candidate_count")} candidate places inspected · ${source.countText("exclusion_count")} construction exclusions", color = RadarMuted)
    EdgeButton(if (expanded) "Hide decision details" else "Why used or excluded?", { expanded = !expanded }, kind = EdgeButtonKind.Link)
    if (expanded) {
        source.rows("plan_intervals").forEach { interval ->
            EdgeMeta("${reportTime(interval.optString("starts_at"))}: ${interval.optString("place")} · ${interval.optString("selection_basis")}", color = RadarMuted)
        }
        val exclusions = source.rows("exclusions")
        exclusions.take(visible).forEach { record ->
            EdgeMeta(record.optString("reason"), color = RadarAmber)
            EdgeMeta("${record.optString("source")} · record ${record.optString("id")}", color = RadarMuted)
        }
        val candidates = source.rows("candidate_records")
        candidates.take(visible).forEach { place ->
            val status = when (place.optString("status")) {
                "now_pool" -> "Eligible for immediate options at review"
                "further_option" -> "A little further option at review"
                "arrival_timing" -> "Activity is not useful at estimated arrival"
                "transport_context" -> "Transport context; not a move trigger"
                else -> "Outside the immediate radius or further-option criteria"
            }
            EdgeMeta("${place.optString("name")} · $status", color = RadarMuted)
            place.rows("evidence").forEach { evidence ->
                EdgeMeta("${evidence.optString("basis")} · ${evidence.optString("role")} · ${if (evidence.optString("role") == "travel") "route estimate at review" else if (evidence.optBoolean("arrival_relevant", true)) "within arrival window" else "outside arrival window"}", color = RadarMuted)
            }
        }
        if (exclusions.size > visible || candidates.size > visible) EdgeButton("Show more decision records", { visible += 20 }, kind = EdgeButtonKind.Link)
        if (exclusions.isEmpty() && candidates.isEmpty() && source.optInt("plan_interval_count") == 0)
            EdgeMeta("No retained candidate or exclusion record for this source in this review. Feed availability alone does not establish decision use.", color = RadarMuted)
    }
}

@Composable
private fun RadarSourceRecord(record: JSONObject) {
    var expanded by rememberSaveable(record.toString()) { mutableStateOf(false) }
    val title = listOf("title", "name", "venue_name", "venue", "route_line", "station", "terminal", "id")
        .firstNotNullOfOrNull { key -> record.optString(key).takeIf { !record.isNull(key) && it.isNotBlank() } } ?: "Source record"
    RadarPanel {
        EdgeHeading(title, size = 17)
        val keys = record.keys().asSequence().toList()
        val common = listOf("zone_label", "basis", "starts_at", "ends_at", "arrival_time", "live_busyness", "typical_busyness", "detail")
        (if (expanded) keys else common.filter { record.has(it) }).forEach { key ->
            val value = record.opt(key)
            if (value != null && value != JSONObject.NULL && value.toString().isNotBlank()) {
                val formatted = if (key.endsWith("_at") || key == "arrival_time") reportTime(value.toString()) else
                    if (value is JSONArray) (0 until value.length()).joinToString(" · ") { value.opt(it).toString() } else value.toString()
                EdgeMeta("${key.replace('_', ' ')}: $formatted", color = RadarMuted)
            }
        }
        EdgeButton(if (expanded) "Fewer fields" else "All retained fields", { expanded = !expanded }, kind = EdgeButtonKind.Link)
    }
}
