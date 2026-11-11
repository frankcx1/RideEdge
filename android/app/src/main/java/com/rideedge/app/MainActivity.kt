package com.rideedge.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
import java.io.File
import java.util.Locale
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine

private val BgDeep = Color(0xFF070B12)
private val BgCard = Color(0xFF101724)
private val BgCardElevated = Color(0xFF162032)
private val BorderSubtle = Color(0xFF23324C)
private val EmeraldCyan = Color(0xFF00E5B0)
private val EmeraldDim = Color(0xFF0A362E)
private val RadarBlue = Color(0xFF58A6FF)
private val RadarDim = Color(0xFF112947)
private val AmberGold = Color(0xFFFFB84D)
private val AmberDim = Color(0xFF3A280E)
private val CoralRed = Color(0xFFFF6B6B)
private val CoralDim = Color(0xFF3B151E)
private val TextPrimary = Color(0xFFF2F6FC)
private val TextSecondary = Color(0xFF9BA9C2)
private val TextMuted = Color(0xFF66758F)

private val RideEdgeColorScheme = darkColorScheme(
    primary = EmeraldCyan,
    onPrimary = Color(0xFF031A14),
    secondary = RadarBlue,
    tertiary = AmberGold,
    background = BgDeep,
    surface = BgCard,
    onBackground = TextPrimary,
    onSurface = TextPrimary,
)

private val QUICK_AREAS = listOf(
    "Bellevue",
    "Kirkland",
    "Totem Lake",
    "Redmond",
    "Bothell",
    "Woodinville",
    "Downtown Seattle",
    "SLU",
    "Capitol Hill",
    "Seattle Center",
    "Ballard",
    "SeaTac Airport",
)

private fun formatDriverAreaName(raw: String): String {
    val clean = raw.trim()
    if (clean.isBlank()) return "Selected Area"
    return when (clean.lowercase(Locale.US)) {
        "bellevue", "bellevue_core", "bellevue core" -> "Bellevue Core"
        "kirkland", "kirkland_waterfront", "kirkland waterfront" -> "Kirkland Waterfront"
        "totem_lake", "totem lake" -> "Totem Lake"
        "redmond", "redmond_downtown", "redmond downtown" -> "Redmond Downtown"
        "bothell" -> "Bothell"
        "woodinville", "woodinville_wine", "woodinville wine country" -> "Woodinville"
        "seattle", "seattle_core", "seattle core", "downtown seattle" -> "Seattle Core"
        "slu", "south_lake_union", "south lake union" -> "South Lake Union"
        "capitol_hill", "capitol hill" -> "Capitol Hill"
        "seattle_center", "seattle center", "queen anne" -> "Seattle Center"
        "fremont_ballard", "fremont / ballard", "ballard", "fremont" -> "Fremont / Ballard"
        "sodo", "sodo_stadiums", "sodo stadiums" -> "SoDo Stadiums"
        "uw", "uw_district", "u district", "university district" -> "U District"
        "sea_airport", "seatac", "seatac airport", "sea-tac airport" -> "Sea-Tac Airport"
        else -> clean.replace('_', ' ').split(" ").filter { it.isNotBlank() }
            .joinToString(" ") { w -> w.replaceFirstChar { it.uppercase() } }
    }
}

private val ISO_TIMESTAMP_REGEX = Regex("""\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?""")

private fun formatClock12h(hour24: Int, minute: Int): String {
    val amPm = if (hour24 < 12) "AM" else "PM"
    val h12 = when {
        hour24 == 0 -> 12
        hour24 > 12 -> hour24 - 12
        else -> hour24
    }
    return String.format(Locale.US, "%d:%02d %s", h12, minute, amPm)
}

private fun cleanDriverText(raw: String): String {
    if (raw.isBlank()) return ""
    var out = ISO_TIMESTAMP_REGEX.replace(raw) { m ->
        val hh = m.groupValues[1].toIntOrNull() ?: 0
        val mm = m.groupValues[2].toIntOrNull() ?: 0
        formatClock12h(hh, mm)
    }
    out = out
        .replace("strongest kind of card Farol will show tonight", "strong local pickup window")
        .replace("Farol", "RideEdge")
        .replace("workstation", "service")
        .replace(" — skip", " · low value")
    return WorkingLocationController.normalizePlainDriverCopy(out)
}

private data class MergedCourseInterval(
    val slotBadge: String,
    val windowLabel: String,
    val hoursSpan: Int,
    val firstStop: ShiftCourseStop,
    val lastStop: ShiftCourseStop,
)

private fun mergeCourseStops(stops: List<ShiftCourseStop>): List<MergedCourseInterval> {
    if (stops.isEmpty()) return emptyList()
    val rawGroups = mutableListOf<MutableList<ShiftCourseStop>>()
    for (stop in stops) {
        val lastGroup = rawGroups.lastOrNull()
        val prev = lastGroup?.lastOrNull()
        val sameZone = prev != null && prev.zone == stop.zone
        val sameAction = prev != null &&
            prev.decisionState.ifBlank { prev.action }.equals(
                stop.decisionState.ifBlank { stop.action },
                ignoreCase = true,
            )
        val isHoldBlock = prev != null &&
            !prev.decisionState.ifBlank { prev.action }.equals("MOVE", ignoreCase = true) &&
            !stop.decisionState.ifBlank { stop.action }.equals("MOVE", ignoreCase = true)
        val sameTrigger = prev != null &&
            prev.primaryTrigger.trim().equals(stop.primaryTrigger.trim(), ignoreCase = true)
        if (lastGroup != null && sameZone && (sameAction || isHoldBlock) && (sameTrigger || isHoldBlock)) {
            lastGroup.add(stop)
        } else {
            rawGroups.add(mutableListOf(stop))
        }
    }
    return rawGroups.mapIndexed { idx, grp ->
        val first = grp.first()
        val last = grp.last()
        val startPart = first.windowLabel.split("–", "-").firstOrNull()?.trim().orEmpty()
        val endPart = last.windowLabel.split("–", "-").lastOrNull()?.trim().orEmpty()
        val mergedWin = if (grp.size > 1 && startPart.isNotBlank() && endPart.isNotBlank()) {
            "$startPart – $endPart (${grp.size}h)"
        } else {
            first.windowLabel
        }
        val badge = when (idx) {
            0 -> "NOW"
            1 -> "NEXT"
            else -> "LATER"
        }
        MergedCourseInterval(
            slotBadge = badge,
            windowLabel = mergedWin,
            hoursSpan = grp.size,
            firstStop = first,
            lastStop = last,
        )
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        enableEdgeToEdge()
        if (BuildConfig.BUILD_TYPE == "preview") {
            if (intent?.getBooleanExtra("expire_preview_car_session", false) == true) {
                (application as RideEdgeApplication).advancePreviewSessionClock()
            }
            (application as RideEdgeApplication).previewScenario = intent?.getStringExtra("radar_fixture_state")
                ?.takeIf { it in setOf("fallback", "cleanup", "stale", "offline", "arrival", "design", "saved", "expired", "unauthorized", "incompatible", "stress", "recording", "positioning", "no_options") } ?: "fallback"
            if (intent?.hasExtra("recording_step") == true) {
                (application as RideEdgeApplication).selectRecordingStep(intent.getIntExtra("recording_step", 0))
            }
            if (intent?.getBooleanExtra("check_access_storage", false) == true) {
                (application as RideEdgeApplication).previewAccessCheck = checkPreviewAccessStorage(this)
            }
        }
        val initialTab = when (intent?.getStringExtra("initial_tab")) {
            "around", "nearby" -> 1
            "ask", "tonight", "plan", "uber_intel" -> 2
            "shift" -> 3
            else -> 0
        }
        val initialPlanSubTab = when (intent?.getStringExtra("initial_tab")) {
            "uber_intel" -> 4
            else -> intent?.getIntExtra("initial_plan_sub_tab", 0) ?: 0
        }
        val initialUberPaste = intent?.getStringExtra("initial_uber_paste").orEmpty().replace("\\ ", " ")
        val initialUberSection = intent?.getStringExtra("initial_uber_section") ?: "all"
        val initialArea = intent?.getStringExtra("initial_area")?.replace("\\ ", " ")?.takeIf { it.isNotBlank() }
        val initialDriverMode = intent?.getStringExtra("initial_driver_mode")?.takeIf { it.isNotBlank() }
        val initialRepositionLimit = intent?.getIntExtra("initial_reposition_limit", -1)?.takeIf { it in 5..45 }
        val initialUberStoreFile = intent?.getStringExtra("initial_uber_store_file")?.takeIf { it.isNotBlank() }
        val initialShowFeedHealth = intent?.getBooleanExtra("initial_show_feed_health", false) ?: false
        val initialFeedAdapter = intent?.getStringExtra("initial_feed_adapter")?.takeIf { it.isNotBlank() }
        val initialUberEditDrive = intent?.getStringExtra("initial_uber_edit_drive")?.takeIf { it.isNotBlank() }
        val initialUberEditWait = intent?.getStringExtra("initial_uber_edit_wait")?.takeIf { it.isNotBlank() }
        val initialUberClearPasteAfterParse = intent?.getBooleanExtra("initial_uber_clear_paste_after_parse", false) ?: false
        val initialQaScenario = intent?.getStringExtra("initial_qa_scenario")?.takeIf { it.isNotBlank() }
        setContent {
            MaterialTheme(colorScheme = RideEdgeColorScheme) {
                if (BuildConfig.BUILD_TYPE == "preview" || intent?.getBooleanExtra("legacy_cockpit", false) != true) {
                    RideEdgeTheme { ActivityRadarApp(initialArea = initialArea, initialTab = initialTab.coerceIn(0, 2)) }
                } else RideEdgeCockpitApp(
                    initialTab = initialTab,
                    initialPlanSubTab = initialPlanSubTab,
                    initialUberPaste = initialUberPaste,
                    initialUberSection = initialUberSection,
                    initialArea = initialArea,
                    initialDriverMode = initialDriverMode,
                    initialRepositionLimit = initialRepositionLimit,
                    initialUberStoreFile = initialUberStoreFile,
                    initialShowFeedHealth = initialShowFeedHealth,
                    initialFeedAdapter = initialFeedAdapter,
                    initialUberEditDrive = initialUberEditDrive,
                    initialUberEditWait = initialUberEditWait,
                    initialUberClearPasteAfterParse = initialUberClearPasteAfterParse,
                    initialQaScenario = initialQaScenario,
                )
            }
        }
    }
}

@Composable
fun RideEdgeCockpitApp(
    initialTab: Int = 0,
    initialPlanSubTab: Int = 0,
    initialUberPaste: String = "",
    initialUberSection: String = "all",
    initialArea: String? = null,
    initialDriverMode: String? = null,
    initialRepositionLimit: Int? = null,
    initialUberStoreFile: String? = null,
    initialShowFeedHealth: Boolean = false,
    initialFeedAdapter: String? = null,
    initialUberEditDrive: String? = null,
    initialUberEditWait: String? = null,
    initialUberClearPasteAfterParse: Boolean = false,
    initialQaScenario: String? = null,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val workingPrefs = remember(context) {
        context.getSharedPreferences("rideedge_working_state_v1", Context.MODE_PRIVATE)
    }

    var selectedTab by rememberSaveable { mutableIntStateOf(initialTab) }
    var planSubTab by rememberSaveable { mutableIntStateOf(initialPlanSubTab) }
    var showFeedHealthView by rememberSaveable { mutableStateOf(initialShowFeedHealth || initialFeedAdapter != null) }
    var health by remember { mutableStateOf<HealthState?>(null) }
    var statusBanner by remember { mutableStateOf<String?>(null) }
    var isRefreshing by remember { mutableStateOf(false) }
    val storeFileName = remember(initialUberStoreFile) {
        initialUberStoreFile?.takeIf { it.isNotBlank() && !it.contains("/") && !it.contains("\\") }
            ?: "uber_assistant_imports_v1.json"
    }
    val uberRepository = remember(context, storeFileName, initialQaScenario) {
        val storeFile = File(context.filesDir, storeFileName)
        if (storeFileName != "uber_assistant_imports_v1.json" && !initialQaScenario.isNullOrBlank()) {
            storeFile.delete()
        }
        val repo = UberIntelligenceRepository(storeFile)
        if (storeFileName != "uber_assistant_imports_v1.json" && !initialQaScenario.isNullOrBlank()) {
            val nowInst = java.time.Instant.now().truncatedTo(java.time.temporal.ChronoUnit.SECONDS)
            when (initialQaScenario) {
                "seqB_fresh" -> {
                    val srcIso = nowInst.minusSeconds(120).toString()
                    val parsed = UberIntelligence.parseAssistantResponse(
                        rawResponse = "Totem Lake: About 38 requests in last 30 minutes, median wait 4 minutes, source updated at $srcIso.",
                        createdAt = nowInst.toString(),
                    ).copy(parseStatus = "reviewed")
                    repo.saveImport(parsed, allowDuplicate = true)
                }
                "seqB_expired" -> {
                    val srcIso = nowInst.minusSeconds(1500).toString()
                    val parsed = UberIntelligence.parseAssistantResponse(
                        rawResponse = "Totem Lake: About 38 requests in last 30 minutes, median wait 4 minutes, source updated at $srcIso.",
                        createdAt = nowInst.minusSeconds(1400).toString(),
                    ).copy(parseStatus = "reviewed")
                    repo.saveImport(parsed, allowDuplicate = true)
                }
                "seqD_episodes" -> {
                    val srcIso = nowInst.minusSeconds(180).toString()
                    val parsed = UberIntelligence.parseAssistantResponse(
                        rawResponse = "Bellevue: About 42 requests in last 30 minutes, median wait 4 minutes, source updated at $srcIso.",
                        createdAt = nowInst.toString(),
                    ).copy(parseStatus = "reviewed")
                    repo.saveImport(parsed, allowDuplicate = true)
                    val baseTarget = UberIntelligence.DecisionTargetContext(
                        recommendationId = "rec-seqD-1",
                        evidenceVersion = "v2",
                        issuedAt = nowInst.toString(),
                        action = "STAY",
                        decisionState = "STAY",
                        originZone = "bellevue_core",
                        targetZone = "bellevue_core",
                        targetLabel = "Bellevue",
                        structuredPremise = "short_wait_expected",
                    )
                    val cmp1 = UberIntelligence.evaluateDecisionComparison(parsed, baseTarget, nowInst)
                    repo.saveComparison(cmp1)
                    // Episode 1: request at 10m, accepted at 18m (waitMinutesToRequest stays 10.0m)
                    repo.linkEpisodeOutcome("rec-seqD-1", "ep-seqD-1-a", "stayed", "waiting")
                    repo.linkEpisodeOutcome("rec-seqD-1", "ep-seqD-1-a", "stayed", "request_within_15m", 10.0)
                    repo.linkEpisodeOutcome("rec-seqD-1", "ep-seqD-1-a", "unknown", "accepted_ride", 18.0, acceptedRide = true)
                    // Episode 2 on same recommendation: dry 15m+ wait without overwriting Episode 1
                    repo.linkEpisodeOutcome("rec-seqD-1", "ep-seqD-1-b", "stayed", "waiting")
                    repo.linkEpisodeOutcome("rec-seqD-1", "ep-seqD-1-b", "stayed", "no_request_after_15m", 16.0)
                    // Comparison 2: late request after 20m (counted in adequatelyLoggedCount)
                    val cmp2 = UberIntelligence.evaluateDecisionComparison(
                        parsed,
                        baseTarget.copy(recommendationId = "rec-seqD-2"),
                        nowInst,
                    )
                    repo.saveComparison(cmp2)
                    repo.linkEpisodeOutcome("rec-seqD-2", "ep-seqD-2-a", "stayed", "request_after_15m", 20.0)
                    // Comparison 3: accepted ride without wait timestamp (excluded from <=15m success)
                    val cmp3 = UberIntelligence.evaluateDecisionComparison(
                        parsed,
                        baseTarget.copy(recommendationId = "rec-seqD-3"),
                        nowInst,
                    )
                    repo.saveComparison(cmp3)
                    repo.linkEpisodeOutcome("rec-seqD-3", "ep-seqD-3-a", "unknown", "accepted_ride", null, acceptedRide = true)
                }
            }
        }
        repo
    }
    var uberReloadGeneration by remember { mutableIntStateOf(0) }

    // Tab 0: Working / Here state owned by WorkingLocationController (F06, G03, G04, H02, R2-03)
    val workingController = remember { WorkingLocationController(initialArea = initialArea ?: "Bellevue").apply {
            val savedJson = workingPrefs.getString("working_controller_json", null)
            if (!savedJson.isNullOrBlank()) {
                runCatching { restoreFromJson(org.json.JSONObject(savedJson)) }
            }
            if (!initialArea.isNullOrBlank()) {
                beginManualAreaLoad(initialArea)
                areaQuery = initialArea.trim()
                awarenessArea = initialArea.trim()
            }
            if (!initialDriverMode.isNullOrBlank()) {
                setDriverPosture(initialDriverMode)
            }
            if (initialRepositionLimit != null) {
                setRepositionLimit(initialRepositionLimit)
            }
            runCatching {
                workingPrefs.edit().putString("working_controller_json", toJson().toString()).commit()
            }
        }
    }
    var areaQuery by rememberSaveable { mutableStateOf(workingController.areaQuery) }
    var originSelectionMode by remember { mutableStateOf(workingController.originSelectionMode) }
    var driverMode by rememberSaveable { mutableStateOf(workingController.driverMode) }
    var positioningTargetId by remember { mutableStateOf(workingController.positioningTargetId) }
    var positioningTargetLabel by remember { mutableStateOf(workingController.positioningTargetLabel) }
    var positioningState by remember { mutableStateOf(workingController.positioningState) }
    var hereState by remember { mutableStateOf<HereState?>(null) }
    var hereLoadedAtMs by remember { mutableStateOf<Long?>(null) }
    var hereFromGps by remember { mutableStateOf(workingController.hereFromGps) }
    var nowTickMs by remember { mutableStateOf(System.currentTimeMillis()) }
    var lastGpsLat by remember { mutableStateOf(workingController.lastGpsLat) }
    var lastGpsLon by remember { mutableStateOf(workingController.lastGpsLon) }
    var lastGpsFixAtMs by remember { mutableStateOf(workingController.lastGpsFixAtMs) }
    var seatacForecast by remember { mutableStateOf<SeatacForecastState?>(null) }
    var seatacPolling by remember { mutableStateOf(false) }
    var activeRecommendationId by remember { mutableStateOf(workingController.activeEpisodeRecommendationId) }
    var activeEvidenceVersion by remember { mutableStateOf(workingController.activeEpisodeEvidenceVersion ?: "v2") }
    var activeEpisodeZone by remember { mutableStateOf(workingController.activeEpisodeZone) }
    var activeEpisodeState by remember { mutableStateOf(workingController.activeEpisodeState) }
    var activeEpisodeStartedAtMs by remember { mutableStateOf(workingController.activeEpisodeStartedAtMs) }
    var outcomeSyncState by remember { mutableStateOf(workingController.lastOutcomeDeliveryState) }
    var outcomePendingStatus by remember {
        mutableStateOf(workingController.pendingOutcomeStatus ?: workingController.failedOutcomeStatus)
    }
    var outcomeFailedZoneLabel by remember {
        mutableStateOf(workingController.failedOutcomeZoneLabel ?: workingController.failedOutcomeZone)
    }
    var outcomeLastError by remember {
        mutableStateOf(
            workingController.lastOutcomeMessage.takeIf { workingController.lastOutcomeDeliveryState == "failed" }
        )
    }

    // Request generation counters (R06/F06: prevent stale async responses from overwriting newer selections)
    var hereReqGen by remember { mutableIntStateOf(0) }
    var awarenessReqGen by remember { mutableIntStateOf(0) }
    var askReqGen by remember { mutableIntStateOf(0) }
    var courseReqGen by remember { mutableIntStateOf(0) }

    // Tab 1: Nearby (Around You) state
    var awarenessState by remember { mutableStateOf<AwarenessState?>(null) }
    var awarenessArea by rememberSaveable { mutableStateOf(workingController.awarenessArea) }
    var awarenessUseGps by rememberSaveable { mutableStateOf(false) }
    var awarenessScope by rememberSaveable { mutableStateOf("nearby") }
    var awarenessRadius by rememberSaveable { mutableIntStateOf(8) }
    var awarenessPeriod by rememberSaveable { mutableStateOf("now") }
    var awarenessLayer by rememberSaveable { mutableStateOf("all") }
    var bestTimePolling by remember { mutableStateOf(false) }

    // Tab 2: Plan (Course + Tonight + Airport + Compare) state
    var askArea by rememberSaveable { mutableStateOf(workingController.areaQuery) }
    var askState by remember { mutableStateOf<AskState?>(null) }
    var shiftCourseState by remember { mutableStateOf<ShiftCourseState?>(null) }
    var courseBlasting by remember { mutableStateOf(false) }
    var courseError by remember { mutableStateOf<String?>(null) }
    var askMinutesAvailable by rememberSaveable { mutableIntStateOf(workingController.planMinutesAvailable) }
    var askRepositionUnder by rememberSaveable { mutableIntStateOf(workingController.repositionLimitMinutes) }
    var askFinishNear by rememberSaveable { mutableStateOf("kirkland_waterfront") }
    var askQuestionText by rememberSaveable { mutableStateOf("") }
    var askBusy by remember { mutableStateOf(false) }
    var tonightState by remember { mutableStateOf<TonightState?>(null) }

    // Tab 3: Shift Odometer & Session Ledger state
    var shiftState by remember { mutableStateOf<ShiftLedgerState?>(null) }
    var odometerInput by rememberSaveable { mutableStateOf("") }
    var odometerNote by rememberSaveable { mutableStateOf("") }

    // Native Text-To-Speech
    var ttsEngine by remember { mutableStateOf<TextToSpeech?>(null) }
    var ttsReady by remember { mutableStateOf(false) }
    DisposableEffect(context) {
        var instance: TextToSpeech? = null
        instance = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                instance?.language = Locale.US
                instance?.setSpeechRate(1.03f)
                ttsReady = true
            }
        }
        ttsEngine = instance
        onDispose {
            instance?.stop()
            instance?.shutdown()
        }
    }

    fun speakOut(text: String) {
        if (text.isBlank()) return
        if (ttsReady) {
            ttsEngine?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "rideedge-spoken")
        } else {
            statusBanner = "Voice synthesizer initializing…"
        }
    }

    suspend fun refreshHealthSilent() {
        runCatching { RideEdgeClient.fetchHealth() }
            .onSuccess { health = it }
    }

    fun syncWorkingControllerState(includeBanner: Boolean = true) {
        hereState = workingController.hereState
        hereLoadedAtMs = workingController.hereLoadedAtMs
        hereFromGps = workingController.hereFromGps
        originSelectionMode = workingController.originSelectionMode
        lastGpsLat = workingController.lastGpsLat
        lastGpsLon = workingController.lastGpsLon
        lastGpsFixAtMs = workingController.lastGpsFixAtMs
        awarenessUseGps = workingController.awarenessUseGps
        areaQuery = workingController.areaQuery
        awarenessArea = workingController.awarenessArea
        driverMode = workingController.driverMode
        askRepositionUnder = workingController.repositionLimitMinutes
        askMinutesAvailable = workingController.planMinutesAvailable
        positioningTargetId = workingController.positioningTargetId
        positioningTargetLabel = workingController.positioningTargetLabel
        positioningState = workingController.positioningState
        hereReqGen = workingController.hereReqGen
        activeRecommendationId = workingController.activeEpisodeRecommendationId
        activeEvidenceVersion = workingController.activeEpisodeEvidenceVersion ?: "v2"
        activeEpisodeZone = workingController.activeEpisodeZone
        activeEpisodeState = workingController.activeEpisodeState
        activeEpisodeStartedAtMs = workingController.activeEpisodeStartedAtMs
        outcomeSyncState = workingController.lastOutcomeDeliveryState
        outcomePendingStatus = workingController.pendingOutcomeStatus ?: workingController.failedOutcomeStatus
        outcomeFailedZoneLabel = workingController.failedOutcomeZoneLabel ?: workingController.failedOutcomeZone
        outcomeLastError = workingController.lastOutcomeMessage.takeIf {
            workingController.lastOutcomeDeliveryState == "failed"
        }
        if (includeBanner) {
            statusBanner = workingController.statusBanner
        }
        runCatching {
            workingPrefs.edit().putString("working_controller_json", workingController.toJson().toString()).commit()
        }
    }

    fun currentFreshGps(nowMs: Long = System.currentTimeMillis()): Pair<Double, Double>? {
        val fresh = workingController.currentFreshGps(nowMs)
        if (
            workingController.hereState !== hereState ||
            workingController.lastGpsLat != lastGpsLat ||
            workingController.hereFromGps != hereFromGps
        ) {
            syncWorkingControllerState(includeBanner = true)
        }
        return fresh
    }

    fun loadAwareness(
        scopeOverride: String = awarenessScope,
        radiusOverride: Int = awarenessRadius,
        periodOverride: String = awarenessPeriod,
        layerOverride: String = awarenessLayer,
        areaOverride: String? = null,
        useGpsOverride: Boolean = awarenessUseGps,
    ) {
        val reqId = ++awarenessReqGen
        scope.launch {
            isRefreshing = true
            refreshHealthSilent()
            val targetArea = areaOverride ?: awarenessArea
            val freshGps = if (useGpsOverride && areaOverride == null) currentFreshGps() else null
            val result = if (scopeOverride == "nearby" && freshGps != null) {
                runCatching {
                    RideEdgeClient.fetchAwarenessByGps(
                        latitude = freshGps.first,
                        longitude = freshGps.second,
                        radius = radiusOverride.toDouble(),
                        period = periodOverride,
                        layer = layerOverride,
                    )
                }
            } else {
                runCatching {
                    RideEdgeClient.fetchAwarenessByArea(
                        scope = scopeOverride,
                        area = targetArea,
                        radius = radiusOverride.toDouble(),
                        period = periodOverride,
                        layer = layerOverride,
                    )
                }
            }
            if (reqId == awarenessReqGen) {
                result.onSuccess { awarenessState = it }
                    .onFailure { statusBanner = it.message }
                isRefreshing = false
            }
        }
    }

    fun loadHereByPlace(place: String) {
        val reqId = workingController.beginManualAreaLoad(place)
        val awReqId = ++awarenessReqGen
        // G04: Immediately clear previous guidance card alongside GPS provenance so a slow or failed
        // manual area switch can never leave old GPS guidance visible without expiry protection.
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        syncWorkingControllerState(includeBanner = true)
        ttsEngine?.stop()
        scope.launch {
            isRefreshing = true
            statusBanner = null
            refreshHealthSilent()
            runCatching {
                RideEdgeClient.fetchHereByText(
                    at = place,
                    driverMode = workingController.driverMode,
                    maxRepositionMinutes = workingController.repositionLimitMinutes,
                )
            }
                .onSuccess {
                    val prevZone = workingController.hereState?.zone
                    if (workingController.completeManualAreaLoad(reqId, it, place, System.currentTimeMillis())) {
                        syncWorkingControllerState(includeBanner = false)
                        askArea = place
                        if (prevZone != null && !prevZone.equals(it.zone, ignoreCase = true)) {
                            shiftCourseState = null
                            askState = null
                        }
                    }
                    runCatching {
                        RideEdgeClient.fetchAwarenessByArea(
                            scope = awarenessScope,
                            area = it.zone.ifBlank { place },
                            radius = awarenessRadius.toDouble(),
                            period = awarenessPeriod,
                            layer = awarenessLayer,
                        )
                    }.onSuccess { aw ->
                        if (awReqId == awarenessReqGen) {
                            awarenessState = aw
                        }
                    }
                }
                .onFailure {
                    if (workingController.failManualAreaLoad(reqId, it.message)) {
                        syncWorkingControllerState(includeBanner = true)
                    }
                }
            if (reqId == hereReqGen) {
                isRefreshing = false
            }
        }
    }

    fun loadHereFromPixelGps() {
        val reqId = workingController.beginGpsLoad()
        val awReqId = ++awarenessReqGen
        hereState = null
        hereLoadedAtMs = null
        hereFromGps = false
        syncWorkingControllerState(includeBanner = true)
        ttsEngine?.stop()
        scope.launch {
            isRefreshing = true
            statusBanner = "Reading Pixel 10 Pro GPS…"
            val loc = readDeviceLocation(context)
            // F06: Check request generation immediately after awaiting location so a delayed GPS callback
            // cannot restore coordinates or overwrite a newer manual area selection.
            if (reqId != hereReqGen) {
                return@launch
            }
            if (loc == null) {
                workingController.failGpsLoad(
                    reqId,
                    "Fresh GPS fix unavailable (>2m old or >250m accuracy); select an area chip.",
                )
                syncWorkingControllerState(includeBanner = true)
                isRefreshing = false
                return@launch
            }
            val nowMs = System.currentTimeMillis()
            val fixTime = if (loc.time > 0L) loc.time else nowMs
            val acc = if (loc.hasAccuracy()) loc.accuracy else null
            if (!workingController.onGpsFixAcquired(reqId, loc.latitude, loc.longitude, fixTime, nowMs, acc)) {
                syncWorkingControllerState(includeBanner = true)
                isRefreshing = false
                return@launch
            }
            syncWorkingControllerState(includeBanner = false)
            runCatching {
                RideEdgeClient.fetchHereByGps(
                    latitude = loc.latitude,
                    longitude = loc.longitude,
                    driverMode = workingController.driverMode,
                    maxRepositionMinutes = workingController.repositionLimitMinutes,
                )
            }
                .onSuccess {
                    if (workingController.completeGpsLoad(reqId, it, loc.latitude, loc.longitude, System.currentTimeMillis())) {
                        syncWorkingControllerState(includeBanner = true)
                        askArea = formatDriverAreaName(it.label.ifBlank { it.zone })
                        shiftCourseState = null
                        askState = null
                    }
                }
                .onFailure {
                    if (workingController.failGpsLoad(reqId, it.message)) {
                        syncWorkingControllerState(includeBanner = true)
                    }
                }
            runCatching {
                RideEdgeClient.fetchAwarenessByGps(
                    latitude = loc.latitude,
                    longitude = loc.longitude,
                    radius = awarenessRadius.toDouble(),
                    period = awarenessPeriod,
                    layer = awarenessLayer,
                )
            }.onSuccess { aw ->
                if (awReqId == awarenessReqGen) {
                    awarenessState = aw
                }
            }
            if (reqId == hereReqGen) {
                isRefreshing = false
            }
        }
    }

    fun loadAskContextForArea(area: String) {
        val reqId = ++askReqGen
        scope.launch {
            askBusy = true
            refreshHealthSilent()
            val canonicalArea = if (
                area.equals(workingController.areaQuery, ignoreCase = true) &&
                workingController.awarenessArea.isNotBlank()
            ) {
                workingController.awarenessArea
            } else {
                area
            }
            runCatching { RideEdgeClient.fetchAskContext(canonicalArea) }
                .onSuccess {
                    if (reqId == askReqGen) {
                        askState = if (area.isNotBlank() && !area.equals(canonicalArea, ignoreCase = true)) {
                            it.copy(origin = area)
                        } else {
                            it
                        }
                        askArea = area
                    }
                }
                .onFailure {
                    if (reqId == askReqGen) {
                        statusBanner = it.message
                    }
                }
            if (reqId == askReqGen) {
                askBusy = false
            }
        }
    }

    fun loadTonight() {
        scope.launch {
            isRefreshing = true
            refreshHealthSilent()
            runCatching { RideEdgeClient.fetchTonight() }
                .onSuccess { tonightState = it }
                .onFailure { statusBanner = it.message }
            isRefreshing = false
        }
    }

    fun loadShiftLedger() {
        scope.launch {
            isRefreshing = true
            refreshHealthSilent()
            runCatching { RideEdgeClient.fetchShiftLedger() }
                .onSuccess { shiftState = it }
                .onFailure { statusBanner = it.message }
            isRefreshing = false
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        val granted = perms[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
            perms[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        if (granted) {
            loadHereFromPixelGps()
        } else {
            val reqId = workingController.beginGpsLoad()
            workingController.failGpsLoad(
                reqId,
                "Location permission denied; tap Use GPS after granting permission or choose an area below.",
            )
            syncWorkingControllerState(includeBanner = true)
        }
    }

    // Initial load when app opens + active 5-second clock ticker for GPS expiry & recheck countdown (F06, R4-05)
    LaunchedEffect(Unit) {
        refreshHealthSilent()
        runCatching { RideEdgeClient.fetchSeatacForecast(pull = false) }
            .onSuccess { seatacForecast = it }
        if (workingController.originSelectionMode == "gps" || workingController.hereFromGps) {
            val hasFine = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.ACCESS_FINE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
            if (hasFine) {
                loadHereFromPixelGps()
            } else {
                val reqId = workingController.beginGpsLoad()
                workingController.failGpsLoad(
                    reqId,
                    "GPS location selected; grant location permission or tap Change location.",
                )
                syncWorkingControllerState(includeBanner = true)
            }
        } else {
            loadHereByPlace(areaQuery)
        }
        loadAskContextForArea(askArea)
        while (true) {
            kotlinx.coroutines.delay(5_000L)
            val now = System.currentTimeMillis()
            nowTickMs = now
            currentFreshGps(now)
        }
    }

    // Auto-dismiss non-error status banners after 3.5 seconds so transient confirmations never obscure cards (N06)
    LaunchedEffect(statusBanner) {
        val msg = statusBanner ?: return@LaunchedEffect
        val isError = msg.contains("failed", ignoreCase = true) ||
            msg.contains("unavailable", ignoreCase = true) ||
            msg.contains("expired", ignoreCase = true) ||
            msg.contains("offline", ignoreCase = true) ||
            msg.contains("denied", ignoreCase = true)
        if (!isError) {
            kotlinx.coroutines.delay(3_500L)
            if (statusBanner == msg) {
                statusBanner = null
            }
        }
    }

    // Load tab-specific data on tab switch and clear transient banners (N03, N06)
    LaunchedEffect(selectedTab, planSubTab, shiftCourseState == null, askState == null) {
        statusBanner?.let { msg ->
            val isError = msg.contains("failed", ignoreCase = true) ||
                msg.contains("unavailable", ignoreCase = true) ||
                msg.contains("expired", ignoreCase = true) ||
                msg.contains("offline", ignoreCase = true)
            if (!isError) {
                statusBanner = null
            }
        }
        when (selectedTab) {
            1 -> if (awarenessState == null) loadAwareness()
            2 -> {
                if (askState == null && !askBusy) loadAskContextForArea(askArea)
                if (tonightState == null) loadTonight()
                if (shiftCourseState == null && courseError == null && !courseBlasting) {
                    val cReqId = ++courseReqGen
                    val freshGps = currentFreshGps()
                    runCatching {
                        RideEdgeClient.fetchShiftCourse(
                            area = askArea,
                            latitude = freshGps?.first,
                            longitude = freshGps?.second,
                            pullAll = false,
                            minutesAvailable = askMinutesAvailable,
                            repositionUnderMinutes = askRepositionUnder,
                            finishNear = askFinishNear,
                        )
                    }.onSuccess {
                        if (cReqId == courseReqGen) {
                            shiftCourseState = it
                            courseError = null
                        }
                    }.onFailure {
                        if (cReqId == courseReqGen) {
                            courseError = it.message
                        }
                    }
                }
            }
            3 -> if (shiftState == null) loadShiftLedger()
        }
    }

    val activeFreshGps = currentFreshGps(nowTickMs)
    val latestUberImport = remember(uberReloadGeneration, selectedTab, planSubTab) {
        uberRepository.listImports().firstOrNull { !it.isDemoSample && !it.suspectedLegacySample }
    }
    val latestNowComparison = remember(
        uberReloadGeneration,
        selectedTab,
        planSubTab,
        nowTickMs,
        activeEpisodeState,
        outcomeSyncState,
        outcomePendingStatus,
        hereState?.recommendationId,
        hereState?.evidenceVersion,
        hereState?.zone,
        hereState?.action,
        hereState?.decisionState,
        hereState?.destinationId,
        hereState?.recommendationBasis,
    ) {
        val savedList = uberRepository.listComparisons()
        val curHere = hereState
        val latestImp = latestUberImport
        when {
            curHere != null && latestImp != null -> {
                val targetCtx = UberIntelligence.buildTargetContextFromHere(curHere)
                val matching = savedList.filter {
                    it.importId == latestImp.id &&
                        it.importDraftRevision == latestImp.draftRevision &&
                        it.targetType == "now" &&
                        it.recommendationId == targetCtx.recommendationId &&
                        it.evidenceVersion == targetCtx.evidenceVersion &&
                        it.action.equals(targetCtx.action, ignoreCase = true) &&
                        it.decisionState.equals(targetCtx.decisionState, ignoreCase = true) &&
                        it.targetZone == targetCtx.targetZone &&
                        it.destinationId == targetCtx.destinationId &&
                        it.structuredPremise == targetCtx.structuredPremise
                }
                val existingUnbound = matching.lastOrNull { it.linkedEpisodeId.isNullOrBlank() }
                val currentEval = UberIntelligence.evaluateDecisionComparison(
                    importRecord = latestImp,
                    target = targetCtx,
                    evalTime = java.time.Instant.ofEpochMilli(nowTickMs),
                    seenBeforeEpisodeStart = activeEpisodeState == "none",
                )
                if (existingUnbound != null && currentEval.reasonCode == existingUnbound.reasonCode && currentEval.verdict == existingUnbound.verdict) {
                    currentEval.copy(
                        id = existingUnbound.id,
                        linkedEpisodeId = null,
                        driverChoice = existingUnbound.driverChoice,
                        outcomeStatus = existingUnbound.outcomeStatus,
                        userPerceivedUseful = existingUnbound.userPerceivedUseful,
                    )
                } else {
                    runCatching { uberRepository.saveComparison(currentEval) }.getOrDefault(currentEval)
                }
            }
            else -> null
        }
    }
    val latestPlanFirstStopComparison = remember(
        uberReloadGeneration,
        selectedTab,
        planSubTab,
        nowTickMs,
        shiftCourseState?.stops,
    ) {
        val firstStop = shiftCourseState?.stops?.firstOrNull()
        val latestImp = latestUberImport
        if (firstStop != null && latestImp != null) {
            val targetCtx = UberIntelligence.buildTargetContextFromPlanStop(
                stop = firstStop,
                originZone = shiftCourseState?.originLabel ?: askArea,
                generatedAt = shiftCourseState?.generatedAt ?: "",
            )
            UberIntelligence.evaluateDecisionComparison(
                importRecord = latestImp,
                target = targetCtx,
                evalTime = java.time.Instant.ofEpochMilli(nowTickMs),
                seenBeforeEpisodeStart = activeEpisodeState == "none",
            )
        } else {
            null
        }
    }

    Scaffold(
        containerColor = BgDeep,
        topBar = {
            CockpitHeader(
                health = health,
                showFeedHealthView = showFeedHealthView,
                isRefreshing = isRefreshing || askBusy || courseBlasting,
                hasGpsLock = activeFreshGps != null,
                onToggleFeedHealth = {
                    showFeedHealthView = !showFeedHealthView
                    if (showFeedHealthView) {
                        scope.launch { refreshHealthSilent() }
                    }
                },
                onUseGps = {
                    showFeedHealthView = false
                    val hasFine = ContextCompat.checkSelfPermission(
                        context,
                        Manifest.permission.ACCESS_FINE_LOCATION
                    ) == PackageManager.PERMISSION_GRANTED
                    if (hasFine) {
                        loadHereFromPixelGps()
                    } else {
                        permissionLauncher.launch(
                            arrayOf(
                                Manifest.permission.ACCESS_FINE_LOCATION,
                                Manifest.permission.ACCESS_COARSE_LOCATION,
                            )
                        )
                    }
                },
                onSpeak = {
                    val textToRead = when (selectedTab) {
                        0 -> hereState?.spoken ?: hereState?.actionPlain ?: ""
                        1 -> {
                            val topObs = awarenessState?.observations?.firstOrNull()
                            if (topObs != null) {
                                "${awarenessState?.locationLabel}: ${awarenessState?.observations?.size ?: 0} signals. Top signal: ${topObs.title}. ${topObs.detail}"
                            } else {
                                awarenessState?.emptyNote ?: ""
                            }
                        }
                        2 -> when (planSubTab) {
                            1 -> tonightState?.narratorSpoken ?: tonightState?.explanation ?: ""
                            2 -> seatacForecast?.summary ?: ""
                            else -> shiftCourseState?.aiBriefing?.ifBlank { askState?.answer ?: "" } ?: askState?.answer ?: ""
                        }
                        else -> shiftState?.earningsStatus ?: ""
                    }
                    speakOut(textToRead)
                },
                onRefresh = {
                    if (showFeedHealthView) {
                        scope.launch {
                            isRefreshing = true
                            statusBanner = "Refreshing live feeds…"
                            runCatching { RideEdgeClient.refreshAllFeeds() }
                            refreshHealthSilent()
                            statusBanner = "Live feeds refreshed."
                            isRefreshing = false
                        }
                    } else {
                        when (selectedTab) {
                            0 -> if (hereFromGps || originSelectionMode == "gps") loadHereFromPixelGps() else loadHereByPlace(areaQuery)
                            1 -> loadAwareness()
                            2 -> {
                                loadAskContextForArea(askArea)
                                loadTonight()
                            }
                            3 -> loadShiftLedger()
                        }
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar(
                containerColor = BgCard,
                tonalElevation = 8.dp,
                modifier = Modifier.navigationBarsPadding(),
            ) {
                val tabs = listOf(
                    Triple(0, "Now", "●"),
                    Triple(1, "Nearby", "◎"),
                    Triple(2, "Plan", "▲"),
                    Triple(3, "Shift", "≡"),
                )
                tabs.forEach { (idx, title, glyph) ->
                    NavigationBarItem(
                        selected = !showFeedHealthView && selectedTab == idx,
                        onClick = {
                            showFeedHealthView = false
                            selectedTab = idx
                        },
                        icon = {
                            Text(
                                text = glyph,
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        },
                        label = {
                            Text(
                                text = title,
                                fontSize = 12.sp,
                                maxLines = 1,
                                fontWeight = if (selectedTab == idx) FontWeight.Bold else FontWeight.Medium,
                            )
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = EmeraldCyan,
                            selectedTextColor = EmeraldCyan,
                            indicatorColor = EmeraldDim,
                            unselectedIconColor = TextSecondary,
                            unselectedTextColor = TextSecondary,
                        ),
                    )
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            statusBanner?.let { msg ->
                val isErrorBanner = msg.contains("failed", ignoreCase = true) ||
                    msg.contains("unavailable", ignoreCase = true) ||
                    msg.contains("expired", ignoreCase = true) ||
                    msg.contains("offline", ignoreCase = true)
                Surface(
                    color = if (isErrorBanner) AmberDim else BgCardElevated,
                    border = BorderStroke(1.dp, if (isErrorBanner) AmberGold else BorderSubtle),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 14.dp, vertical = 6.dp),
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = cleanDriverText(msg),
                            color = if (isErrorBanner) AmberGold else EmeraldCyan,
                            fontSize = 13.sp,
                            fontWeight = if (isErrorBanner) FontWeight.SemiBold else FontWeight.Normal,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = "✕",
                            color = TextSecondary,
                            fontSize = 14.sp,
                            modifier = Modifier
                                .padding(start = 8.dp)
                                .clickable { statusBanner = null },
                        )
                    }
                }
            }

            val openMapsQueryOrUrl: (String, String) -> Unit = { mapsUrl, fallbackQuery ->
                val targetUri = if (mapsUrl.isNotBlank()) {
                    Uri.parse(mapsUrl)
                } else {
                    Uri.parse("geo:0,0?q=${Uri.encode(fallbackQuery)}")
                }
                val mapIntent = Intent(Intent.ACTION_VIEW, targetUri).apply {
                    setPackage("com.google.android.apps.maps")
                }
                runCatching { context.startActivity(mapIntent) }
                    .onFailure {
                        context.startActivity(
                            Intent(
                                Intent.ACTION_VIEW,
                                if (mapsUrl.isNotBlank()) Uri.parse(mapsUrl)
                                else Uri.parse("https://www.google.com/maps/search/?api=1&query=${Uri.encode(fallbackQuery)}")
                            )
                        )
                    }
            }

            if (showFeedHealthView) {
                FeedHealthDashboardScreen(
                    health = health,
                    isRefreshing = isRefreshing,
                    initialAdapter = initialFeedAdapter,
                    onClose = { showFeedHealthView = false },
                    onRefreshHealthSummary = {
                        scope.launch { refreshHealthSilent() }
                    },
                    onForceRefreshAll = {
                        scope.launch {
                            isRefreshing = true
                            statusBanner = "Refreshing live feeds…"
                            runCatching { RideEdgeClient.refreshAllFeeds() }
                            refreshHealthSilent()
                            statusBanner = "Live feeds refreshed."
                            isRefreshing = false
                        }
                    },
                )
            } else when (selectedTab) {
                0 -> {
                    val recheckRemainingMin = hereState?.let { h ->
                        val loadedMs = hereLoadedAtMs
                        if (loadedMs != null) {
                            val elapsedMin = ((nowTickMs - loadedMs) / 60_000L).toInt()
                            h.recheckMinutes - elapsedMin
                        } else {
                            h.recheckMinutes
                        }
                    }
                    val waitElapsedMin = activeEpisodeStartedAtMs?.let { started ->
                        ((nowTickMs - started) / 60_000L).toInt().coerceAtLeast(0)
                    }
                    WorkingTabScreen(
                        areaQuery = areaQuery,
                        onAreaQueryChange = { areaQuery = it },
                        originSelectionMode = originSelectionMode,
                        driverMode = driverMode,
                        onDriverModeChange = { newMode ->
                            workingController.setDriverPosture(newMode)
                            syncWorkingControllerState(includeBanner = false)
                            if (hereFromGps || originSelectionMode == "gps") {
                                loadHereFromPixelGps()
                            } else {
                                loadHereByPlace(areaQuery)
                            }
                        },
                        hereState = hereState,
                        hereFromGps = hereFromGps,
                        isRefreshing = isRefreshing,
                        errorBanner = statusBanner,
                        episodeState = activeEpisodeState,
                        waitingElapsedMinutes = waitElapsedMin,
                        activeEpisodeZone = activeEpisodeZone,
                        activeRecommendationId = activeRecommendationId,
                        activeEvidenceVersion = activeEvidenceVersion,
                        outcomeSyncState = outcomeSyncState,
                        outcomePendingStatus = outcomePendingStatus,
                        outcomeFailedZoneLabel = outcomeFailedZoneLabel,
                        outcomeLastError = outcomeLastError,
                        repositionLimitMinutes = askRepositionUnder,
                        onRepositionLimitChange = { newLimit ->
                            workingController.setRepositionLimit(newLimit)
                            askRepositionUnder = newLimit
                            syncWorkingControllerState(includeBanner = false)
                            if (hereFromGps || originSelectionMode == "gps") {
                                loadHereFromPixelGps()
                            } else {
                                loadHereByPlace(areaQuery)
                            }
                        },
                        positioningState = positioningState,
                        positioningTargetLabel = positioningTargetLabel,
                        onConfirmArrivalAtDestination = {
                            val destLabel = workingController.confirmArrivalAtDestination()
                            syncWorkingControllerState(includeBanner = false)
                            if (!destLabel.isNullOrBlank()) {
                                loadHereByPlace(destLabel)
                            }
                        },
                        onMarkPositioningNavigationOpened = {
                            workingController.markPositioningNavigationOpened()
                            syncWorkingControllerState(includeBanner = false)
                        },
                        lastGpsLat = activeFreshGps?.first,
                        lastGpsLon = activeFreshGps?.second,
                        lastGpsAgeSeconds = if (activeFreshGps != null) {
                            lastGpsFixAtMs?.let { ((nowTickMs - it) / 1000L).coerceAtLeast(0L) }
                        } else null,
                        recheckRemainingMinutes = recheckRemainingMin,
                        seatacForecast = seatacForecast,
                        seatacPolling = seatacPolling,
                        onPollSeatacForecast = {
                            scope.launch {
                                seatacPolling = true
                                runCatching { RideEdgeClient.fetchSeatacForecast(pull = true) }
                                    .onSuccess {
                                        seatacForecast = it
                                        statusBanner = "Updated Sea-Tac arrival forecast: ${it.bestHourLabel}"
                                        refreshHealthSilent()
                                    }
                                    .onFailure {
                                        statusBanner = "Airport forecast update failed: ${it.message}"
                                    }
                                seatacPolling = false
                            }
                        },
                        onSearchArea = { loadHereByPlace(it) },
                        onUsePixelGps = {
                            val hasFine = ContextCompat.checkSelfPermission(
                                context,
                                Manifest.permission.ACCESS_FINE_LOCATION
                            ) == PackageManager.PERMISSION_GRANTED
                            if (hasFine) {
                                loadHereFromPixelGps()
                            } else {
                                permissionLauncher.launch(
                                    arrayOf(
                                        Manifest.permission.ACCESS_FINE_LOCATION,
                                        Manifest.permission.ACCESS_COARSE_LOCATION,
                                    )
                                )
                            }
                        },
                        onSaveParkedSpot = { lat, lon, label, zone ->
                            scope.launch {
                                runCatching {
                                    RideEdgeClient.saveCustomParkedSpot(lat, lon, label, zone)
                                }.onSuccess {
                                    statusBanner = "Saved '$label' as an approved staging curb."
                                }.onFailure {
                                    statusBanner = "Save curb failed: ${it.message}"
                                }
                            }
                        },
                        onApproveCurb = { anchorId ->
                            scope.launch {
                                runCatching {
                                    RideEdgeClient.approveAnchor(anchorId)
                                }.onSuccess {
                                    if (hereFromGps || originSelectionMode == "gps") {
                                        loadHereFromPixelGps()
                                    } else {
                                        loadHereByPlace(areaQuery)
                                    }
                                    statusBanner = "Curb approved — 1-tap Navigate unlocked."
                                }.onFailure {
                                    statusBanner = "Approve curb failed: ${it.message}"
                                }
                            }
                        },
                        onLogOutcome = { status, zone, recAction, recId, evVer ->
                            val preSubmitWaitMin = activeEpisodeStartedAtMs?.let {
                                ((System.currentTimeMillis() - it) / 60_000.0).coerceAtLeast(0.0)
                            }
                            val effectiveHere = (hereState ?: HereState(
                                zone = zone,
                                label = zone,
                                matched = zone,
                                note = "",
                                action = recAction,
                                actionPlain = recAction,
                                spoken = "",
                                stayRow = null,
                                bestRow = null,
                                rankedHours = emptyList(),
                                nearby = emptyList(),
                                nearbyStations = emptyList(),
                                warnings = emptyList(),
                            )).copy(
                                zone = zone,
                                recommendationId = recId,
                                evidenceVersion = evVer,
                            )
                            // G03/N04/R5-02: workingController.resolveOutcomeAttribution is invoked inside beginOutcomeSubmission
                            // and replays the immutable failed outcome command on retry even if the area changed.
                            val (attributedRecId, attributedEvVer, idemKey) = workingController.beginOutcomeSubmission(
                                status = status,
                                currentHere = effectiveHere,
                                nowMs = System.currentTimeMillis(),
                            )
                            val submittedZone = workingController.lastSubmittedZone ?: zone
                            val submittedRecAction = workingController.lastSubmittedRecommendedAction ?: recAction
                            val submittedEpisodeId = workingController.lastSubmittedEpisodeId
                                ?: "ep-$attributedRecId-${System.currentTimeMillis()}"
                            val submittedFirstReqMin = workingController.lastSubmittedFirstRequestWaitMinutes
                                ?: preSubmitWaitMin
                            val submittedRecordedAt = workingController.lastSubmittedEventAtIso
                            // R5-03: Freeze the tap-time comparison snapshot before awaiting the network call so a delayed
                            // waiting acknowledgement crossing source expiry cannot replace the tap-time verdict with SOURCE_STALE.
                            if (status == "waiting") {
                                val tapEvalTime = submittedRecordedAt?.let {
                                    runCatching { java.time.Instant.parse(it) }.getOrNull()
                                } ?: java.time.Instant.now()
                                val tapComparison = latestUberImport?.let { imp ->
                                    UberIntelligence.evaluateDecisionComparison(
                                        importRecord = imp,
                                        target = UberIntelligence.buildTargetContextFromHere(
                                            effectiveHere.copy(
                                                zone = submittedZone,
                                                recommendationId = attributedRecId,
                                                evidenceVersion = attributedEvVer,
                                            )
                                        ),
                                        evalTime = tapEvalTime,
                                        seenBeforeEpisodeStart = true,
                                    )
                                } ?: latestNowComparison
                                if (tapComparison != null) {
                                    runCatching {
                                        uberRepository.stageEpisodeStart(
                                            recommendationId = attributedRecId,
                                            episodeId = submittedEpisodeId,
                                            tapComparison = tapComparison,
                                        )
                                    }
                                }
                            }
                            syncWorkingControllerState(includeBanner = false)
                            scope.launch {
                                val backendStatus = if (status == "no_request_after_15m") "no_request" else status
                                runCatching {
                                    RideEdgeClient.logDriverOutcome(
                                        status = backendStatus,
                                        zone = submittedZone,
                                        recommendedAction = submittedRecAction,
                                        recommendationId = attributedRecId,
                                        evidenceVersion = attributedEvVer,
                                        idempotencyKey = idemKey,
                                        recordedAt = submittedRecordedAt,
                                    )
                                }.onSuccess {
                                    workingController.completeOutcomeSubmission(backendStatus)
                                    syncWorkingControllerState(includeBanner = true)
                                    runCatching {
                                        val choice = when {
                                            status == "repositioned" -> "moved"
                                            positioningState == "arrived" && submittedRecAction.equals("MOVE", ignoreCase = true) -> "moved"
                                            status in setOf("waiting", "request_received", "accepted_ride", "no_request", "no_request_after_15m") &&
                                                submittedRecAction.uppercase(Locale.US) in setOf("WAIT", "STAY") -> "stayed"
                                            else -> "unknown"
                                        }
                                        val mappedStatus = when {
                                            status == "request_received" && (submittedFirstReqMin ?: 0.0) <= 15.0 -> "request_within_15m"
                                            status == "request_received" -> "request_after_15m"
                                            status == "accepted_ride" -> "accepted_ride"
                                            status in setOf("no_request", "no_request_after_15m", "observed_15m_no_request", "dry_wait_15m") &&
                                                (submittedFirstReqMin ?: preSubmitWaitMin ?: 0.0) >= 15.0 -> "no_request_after_15m"
                                            status in setOf("no_request", "no_request_after_15m", "observed_15m_no_request", "dry_wait_15m") -> "incomplete_ended_early"
                                            status == "repositioned" -> "repositioned"
                                            status == "break" -> "break"
                                            else -> status
                                        }
                                        uberRepository.linkEpisodeOutcome(
                                            recommendationId = attributedRecId,
                                            episodeId = submittedEpisodeId,
                                            driverChoice = choice,
                                            outcomeStatus = mappedStatus,
                                            waitMinutesToRequest = if (status == "request_received" || status == "accepted_ride") submittedFirstReqMin else null,
                                            acceptedRide = status == "accepted_ride",
                                        )
                                        uberReloadGeneration++
                                    }
                                }.onFailure {
                                    workingController.failOutcomeSubmission(it.message)
                                    syncWorkingControllerState(includeBanner = true)
                                }
                            }
                        },
                        secondOpinionComparison = latestNowComparison,
                        onOpenUberIntel = {
                            planSubTab = 4
                            selectedTab = 2
                        },
                        onSecondOpinionFeedback = { cmpId, useful ->
                            runCatching {
                                uberRepository.recordPerceivedUsefulness(cmpId, useful)
                                uberReloadGeneration++
                            }
                        },
                        onJumpToAsk = { selectedZone ->
                            askArea = formatDriverAreaName(selectedZone)
                            planSubTab = 0
                            selectedTab = 2
                            loadAskContextForArea(selectedZone)
                        },
                        onOpenMaps = openMapsQueryOrUrl,
                    )
                }

                1 -> AroundTabScreen(
                    awareness = awarenessState,
                    hereNearbyWindows = hereState?.nearby.orEmpty(),
                    selectedArea = awarenessArea,
                    scopeMode = awarenessScope,
                    radiusMiles = awarenessRadius,
                    period = awarenessPeriod,
                    selectedLayer = awarenessLayer,
                    onSelectArea = { area ->
                        awarenessArea = area
                        awarenessUseGps = false
                        awarenessScope = "nearby"
                        loadAwareness(
                            scopeOverride = "nearby",
                            areaOverride = area,
                            useGpsOverride = false,
                        )
                    },
                    onUsePixelGps = {
                        awarenessScope = "nearby"
                        val hasFine = ContextCompat.checkSelfPermission(
                            context,
                            Manifest.permission.ACCESS_FINE_LOCATION
                        ) == PackageManager.PERMISSION_GRANTED
                        if (hasFine) {
                            loadHereFromPixelGps()
                        } else {
                            permissionLauncher.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION,
                                )
                            )
                        }
                    },
                    onChangeFilters = { newScope, newRadius, newPeriod, newLayer ->
                        awarenessScope = newScope
                        awarenessRadius = newRadius
                        awarenessPeriod = newPeriod
                        awarenessLayer = newLayer
                        loadAwareness(
                            scopeOverride = newScope,
                            radiusOverride = newRadius,
                            periodOverride = newPeriod,
                            layerOverride = newLayer,
                        )
                    },
                    onPollBestTime = {
                        if (!bestTimePolling) {
                            scope.launch {
                                bestTimePolling = true
                                isRefreshing = true
                                val targetArea = awarenessState?.area?.ifBlank { awarenessArea } ?: awarenessArea
                                val displayLabel = awarenessState?.locationLabel?.ifBlank { awarenessArea } ?: awarenessArea
                                runCatching { RideEdgeClient.pollBestTimeArea(targetArea, forceLive = true) }
                                    .onSuccess { count ->
                                        val freshGps = if (awarenessScope == "nearby" && awarenessUseGps) currentFreshGps() else null
                                        val refreshed = if (freshGps != null) {
                                            runCatching {
                                                RideEdgeClient.fetchAwarenessByGps(
                                                    latitude = freshGps.first,
                                                    longitude = freshGps.second,
                                                    radius = awarenessRadius.toDouble(),
                                                    period = awarenessPeriod,
                                                    layer = awarenessLayer,
                                                )
                                            }.getOrNull()
                                        } else {
                                            runCatching {
                                                RideEdgeClient.fetchAwarenessByArea(
                                                    scope = awarenessScope,
                                                    area = targetArea,
                                                    radius = awarenessRadius.toDouble(),
                                                    period = awarenessPeriod,
                                                    layer = awarenessLayer,
                                                )
                                            }.getOrNull()
                                        }
                                        if (refreshed != null) {
                                            awarenessState = refreshed
                                        }
                                        refreshHealthSilent()
                                        statusBanner = WorkingLocationController.formatVenuePollStatus(
                                            polledCount = count,
                                            refreshedAwareness = refreshed,
                                        ).first
                                    }
                                    .onFailure { statusBanner = "Live venue check failed: ${it.message}" }
                                bestTimePolling = false
                                isRefreshing = false
                            }
                        }
                    },
                    isPollingBestTime = bestTimePolling,
                    onOpenMaps = openMapsQueryOrUrl,
                )

                2 -> PlanTabScreen(
                    planSubTab = planSubTab,
                    onSelectSubTab = { planSubTab = it },
                    initialUberPaste = initialUberPaste,
                    initialUberSection = initialUberSection,
                    uberStoreFileName = storeFileName,
                    initialUberEditDrive = initialUberEditDrive,
                    initialUberEditWait = initialUberEditWait,
                    initialUberClearPasteAfterParse = initialUberClearPasteAfterParse,
                    currentHereState = hereState,
                    hasActiveWaitEpisode = activeEpisodeState != "none",
                    firstStopComparison = latestPlanFirstStopComparison,
                    onComparisonSaved = { uberReloadGeneration++ },
                    onSecondOpinionFeedback = { cmpId, useful ->
                        runCatching {
                            uberRepository.recordPerceivedUsefulness(cmpId, useful)
                            uberReloadGeneration++
                        }
                    },
                    askArea = askArea,
                    askState = askState,
                    shiftCourse = shiftCourseState,
                    courseBlasting = courseBlasting,
                    courseError = courseError,
                    minutesAvailable = askMinutesAvailable,
                    repositionUnder = askRepositionUnder,
                    finishNear = askFinishNear,
                    questionText = askQuestionText,
                    busy = askBusy,
                    tonight = tonightState,
                    seatacForecast = seatacForecast,
                    seatacPolling = seatacPolling,
                    onPollSeatacForecast = {
                        scope.launch {
                            seatacPolling = true
                            runCatching { RideEdgeClient.fetchSeatacForecast(pull = true) }
                                .onSuccess {
                                    seatacForecast = it
                                    statusBanner = "Updated Sea-Tac arrival forecast: ${it.bestHourLabel}"
                                    refreshHealthSilent()
                                }
                                .onFailure {
                                    statusBanner = "Airport forecast update failed: ${it.message}"
                                }
                            seatacPolling = false
                        }
                    },
                    onSelectArea = {
                        askArea = formatDriverAreaName(it)
                        loadAskContextForArea(it)
                        val cReqId = ++courseReqGen
                        scope.launch {
                            runCatching {
                                RideEdgeClient.fetchShiftCourse(
                                    area = it,
                                    latitude = null,
                                    longitude = null,
                                    pullAll = false,
                                    minutesAvailable = askMinutesAvailable,
                                    repositionUnderMinutes = askRepositionUnder,
                                    finishNear = askFinishNear,
                                )
                            }.onSuccess { course ->
                                if (cReqId == courseReqGen) {
                                    shiftCourseState = course
                                    courseError = null
                                }
                            }.onFailure { err ->
                                if (cReqId == courseReqGen) {
                                    courseError = err.message
                                }
                            }
                        }
                    },
                    onBlastCourse = {
                        if (!courseBlasting) {
                            val cReqId = ++courseReqGen
                            scope.launch {
                                courseBlasting = true
                                courseError = null
                                val freshGps = currentFreshGps()
                                runCatching {
                                    RideEdgeClient.fetchShiftCourse(
                                        area = askArea,
                                        latitude = freshGps?.first,
                                        longitude = freshGps?.second,
                                        pullAll = true,
                                        minutesAvailable = askMinutesAvailable,
                                        repositionUnderMinutes = askRepositionUnder,
                                        finishNear = askFinishNear,
                                    )
                                }.onSuccess { course ->
                                    if (cReqId == courseReqGen) {
                                        shiftCourseState = course
                                        askArea = formatDriverAreaName(course.originLabel.ifBlank { askArea })
                                        courseError = null
                                        refreshHealthSilent()
                                        runCatching { RideEdgeClient.fetchSeatacForecast(pull = false) }
                                            .onSuccess { seatacForecast = it }
                                        statusBanner = "✓ Updated shift plan for ${course.originLabel}"
                                    }
                                }.onFailure {
                                    if (cReqId == courseReqGen) {
                                        courseError = it.message ?: "Refresh timed out"
                                        statusBanner = "Plan update failed: ${it.message}"
                                    }
                                }
                                if (cReqId == courseReqGen) {
                                    courseBlasting = false
                                }
                            }
                        }
                    },
                    onUpdateConstraints = { mins, repo, finish ->
                        askMinutesAvailable = mins
                        askRepositionUnder = repo
                        askFinishNear = finish
                        workingController.setPlanDurationMinutes(mins)
                        workingController.setRepositionLimit(repo)
                        syncWorkingControllerState(includeBanner = false)
                        val cReqId = ++courseReqGen
                        val freshGps = currentFreshGps()
                        scope.launch {
                            runCatching {
                                RideEdgeClient.fetchShiftCourse(
                                    area = askArea,
                                    latitude = freshGps?.first,
                                    longitude = freshGps?.second,
                                    pullAll = false,
                                    minutesAvailable = mins,
                                    repositionUnderMinutes = repo,
                                    finishNear = finish,
                                )
                            }.onSuccess { course ->
                                if (cReqId == courseReqGen) {
                                    shiftCourseState = course
                                    courseError = null
                                }
                            }.onFailure { err ->
                                if (cReqId == courseReqGen) {
                                    courseError = err.message
                                }
                            }
                        }
                        val cur = askState ?: return@PlanTabScreen
                        scope.launch {
                            askBusy = true
                            runCatching {
                                RideEdgeClient.updateAskConstraints(
                                    snapshotId = cur.snapshotId,
                                    origin = cur.origin,
                                    mode = cur.mode,
                                    minutesAvailable = mins,
                                    repositionUnderMinutes = repo,
                                    finishNear = finish,
                                )
                            }.onSuccess { askState = it }
                                .onFailure { statusBanner = it.message }
                            askBusy = false
                        }
                    },
                    onQuestionTextChange = { askQuestionText = it },
                    onAskQwen = { question, fresh ->
                        val cur = askState ?: return@PlanTabScreen
                        scope.launch {
                            askBusy = true
                            runCatching {
                                RideEdgeClient.askQwen(
                                    current = cur,
                                    question = question,
                                    minutesAvailable = askMinutesAvailable,
                                    repositionUnderMinutes = askRepositionUnder,
                                    finishNear = askFinishNear,
                                    fresh = fresh,
                                )
                            }.onSuccess {
                                askState = it
                            }.onFailure {
                                statusBanner = it.message
                            }
                            askBusy = false
                        }
                    },
                    onRefreshTonight = { loadTonight() },
                    onApproveCurb = { anchorId ->
                        scope.launch {
                            runCatching { RideEdgeClient.approveAnchor(anchorId) }
                                .onSuccess {
                                    statusBanner = "Approved staging curb."
                                    loadTonight()
                                }
                                .onFailure { statusBanner = it.message }
                        }
                    },
                    onOpenGoogleMaps = { lat, lon, label ->
                        val uri = if (lat != null && lon != null) {
                            Uri.parse("google.navigation:q=$lat,$lon")
                        } else {
                            Uri.parse("geo:0,0?q=${Uri.encode(label)}")
                        }
                        val mapIntent = Intent(Intent.ACTION_VIEW, uri).apply {
                            setPackage("com.google.android.apps.maps")
                        }
                        runCatching { context.startActivity(mapIntent) }
                            .onFailure {
                                context.startActivity(
                                    Intent(
                                        Intent.ACTION_VIEW,
                                        Uri.parse("https://www.google.com/maps/search/?api=1&query=${Uri.encode(label)}")
                                    )
                                )
                            }
                    },
                    onSendToVolvo = { oppId ->
                        scope.launch {
                            runCatching { RideEdgeClient.sendToVolvo(oppId) }
                                .onSuccess { statusBanner = "Queued destination in vehicle navigation." }
                                .onFailure { statusBanner = it.message }
                        }
                    },
                    onSpeakAnswer = { speakOut(it) },
                    onOpenMaps = openMapsQueryOrUrl,
                )

                3 -> ShiftTabScreen(
                    shiftState = shiftState,
                    odometerInput = odometerInput,
                    odometerNote = odometerNote,
                    onOdometerInputChange = { odometerInput = it },
                    onOdometerNoteChange = { odometerNote = it },
                    onStartShift = {
                        val miles = odometerInput.toDoubleOrNull()
                        if (miles == null || miles <= 0.0) {
                            statusBanner = "Enter a valid starting odometer reading."
                            return@ShiftTabScreen
                        }
                        scope.launch {
                            runCatching { RideEdgeClient.startOdometerShift(miles, odometerNote) }
                                .onSuccess {
                                    statusBanner = "Shift started at $miles mi."
                                    odometerInput = ""
                                    loadShiftLedger()
                                }
                                .onFailure { statusBanner = it.message }
                        }
                    },
                    onEndShift = {
                        val miles = odometerInput.toDoubleOrNull()
                        if (miles == null || miles <= 0.0) {
                            statusBanner = "Enter a valid ending odometer reading."
                            return@ShiftTabScreen
                        }
                        scope.launch {
                            runCatching { RideEdgeClient.endOdometerShift(miles, odometerNote) }
                                .onSuccess {
                                    statusBanner = "Shift closed at $miles mi; session calibrated."
                                    odometerInput = ""
                                    loadShiftLedger()
                                }
                                .onFailure { statusBanner = it.message }
                        }
                    },
                    onLogTrip = { fare, miles, note ->
                        scope.launch {
                            runCatching { RideEdgeClient.logShiftTrip(fare, miles, note) }
                                .onSuccess {
                                    statusBanner = "Logged $$fare ride ($miles mi) to active shift."
                                    loadShiftLedger()
                                }
                                .onFailure { statusBanner = it.message }
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun CockpitHeader(
    health: HealthState?,
    showFeedHealthView: Boolean,
    isRefreshing: Boolean,
    hasGpsLock: Boolean,
    onToggleFeedHealth: () -> Unit,
    onUseGps: () -> Unit,
    onSpeak: () -> Unit,
    onRefresh: () -> Unit,
) {
    val snapAge = health?.snapshotAgeMinutes
    val isSummaryStale = (snapAge != null && snapAge > 30.0) || (health?.degradedCount ?: 0) > 0
    val stoplightColor = when {
        health?.overallStoplight == "red" -> CoralRed
        health?.overallStoplight == "amber" || isSummaryStale -> AmberGold
        else -> EmeraldCyan
    }
    val apiSourcesLabel = when {
        health == null -> "API sources · Checking…"
        health.snapshotState in setOf("error", "missing") -> "API sources · Status unavailable ›"
        snapAge != null && snapAge > 30.0 ->
            "API sources · ${health.healthyCount}/${health.enabledCount} healthy · Summary out of date (${snapAge.toInt()}m old) ›"
        health.degradedCount > 0 ->
            "API sources · ${health.healthyCount}/${health.enabledCount} healthy · ${health.degradedCount} degraded ›"
        else -> "API sources · ${health.healthyCount}/${health.enabledCount} healthy ›"
    }
    val a11yDescription = if (health != null) {
        if (snapAge != null && snapAge > 30.0) {
            "API sources: ${health.healthyCount} of ${health.enabledCount} healthy, summary out of date (${snapAge.toInt()} minutes old)"
        } else {
            "API sources: ${health.healthyCount} of ${health.enabledCount} healthy"
        }
    } else {
        "API sources: checking status"
    }

    Surface(
        color = BgCard,
        border = BorderStroke(1.dp, BorderSubtle),
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .weight(1f, fill = false)
                    .semantics { contentDescription = a11yDescription }
                    .clickable { onToggleFeedHealth() },
            ) {
                Box(
                    modifier = Modifier
                        .size(32.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(BgCardElevated),
                    contentAlignment = Alignment.Center,
                ) {
                    Image(
                        painter = painterResource(id = R.drawable.ic_rideedge_sedan),
                        contentDescription = "RideEdge",
                        modifier = Modifier.size(28.dp),
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "RideEdge",
                            color = TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 15.sp,
                            maxLines = 1,
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Box(
                            modifier = Modifier
                                .size(7.dp)
                                .clip(CircleShape)
                                .background(if (health != null) stoplightColor else AmberGold)
                        )
                    }
                    Surface(
                        color = if (showFeedHealthView) EmeraldDim else BgCardElevated,
                        border = BorderStroke(1.dp, if (showFeedHealthView) EmeraldCyan else stoplightColor.copy(alpha = 0.55f)),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.padding(top = 2.dp),
                    ) {
                        Text(
                            text = if (showFeedHealthView) "Viewing $apiSourcesLabel" else "● $apiSourcesLabel",
                            color = if (health != null) stoplightColor else AmberGold,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.ExtraBold,
                            maxLines = 1,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                        )
                    }
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Surface(
                    color = BgCardElevated,
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.clickable { onSpeak() },
                ) {
                    Text(
                        text = "🔊 Listen",
                        color = TextPrimary,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp),
                    )
                }
                Surface(
                    color = BgCardElevated,
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.clickable(enabled = !isRefreshing) { onRefresh() },
                ) {
                    Box(
                        modifier = Modifier
                            .size(width = 34.dp, height = 30.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (isRefreshing) {
                            CircularProgressIndicator(
                                color = EmeraldCyan,
                                strokeWidth = 2.dp,
                                modifier = Modifier.size(15.dp),
                            )
                        } else {
                            Text(
                                text = "↻",
                                color = TextPrimary,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FeedHealthDashboardScreen(
    health: HealthState?,
    isRefreshing: Boolean,
    initialAdapter: String? = null,
    onClose: () -> Unit,
    onRefreshHealthSummary: () -> Unit = {},
    onForceRefreshAll: () -> Unit,
) {
    val context = LocalContext.current
    var selectedFeedAdapter by rememberSaveable { mutableStateOf<String?>(initialAdapter) }
    var feedDetailState by remember { mutableStateOf<FeedDetailState?>(null) }
    var feedDetailLoading by remember { mutableStateOf(false) }
    var feedDetailError by remember { mutableStateOf<String?>(null) }
    var tmFilter by rememberSaveable { mutableStateOf("mapped") }
    var showQueries by rememberSaveable { mutableStateOf(false) }
    var showSnapshotDiagnostics by rememberSaveable { mutableStateOf(false) }

    val selectedAdapter = selectedFeedAdapter
    if (selectedAdapter != null) {
        var transitionNotice by remember(selectedAdapter) { mutableStateOf<String?>(null) }
        var transitionDiagnostic by remember(selectedAdapter) { mutableStateOf<String?>(null) }
        LaunchedEffect(selectedAdapter, health?.snapshotId, isRefreshing) {
            val cur = feedDetailState
            if (!isRefreshing && cur != null && cur.adapter == selectedAdapter &&
                !health?.snapshotId.isNullOrBlank() && cur.snapshotId == health?.snapshotId
            ) {
                return@LaunchedEffect
            }
            feedDetailLoading = true
            feedDetailError = null
            runCatching { RideEdgeClient.fetchFeedDetail(selectedAdapter, health?.snapshotId) }
                .onSuccess {
                    val mergedNotice = it.snapshotTransitionNotice ?: transitionNotice
                    val mergedDiag = it.snapshotTransitionDiagnostic ?: transitionDiagnostic
                    if (it.snapshotTransitionNotice != null) {
                        transitionNotice = it.snapshotTransitionNotice
                    }
                    if (it.snapshotTransitionDiagnostic != null) {
                        transitionDiagnostic = it.snapshotTransitionDiagnostic
                    }
                    feedDetailState = if (mergedNotice != null && it.snapshotTransitionNotice == null) {
                        it.copy(
                            snapshotTransitionNotice = mergedNotice,
                            snapshotTransitionDiagnostic = mergedDiag,
                        )
                    } else {
                        it
                    }
                    if (it.snapshotTransitionNotice != null) {
                        onRefreshHealthSummary()
                    }
                }
                .onFailure { feedDetailError = it.message ?: "Failed to load source details" }
            feedDetailLoading = false
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                val detHeader = feedDetailState
                val headerAgeMins = detHeader?.ageMinutes
                val headerIsStale = headerAgeMins != null && headerAgeMins > 30.0
                val headerIsHealthy = detHeader != null && detHeader.stoplight != "red" &&
                    detHeader.mode != "error" && detHeader.mode != "needs_key"
                val headerAccent = when {
                    detHeader == null -> RadarBlue
                    !headerIsHealthy -> CoralRed
                    headerIsStale -> AmberGold
                    else -> EmeraldCyan
                }
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, headerAccent),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = feedDetailState?.label ?: selectedAdapter,
                                    color = TextPrimary,
                                    fontSize = 18.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                )
                                val ageBadge = detHeader?.ageMinutes?.let { "Updated ${it.toInt()}m ago" } ?: "Checking age…"
                                val statusWord = when {
                                    detHeader == null -> "Loading…"
                                    !headerIsHealthy -> "Degraded"
                                    headerIsStale -> "Healthy · Summary out of date"
                                    else -> "Healthy"
                                }
                                Text(
                                    text = "$statusWord · $ageBadge",
                                    color = headerAccent,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Surface(
                                    color = BgCardElevated,
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.clickable(enabled = !isRefreshing) { onForceRefreshAll() },
                                ) {
                                    Text(
                                        text = if (isRefreshing) "…" else "↻ Refresh",
                                        color = EmeraldCyan,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                    )
                                }
                                Surface(
                                    color = BgCardElevated,
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.clickable { selectedFeedAdapter = null },
                                ) {
                                    Text(
                                        text = "← Sources",
                                        color = TextPrimary,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                    )
                                }
                            }
                        }

                        if (feedDetailLoading) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text("Loading source records…", color = RadarBlue, fontSize = 12.sp)
                        }
                        feedDetailError?.let { err ->
                            Spacer(modifier = Modifier.height(8.dp))
                            Text("Error loading detail: $err", color = CoralRed, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }
                        feedDetailState?.let { det ->
                            det.snapshotTransitionNotice?.let { notice ->
                                Spacer(modifier = Modifier.height(8.dp))
                                Surface(
                                    color = BgCardElevated,
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                text = notice,
                                                color = EmeraldCyan,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.SemiBold,
                                            )
                                            if (!det.snapshotTransitionDiagnostic.isNullOrBlank()) {
                                                Text(
                                                    text = if (showSnapshotDiagnostics) "Hide diagnostics ▴" else "Diagnostics ▾",
                                                    color = RadarBlue,
                                                    fontSize = 11.sp,
                                                    fontWeight = FontWeight.Bold,
                                                    modifier = Modifier.clickable {
                                                        showSnapshotDiagnostics = !showSnapshotDiagnostics
                                                    },
                                                )
                                            }
                                        }
                                        if (showSnapshotDiagnostics && !det.snapshotTransitionDiagnostic.isNullOrBlank()) {
                                            Spacer(modifier = Modifier.height(4.dp))
                                            Text(
                                                text = det.snapshotTransitionDiagnostic,
                                                color = TextSecondary,
                                                fontSize = 11.sp,
                                            )
                                        }
                                    }
                                }
                            }
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = det.plainSummary.ifBlank { det.summary },
                                color = TextPrimary,
                                fontSize = 13.sp,
                            )
                        }
                    }
                }
            }

            val det = feedDetailState
            if (det != null) {
                if (det.detailState == "details_not_saved") {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = AmberDim),
                            border = BorderStroke(1.dp, AmberGold),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(12.dp)) {
                                Text(
                                    text = "Details weren't saved for this check",
                                    color = AmberGold,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = det.statusMessage.ifBlank {
                                        "Summary counts exist for this check, but individual records were not stored."
                                    },
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Button(
                                    onClick = onForceRefreshAll,
                                    enabled = !isRefreshing,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = AmberGold,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(8.dp),
                                ) {
                                    Text(
                                        text = if (isRefreshing) "Refreshing…" else "↻ Refresh sources",
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 12.sp,
                                    )
                                }
                            }
                        }
                    }
                } else if (det.adapter == "ticketmaster_events") {
                    item {
                        Column(modifier = Modifier.fillMaxWidth()) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                listOf(
                                    "mapped" to "Relevant (${det.mappedSignalsCount})",
                                    "all" to "All (${det.ticketmasterEvents.size})",
                                    "excluded" to "Excluded (${det.excludedEventsCount})",
                                ).forEach { (key, label) ->
                                    FilterChip(
                                        selected = tmFilter == key,
                                        onClick = { tmFilter = key },
                                        label = { Text(label, fontSize = 12.sp) },
                                        colors = FilterChipDefaults.filterChipColors(
                                            selectedContainerColor = EmeraldDim,
                                            selectedLabelColor = EmeraldCyan,
                                            containerColor = BgCard,
                                            labelColor = TextSecondary,
                                        ),
                                    )
                                }
                            }
                            if (det.queries.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = if (showQueries) "Hide API queries ▴" else "Show API queries (${det.queries.size}) ▾",
                                    color = RadarBlue,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable { showQueries = !showQueries },
                                )
                                if (showQueries) {
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Card(
                                        colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                                        border = BorderStroke(1.dp, BorderSubtle),
                                        shape = RoundedCornerShape(10.dp),
                                        modifier = Modifier.fillMaxWidth(),
                                    ) {
                                        Column(modifier = Modifier.padding(10.dp)) {
                                            det.queries.forEach { q ->
                                                Text(
                                                    text = "• \"${q.label}\": fetched ${q.fetchedCount}/${q.totalElements ?: q.fetchedCount} (${q.mode})" +
                                                        if (q.truncated) " · ⚠️ truncated" else "",
                                                    color = if (q.truncated) AmberGold else TextSecondary,
                                                    fontSize = 11.sp,
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    val filteredTm = when (tmFilter) {
                        "mapped" -> det.ticketmasterEvents.filter {
                            it.mappingStatus == "mapped_signal" || it.mappingStatus == "mapped_departure_signal"
                        }
                        "excluded" -> det.ticketmasterEvents.filter {
                            it.mappingStatus != "mapped_signal" && it.mappingStatus != "mapped_departure_signal"
                        }
                        else -> det.ticketmasterEvents
                    }
                    items(filteredTm, key = { it.eventId.ifBlank { it.title + it.localDate + it.localTime } }) { ev ->
                        val isMapped = ev.mappingStatus == "mapped_signal" || ev.mappingStatus == "mapped_departure_signal"
                        val plainBadge = if (isMapped) {
                            "Ticketmaster events"
                        } else {
                            when (ev.exclusionReason?.lowercase(Locale.US)) {
                                "covered_by_sports_feed", "sports_duplicate" -> "Covered by sports feed"
                                "future_date", "outside_tonight_window", "not_today" -> "Tomorrow's event"
                                "missing_venue_or_zone", "unmapped_zone" -> "Unmapped venue"
                                else -> (ev.exclusionReason ?: "Outside tonight's window").replace('_', ' ')
                                    .replaceFirstChar { it.uppercase() }
                            }
                        }
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(
                                1.dp,
                                if (isMapped) EmeraldCyan.copy(alpha = 0.7f) else BorderSubtle
                            ),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(12.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = ev.title,
                                        color = TextPrimary,
                                        fontSize = 14.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                        modifier = Modifier.weight(1f),
                                    )
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Surface(
                                        color = if (isMapped) EmeraldDim else AmberDim,
                                        shape = RoundedCornerShape(6.dp),
                                    ) {
                                        Text(
                                            text = plainBadge,
                                            color = if (isMapped) EmeraldCyan else AmberGold,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.height(4.dp))
                                val areaText = ev.zoneLabel.ifBlank { ev.zone?.let { formatDriverAreaName(it) } ?: ev.city }
                                Text(
                                    text = "${ev.venue.ifBlank { "Venue" }} · $areaText",
                                    color = TextSecondary,
                                    fontSize = 12.sp,
                                )
                                Text(
                                    text = "Start: ${ev.localDate} ${ev.localTime.ifBlank { "time N/A" }}",
                                    color = TextSecondary,
                                    fontSize = 11.sp,
                                )
                                if (isMapped) {
                                    val depStart = ev.estimatedDepartureStart?.take(16)?.replace('T', ' ') ?: "N/A"
                                    val depEnd = ev.estimatedDepartureEnd?.take(16)?.replace('T', ' ') ?: "N/A"
                                    Text(
                                        text = "Est. exit window: $depStart → $depEnd",
                                        color = EmeraldCyan,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                } else if (ev.mappingExplanation.isNotBlank()) {
                                    Text(
                                        text = cleanDriverText(ev.mappingExplanation),
                                        color = AmberGold,
                                        fontSize = 11.sp,
                                    )
                                }
                                if (ev.url.isNotBlank()) {
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = "Open Ticketmaster listing ↗",
                                        color = RadarBlue,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.clickable {
                                            runCatching {
                                                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(ev.url)))
                                            }
                                        },
                                    )
                                }
                            }
                        }
                    }
                } else {
                    if (det.records.isEmpty()) {
                        item {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = BgCard),
                                border = BorderStroke(1.dp, BorderSubtle),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(modifier = Modifier.padding(14.dp)) {
                                    Text(
                                        text = "0 active records in this window",
                                        color = TextPrimary,
                                        fontSize = 14.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = "This source responded normally (${det.detailState.replace('_', ' ')}), so it counts as healthy even though there are currently 0 active departures or alerts in the window.",
                                        color = TextSecondary,
                                        fontSize = 12.sp,
                                    )
                                }
                            }
                        }
                    } else {
                        items(det.records, key = { it.id }) { rec ->
                            val isLive = rec.basis.contains("live", ignoreCase = true) || rec.recordType.contains("hotspot", ignoreCase = true)
                            Card(
                                colors = CardDefaults.cardColors(containerColor = BgCard),
                                border = BorderStroke(1.dp, if (isLive) EmeraldCyan.copy(alpha = 0.6f) else BorderSubtle),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = rec.title,
                                            color = TextPrimary,
                                            fontSize = 14.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.weight(1f),
                                        )
                                        if (rec.basis.isNotBlank()) {
                                            val isExpired = rec.basis.contains("expired", ignoreCase = true)
                                            val badgeText = when (rec.basis.lowercase(Locale.US)) {
                                                "expired_telemetry" -> "EXPIRED · NOT REBASED"
                                                else -> rec.basis.replace('_', ' ').uppercase(Locale.US)
                                            }
                                            Spacer(modifier = Modifier.width(6.dp))
                                            Surface(
                                                color = when {
                                                    isExpired -> AmberDim
                                                    isLive -> EmeraldDim
                                                    else -> RadarDim
                                                },
                                                shape = RoundedCornerShape(6.dp),
                                            ) {
                                                Text(
                                                    text = badgeText,
                                                    color = when {
                                                        isExpired -> AmberGold
                                                        isLive -> EmeraldCyan
                                                        else -> RadarBlue
                                                    },
                                                    fontSize = 9.sp,
                                                    fontWeight = FontWeight.ExtraBold,
                                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                                                )
                                            }
                                        }
                                    }
                                    if (rec.subtitle.isNotBlank() || rec.zoneLabel.isNotBlank()) {
                                        Text(
                                            text = listOfNotNull(
                                                rec.subtitle.takeIf { it.isNotBlank() },
                                                rec.zoneLabel.takeIf { it.isNotBlank() }?.let { "Zone: $it" },
                                            ).joinToString(" · "),
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                    if (rec.timeLabel.isNotBlank()) {
                                        Text(
                                            text = "Time/Window: ${rec.timeLabel}",
                                            color = EmeraldCyan,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.SemiBold,
                                        )
                                    }
                                    if (rec.detail.isNotBlank()) {
                                        Text(
                                            text = rec.detail,
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                        )
                                    }
                                    rec.alertText?.takeIf { it.isNotBlank() }?.let { alert ->
                                        Text(
                                            text = "⚠️ $alert",
                                            color = AmberGold,
                                            fontSize = 11.sp,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return
    }

    val feeds = health?.feeds ?: emptyList()
    val enabledFeeds = remember(feeds) { feeds.filter { it.enabled } }
    val disabledFeeds = remember(feeds) { feeds.filter { !it.enabled } }
    val groupedEnabled = remember(enabledFeeds) {
        enabledFeeds.groupBy { it.category }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCard),
                border = BorderStroke(1.dp, BorderSubtle),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "SERVICE & DATA FEEDS",
                                color = EmeraldCyan,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.ExtraBold,
                                letterSpacing = 1.sp,
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            Text(
                                text = "API Sources · ${health?.healthyCount ?: 0}/${health?.enabledCount ?: 0} Healthy (${health?.totalCount ?: 0} Catalog)",
                                color = TextPrimary,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Surface(
                            color = BgCardElevated,
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.clickable { onClose() },
                        ) {
                            Text(
                                text = "← Back",
                                color = TextSecondary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        StoplightSummaryBadge(
                            modifier = Modifier.weight(1f),
                            dotColor = EmeraldCyan,
                            bgColor = EmeraldDim,
                            count = health?.healthyCount ?: 0,
                            label = "Healthy",
                        )
                        StoplightSummaryBadge(
                            modifier = Modifier.weight(1f),
                            dotColor = CoralRed,
                            bgColor = Color(0xFF3A1418),
                            count = health?.degradedCount ?: 0,
                            label = "Degraded",
                        )
                        StoplightSummaryBadge(
                            modifier = Modifier.weight(1f),
                            dotColor = AmberGold,
                            bgColor = AmberDim,
                            count = health?.disabledCount ?: 0,
                            label = "Disabled",
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = health?.serviceHealthNote?.ifBlank {
                            "Source health means the feed is reachable and fresh; 0 active signals can still be healthy. Tap any row to inspect retained records."
                        } ?: "Source health means the feed is reachable and fresh; 0 active signals can still be healthy. Tap any row to inspect retained records.",
                        color = TextSecondary,
                        fontSize = 11.sp,
                        lineHeight = 15.sp,
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    Button(
                        onClick = onForceRefreshAll,
                        enabled = !isRefreshing,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = EmeraldCyan,
                            contentColor = Color(0xFF041410),
                        ),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            text = if (isRefreshing) "Refreshing Data Sources…" else "↻ Refresh All Data Sources",
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 13.sp,
                        )
                    }
                }
            }
        }

        groupedEnabled.forEach { (category, categoryFeeds) ->
            item {
                Text(
                    text = "${category.uppercase(Locale.US)} (TAP ROW TO INSPECT RECORDS)",
                    color = RadarBlue,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.ExtraBold,
                    letterSpacing = 0.9.sp,
                    modifier = Modifier.padding(top = 4.dp, start = 4.dp),
                )
            }
            items(categoryFeeds, key = { it.adapter }) { feed ->
                val dotColor = when {
                    !feed.healthy || feed.stoplight == "red" -> CoralRed
                    feed.stoplight == "amber" -> AmberGold
                    else -> EmeraldCyan
                }
                val haloColor = when {
                    !feed.healthy || feed.stoplight == "red" -> Color(0x44FF6B6B)
                    feed.stoplight == "amber" -> Color(0x44FFB84D)
                    else -> Color(0x4400E5B0)
                }
                val modeBadge = when (feed.mode) {
                    "live" -> "LIVE"
                    "cache" -> "CACHED"
                    "static" -> "READY"
                    "on_demand" -> "ON-DEMAND"
                    "stale_cache" -> "STALE CACHE"
                    "needs_key" -> "DISABLED"
                    "error" -> "DEGRADED"
                    else -> feed.mode.uppercase(Locale.US)
                }
                val ageText = feed.ageMinutes?.let { mins ->
                    if (mins < 1.0) "just now" else "${mins.toInt()}m ago"
                }

                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(
                        1.dp,
                        if (!feed.healthy || feed.stoplight == "red") CoralRed else BorderSubtle
                    ),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { selectedFeedAdapter = feed.adapter },
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .size(22.dp)
                                .clip(CircleShape)
                                .background(haloColor),
                            contentAlignment = Alignment.Center,
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(11.dp)
                                    .clip(CircleShape)
                                    .background(dotColor)
                            )
                        }

                        Spacer(modifier = Modifier.width(12.dp))

                        Column(modifier = Modifier.weight(1f)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = feed.label,
                                    color = TextPrimary,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.weight(1f),
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Surface(
                                    color = BgCardElevated,
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(6.dp),
                                ) {
                                    Text(
                                        text = if (ageText != null) "$modeBadge · $ageText" else modeBadge,
                                        color = dotColor,
                                        fontSize = 10.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                                    )
                                }
                            }
                            val summaryLine = feed.plainSummary.ifBlank { feed.detail }
                            if (summaryLine.isNotBlank()) {
                                Spacer(modifier = Modifier.height(3.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = summaryLine,
                                        color = TextSecondary,
                                        fontSize = 12.sp,
                                        modifier = Modifier.weight(1f),
                                    )
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text(
                                        text = "Inspect ›",
                                        color = RadarBlue,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        if (disabledFeeds.isNotEmpty()) {
            item {
                Text(
                    text = "DISABLED / UNCONFIGURED SOURCES (${disabledFeeds.size} EXCLUDED FROM HEALTH DENOMINATOR)",
                    color = AmberGold,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.ExtraBold,
                    letterSpacing = 0.8.sp,
                    modifier = Modifier.padding(top = 6.dp, start = 4.dp),
                )
            }
            items(disabledFeeds, key = { "disabled-${it.adapter}" }) { feed ->
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { selectedFeedAdapter = feed.adapter },
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 9.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = feed.label,
                                color = TextSecondary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = feed.plainSummary.ifBlank { feed.detail },
                                color = TextMuted,
                                fontSize = 11.sp,
                            )
                        }
                        Surface(
                            color = AmberDim,
                            shape = RoundedCornerShape(6.dp),
                        ) {
                            Text(
                                text = "DISABLED",
                                color = AmberGold,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.ExtraBold,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StoplightSummaryBadge(
    modifier: Modifier = Modifier,
    dotColor: Color,
    bgColor: Color,
    count: Int,
    label: String,
) {
    Surface(
        color = bgColor,
        border = BorderStroke(1.dp, dotColor.copy(alpha = 0.45f)),
        shape = RoundedCornerShape(10.dp),
        modifier = modifier,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .clip(CircleShape)
                    .background(dotColor)
            )
            Spacer(modifier = Modifier.width(7.dp))
            Column {
                Text(
                    text = "$count",
                    color = TextPrimary,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.ExtraBold,
                )
                Text(
                    text = label,
                    color = TextSecondary,
                    fontSize = 10.sp,
                )
            }
        }
    }
}

@Composable
private fun SeatacForecastCard(
    forecast: SeatacForecastState?,
    isPolling: Boolean,
    onPollForecast: () -> Unit,
    onOpenMaps: (String, String) -> Unit,
) {
    val hours = forecast?.hours ?: emptyList()
    val maxPlanes = (hours.maxOfOrNull { it.estimatedPlanes } ?: 30).coerceAtLeast(10)
    var showSampleFlights by rememberSaveable { mutableStateOf(false) }

    Card(
        colors = CardDefaults.cardColors(containerColor = BgCard),
        border = BorderStroke(1.5.dp, RadarBlue),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "✈ SEA-TAC 6-HOUR ARRIVAL FORECAST",
                        color = RadarBlue,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.ExtraBold,
                        letterSpacing = 0.8.sp,
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = forecast?.bestHourLabel?.ifBlank { "Tap below to load arrival volume" }
                            ?: "Tap below to load arrival volume",
                        color = TextPrimary,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                }
                Surface(
                    color = BgCardElevated,
                    border = BorderStroke(1.dp, RadarBlue),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.clickable {
                        onOpenMaps(
                            "https://www.google.com/maps/dir/?api=1&destination=47.4395,-122.2995",
                            "Sea-Tac Rideshare Holding Lot"
                        )
                    },
                ) {
                    Text(
                        text = "🗺 View Holding Lot",
                        color = RadarBlue,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Surface(
                color = AmberDim,
                border = BorderStroke(1.dp, AmberGold.copy(alpha = 0.55f)),
                shape = RoundedCornerShape(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = "Queue wait: Unknown · Forecast arrivals do not measure airport holding-lot queue length or wait time.",
                    color = AmberGold,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                )
            }

            if (hours.isNotEmpty()) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    hours.forEach { bucket ->
                        val barColor = if (bucket.isPeak) EmeraldCyan else RadarBlue
                        val bgBarColor = if (bucket.isPeak) EmeraldDim else BgCardElevated
                        val fraction = (bucket.estimatedPlanes.toFloat() / maxPlanes.toFloat()).coerceIn(0.08f, 1f)

                        Surface(
                            color = bgBarColor,
                            border = BorderStroke(1.dp, if (bucket.isPeak) EmeraldCyan else BorderSubtle),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(10.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text(
                                            text = bucket.hourLabel,
                                            color = TextPrimary,
                                            fontSize = 13.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        if (bucket.isPeak) {
                                            Spacer(modifier = Modifier.width(6.dp))
                                            Surface(
                                                color = EmeraldCyan,
                                                shape = RoundedCornerShape(4.dp),
                                            ) {
                                                Text(
                                                    text = "MOST FORECAST ARRIVALS",
                                                    color = Color(0xFF041410),
                                                    fontSize = 9.sp,
                                                    fontWeight = FontWeight.ExtraBold,
                                                    modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp),
                                                )
                                            }
                                        }
                                    }
                                    Text(
                                        text = "~${bucket.estimatedPlanes} planes" +
                                            if (bucket.longHaulCount > 0) " (${bucket.longHaulCount} long-haul)" else "",
                                        color = barColor,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                }

                                Spacer(modifier = Modifier.height(6.dp))
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(7.dp)
                                        .clip(RoundedCornerShape(4.dp))
                                        .background(BgDeep)
                                ) {
                                    Box(
                                        modifier = Modifier
                                            .fillMaxWidth(fraction)
                                            .height(7.dp)
                                            .clip(RoundedCornerShape(4.dp))
                                            .background(barColor)
                                    )
                                }

                                if (showSampleFlights && bucket.sampleFlights.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(5.dp))
                                    Text(
                                        text = "Sample inbound: ${bucket.sampleFlights.joinToString(", ")}",
                                        color = TextSecondary,
                                        fontSize = 11.sp,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                            }
                        }
                    }
                }
                if (hours.any { it.sampleFlights.isNotEmpty() }) {
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = if (showSampleFlights) "Hide sample flight numbers ▴" else "Show sample flight numbers ▾",
                        color = RadarBlue,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier
                            .padding(start = 4.dp)
                            .clickable { showSampleFlights = !showSampleFlights },
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            Button(
                onClick = onPollForecast,
                enabled = !isPolling,
                colors = ButtonDefaults.buttonColors(
                    containerColor = RadarBlue,
                    contentColor = Color(0xFF041410),
                ),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = if (isPolling) {
                        "Updating 6-Hour Sea-Tac Arrival Forecast…"
                    } else if (hours.isEmpty()) {
                        "✈ Load 6-Hour Sea-Tac Arrival Forecast"
                    } else {
                        "↻ Refresh Sea-Tac Arrival Forecast"
                    },
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 13.sp,
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun WorkingTabScreen(
    areaQuery: String,
    onAreaQueryChange: (String) -> Unit,
    originSelectionMode: String = "manual",
    driverMode: String = "active_working",
    onDriverModeChange: (String) -> Unit = {},
    hereState: HereState?,
    hereFromGps: Boolean = false,
    isRefreshing: Boolean = false,
    errorBanner: String? = null,
    episodeState: String = "none",
    waitingElapsedMinutes: Int? = null,
    activeEpisodeZone: String? = null,
    activeRecommendationId: String? = null,
    activeEvidenceVersion: String = "v2",
    outcomeSyncState: String = "idle",
    outcomePendingStatus: String? = null,
    outcomeFailedZoneLabel: String? = null,
    outcomeLastError: String? = null,
    repositionLimitMinutes: Int = 20,
    onRepositionLimitChange: (Int) -> Unit = {},
    positioningState: String = "none",
    positioningTargetLabel: String? = null,
    onConfirmArrivalAtDestination: () -> Unit = {},
    onMarkPositioningNavigationOpened: () -> Unit = {},
    lastGpsLat: Double?,
    lastGpsLon: Double?,
    lastGpsAgeSeconds: Long? = null,
    recheckRemainingMinutes: Int? = null,
    seatacForecast: SeatacForecastState?,
    seatacPolling: Boolean,
    onPollSeatacForecast: () -> Unit,
    onSearchArea: (String) -> Unit,
    onUsePixelGps: () -> Unit,
    onSaveParkedSpot: (Double, Double, String, String) -> Unit,
    onApproveCurb: (String) -> Unit = {},
    onLogOutcome: (String, String, String, String, String) -> Unit = { _, _, _, _, _ -> },
    secondOpinionComparison: UberIntelligence.DecisionComparisonRecord? = null,
    onOpenUberIntel: () -> Unit = {},
    onSecondOpinionFeedback: (String, Boolean) -> Unit = { _, _ -> },
    onJumpToAsk: (String) -> Unit,
    onOpenMaps: (String, String) -> Unit,
) {
    var showAreaSelector by rememberSaveable { mutableStateOf(false) }
    var showSettingsEditor by rememberSaveable { mutableStateOf(false) }
    var showWhyDetails by rememberSaveable { mutableStateOf(false) }
    var showAlternativeReview by rememberSaveable { mutableStateOf(false) }
    var showEndWaitReasons by rememberSaveable { mutableStateOf(false) }
    var showWiderAreaWindows by rememberSaveable { mutableStateOf(false) }
    var waitTrackerExpanded by rememberSaveable { mutableStateOf(false) }
    val isSeaTac = hereState?.zone == "sea_airport" ||
        areaQuery.contains("seatac", ignoreCase = true) ||
        areaQuery.contains("airport", ignoreCase = true)
    val voiceLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { res ->
        if (res.resultCode == Activity.RESULT_OK) {
            val spoken = res.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spoken.isNullOrBlank()) {
                onAreaQueryChange(spoken)
                onSearchArea(spoken)
                showAreaSelector = false
            }
        }
    }

    val isGpsSelected = hereFromGps || originSelectionMode == "gps"
    val isHomeOrigin = hereState?.originPlaceId?.equals("home", ignoreCase = true) == true ||
        hereState?.originPlaceId?.equals("example_public_origin", ignoreCase = true) == true ||
        (!isGpsSelected && areaQuery.trim().equals("home", ignoreCase = true))
    val hasLiveGps = hereFromGps && lastGpsLat != null && lastGpsLon != null && lastGpsAgeSeconds != null
    val currentAreaDisplay = when {
        isHomeOrigin -> "Selected starting area"
        positioningState == "arrived" && !positioningTargetLabel.isNullOrBlank() -> positioningTargetLabel
        hereState != null -> formatDriverAreaName(hereState.label.ifBlank { hereState.zone.ifBlank { areaQuery } })
        isGpsSelected -> "Phone GPS"
        else -> formatDriverAreaName(areaQuery)
    }
    val locationModeSuffix = when {
        hasLiveGps -> "GPS (${lastGpsAgeSeconds}s ago)"
        isGpsSelected -> "GPS (waiting)"
        positioningState == "arrived" -> "Arrived"
        else -> "Manual"
    }
    val modeLabelDisplay = when (driverMode) {
        "wait_at_home" -> "Wait at home"
        "break" -> "Break"
        "offline" -> "Offline"
        else -> "Working"
    }
    val failedActionName = when (outcomePendingStatus) {
        "request_received" -> "Ride request"
        "accepted_ride" -> "Accepted ride"
        "no_request_after_15m", "no_request" -> "End wait"
        "repositioned" -> "Move outcome"
        "break" -> "Break outcome"
        else -> "Wait start"
    }
    val failedAreaDisplay = formatDriverAreaName(
        outcomeFailedZoneLabel?.ifBlank { null }
            ?: activeEpisodeZone?.ifBlank { null }
            ?: hereState?.zone?.ifBlank { null }
            ?: areaQuery
    )

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // 1. Compact Location + Settings Bar (Section 2: 2 compact lines with Change + Edit)
        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCard),
                border = BorderStroke(1.dp, BorderSubtle),
                shape = RoundedCornerShape(14.dp),
            ) {
                Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "$currentAreaDisplay · $locationModeSuffix",
                            color = TextPrimary,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.ExtraBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            color = BgCardElevated,
                            border = BorderStroke(1.dp, if (showAreaSelector) EmeraldCyan else BorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.clickable {
                                showAreaSelector = !showAreaSelector
                                if (showAreaSelector) showSettingsEditor = false
                            },
                        ) {
                            Text(
                                text = if (showAreaSelector) "Done" else "Change",
                                color = if (showAreaSelector) EmeraldCyan else TextPrimary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(6.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "$modeLabelDisplay · Max drive $repositionLimitMinutes min",
                            color = TextSecondary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            color = BgCardElevated,
                            border = BorderStroke(1.dp, if (showSettingsEditor) RadarBlue else BorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.clickable {
                                showSettingsEditor = !showSettingsEditor
                                if (showSettingsEditor) showAreaSelector = false
                            },
                        ) {
                            Text(
                                text = if (showSettingsEditor) "Done" else "Edit",
                                color = if (showSettingsEditor) RadarBlue else TextSecondary,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            )
                        }
                    }

                    if (showSettingsEditor) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = BorderSubtle.copy(alpha = 0.6f))
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("Driver mode", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(4.dp))
                        FlowRow(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(
                                "active_working" to "Working",
                                "wait_at_home" to "Wait at home",
                                "break" to "Break",
                                "offline" to "Offline",
                            ).forEach { (modeKey, modeLabel) ->
                                val selected = driverMode == modeKey
                                Surface(
                                    color = if (selected) EmeraldDim else BgCardElevated,
                                    border = BorderStroke(1.dp, if (selected) EmeraldCyan else BorderSubtle),
                                    shape = RoundedCornerShape(6.dp),
                                    modifier = Modifier.clickable {
                                        onDriverModeChange(modeKey)
                                        showSettingsEditor = false
                                    },
                                ) {
                                    Text(
                                        text = modeLabel,
                                        color = if (selected) EmeraldCyan else TextSecondary,
                                        fontSize = 12.sp,
                                        fontWeight = if (selected) FontWeight.ExtraBold else FontWeight.Medium,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                    )
                                }
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("Max drive", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            listOf(10, 15, 20).forEach { mins ->
                                val selected = repositionLimitMinutes == mins
                                Surface(
                                    color = if (selected) RadarDim else BgCardElevated,
                                    border = BorderStroke(1.dp, if (selected) RadarBlue else BorderSubtle),
                                    shape = RoundedCornerShape(6.dp),
                                    modifier = Modifier.clickable {
                                        onRepositionLimitChange(mins)
                                        showSettingsEditor = false
                                    },
                                ) {
                                    Text(
                                        text = "$mins min",
                                        color = if (selected) RadarBlue else TextSecondary,
                                        fontSize = 12.sp,
                                        fontWeight = if (selected) FontWeight.ExtraBold else FontWeight.Medium,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                    )
                                }
                            }
                        }
                    }

                    if (showAreaSelector) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = BorderSubtle.copy(alpha = 0.6f))
                        Spacer(modifier = Modifier.height(8.dp))

                        Button(
                            onClick = {
                                showAreaSelector = false
                                onUsePixelGps()
                            },
                            colors = ButtonDefaults.buttonColors(
                                containerColor = EmeraldCyan,
                                contentColor = Color(0xFF041410),
                            ),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = "Use GPS",
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 13.sp,
                            )
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedTextField(
                            value = areaQuery,
                            onValueChange = onAreaQueryChange,
                            placeholder = { Text("Area or address…", color = TextMuted, fontSize = 13.sp) },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                            keyboardActions = KeyboardActions(onSearch = {
                                showAreaSelector = false
                                onSearchArea(areaQuery)
                            }),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = EmeraldCyan,
                                unfocusedBorderColor = BorderSubtle,
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                            ),
                            trailingIcon = {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                    modifier = Modifier.padding(end = 10.dp),
                                ) {
                                    Text(
                                        text = "🎤",
                                        fontSize = 14.sp,
                                        modifier = Modifier.clickable {
                                            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                                                putExtra(
                                                    RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                                                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
                                                )
                                                putExtra(RecognizerIntent.EXTRA_PROMPT, "Say area or intersection…")
                                            }
                                            runCatching { voiceLauncher.launch(intent) }
                                        },
                                    )
                                    Text(
                                        text = "Apply",
                                        color = EmeraldCyan,
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 13.sp,
                                        modifier = Modifier.clickable {
                                            showAreaSelector = false
                                            onSearchArea(areaQuery)
                                        },
                                    )
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                        )

                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            (listOf("Home") + QUICK_AREAS).forEach { area ->
                                val selected = if (area == "Home") {
                                    isHomeOrigin
                                } else {
                                    hereState?.zone?.equals(area, ignoreCase = true) == true ||
                                        areaQuery.equals(area, ignoreCase = true)
                                }
                                FilterChip(
                                    selected = selected,
                                    onClick = {
                                        val q = if (area == "Home") "home" else area
                                        onAreaQueryChange(q)
                                        showAreaSelector = false
                                        onSearchArea(q)
                                    },
                                    label = { Text(area, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = EmeraldDim,
                                        selectedLabelColor = EmeraldCyan,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }
                    }
                }
            }
        }

        // 2. Guidance Paused / Loading State when hereState is null (UI-03, R4-01, R4-05)
        if (hereState == null) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                    border = BorderStroke(1.5.dp, if (isRefreshing) EmeraldCyan else AmberGold),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = if (isRefreshing) "Updating guidance…" else "Guidance paused",
                            color = if (isRefreshing) EmeraldCyan else AmberGold,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.ExtraBold,
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = if (isRefreshing) {
                                "Checking demand and routes for $currentAreaDisplay…"
                            } else {
                                cleanDriverText(
                                    errorBanner
                                        ?: if (isGpsSelected) {
                                            "Fresh GPS location required before showing stay/move advice."
                                        } else {
                                            "Fresh location or service update required before showing stay/move advice."
                                        }
                                )
                            },
                            color = TextPrimary,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Bold,
                            lineHeight = 21.sp,
                        )
                        if (!isRefreshing) {
                            Spacer(modifier = Modifier.height(10.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Button(
                                    onClick = {
                                        if (isGpsSelected) onUsePixelGps() else onSearchArea(areaQuery)
                                    },
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = EmeraldCyan,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(
                                        text = if (isGpsSelected) "Refresh GPS" else "Try again",
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                }
                                OutlinedButton(
                                    onClick = { showAreaSelector = true },
                                    border = BorderStroke(1.dp, EmeraldCyan),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("Change location", color = EmeraldCyan, fontWeight = FontWeight.Bold)
                                }
                            }
                        }
                        if (episodeState in setOf("waiting", "pinged") || outcomeSyncState == "failed") {
                            Spacer(modifier = Modifier.height(10.dp))
                            val fallbackZone = activeEpisodeZone?.ifBlank { areaQuery } ?: areaQuery
                            val fallbackRecId = activeRecommendationId.orEmpty()
                            Surface(
                                color = BgCard,
                                border = BorderStroke(1.dp, if (outcomeSyncState == "failed") CoralRed else BorderSubtle),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    if (outcomeSyncState == "failed") {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                text = "$failedActionName at $failedAreaDisplay not saved",
                                                color = CoralRed,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Bold,
                                                modifier = Modifier.weight(1f),
                                            )
                                            Spacer(modifier = Modifier.width(8.dp))
                                            Surface(
                                                color = CoralDim,
                                                border = BorderStroke(1.dp, CoralRed),
                                                shape = RoundedCornerShape(6.dp),
                                                modifier = Modifier.clickable {
                                                    val retryStatus = outcomePendingStatus ?: "waiting"
                                                    onLogOutcome(
                                                        retryStatus,
                                                        fallbackZone,
                                                        "WAIT",
                                                        fallbackRecId,
                                                        activeEvidenceVersion,
                                                    )
                                                },
                                            ) {
                                                Text(
                                                    text = "Retry",
                                                    color = CoralRed,
                                                    fontSize = 12.sp,
                                                    fontWeight = FontWeight.ExtraBold,
                                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                                                )
                                            }
                                        }
                                    } else {
                                        Text(
                                            text = "Waiting in ${formatDriverAreaName(fallbackZone)} · ${waitingElapsedMinutes ?: 0} min",
                                            color = TextPrimary,
                                            fontSize = 13.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. Single Decision Card Above the Fold (Section 2: 1 decision, 1 reason, 1 cost/time line, 1 recheck line, 1 action row)
        hereState?.let { here ->
            item {
                val best = here.bestRow ?: here.rankedHours.firstOrNull()
                val bestZoneTitle = formatDriverAreaName(best?.zone ?: "")
                val currentZoneTitle = formatDriverAreaName(here.label.ifBlank { here.zone })

                val resolvedDecision = WorkingLocationController.resolveHereDecision(
                    here = here,
                    repositionLimitMinutes = repositionLimitMinutes,
                )
                val decisionColor = when (resolvedDecision.stateCode) {
                    "MOVE" -> RadarBlue
                    "WAIT" -> EmeraldCyan
                    else -> AmberGold
                }
                val isPositioningMove = here.recommendationBasis.equals("positioning_heuristic", ignoreCase = true) &&
                    here.destinationLabel.isNotBlank() &&
                    positioningState != "arrived"
                val isPositionedAtHub = here.recommendationBasis.equals("positioned_pickup_center", ignoreCase = true) ||
                    (positioningState == "arrived" && !positioningTargetLabel.isNullOrBlank() &&
                        !here.decisionState.equals("MOVE", ignoreCase = true) &&
                        !here.originKind.startsWith("residential", ignoreCase = true) &&
                        !here.originPlaceId.equals("home", ignoreCase = true))

                val decisionHeadline = when {
                    isPositioningMove -> "Position near ${here.destinationLabel}"
                    isPositionedAtHub -> {
                        val hubName = here.destinationLabel.ifBlank { positioningTargetLabel ?: currentZoneTitle }
                        "Hold at $hubName · demand unverified"
                    }
                    resolvedDecision.stateCode == "MOVE" && best != null -> "Move to $bestZoneTitle"
                    resolvedDecision.stateCode == "CHECK_AIRPORT" -> resolvedDecision.headline
                    isHomeOrigin && driverMode == "wait_at_home" -> "Hold at Home"
                    resolvedDecision.stateCode == "WATCH" -> "Hold in $currentZoneTitle · insufficient evidence"
                    else -> "Stay in $currentZoneTitle"
                }

                val decisionReason = when {
                    isPositioningMove ->
                        "Starting from a residential area with live rider demand unverified. Position near this commercial pickup center instead of waiting in a neighborhood."
                    isPositionedAtHub ->
                        "Positioned at a commercial pickup center. Current rider demand is unverified; hold here for up to ${here.recheckMinutes} minutes before repositioning."
                    isHomeOrigin && driverMode == "wait_at_home" ->
                        "Wait-at-home mode is active and no verified nearby surge beats holding at home right now."
                    else -> {
                        val rawWhy = cleanDriverText(resolvedDecision.whyText)
                            .replace(Regex("""[Ww]ait here for up to \d+ minutes,? then reassess\.?"""), "")
                            .replace(Regex("""[Hh]old here for up to \d+ minutes,? then reassess\.?"""), "")
                            .trim()
                        rawWhy.ifBlank {
                            when (resolvedDecision.stateCode) {
                                "MOVE" -> "Stronger demand expected in $bestZoneTitle within your drive limit."
                                "WATCH" -> "Insufficient live or historical evidence in $currentZoneTitle right now to confirm staying or moving."
                                else -> "Local evidence supports staying in $currentZoneTitle rather than driving empty miles."
                            }
                        }
                    }
                }

                val showDriveLine = isPositioningMove || (resolvedDecision.stateCode == "MOVE" && best != null)
                val driveLineText = if (showDriveLine) {
                    val emptyDriveMin = best?.repositionMinutes?.toInt() ?: 0
                    val emptyDriveMiles = best?.repositionMiles ?: 0.0
                    val emptyCostEst = emptyDriveMiles * 0.45 + (if (here.crossesLake) here.sr520TollDollars else 0.0)
                    buildList {
                        if (emptyDriveMin > 0) add("$emptyDriveMin min")
                        if (emptyDriveMiles > 0.0) add("${String.format(Locale.US, "%.1f", emptyDriveMiles)} mi")
                        if (emptyDriveMiles > 0.0) add("~$${String.format(Locale.US, "%.2f", emptyCostEst)} drive cost")
                    }.joinToString(" · ")
                } else ""

                val remMin = recheckRemainingMinutes ?: here.recheckMinutes
                val isOverdue = remMin <= 0
                // RECHECK NOW (OVERDUE) state
                val recheckLineText = if (isOverdue) {
                    "Recheck now (overdue)"
                } else {
                    "Recheck in ${remMin.coerceAtLeast(1)} min"
                }

                val canNavigateCurb = here.stagingApproved && here.navigationAvailable

                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                    border = BorderStroke(1.5.dp, if (isOverdue) CoralRed else decisionColor.copy(alpha = 0.7f)),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        // Block 1: Action + Place
                        Text(
                            text = decisionHeadline,
                            color = TextPrimary,
                            fontSize = 22.sp,
                            lineHeight = 27.sp,
                            fontWeight = FontWeight.ExtraBold,
                        )

                        Spacer(modifier = Modifier.height(4.dp))

                        // Block 2: One short reason
                        Text(
                            text = decisionReason,
                            color = TextSecondary,
                            fontSize = 13.sp,
                            lineHeight = 18.sp,
                            maxLines = 3,
                            overflow = TextOverflow.Ellipsis,
                        )

                        // Block 3: Cost / time line (only when moving/driving)
                        if (driveLineText.isNotBlank()) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = driveLineText,
                                color = RadarBlue,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }

                        // Block 4: Recheck line
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = recheckLineText,
                            color = if (isOverdue) CoralRed else EmeraldCyan,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                        )

                        // Action button row when moving/positioning
                        if (isPositioningMove) {
                            Spacer(modifier = Modifier.height(10.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                OutlinedButton(
                                    onClick = {
                                        onMarkPositioningNavigationOpened()
                                        onOpenMaps(
                                            if (canNavigateCurb) here.bestRow?.mapsUrl.orEmpty() else "",
                                            "${here.destinationLabel}, WA",
                                        )
                                    },
                                    border = BorderStroke(1.dp, RadarBlue),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(
                                        text = if (canNavigateCurb) "Navigate" else "View area",
                                        color = RadarBlue,
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                                Button(
                                    onClick = onConfirmArrivalAtDestination,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = EmeraldCyan,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(
                                        text = "I'm here",
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                }
                            }
                            if (!canNavigateCurb) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = "Pickup spot not verified",
                                        color = TextMuted,
                                        fontSize = 11.sp,
                                    )
                                    Surface(
                                        color = EmeraldDim,
                                        border = BorderStroke(1.dp, EmeraldCyan),
                                        shape = RoundedCornerShape(6.dp),
                                        modifier = Modifier.clickable {
                                            val targetId = here.destinationId.ifBlank { best?.zone ?: here.zone }
                                            onApproveCurb(targetId)
                                        },
                                    ) {
                                        Text(
                                            text = "✓ Approve curb",
                                            color = EmeraldCyan,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                        )
                                    }
                                }
                            }
                        } else if (resolvedDecision.stateCode == "MOVE" && best != null) {
                            Spacer(modifier = Modifier.height(10.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Button(
                                    onClick = {
                                        onOpenMaps(
                                            if (canNavigateCurb) best.mapsUrl else "",
                                            "$bestZoneTitle, WA",
                                        )
                                    },
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = RadarBlue,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(
                                        text = if (canNavigateCurb) "Navigate" else "View area",
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                }
                                OutlinedButton(
                                    onClick = { onJumpToAsk(here.zone.ifBlank { here.label }) },
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(
                                        text = "Compare in Plan",
                                        color = TextSecondary,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                            }
                            if (!canNavigateCurb) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = "Pickup spot not verified",
                                        color = TextMuted,
                                        fontSize = 11.sp,
                                    )
                                    Surface(
                                        color = EmeraldDim,
                                        border = BorderStroke(1.dp, EmeraldCyan),
                                        shape = RoundedCornerShape(6.dp),
                                        modifier = Modifier.clickable {
                                            val targetId = here.destinationId.ifBlank { best.zone.ifBlank { here.zone } }
                                            onApproveCurb(targetId)
                                        },
                                    ) {
                                        Text(
                                            text = "✓ Approve curb",
                                            color = EmeraldCyan,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 3b. Compact Uber Second Opinion Row — directly under Decision Card and ABOVE Wait Tracking (Section 2)
            if (secondOpinionComparison != null && UberIntelligence.UBER_ASSISTANT_COMPARISON_DISPLAY_ENABLED) {
                item {
                    CompactSecondOpinionBanner(
                        comparison = secondOpinionComparison,
                        onOpenIntelTab = onOpenUberIntel,
                        onFeedbackUseful = { useful ->
                            onSecondOpinionFeedback(secondOpinionComparison.id, useful)
                        },
                    )
                }
            }

            // 3c. Wait Tracking Card — collapsed until a wait starts or expanded/failed (Section 2)
            item {
                val isWaitActive = episodeState in setOf("waiting", "pinged")
                val isFailed = outcomeSyncState == "failed"
                val shouldShowExpanded = isWaitActive || isFailed || waitTrackerExpanded
                val episodeAreaDisplay = formatDriverAreaName(
                    activeEpisodeZone?.ifBlank { null } ?: here.label.ifBlank { here.zone }
                )

                Surface(
                    color = BgCard,
                    border = BorderStroke(
                        1.dp,
                        when {
                            isFailed -> CoralRed
                            isWaitActive -> EmeraldCyan.copy(alpha = 0.7f)
                            else -> BorderSubtle
                        }
                    ),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (!shouldShowExpanded) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 14.dp, vertical = 9.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "Track a wait (optional)",
                                color = TextSecondary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier
                                    .weight(1f)
                                    .clickable { waitTrackerExpanded = true },
                            )
                            Surface(
                                color = EmeraldDim,
                                border = BorderStroke(1.dp, EmeraldCyan),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.clickable(enabled = outcomeSyncState != "pending") {
                                    onLogOutcome(
                                        "waiting",
                                        here.zone,
                                        here.action.ifBlank { "WAIT" },
                                        activeRecommendationId ?: here.recommendationId,
                                        activeEvidenceVersion,
                                    )
                                },
                            ) {
                                Text(
                                    text = "Start wait",
                                    color = EmeraldCyan,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                                )
                            }
                        }
                    } else {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = when (episodeState) {
                                        "waiting" -> "Waiting in $episodeAreaDisplay · ${waitingElapsedMinutes ?: 0} min"
                                        "pinged" -> "Request in $episodeAreaDisplay · ${waitingElapsedMinutes ?: 0} min"
                                        else -> "Track a wait in $episodeAreaDisplay"
                                    },
                                    color = TextPrimary,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.weight(1f),
                                )
                                when (outcomeSyncState) {
                                    "pending" -> Text(
                                        text = "Saving…",
                                        color = AmberGold,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    "saved" -> Text(
                                        text = "Saved",
                                        color = EmeraldCyan,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    else -> if (!isWaitActive && !isFailed) {
                                        Text(
                                            text = "Hide ▴",
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.SemiBold,
                                            modifier = Modifier.clickable { waitTrackerExpanded = false },
                                        )
                                    }
                                }
                            }

                            if (isFailed) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Surface(
                                    color = CoralDim,
                                    border = BorderStroke(1.dp, CoralRed),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 10.dp, vertical = 7.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = "$failedActionName at $failedAreaDisplay not saved",
                                            color = CoralRed,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.weight(1f),
                                        )
                                        Spacer(modifier = Modifier.width(8.dp))
                                        Surface(
                                            color = BgCard,
                                            border = BorderStroke(1.dp, CoralRed),
                                            shape = RoundedCornerShape(6.dp),
                                            modifier = Modifier.clickable {
                                                val retryStatus = outcomePendingStatus ?: "waiting"
                                                onLogOutcome(
                                                    retryStatus,
                                                    here.zone,
                                                    here.action,
                                                    here.recommendationId,
                                                    here.evidenceVersion,
                                                )
                                            },
                                        ) {
                                            Text(
                                                text = "Retry",
                                                color = CoralRed,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.ExtraBold,
                                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                                            )
                                        }
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(8.dp))

                            if (episodeState == "none") {
                                Button(
                                    onClick = {
                                        showEndWaitReasons = false
                                        onLogOutcome(
                                            "waiting",
                                            here.zone,
                                            here.action,
                                            here.recommendationId,
                                            here.evidenceVersion,
                                        )
                                    },
                                    enabled = outcomeSyncState != "pending",
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = EmeraldCyan,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text(
                                        text = "Start wait",
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 13.sp,
                                    )
                                }
                            } else {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    if (episodeState == "waiting") {
                                        Button(
                                            onClick = {
                                                showEndWaitReasons = false
                                                onLogOutcome(
                                                    "request_received",
                                                    here.zone,
                                                    here.action,
                                                    here.recommendationId,
                                                    here.evidenceVersion,
                                                )
                                            },
                                            enabled = outcomeSyncState != "pending",
                                            colors = ButtonDefaults.buttonColors(
                                                containerColor = EmeraldCyan,
                                                contentColor = Color(0xFF041410),
                                            ),
                                            shape = RoundedCornerShape(8.dp),
                                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
                                            modifier = Modifier.weight(1f),
                                        ) {
                                            Text(
                                                text = "Got a request",
                                                fontWeight = FontWeight.ExtraBold,
                                                fontSize = 12.sp,
                                                maxLines = 1,
                                            )
                                        }
                                    }
                                    OutlinedButton(
                                        onClick = {
                                            showEndWaitReasons = false
                                            onLogOutcome(
                                                "accepted_ride",
                                                here.zone,
                                                here.action,
                                                here.recommendationId,
                                                here.evidenceVersion,
                                            )
                                        },
                                        enabled = outcomeSyncState != "pending",
                                        border = BorderStroke(1.dp, EmeraldCyan),
                                        shape = RoundedCornerShape(8.dp),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        Text(
                                            text = "Accepted a ride",
                                            color = EmeraldCyan,
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 12.sp,
                                            maxLines = 1,
                                        )
                                    }
                                    OutlinedButton(
                                        onClick = { showEndWaitReasons = !showEndWaitReasons },
                                        enabled = outcomeSyncState != "pending",
                                        border = BorderStroke(1.dp, BorderSubtle),
                                        shape = RoundedCornerShape(8.dp),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
                                    ) {
                                        Text(
                                            text = "End wait",
                                            color = TextSecondary,
                                            fontWeight = FontWeight.SemiBold,
                                            fontSize = 12.sp,
                                            maxLines = 1,
                                        )
                                    }
                                }

                                if (showEndWaitReasons) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    val canLogDry15 = (waitingElapsedMinutes ?: 0) >= 15
                                    val endReasons = buildList {
                                        if (canLogDry15) {
                                            add("15m+ dry wait" to "no_request_after_15m")
                                        }
                                        add("Ended early (<15m)" to "no_request")
                                        add("Move to another area" to "repositioned")
                                        add("Take a break" to "break")
                                    }
                                    FlowRow(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        verticalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        endReasons.forEach { (reasonLabel, outcomeCode) ->
                                            Surface(
                                                color = BgCardElevated,
                                                border = BorderStroke(1.dp, BorderSubtle),
                                                shape = RoundedCornerShape(8.dp),
                                                modifier = Modifier.clickable {
                                                    showEndWaitReasons = false
                                                    waitTrackerExpanded = false
                                                    onLogOutcome(
                                                        outcomeCode,
                                                        here.zone,
                                                        here.action,
                                                        here.recommendationId,
                                                        here.evidenceVersion,
                                                    )
                                                },
                                            ) {
                                                Text(
                                                    text = reasonLabel,
                                                    color = TextSecondary,
                                                    fontSize = 11.sp,
                                                    fontWeight = FontWeight.SemiBold,
                                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 3d. Below the fold: Expandable "Why this?" card (Section 2)
            item {
                val stay = here.stayRow
                val best = here.bestRow ?: here.rankedHours.firstOrNull()
                val bestIsDifferent = best != null && !best.zone.equals(here.zone, ignoreCase = true)
                val bestZoneTitle = formatDriverAreaName(best?.zone ?: "")
                val currentZoneTitle = formatDriverAreaName(here.label.ifBlank { here.zone })
                val nextTrainStation = here.nearbyStations
                    .filter { it.nextEtaMinutes != null }
                    .minByOrNull { it.nextEtaMinutes ?: 999 }
                val resolvedDecision = WorkingLocationController.resolveHereDecision(
                    here = here,
                    repositionLimitMinutes = repositionLimitMinutes,
                )
                val evidenceSub = cleanDriverText(resolvedDecision.remoteContextNote ?: here.stayOrMoveReason)

                Surface(
                    color = BgCard,
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { showWhyDetails = !showWhyDetails },
                ) {
                    Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "Why this?",
                                color = TextSecondary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                text = if (showWhyDetails) "Hide ▴" else "Details ›",
                                color = RadarBlue,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }

                        if (showWhyDetails) {
                            Spacer(modifier = Modifier.height(8.dp))
                            HorizontalDivider(color = BorderSubtle.copy(alpha = 0.6f))
                            Spacer(modifier = Modifier.height(8.dp))

                            if (evidenceSub.isNotBlank()) {
                                Text(
                                    text = "• $evidenceSub",
                                    color = TextPrimary,
                                    fontSize = 12.sp,
                                    lineHeight = 17.sp,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                            }
                            if (here.costNote.isNotBlank()) {
                                Text(
                                    text = "• ${cleanDriverText(here.costNote)}",
                                    color = if (here.crossesLake) AmberGold else TextSecondary,
                                    fontSize = 12.sp,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                            }
                            nextTrainStation?.let { st ->
                                Text(
                                    text = "• Nearest train station: ${st.name} (${String.format(Locale.US, "%.1f", st.distanceMiles)} mi) · next train in ~${st.nextEtaMinutes}m",
                                    color = TextSecondary,
                                    fontSize = 12.sp,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                            }
                            Text(
                                text = if (stay != null && stay.sampleTrips > 0) {
                                    "• Historical paid-trip rate in $currentZoneTitle: ~$${String.format(Locale.US, "%.0f", stay.netPerHour)}/hr (${stay.sampleTrips} trips; excludes unpaid wait and empty miles)"
                                } else {
                                    "• Historical paid-trip rate in $currentZoneTitle: No sample for this window"
                                },
                                color = TextSecondary,
                                fontSize = 12.sp,
                            )
                            if (best != null && bestIsDifferent && best.sampleTrips > 0) {
                                Spacer(modifier = Modifier.height(3.dp))
                                Text(
                                    text = "• Historical paid-trip rate in $bestZoneTitle: ~$${String.format(Locale.US, "%.0f", best.netPerHour)}/hr (${best.sampleTrips} trips)",
                                    color = TextSecondary,
                                    fontSize = 12.sp,
                                )
                            }
                            if (lastGpsLat != null && lastGpsLon != null) {
                                Spacer(modifier = Modifier.height(8.dp))
                                OutlinedButton(
                                    onClick = {
                                        onSaveParkedSpot(
                                            lastGpsLat,
                                            lastGpsLon,
                                            "$currentZoneTitle Parked Spot",
                                            here.zone
                                        )
                                    },
                                    border = BorderStroke(1.dp, RadarBlue),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text("Save current GPS spot as pickup spot", color = RadarBlue, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
            }

            // 4. Single Compact "Alternative / Backup Option · [Area]" Row (UI-02)
            val best = here.bestRow ?: here.rankedHours.firstOrNull()
            val isMoveDecision = here.decisionState.ifBlank { here.action }.equals("MOVE", ignoreCase = true)
            val primaryTargetZone = if (isMoveDecision && best != null) best.zone else here.zone
            val altCandidate = if (isMoveDecision && best != null) {
                val runnerUps = here.rankedHours.filter { row ->
                    !row.zone.equals(here.zone, ignoreCase = true) &&
                        !row.zone.equals(best.zone, ignoreCase = true) &&
                        row.score > 0.0
                }
                runnerUps.firstOrNull { it.repositionMinutes <= repositionLimitMinutes } ?: runnerUps.firstOrNull()
            } else {
                best?.takeIf { !it.zone.equals(here.zone, ignoreCase = true) }
            }
            if (altCandidate != null && !altCandidate.zone.equals(primaryTargetZone, ignoreCase = true)) {
                item {
                    val altTitle = formatDriverAreaName(altCandidate.zone)
                    val headerPrefix = if (isMoveDecision) "BACKUP OPTION" else "ALTERNATIVE"
                    val moveCostEst = altCandidate.repositionMiles * 0.45 + (if (here.crossesLake) here.sr520TollDollars else 0.0)
                    Card(
                        colors = CardDefaults.cardColors(containerColor = BgCard),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(14.dp),
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "$headerPrefix · ${altTitle.uppercase()}",
                                        color = TextSecondary,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                        letterSpacing = 0.7.sp,
                                    )
                                    Spacer(modifier = Modifier.height(2.dp))
                                    Text(
                                        text = "~${String.format(Locale.US, "%.0f", altCandidate.repositionMinutes)} min · ${String.format(Locale.US, "%.1f", altCandidate.repositionMiles)} mi · est. $${String.format(Locale.US, "%.2f", moveCostEst)} reposition cost",
                                        color = TextPrimary,
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                                Surface(
                                    color = BgCardElevated,
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.clickable { showAlternativeReview = !showAlternativeReview },
                                ) {
                                    Text(
                                        text = if (showAlternativeReview) "Close ▴" else "Review ▾",
                                        color = RadarBlue,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                    )
                                }
                            }

                            if (showAlternativeReview) {
                                Spacer(modifier = Modifier.height(10.dp))
                                HorizontalDivider(color = BorderSubtle.copy(alpha = 0.6f))
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = if (altCandidate.sampleTrips > 0) {
                                        "Historical archive: ~$${String.format(Locale.US, "%.0f", altCandidate.netPerHour)}/hr paid-trip (${altCandidate.sampleTrips} trips, ${altCandidate.grain}). Empty drive time and wait time at destination are not guaranteed."
                                    } else {
                                        "Historical earnings unknown for this window."
                                    },
                                    color = TextSecondary,
                                    fontSize = 12.sp,
                                    lineHeight = 18.sp,
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    OutlinedButton(
                                        onClick = { onJumpToAsk(here.zone.ifBlank { here.label }) },
                                        border = BorderStroke(1.dp, EmeraldCyan),
                                        shape = RoundedCornerShape(8.dp),
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        Text("Compare in Plan", color = EmeraldCyan, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                    }
                                    OutlinedButton(
                                        onClick = {
                                            onOpenMaps(altCandidate.mapsUrl, "$altTitle, WA")
                                        },
                                        border = BorderStroke(1.dp, BorderSubtle),
                                        shape = RoundedCornerShape(8.dp),
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        Text("View Area Map", color = TextSecondary, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 5. Sea-Tac Forecast only shown on Now tab if driver selected Sea-Tac Airport (UI-06)
            if (isSeaTac) {
                item {
                    SeatacForecastCard(
                        forecast = seatacForecast,
                        isPolling = seatacPolling,
                        onPollForecast = onPollSeatacForecast,
                        onOpenMaps = onOpenMaps,
                    )
                }
            }

            // 6. Nearby Places to Check (N07: plain driver language + drive-limit filtering)
            val allPositiveWindows = here.nearby.filter {
                it.score > 0.0 && !it.action.equals("AVOID", ignoreCase = true)
            }
            val inRangeWindows = allPositiveWindows.filter {
                it.isSameZone || (it.minutesAway != null && it.minutesAway <= repositionLimitMinutes.toDouble())
            }.take(3)
            val widerAreaWindows = allPositiveWindows.filter {
                !it.isSameZone && (it.minutesAway == null || it.minutesAway > repositionLimitMinutes.toDouble())
            }.take(3)
            val displayedWindows = if (showWiderAreaWindows) {
                (inRangeWindows + widerAreaWindows).distinctBy { it.id }
            } else {
                inRangeWindows
            }

            if (displayedWindows.isNotEmpty() || widerAreaWindows.isNotEmpty()) {
                item {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 2.dp, start = 4.dp, end = 4.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "NEARBY PLACES TO CHECK",
                            color = TextSecondary,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.8.sp,
                        )
                        if (widerAreaWindows.isNotEmpty()) {
                            Text(
                                text = if (showWiderAreaWindows) {
                                    "Hide wider-area options ▴"
                                } else {
                                    "Show wider-area options (${widerAreaWindows.size}) ▾"
                                },
                                color = RadarBlue,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.clickable { showWiderAreaWindows = !showWiderAreaWindows },
                            )
                        }
                    }
                }
                if (displayedWindows.isEmpty() && widerAreaWindows.isNotEmpty()) {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(12.dp),
                        ) {
                            Column(modifier = Modifier.padding(13.dp)) {
                                Text(
                                    text = "No places within your ${repositionLimitMinutes}-minute drive limit right now.",
                                    color = TextSecondary,
                                    fontSize = 13.sp,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "Show wider-area options (${widerAreaWindows.size} outside ${repositionLimitMinutes}m drive limit)",
                                    color = RadarBlue,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable { showWiderAreaWindows = true },
                                )
                            }
                        }
                    }
                }
                items(displayedWindows, key = { it.id }) { win ->
                    Card(
                        colors = CardDefaults.cardColors(containerColor = BgCard),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(modifier = Modifier.padding(13.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = formatDriverAreaName(win.zone),
                                    color = EmeraldCyan,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 14.sp,
                                )
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    win.minutesAway?.let { mins ->
                                        Text(
                                            text = "${String.format(Locale.US, "%.0f", mins)} min · ",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                    RouteBasisPill(win.routeBasis)
                                }
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = cleanDriverText(win.headline),
                                color = TextPrimary,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 14.sp,
                            )
                            if (win.detail.isNotBlank()) {
                                Spacer(modifier = Modifier.height(2.dp))
                                Text(
                                    text = cleanDriverText(win.detail),
                                    color = TextSecondary,
                                    fontSize = 12.sp,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PlanSubTabSelectorRow(
    planSubTab: Int,
    minutesAvailable: Int = 360,
    onSelectSubTab: (Int) -> Unit,
) {
    val durationLabel = when {
        minutesAvailable <= 0 -> "6h"
        minutesAvailable % 60 == 0 -> "${minutesAvailable / 60}h"
        else -> "${minutesAvailable}m"
    }
    val subTabs = buildList {
        add(0 to "My plan ($durationLabel)")
        add(3 to "Compare")
        add(1 to "Tonight")
        add(2 to "Airport")
        if (UberIntelligence.UBER_ASSISTANT_INTELLIGENCE_EXPERIMENTAL) {
            add(4 to "Uber second opinion")
        }
    }
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        subTabs.forEach { (idx, label) ->
            val selected = planSubTab == idx
            Surface(
                color = if (selected) EmeraldDim else BgCard,
                border = BorderStroke(1.dp, if (selected) EmeraldCyan else BorderSubtle),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.clickable { onSelectSubTab(idx) },
            ) {
                Text(
                    text = label,
                    color = if (selected) EmeraldCyan else TextSecondary,
                    fontSize = 11.sp,
                    fontWeight = if (selected) FontWeight.ExtraBold else FontWeight.SemiBold,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    modifier = Modifier.padding(vertical = 7.dp, horizontal = 9.dp),
                )
            }
        }
    }
}

private fun buildNonContradictoryPlanStepCopy(
    originDisplay: String,
    stop: ShiftCourseStop,
): Pair<String, String> {
    val triggerLower = stop.primaryTrigger.lowercase(Locale.US)
    val explicitAction = stop.decisionState.ifBlank { stop.action }.trim().uppercase(Locale.US)
    val hasNoEvidenceOrHold = explicitAction in setOf("WATCH", "WAIT", "STAY", "HOLD") ||
        "insufficient" in triggerLower ||
        "hold position" in triggerLower ||
        "stay local" in triggerLower ||
        "no verified" in triggerLower ||
        "no clear" in triggerLower ||
        (
            stop.score <= 0.0 &&
                stop.hotVenues.isEmpty() &&
                stop.spilloutVenues.isEmpty() &&
                stop.events.isEmpty() &&
                stop.flightArrivals <= 0 &&
                (stop.expectedNetPerHour == null || stop.sampleTrips < 3)
            )
    val sameArea = stop.zoneLabel.equals(originDisplay, ignoreCase = true) ||
        stop.repositionLabel.contains("already in area", ignoreCase = true) ||
        stop.driveMinutesFromPrev <= 1
    val isPositioningSuggestion = stop.recommendationBasis.equals("positioning_heuristic", ignoreCase = true) ||
        "positioning suggestion" in triggerLower

    val holdArea = originDisplay.ifBlank { stop.zoneLabel }
    val actionTitle = when {
        explicitAction == "WATCH" || "insufficient" in triggerLower || "no verified" in triggerLower ->
            "Hold in ${if (sameArea) stop.zoneLabel else holdArea} · insufficient evidence"
        hasNoEvidenceOrHold ->
            if (sameArea) "Stay in ${stop.zoneLabel}" else "Hold in $holdArea"
        isPositioningSuggestion && !sameArea ->
            "Position near ${stop.zoneLabel}"
        sameArea ->
            "Stay in ${stop.zoneLabel}"
        else ->
            "Move to ${stop.zoneLabel}"
    }
    var rawReason = cleanDriverText(stop.primaryTrigger)
    if (rawReason.isBlank()) {
        rawReason = when {
            hasNoEvidenceOrHold ->
                "Insufficient live or historical evidence to justify repositioning right now — hold position and recheck."
            sameArea ->
                "Best nearby pickup window for your current area."
            else -> {
                val driveMin = stop.driveMinutesFromPrev.coerceAtLeast(1)
                "Strongest nearby pickup window (~$driveMin min drive from $originDisplay)."
            }
        }
    }
    return actionTitle to rawReason
}

@Composable
private fun PlanTabScreen(
    planSubTab: Int,
    onSelectSubTab: (Int) -> Unit,
    initialUberPaste: String = "",
    initialUberSection: String = "all",
    uberStoreFileName: String = "uber_assistant_imports_v1.json",
    initialUberEditDrive: String? = null,
    initialUberEditWait: String? = null,
    initialUberClearPasteAfterParse: Boolean = false,
    currentHereState: HereState? = null,
    hasActiveWaitEpisode: Boolean = false,
    firstStopComparison: UberIntelligence.DecisionComparisonRecord? = null,
    onComparisonSaved: () -> Unit = {},
    onSecondOpinionFeedback: (String, Boolean) -> Unit = { _, _ -> },
    askArea: String,
    askState: AskState?,
    shiftCourse: ShiftCourseState?,
    courseBlasting: Boolean,
    courseError: String?,
    minutesAvailable: Int,
    repositionUnder: Int,
    finishNear: String,
    questionText: String,
    busy: Boolean,
    tonight: TonightState?,
    seatacForecast: SeatacForecastState?,
    seatacPolling: Boolean,
    onPollSeatacForecast: () -> Unit,
    onSelectArea: (String) -> Unit,
    onBlastCourse: () -> Unit,
    onUpdateConstraints: (Int, Int, String) -> Unit,
    onQuestionTextChange: (String) -> Unit,
    onAskQwen: (String, Boolean) -> Unit,
    onRefreshTonight: () -> Unit,
    onApproveCurb: (String) -> Unit,
    onOpenGoogleMaps: (Double?, Double?, String) -> Unit,
    onSendToVolvo: (String) -> Unit,
    onSpeakAnswer: (String) -> Unit,
    onOpenMaps: (String, String) -> Unit,
) {
    var whyThisPlanExpanded by rememberSaveable { mutableStateOf(false) }
    var constraintsExpanded by rememberSaveable { mutableStateOf(false) }
    var expandedStageKeys by rememberSaveable { mutableStateOf(listOf<String>()) }
    val voiceLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { res ->
        if (res.resultCode == Activity.RESULT_OK) {
            val spoken = res.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spoken.isNullOrBlank()) {
                onQuestionTextChange(spoken)
                onAskQwen(spoken, true)
            }
        }
    }

    if (planSubTab == 4 && UberIntelligence.UBER_ASSISTANT_INTELLIGENCE_EXPERIMENTAL) {
        Column(modifier = Modifier.fillMaxSize()) {
            Box(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                PlanSubTabSelectorRow(
                    planSubTab = planSubTab,
                    minutesAvailable = minutesAvailable,
                    onSelectSubTab = onSelectSubTab,
                )
            }
            UberIntelligenceScreen(
                initialPasteText = initialUberPaste,
                initialSection = initialUberSection,
                storeFileName = uberStoreFileName,
                initialEditDriveText = initialUberEditDrive,
                initialEditWaitExactText = initialUberEditWait,
                initialClearPasteAfterParse = initialUberClearPasteAfterParse,
                currentHereState = currentHereState,
                hasActiveWaitEpisode = hasActiveWaitEpisode,
                onComparisonSaved = { onComparisonSaved() },
            )
        }
        return
    }

    val finishLabel = when (finishNear) {
        "kirkland_waterfront" -> "Finish near Kirkland"
        "bellevue_core" -> "Finish near Bellevue"
        "capitol_hill" -> "Finish near Seattle"
        else -> "Finish anywhere"
    }
    val planOriginDisplay = formatDriverAreaName(shiftCourse?.originLabel?.ifBlank { askArea } ?: askArea)

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Sub-Tabs: My plan (90m) · Compare · Tonight · Airport · Uber second opinion
        item {
            PlanSubTabSelectorRow(
                planSubTab = planSubTab,
                minutesAvailable = minutesAvailable,
                onSelectSubTab = onSelectSubTab,
            )
        }

        // Single Compact Constraints Line: Totem Lake · 90 min · Max drive 15 min · Finish anywhere [Edit]
        item {
            Surface(
                color = BgCard,
                border = BorderStroke(1.dp, if (constraintsExpanded) EmeraldCyan else BorderSubtle),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { constraintsExpanded = !constraintsExpanded },
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        val durSummary = if (minutesAvailable % 60 == 0) {
                            "${minutesAvailable / 60}h (${minutesAvailable}m)"
                        } else {
                            "$minutesAvailable min"
                        }
                        Text(
                            text = "$planOriginDisplay · $durSummary · Max drive $repositionUnder min · $finishLabel",
                            color = TextPrimary,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            color = BgCardElevated,
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                        ) {
                            Text(
                                text = if (constraintsExpanded) "Done" else "Edit",
                                color = RadarBlue,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            )
                        }
                    }

                    if (constraintsExpanded) {
                        Spacer(modifier = Modifier.height(10.dp))
                        HorizontalDivider(color = BorderSubtle)
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("Starting area:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            QUICK_AREAS.forEach { area ->
                                FilterChip(
                                    selected = askArea.equals(area, ignoreCase = true),
                                    onClick = { onSelectArea(area) },
                                    label = { Text(area, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = EmeraldDim,
                                        selectedLabelColor = EmeraldCyan,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        Text("Time available:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(360, 240, 180, 120, 90, 60, 45).forEach { mins ->
                                val chipLabel = if (mins % 60 == 0) "${mins / 60}h (${mins}m)" else "${mins}m"
                                FilterChip(
                                    selected = minutesAvailable == mins,
                                    onClick = { onUpdateConstraints(mins, repositionUnder, finishNear) },
                                    label = { Text(chipLabel, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = RadarDim,
                                        selectedLabelColor = RadarBlue,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(4.dp))
                        Text("Max drive:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(10, 15, 20, 30).forEach { repo ->
                                FilterChip(
                                    selected = repositionUnder == repo,
                                    onClick = { onUpdateConstraints(minutesAvailable, repo, finishNear) },
                                    label = { Text("${repo}m", fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = RadarDim,
                                        selectedLabelColor = RadarBlue,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(4.dp))
                        Text("Finish near:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(
                                "kirkland_waterfront" to "Kirkland",
                                "bellevue_core" to "Bellevue",
                                "capitol_hill" to "Seattle",
                                "none" to "Anywhere",
                            ).forEach { (fnKey, fnLabel) ->
                                FilterChip(
                                    selected = finishNear == fnKey,
                                    onClick = { onUpdateConstraints(minutesAvailable, repositionUnder, fnKey) },
                                    label = { Text(fnLabel, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = RadarDim,
                                        selectedLabelColor = RadarBlue,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }
                    }
                }
            }
        }

        when (planSubTab) {
            0 -> {
                val isCachedOrFailedPlan = !courseError.isNullOrBlank()
                if (!courseError.isNullOrBlank()) {
                    item {
                        Surface(
                            color = CoralDim,
                            border = BorderStroke(1.dp, CoralRed),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(10.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "Plan update failed · showing last saved plan",
                                        color = CoralRed,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                    Text(
                                        text = cleanDriverText(courseError),
                                        color = TextPrimary,
                                        fontSize = 12.sp,
                                    )
                                }
                                OutlinedButton(onClick = onBlastCourse, enabled = !courseBlasting) {
                                    Text("Retry", color = EmeraldCyan, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }

                // Timeline (Now expanded, Next / Later collapsed by default)
                shiftCourse?.let { course ->
                    val mergedIntervals = mergeCourseStops(course.stops)
                    if (mergedIntervals.isNotEmpty()) {
                        items(mergedIntervals, key = { "merged-${it.firstStop.hourIndex}-${it.lastStop.hourIndex}" }) { interval ->
                            val stop = interval.firstStop
                            val stageKey = "${interval.firstStop.hourIndex}-${interval.lastStop.hourIndex}"
                            val displayBadge = if (interval.slotBadge == "NOW" && isCachedOrFailedPlan) "CACHED" else interval.slotBadge
                            val isNow = displayBadge == "NOW" || interval.firstStop.hourIndex == 1
                            val isExpanded = isNow || expandedStageKeys.contains(stageKey)
                            val (actionTitle, cleanReason) = buildNonContradictoryPlanStepCopy(
                                originDisplay = planOriginDisplay,
                                stop = stop,
                            )

                            Card(
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isNow) BgCardElevated else BgCard
                                ),
                                border = BorderStroke(
                                    if (isNow) 1.5.dp else 1.dp,
                                    when {
                                        isCachedOrFailedPlan && isNow -> CoralRed
                                        isNow -> EmeraldCyan
                                        else -> BorderSubtle
                                    }
                                ),
                                shape = RoundedCornerShape(14.dp),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable(enabled = !isNow) {
                                        expandedStageKeys = if (expandedStageKeys.contains(stageKey)) {
                                            expandedStageKeys - stageKey
                                        } else {
                                            expandedStageKeys + stageKey
                                        }
                                    },
                            ) {
                                Column(modifier = Modifier.padding(14.dp)) {
                                    if (isNow) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Surface(
                                                    color = if (isCachedOrFailedPlan) AmberDim else EmeraldCyan,
                                                    shape = RoundedCornerShape(6.dp),
                                                ) {
                                                    Text(
                                                        text = displayBadge,
                                                        color = if (isCachedOrFailedPlan) AmberGold else Color(0xFF041410),
                                                        fontSize = 10.sp,
                                                        fontWeight = FontWeight.ExtraBold,
                                                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
                                                    )
                                                }
                                                Spacer(modifier = Modifier.width(8.dp))
                                                Text(
                                                    text = interval.windowLabel,
                                                    color = TextSecondary,
                                                    fontSize = 12.sp,
                                                    fontWeight = FontWeight.Bold,
                                                )
                                            }
                                            Text(
                                                text = if (courseBlasting) "Updating…" else "↻ Refresh",
                                                color = RadarBlue,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.Bold,
                                                modifier = Modifier.clickable(enabled = !courseBlasting) { onBlastCourse() },
                                            )
                                        }

                                        Spacer(modifier = Modifier.height(6.dp))
                                        Text(
                                            text = actionTitle,
                                            color = TextPrimary,
                                            fontSize = 20.sp,
                                            fontWeight = FontWeight.ExtraBold,
                                        )
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = cleanReason,
                                            color = TextPrimary,
                                            fontSize = 13.sp,
                                        )
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = if (stop.navigationAvailable && stop.stagingSpot.isNotBlank()) {
                                                "Pickup spot: ${stop.stagingSpot}"
                                            } else {
                                                "Area only — pickup spot not verified"
                                            },
                                            color = if (stop.navigationAvailable) EmeraldCyan else TextSecondary,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Medium,
                                        )

                                        Spacer(modifier = Modifier.height(10.dp))
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            if (stop.navigationAvailable && stop.mapsUrl.isNotBlank()) {
                                                Button(
                                                    onClick = { onOpenMaps(stop.mapsUrl, stop.stagingSpot) },
                                                    colors = ButtonDefaults.buttonColors(
                                                        containerColor = EmeraldCyan,
                                                        contentColor = Color(0xFF041410),
                                                    ),
                                                    shape = RoundedCornerShape(10.dp),
                                                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp),
                                                ) {
                                                    Text("Navigate", fontWeight = FontWeight.ExtraBold, fontSize = 12.sp)
                                                }
                                            } else {
                                                OutlinedButton(
                                                    onClick = { onOpenMaps("", "${stop.zoneLabel}, WA") },
                                                    border = BorderStroke(1.dp, BorderSubtle),
                                                    shape = RoundedCornerShape(10.dp),
                                                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp),
                                                ) {
                                                    Text("View area", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                                }
                                            }

                                            if (stop.expectedNetPerHour != null && stop.sampleTrips >= 3) {
                                                Text(
                                                    text = "~$${String.format(Locale.US, "%.0f", stop.expectedNetPerHour)}/hr paid-trip avg (${stop.sampleTrips}t)",
                                                    color = TextSecondary,
                                                    fontSize = 11.sp,
                                                    fontFamily = FontFamily.Monospace,
                                                )
                                            }
                                        }

                                        if (firstStopComparison != null && UberIntelligence.UBER_ASSISTANT_COMPARISON_DISPLAY_ENABLED) {
                                            Spacer(modifier = Modifier.height(8.dp))
                                            CompactSecondOpinionBanner(
                                                comparison = firstStopComparison,
                                                onOpenIntelTab = { onSelectSubTab(4) },
                                                onFeedbackUseful = { useful ->
                                                    onSecondOpinionFeedback(firstStopComparison.id, useful)
                                                },
                                            )
                                        }
                                    } else {
                                        // Collapsed Next / Later row by default
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Row(
                                                modifier = Modifier.weight(1f),
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Surface(
                                                    color = if (displayBadge == "NEXT") RadarDim else BgCardElevated,
                                                    shape = RoundedCornerShape(6.dp),
                                                ) {
                                                    Text(
                                                        text = displayBadge,
                                                        color = if (displayBadge == "NEXT") RadarBlue else TextSecondary,
                                                        fontSize = 10.sp,
                                                        fontWeight = FontWeight.ExtraBold,
                                                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
                                                    )
                                                }
                                                Spacer(modifier = Modifier.width(8.dp))
                                                Text(
                                                    text = "${interval.windowLabel} · ${stop.zoneLabel}",
                                                    color = TextPrimary,
                                                    fontSize = 13.sp,
                                                    fontWeight = FontWeight.Bold,
                                                )
                                            }
                                            Text(
                                                text = if (isExpanded) "Hide ▴" else "Details ▾",
                                                color = RadarBlue,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }

                                        if (isExpanded) {
                                            Spacer(modifier = Modifier.height(8.dp))
                                            HorizontalDivider(color = BorderSubtle)
                                            Spacer(modifier = Modifier.height(8.dp))
                                            Text(
                                                text = actionTitle,
                                                color = TextPrimary,
                                                fontSize = 15.sp,
                                                fontWeight = FontWeight.ExtraBold,
                                            )
                                            Spacer(modifier = Modifier.height(3.dp))
                                            Text(
                                                text = cleanReason,
                                                color = TextSecondary,
                                                fontSize = 12.sp,
                                            )
                                            Spacer(modifier = Modifier.height(4.dp))
                                            Row(
                                                modifier = Modifier.fillMaxWidth(),
                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Text(
                                                    text = if (stop.navigationAvailable && stop.stagingSpot.isNotBlank()) {
                                                        "Pickup spot: ${stop.stagingSpot}"
                                                    } else {
                                                        "Area only — pickup spot not verified"
                                                    },
                                                    color = if (stop.navigationAvailable) EmeraldCyan else TextSecondary,
                                                    fontSize = 11.sp,
                                                    modifier = Modifier.weight(1f),
                                                )
                                                Spacer(modifier = Modifier.width(8.dp))
                                                Surface(
                                                    color = BgCardElevated,
                                                    border = BorderStroke(1.dp, BorderSubtle),
                                                    shape = RoundedCornerShape(8.dp),
                                                    modifier = Modifier.clickable {
                                                        if (stop.navigationAvailable && stop.mapsUrl.isNotBlank()) {
                                                            onOpenMaps(stop.mapsUrl, stop.stagingSpot)
                                                        } else {
                                                            onOpenMaps("", "${stop.zoneLabel}, WA")
                                                        }
                                                    },
                                                ) {
                                                    Text(
                                                        text = if (stop.navigationAvailable && stop.mapsUrl.isNotBlank()) "Navigate" else "View area",
                                                        color = RadarBlue,
                                                        fontSize = 11.sp,
                                                        fontWeight = FontWeight.Bold,
                                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 3. Single Collapsed Supporting Evidence Section ("Why this plan")
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(14.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(14.dp)) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable { whyThisPlanExpanded = !whyThisPlanExpanded },
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = "Why this plan",
                                            color = TextPrimary,
                                            fontSize = 13.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Text(
                                            text = "${course.totalFeedsOnline}/${course.totalFeedsCatalog} sources active · ${course.besttimeHotspotsActive} busy venues · ~${course.flightaware6hPlanes} SEA arrivals (6h)",
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                        )
                                    }
                                    Text(
                                        text = if (whyThisPlanExpanded) "Hide ▴" else "Details ▾",
                                        color = RadarBlue,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }

                                if (whyThisPlanExpanded) {
                                    Spacer(modifier = Modifier.height(10.dp))
                                    HorizontalDivider(color = BorderSubtle)
                                    Spacer(modifier = Modifier.height(8.dp))
                                    if (course.planWatchouts.isNotBlank()) {
                                        Text(
                                            text = "Watchouts: ${cleanDriverText(course.planWatchouts)}",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                        Spacer(modifier = Modifier.height(8.dp))
                                    }
                                    if (course.topHotspotsNow.isNotEmpty()) {
                                        Text(
                                            text = "Metro crowd activity (${course.topHotspotsNow.size} venues)",
                                            color = AmberGold,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Spacer(modifier = Modifier.height(6.dp))
                                        course.topHotspotsNow.take(6).forEachIndexed { idx, hs ->
                                            if (idx > 0) {
                                                HorizontalDivider(
                                                    color = BorderSubtle.copy(alpha = 0.5f),
                                                    modifier = Modifier.padding(vertical = 4.dp),
                                                )
                                            }
                                            Row(
                                                modifier = Modifier.fillMaxWidth(),
                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Column(modifier = Modifier.weight(1f)) {
                                                    Text(
                                                        text = hs.name,
                                                        color = TextPrimary,
                                                        fontWeight = FontWeight.SemiBold,
                                                        fontSize = 12.sp,
                                                    )
                                                    Text(
                                                        text = formatDriverAreaName(hs.area),
                                                        color = TextSecondary,
                                                        fontSize = 11.sp,
                                                    )
                                                }
                                                Text(
                                                    text = "${hs.busynessPct}%",
                                                    color = if (hs.busynessPct >= 70) EmeraldCyan else AmberGold,
                                                    fontWeight = FontWeight.Bold,
                                                    fontSize = 12.sp,
                                                    fontFamily = FontFamily.Monospace,
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            1 -> {
                // Sub-tab 1: Tonight's Shift Brief & Ranked Staging Curbs
                if (tonight == null) {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(24.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                CircularProgressIndicator(color = EmeraldCyan)
                                Spacer(modifier = Modifier.height(10.dp))
                                Text("Loading Tonight's Shift Brief…", color = TextSecondary)
                            }
                        }
                    }
                } else {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                            border = BorderStroke(1.5.dp, EmeraldCyan.copy(alpha = 0.7f)),
                            shape = RoundedCornerShape(16.dp),
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Surface(
                                        color = EmeraldDim,
                                        shape = RoundedCornerShape(6.dp),
                                    ) {
                                        Text(
                                            text = tonight.shiftAction.uppercase(),
                                            color = EmeraldCyan,
                                            fontWeight = FontWeight.ExtraBold,
                                            fontSize = 12.sp,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        )
                                    }
                                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                        Text(
                                            text = "↻ Refresh",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.clickable { onRefreshTonight() },
                                        )
                                        Text(
                                            text = "🔊 Listen",
                                            color = RadarBlue,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.clickable {
                                                onSpeakAnswer(tonight.narratorSpoken.ifBlank { tonight.explanation })
                                            },
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = formatDriverAreaName(tonight.bestZone.ifBlank { "Seattle / Eastside Metro" }),
                                    color = TextPrimary,
                                    fontSize = 22.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                )
                                Spacer(modifier = Modifier.height(6.dp))
                                Text(
                                    text = cleanDriverText(tonight.explanation),
                                    color = TextPrimary,
                                    fontSize = 14.sp,
                                    lineHeight = 20.sp,
                                )
                            }
                        }
                    }

                    items(tonight.opportunities, key = { it.id }) { opp ->
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Column(modifier = Modifier.padding(14.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = "${formatDriverAreaName(opp.zone)} · ${opp.venueName}",
                                            color = TextPrimary,
                                            fontWeight = FontWeight.ExtraBold,
                                            fontSize = 16.sp,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        Text(
                                            text = "${opp.action} · ${opp.trafficMinutes?.let { "${String.format(Locale.US, "%.0f", it)} min drive" } ?: "route pending"}",
                                            color = EmeraldCyan,
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.SemiBold,
                                        )
                                    }
                                    RouteBasisPill(opp.routeBasis)
                                }

                                if (opp.anchorLabel.isNotBlank()) {
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = if (opp.anchorApproved) {
                                            "Approved curb: ${opp.anchorLabel}"
                                        } else {
                                            "Suggested curb: ${opp.anchorLabel} (unverified)"
                                        },
                                        color = if (opp.anchorApproved) EmeraldCyan else AmberGold,
                                        fontSize = 12.sp,
                                    )
                                }

                                if (opp.facts.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(6.dp))
                                    opp.facts.take(3).forEach { fact ->
                                        Text(
                                            text = "• ${cleanDriverText(fact)}",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                }

                                Spacer(modifier = Modifier.height(10.dp))
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Button(
                                        onClick = {
                                            onOpenGoogleMaps(
                                                opp.anchorLat,
                                                opp.anchorLon,
                                                opp.anchorLabel.ifBlank { "${opp.venueName} ${opp.zone}" }
                                            )
                                        },
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = EmeraldCyan,
                                            contentColor = Color(0xFF041410),
                                        ),
                                        shape = RoundedCornerShape(8.dp),
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        Text(
                                            text = if (opp.anchorApproved) "🗺 Navigate Curb" else "🗺 Area Map",
                                            fontWeight = FontWeight.ExtraBold,
                                            fontSize = 12.sp,
                                        )
                                    }

                                    if (!opp.anchorApproved && opp.anchorId.isNotBlank()) {
                                        OutlinedButton(
                                            onClick = { onApproveCurb(opp.anchorId) },
                                            border = BorderStroke(1.dp, AmberGold),
                                            shape = RoundedCornerShape(8.dp),
                                            modifier = Modifier.weight(1f),
                                        ) {
                                            Text("✓ Approve Curb", color = AmberGold, fontSize = 12.sp)
                                        }
                                    } else {
                                        OutlinedButton(
                                            onClick = { onSendToVolvo(opp.id) },
                                            border = BorderStroke(1.dp, RadarBlue),
                                            shape = RoundedCornerShape(8.dp),
                                            modifier = Modifier.weight(1f),
                                        ) {
                                            Text("🚗 Send to Car", color = RadarBlue, fontSize = 12.sp)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            2 -> {
                // Sub-tab 2: Dedicated Sea-Tac Airport Forecast & Queue Guidance (UI-06)
                item {
                    SeatacForecastCard(
                        forecast = seatacForecast,
                        isPolling = seatacPolling,
                        onPollForecast = onPollSeatacForecast,
                        onOpenMaps = onOpenMaps,
                    )
                }
            }

            3 -> {
                // Sub-tab 3: Compare areas & Ask Assistant (N07, N10)
                item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = BgCard),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(14.dp),
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Button(
                                    onClick = { onAskQwen("Compare my options right now.", true) },
                                    enabled = !busy,
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = EmeraldCyan,
                                        contentColor = Color(0xFF041410),
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("Compare areas", fontWeight = FontWeight.ExtraBold)
                                }
                                OutlinedButton(
                                    onClick = { onAskQwen("What changed since the last check?", true) },
                                    enabled = !busy,
                                    border = BorderStroke(1.dp, RadarBlue),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("What Changed?", color = RadarBlue, fontWeight = FontWeight.Bold)
                                }
                            }

                            Spacer(modifier = Modifier.height(8.dp))

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                OutlinedTextField(
                                    value = questionText,
                                    onValueChange = onQuestionTextChange,
                                    placeholder = { Text("Ask about areas, timing, or tradeoffs…", color = TextMuted) },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                                    keyboardActions = KeyboardActions(
                                        onSend = {
                                            if (questionText.isNotBlank()) onAskQwen(questionText, true)
                                        }
                                    ),
                                    colors = OutlinedTextFieldDefaults.colors(
                                        focusedBorderColor = EmeraldCyan,
                                        unfocusedBorderColor = BorderSubtle,
                                        focusedTextColor = TextPrimary,
                                        unfocusedTextColor = TextPrimary,
                                    ),
                                    modifier = Modifier.weight(1f),
                                )
                                OutlinedButton(
                                    onClick = {
                                        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                                            putExtra(
                                                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                                                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
                                            )
                                            putExtra(RecognizerIntent.EXTRA_PROMPT, "Ask about your shift…")
                                        }
                                        runCatching { voiceLauncher.launch(intent) }
                                    },
                                    border = BorderStroke(1.dp, BorderSubtle),
                                    shape = RoundedCornerShape(10.dp),
                                ) {
                                    Text("🎤", fontSize = 16.sp)
                                }
                            }
                        }
                    }
                }

                askState?.let { state ->
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                            border = BorderStroke(1.5.dp, EmeraldCyan.copy(alpha = 0.6f)),
                            shape = RoundedCornerShape(16.dp),
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = cleanDriverText(state.answerState).uppercase(),
                                        color = EmeraldCyan,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                        letterSpacing = 0.8.sp,
                                    )
                                }
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = cleanDriverText(state.answer),
                                    color = TextPrimary,
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Bold,
                                    lineHeight = 22.sp,
                                )
                                if (state.explanationBullets.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(10.dp))
                                    state.explanationBullets.forEach { bullet ->
                                        Text(
                                            text = "• ${cleanDriverText(bullet)}",
                                            color = TextSecondary,
                                            fontSize = 13.sp,
                                            lineHeight = 19.sp,
                                            modifier = Modifier.padding(vertical = 2.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }

                    items(state.options, key = { it.id }) { opt ->
                        val isBest = opt.id == state.bestId
                        val (exclusionBadge, exclusionDetail) = if (!opt.eligible) {
                            WorkingLocationController.formatCompareExclusion(opt, repositionUnder)
                        } else {
                            "" to ""
                        }
                        Card(
                            colors = CardDefaults.cardColors(containerColor = BgCard),
                            border = BorderStroke(
                                1.dp,
                                if (isBest) EmeraldCyan else if (opt.eligible) BorderSubtle else CoralRed.copy(alpha = 0.4f)
                            ),
                            shape = RoundedCornerShape(12.dp),
                        ) {
                            Column(modifier = Modifier.padding(14.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = formatDriverAreaName(opt.area),
                                            color = if (isBest) EmeraldCyan else TextPrimary,
                                            fontWeight = FontWeight.ExtraBold,
                                            fontSize = 16.sp,
                                        )
                                        if (opt.venue.isNotBlank()) {
                                            Text(
                                                text = opt.venue,
                                                color = TextSecondary,
                                                fontSize = 12.sp,
                                            )
                                        }
                                    }
                                    Surface(
                                        color = if (opt.eligible) EmeraldDim else AmberDim,
                                        shape = RoundedCornerShape(6.dp),
                                    ) {
                                        Text(
                                            text = when {
                                                isBest -> "RECOMMENDED"
                                                opt.eligible -> "WITHIN LIMITS"
                                                else -> exclusionBadge.uppercase()
                                            },
                                            color = if (opt.eligible) EmeraldCyan else AmberGold,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.height(6.dp))
                                if (!opt.eligible && exclusionDetail.isNotBlank()) {
                                    Text(
                                        text = "· $exclusionDetail",
                                        color = AmberGold,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                                opt.reasons.forEach { reason ->
                                    val cleanedReason = cleanDriverText(reason)
                                    if (
                                        !cleanedReason.equals(exclusionBadge, ignoreCase = true) &&
                                        !cleanedReason.equals(exclusionDetail, ignoreCase = true)
                                    ) {
                                        Text(
                                            text = "· $cleanedReason",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NearbyTrainStationsPullDown(
    stations: List<NearbyTrainStation>,
    onOpenMaps: (String, String) -> Unit,
) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    var selectedStationId by rememberSaveable { mutableStateOf(stations.firstOrNull()?.id ?: "") }
    val soonest = stations.mapNotNull { it.nextEtaMinutes }.minOrNull()
    val hasUnknownStations = stations.any { it.nextEtaMinutes == null }

    Card(
        colors = CardDefaults.cardColors(containerColor = BgCard),
        border = BorderStroke(1.dp, if (expanded) EmeraldCyan else BorderSubtle),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "🚆 NEARBY TRAIN STATIONS (WITHIN 5 MI)",
                        color = EmeraldCyan,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.ExtraBold,
                        letterSpacing = 0.8.sp,
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    val summaryEtaText = when {
                        soonest != null && hasUnknownStations -> " · Next known arrival in ~${soonest}m"
                        soonest != null -> " · Next train arriving in ~${soonest}m"
                        else -> " · Arrival times unknown"
                    }
                    Text(
                        text = "${stations.size} station(s) nearby$summaryEtaText",
                        color = TextPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold,
                    )
                }
                Surface(
                    color = BgCardElevated,
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Text(
                        text = if (expanded) "Hide train arrivals ▴" else "Show train arrivals ▾",
                        color = EmeraldCyan,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
            }

            if (expanded) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    stations.forEach { st ->
                        val isSelected = st.id == selectedStationId || (selectedStationId.isBlank() && st == stations.first())
                        val estDriveMin = maxOf(2, kotlin.math.round(st.distanceMiles * 2.5).toInt())
                        Surface(
                            color = if (isSelected) BgCardElevated else BgDeep,
                            border = BorderStroke(1.dp, if (isSelected) RadarBlue else BorderSubtle),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    selectedStationId = if (selectedStationId == st.id) "" else st.id
                                },
                        ) {
                            Column(modifier = Modifier.padding(11.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = st.name,
                                            color = TextPrimary,
                                            fontSize = 14.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Text(
                                            text = "${String.format(Locale.US, "%.1f", st.distanceMiles)} mi away (~${estDriveMin}m drive) · ${st.lines.joinToString(", ")}",
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                        val reachabilityNote = st.nextEtaMinutes?.let { eta ->
                                            if (eta < estDriveMin) {
                                                "Train arrives in ~${eta}m vs ~${estDriveMin}m drive"
                                            } else {
                                                "Reachable before arrival (~${estDriveMin}m drive)"
                                            }
                                        }
                                        if (reachabilityNote != null) {
                                            Text(
                                                text = reachabilityNote,
                                                color = if ((st.nextEtaMinutes ?: 0) < estDriveMin) AmberGold else EmeraldCyan,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.SemiBold,
                                            )
                                        }
                                    }
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        val eta = st.nextEtaMinutes
                                        if (eta != null) {
                                            Surface(
                                                color = EmeraldDim,
                                                shape = RoundedCornerShape(6.dp),
                                            ) {
                                                Text(
                                                    text = "in ~${eta}m",
                                                    color = EmeraldCyan,
                                                    fontSize = 11.sp,
                                                    fontWeight = FontWeight.ExtraBold,
                                                    modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                                                )
                                            }
                                        } else {
                                            Surface(
                                                color = BgCardElevated,
                                                border = BorderStroke(1.dp, BorderSubtle),
                                                shape = RoundedCornerShape(6.dp),
                                            ) {
                                                Text(
                                                    text = "Arrival time unknown",
                                                    color = TextSecondary,
                                                    fontSize = 10.sp,
                                                    fontWeight = FontWeight.SemiBold,
                                                    modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                                                )
                                            }
                                        }
                                        Surface(
                                            color = RadarDim,
                                            shape = RoundedCornerShape(6.dp),
                                            modifier = Modifier.clickable {
                                                onOpenMaps(st.mapsUrl, st.name)
                                            },
                                        ) {
                                            Text(
                                                text = "🗺 View pickup spot",
                                                color = RadarBlue,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.Bold,
                                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                            )
                                        }
                                    }
                                }

                                if (isSelected && st.trains.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    HorizontalDivider(color = BorderSubtle.copy(alpha = 0.6f))
                                    Spacer(modifier = Modifier.height(6.dp))
                                    st.trains.forEach { tr ->
                                        Row(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(vertical = 3.dp),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Row(
                                                verticalAlignment = Alignment.CenterVertically,
                                                modifier = Modifier.weight(1f),
                                            ) {
                                                Surface(
                                                    color = RadarDim,
                                                    shape = RoundedCornerShape(4.dp),
                                                ) {
                                                    Text(
                                                        text = tr.line,
                                                        color = RadarBlue,
                                                        fontSize = 10.sp,
                                                        fontWeight = FontWeight.ExtraBold,
                                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                                                    )
                                                }
                                                Spacer(modifier = Modifier.width(7.dp))
                                                Text(
                                                    text = "${tr.headsign} (${tr.status})",
                                                    color = TextSecondary,
                                                    fontSize = 12.sp,
                                                    maxLines = 1,
                                                    overflow = TextOverflow.Ellipsis,
                                                )
                                            }
                                            Text(
                                                text = "${tr.arrivalClock} (~${tr.etaMinutes}m)",
                                                color = EmeraldCyan,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Bold,
                                                fontFamily = FontFamily.Monospace,
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private data class NearbyAreaSummaryRow(
    val id: String,
    val areaName: String,
    val driveLabel: String,
    val reason: String,
    val evidenceType: String,
    val detailText: String,
)

@Composable
private fun AroundTabScreen(
    awareness: AwarenessState?,
    hereNearbyWindows: List<NearbyWindow> = emptyList(),
    selectedArea: String,
    scopeMode: String,
    radiusMiles: Int,
    period: String,
    selectedLayer: String,
    onSelectArea: (String) -> Unit,
    onUsePixelGps: () -> Unit,
    onChangeFilters: (String, Int, String, String) -> Unit,
    onPollBestTime: () -> Unit,
    isPollingBestTime: Boolean = false,
    onOpenMaps: (String, String) -> Unit,
) {
    var filtersExpanded by rememberSaveable { mutableStateOf(false) }
    var moreAreasExpanded by rememberSaveable { mutableStateOf(false) }
    var expandedAreaIds by rememberSaveable { mutableStateOf(listOf<String>()) }
    var roadAdvisoriesExpanded by rememberSaveable(selectedLayer) {
        mutableStateOf(selectedLayer == "access")
    }
    var typicalVenuesExpanded by rememberSaveable(selectedLayer) {
        mutableStateOf(selectedLayer == "dining")
    }
    var expandedDetailIds by remember { mutableStateOf(setOf<String>()) }

    val periodLabel = when (period) {
        "now" -> "Right now"
        "next" -> "Next 1h"
        "all" -> "Next 6h"
        "today" -> "Tonight"
        "week" -> "7 days"
        else -> "Right now"
    }
    val scopeLabel = if (scopeMode == "metro") "All metro" else "Within $radiusMiles mi"
    val areaDisplay = formatDriverAreaName(awareness?.locationLabel ?: selectedArea)

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // 1. Single Compact Header Row + Category Chips (Section 4.1)
        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCard),
                border = BorderStroke(1.dp, if (filtersExpanded) EmeraldCyan else BorderSubtle),
                shape = RoundedCornerShape(14.dp),
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { filtersExpanded = !filtersExpanded },
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "$areaDisplay · $scopeLabel · $periodLabel",
                            color = TextPrimary,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.ExtraBold,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            color = BgCardElevated,
                            border = BorderStroke(1.dp, BorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                        ) {
                            Text(
                                text = if (filtersExpanded) "Done" else "Filters",
                                color = RadarBlue,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    val layers = awareness?.layers.orEmpty()
                    val totalCount = layers.sumOf { it.count }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        FilterChip(
                            selected = selectedLayer == "all",
                            onClick = { onChangeFilters(scopeMode, radiusMiles, period, "all") },
                            label = { Text("All ($totalCount)", fontSize = 12.sp) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = EmeraldDim,
                                selectedLabelColor = EmeraldCyan,
                                containerColor = BgCardElevated,
                                labelColor = TextSecondary,
                            ),
                        )
                        layers.forEach { layerItem ->
                            FilterChip(
                                selected = selectedLayer == layerItem.id,
                                onClick = { onChangeFilters(scopeMode, radiusMiles, period, layerItem.id) },
                                label = { Text("${layerItem.label} (${layerItem.count})", fontSize = 12.sp) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = EmeraldDim,
                                    selectedLabelColor = EmeraldCyan,
                                    containerColor = BgCardElevated,
                                    labelColor = TextSecondary,
                                ),
                            )
                        }
                    }

                    if (filtersExpanded) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = BorderSubtle)
                        Spacer(modifier = Modifier.height(8.dp))

                        Text("Area:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            QUICK_AREAS.forEach { area ->
                                val isSelected = selectedArea.equals(area, ignoreCase = true) ||
                                    (awareness != null && RideEdgeClient.canonicalAwarenessArea(area) == awareness.area && selectedArea.equals(area, ignoreCase = true))
                                FilterChip(
                                    selected = isSelected && scopeMode == "nearby",
                                    onClick = { onSelectArea(area) },
                                    label = { Text(area, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = EmeraldDim,
                                        selectedLabelColor = EmeraldCyan,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        Text("Distance:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(
                                Triple("nearby", 5, "Within 5 mi"),
                                Triple("nearby", 8, "Within 8 mi"),
                                Triple("nearby", 15, "Within 15 mi"),
                                Triple("metro", 25, "All Metro"),
                            ).forEach { (sc, rad, label) ->
                                val sel = scopeMode == sc && (sc == "metro" || radiusMiles == rad)
                                FilterChip(
                                    selected = sel,
                                    onClick = { onChangeFilters(sc, rad, period, selectedLayer) },
                                    label = { Text(label, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = RadarDim,
                                        selectedLabelColor = RadarBlue,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        Text("Time window:", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            listOf(
                                "now" to "Right Now",
                                "next" to "Next 1h",
                                "all" to "Next 6h",
                                "today" to "Tonight (14h)",
                                "week" to "7 Days",
                            ).forEach { (pKey, pLabel) ->
                                FilterChip(
                                    selected = period == pKey,
                                    onClick = { onChangeFilters(scopeMode, radiusMiles, pKey, selectedLayer) },
                                    label = { Text(pLabel, fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = RadarDim,
                                        selectedLabelColor = RadarBlue,
                                        containerColor = BgCardElevated,
                                        labelColor = TextSecondary,
                                    ),
                                )
                            }
                        }
                    }
                }
            }
        }

        if (awareness == null) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        CircularProgressIndicator(color = EmeraldCyan)
                        Spacer(modifier = Modifier.height(10.dp))
                        Text("Loading Nearby signals…", color = TextSecondary)
                    }
                }
            }
            return@LazyColumn
        }

        val isRoadAdvisory: (AwarenessObservation) -> Boolean = { obs ->
            obs.kind == "highway_alert" || obs.state.equals("road advisory", ignoreCase = true)
        }
        val primaryObservations = awareness.observations.filterNot(isRoadAdvisory)
        val roadAdvisories = awareness.observations.filter(isRoadAdvisory)
        val liveVenues = awareness.venueActivity
            .filter { it.liveRecent && it.liveValue != null }
            .let { list -> if (scopeMode == "nearby") list else list.sortedByDescending { it.liveValue ?: 0 } }
        val typicalVenues = awareness.venueActivity
            .filter { !(it.liveRecent && it.liveValue != null) && (it.typicalNow ?: 0) > 0 }
            .let { list -> if (scopeMode == "nearby") list else list.sortedByDescending { it.typicalNow ?: 0 } }
        val quietVenues = awareness.venueActivity
            .filter { !(it.liveRecent && it.liveValue != null) && (it.typicalNow ?: 0) <= 0 }
        val pollAreaDisplay = formatDriverAreaName(awareness.locationLabel.ifBlank { selectedArea })

        // 2. Lead with Useful Area Alternatives (Section 4.2: up to 3 area summaries first, rest behind More areas)
        val areaAlternatives = buildList<NearbyAreaSummaryRow> {
            hereNearbyWindows.forEach { win ->
                val areaName = formatDriverAreaName(win.zone)
                if (none { it.areaName.equals(areaName, ignoreCase = true) }) {
                    val driveLabel = win.minutesAway?.let { "${String.format(Locale.US, "%.0f", it)} min drive" } ?: "Nearby"
                    val evidenceType = when {
                        win.headline.contains("live", ignoreCase = true) -> "Live"
                        win.headline.contains("event", ignoreCase = true) || win.headline.contains("egress", ignoreCase = true) -> "Event"
                        win.headline.contains("flight", ignoreCase = true) || win.headline.contains("train", ignoreCase = true) -> "Schedule"
                        else -> "Typical pattern"
                    }
                    add(
                        NearbyAreaSummaryRow(
                            id = "win-${win.id}",
                            areaName = areaName,
                            driveLabel = driveLabel,
                            reason = cleanDriverText(win.headline),
                            evidenceType = evidenceType,
                            detailText = cleanDriverText(win.detail),
                        )
                    )
                }
            }
            primaryObservations.forEach { obs ->
                val zoneName = obs.zoneLabels.firstOrNull()?.let { formatDriverAreaName(it) } ?: areaDisplay
                if (none { it.areaName.equals(zoneName, ignoreCase = true) }) {
                    val driveLabel = obs.distanceMiles?.let {
                        val estMins = maxOf(2, kotlin.math.round(it * 2.5).toInt())
                        "~$estMins min drive"
                    } ?: "Nearby"
                    val evidenceType = when (obs.layer) {
                        "events" -> "Event"
                        "airport", "transit" -> "Schedule"
                        else -> "Live"
                    }
                    add(
                        NearbyAreaSummaryRow(
                            id = "obs-area-${obs.id}",
                            areaName = zoneName,
                            driveLabel = driveLabel,
                            reason = cleanDriverText(obs.title),
                            evidenceType = evidenceType,
                            detailText = cleanDriverText(obs.detail),
                        )
                    )
                }
            }
            typicalVenues.groupBy { formatDriverAreaName(it.area) }.forEach { (zoneName, venues) ->
                if (none { it.areaName.equals(zoneName, ignoreCase = true) }) {
                    val topVenue = venues.first()
                    add(
                        NearbyAreaSummaryRow(
                            id = "typ-area-$zoneName",
                            areaName = zoneName,
                            driveLabel = "Nearby area",
                            reason = "${topVenue.name} (usual ${topVenue.typicalNow ?: 0}% busy)",
                            evidenceType = "Typical pattern",
                            detailText = "Historical weekly pattern across ${venues.size} tracked venue(s) in $zoneName.",
                        )
                    )
                }
            }
        }

        if (areaAlternatives.isNotEmpty() && selectedLayer == "all") {
            val topAreas = if (moreAreasExpanded) areaAlternatives else areaAlternatives.take(3)
            val extraAreaCount = (areaAlternatives.size - 3).coerceAtLeast(0)
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "Nearby area options",
                                color = TextPrimary,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.ExtraBold,
                            )
                            if (extraAreaCount > 0) {
                                Text(
                                    text = if (moreAreasExpanded) "Less areas ▴" else "More areas (+$extraAreaCount) ▾",
                                    color = RadarBlue,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable { moreAreasExpanded = !moreAreasExpanded },
                                )
                            }
                        }

                        topAreas.forEachIndexed { idx, alt ->
                            if (idx > 0) {
                                HorizontalDivider(color = BorderSubtle.copy(alpha = 0.5f))
                            }
                            val isAreaExpanded = expandedAreaIds.contains(alt.id)
                            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = "${alt.areaName} · ${alt.driveLabel}",
                                            color = TextPrimary,
                                            fontSize = 14.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Text(
                                            text = alt.reason,
                                            color = TextSecondary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        Surface(
                                            color = if (alt.evidenceType == "Typical pattern") BgCardElevated else EmeraldDim,
                                            border = BorderStroke(1.dp, if (alt.evidenceType == "Typical pattern") BorderSubtle else EmeraldCyan),
                                            shape = RoundedCornerShape(6.dp),
                                        ) {
                                            Text(
                                                text = alt.evidenceType,
                                                color = if (alt.evidenceType == "Typical pattern") TextSecondary else EmeraldCyan,
                                                fontSize = 10.sp,
                                                fontWeight = FontWeight.Bold,
                                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 3.dp),
                                            )
                                        }
                                        Text(
                                            text = if (isAreaExpanded) "Hide" else "Details",
                                            color = RadarBlue,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.clickable {
                                                expandedAreaIds = if (isAreaExpanded) {
                                                    expandedAreaIds - alt.id
                                                } else {
                                                    expandedAreaIds + alt.id
                                                }
                                            },
                                        )
                                    }
                                }
                                if (isAreaExpanded) {
                                    if (alt.detailText.isNotBlank()) {
                                        Text(
                                            text = alt.detailText,
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                        )
                                    }
                                    Row(
                                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = "View area map",
                                            color = EmeraldCyan,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.clickable {
                                                onOpenMaps("", "${alt.areaName}, WA")
                                            },
                                        )
                                        Text(
                                            text = "Focus Nearby on ${alt.areaName}",
                                            color = RadarBlue,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.clickable {
                                                onSelectArea(alt.areaName)
                                            },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. Primary Demand Signals (Events, Transit, Airport)
        if (primaryObservations.isEmpty() && roadAdvisories.isEmpty() && liveVenues.isEmpty() && typicalVenues.isEmpty()) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Text(
                            text = cleanDriverText(awareness.emptyNote),
                            color = TextSecondary,
                            fontSize = 14.sp,
                        )
                    }
                }
            }
        } else {
            items(primaryObservations, key = { it.id }) { obs ->
                AwarenessObservationCard(
                    obs = obs,
                    isExpanded = expandedDetailIds.contains(obs.id),
                    onToggleExpand = {
                        expandedDetailIds = if (expandedDetailIds.contains(obs.id)) {
                            expandedDetailIds - obs.id
                        } else {
                            expandedDetailIds + obs.id
                        }
                    },
                    onOpenMaps = {
                        val dest = obs.venue.ifBlank { obs.zoneLabels.firstOrNull() ?: obs.title }
                        onOpenMaps("", "$dest, Seattle WA")
                    },
                )
            }
        }

        // 4. Venue Activity: Live Readings first, Typical Weekly Activity collapsed by default under "Typical activity" (Section 4.3)
        if (selectedLayer in listOf("all", "dining")) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = if (liveVenues.isNotEmpty()) {
                                        "Live venue activity (${liveVenues.size})"
                                    } else {
                                        "Typical activity (${typicalVenues.size + quietVenues.size} venues)"
                                    },
                                    color = TextPrimary,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                                Text(
                                    text = if (liveVenues.isNotEmpty()) {
                                        "Live crowd readings in $pollAreaDisplay"
                                    } else {
                                        "Typical venue busyness (historical weekly pattern) · live reading unavailable"
                                    },
                                    color = TextSecondary,
                                    fontSize = 11.sp,
                                )
                            }
                            Spacer(modifier = Modifier.width(8.dp))
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = if (isPollingBestTime) "Checking…" else "↻ Check live",
                                    color = EmeraldCyan,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable(enabled = !isPollingBestTime) {
                                        onPollBestTime()
                                    },
                                )
                                val secondaryCount = typicalVenues.size + quietVenues.size
                                if (secondaryCount > 0) {
                                    Text(
                                        text = if (typicalVenuesExpanded) "Hide ▴" else "Typical activity ▾",
                                        color = RadarBlue,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.clickable { typicalVenuesExpanded = !typicalVenuesExpanded },
                                    )
                                }
                            }
                        }

                        if (liveVenues.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            liveVenues.take(6).forEachIndexed { idx, v ->
                                if (idx > 0) {
                                    HorizontalDivider(
                                        color = BorderSubtle.copy(alpha = 0.5f),
                                        modifier = Modifier.padding(vertical = 5.dp),
                                    )
                                }
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = v.name,
                                            color = TextPrimary,
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 13.sp,
                                        )
                                        Text(
                                            text = "${formatDriverAreaName(v.area)} · ${cleanDriverText(v.note)}",
                                            color = TextSecondary,
                                            fontSize = 11.sp,
                                        )
                                    }
                                    Text(
                                        text = "Live ${v.liveValue}%",
                                        color = EmeraldCyan,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 12.sp,
                                        fontFamily = FontFamily.Monospace,
                                    )
                                }
                            }
                        }

                        if (typicalVenuesExpanded) {
                            val typicalListToShow = (typicalVenues + quietVenues).take(10)
                            if (typicalListToShow.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(10.dp))
                                HorizontalDivider(color = BorderSubtle)
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = "Typical venue busyness (historical weekly pattern)",
                                    color = AmberGold,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                                Spacer(modifier = Modifier.height(6.dp))
                                typicalListToShow.forEachIndexed { idx, v ->
                                    if (idx > 0) {
                                        HorizontalDivider(
                                            color = BorderSubtle.copy(alpha = 0.4f),
                                            modifier = Modifier.padding(vertical = 5.dp),
                                        )
                                    }
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                text = v.name,
                                                color = TextPrimary,
                                                fontWeight = FontWeight.SemiBold,
                                                fontSize = 13.sp,
                                            )
                                            Text(
                                                text = "${formatDriverAreaName(v.area)} · Historical weekly pattern",
                                                color = TextSecondary,
                                                fontSize = 11.sp,
                                            )
                                        }
                                        val typVal = v.typicalNow
                                        Text(
                                            text = if (typVal != null && typVal > 0) "Usual $typVal%" else "Quiet",
                                            color = TextSecondary,
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 12.sp,
                                            fontFamily = FontFamily.Monospace,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 5. Road Advisories collapsed by default
        if (roadAdvisories.isNotEmpty()) {
            item(key = "road-advisories-header") {
                val sampleRoadTitles = roadAdvisories.take(2).joinToString(" · ") {
                    it.title.substringBefore(":").trim()
                }
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                    border = BorderStroke(1.dp, AmberGold.copy(alpha = 0.45f)),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { roadAdvisoriesExpanded = !roadAdvisoriesExpanded },
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "Road & ramp advisories (${roadAdvisories.size})",
                                color = AmberGold,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = if (roadAdvisoriesExpanded) {
                                    "Tap to collapse WSDOT highway & ramp restrictions"
                                } else {
                                    sampleRoadTitles.ifBlank { "Tap to inspect route restrictions" }
                                },
                                color = TextSecondary,
                                fontSize = 11.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = if (roadAdvisoriesExpanded) "Hide ▴" else "Details ▾",
                            color = RadarBlue,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }

            if (roadAdvisoriesExpanded) {
                items(roadAdvisories, key = { it.id }) { obs ->
                    AwarenessObservationCard(
                        obs = obs,
                        isExpanded = expandedDetailIds.contains(obs.id),
                        onToggleExpand = {
                            expandedDetailIds = if (expandedDetailIds.contains(obs.id)) {
                                expandedDetailIds - obs.id
                            } else {
                                expandedDetailIds + obs.id
                            }
                        },
                        onOpenMaps = {
                            val dest = obs.venue.ifBlank { obs.zoneLabels.firstOrNull() ?: obs.title }
                            onOpenMaps("", "$dest, WA")
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun AwarenessObservationCard(
    obs: AwarenessObservation,
    isExpanded: Boolean,
    onToggleExpand: () -> Unit,
    onOpenMaps: () -> Unit,
) {
    val accent = when (obs.layer) {
        "events" -> EmeraldCyan
        "airport" -> RadarBlue
        "access", "transit" -> AmberGold
        "weather" -> CoralRed
        else -> TextPrimary
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = BgCard),
        border = BorderStroke(1.dp, BorderSubtle),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onToggleExpand() },
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Surface(
                        color = accent.copy(alpha = 0.16f),
                        shape = RoundedCornerShape(6.dp),
                    ) {
                        Text(
                            text = obs.state.uppercase(),
                            color = accent,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.ExtraBold,
                            modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                        )
                    }
                    val countdownText = remember(obs.startsAt, obs.endsAt) {
                        val nowSec = System.currentTimeMillis() / 1000L
                        val startSec = runCatching { java.time.OffsetDateTime.parse(obs.startsAt).toEpochSecond() }.getOrNull()
                        val endSec = runCatching { java.time.OffsetDateTime.parse(obs.endsAt).toEpochSecond() }.getOrNull()
                        when {
                            startSec != null && startSec > nowSec + 60L -> {
                                val mins = ((startSec - nowSec + 30L) / 60L).toInt()
                                if (mins >= 60) "Starts in ${mins / 60}h ${mins % 60}m" else "Starts in ${mins}m"
                            }
                            endSec != null && endSec > nowSec + 60L && obs.kind != "highway_alert" -> {
                                val mins = ((endSec - nowSec + 30L) / 60L).toInt()
                                if (mins >= 60) "${mins / 60}h ${mins % 60}m left" else "${mins}m left"
                            }
                            else -> ""
                        }
                    }
                    if (countdownText.isNotBlank()) {
                        Surface(
                            color = AmberDim,
                            shape = RoundedCornerShape(6.dp),
                        ) {
                            Text(
                                text = countdownText,
                                color = AmberGold,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 3.dp),
                            )
                        }
                    }
                    if (obs.priority.isNotBlank()) {
                        Text(
                            text = obs.priority.uppercase(),
                            color = TextSecondary,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                val distLabel = obs.distanceMiles?.let { "${String.format(Locale.US, "%.1f", it)} mi · " } ?: ""
                val formattedZones = obs.zoneLabels.map { formatDriverAreaName(it) }.distinct().joinToString(", ")
                Text(
                    text = "$distLabel$formattedZones",
                    color = TextSecondary,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = cleanDriverText(obs.title),
                color = TextPrimary,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 15.sp,
            )
            if (obs.venue.isNotBlank()) {
                Text(
                    text = obs.venue,
                    color = EmeraldCyan,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            if (obs.detail.isNotBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = cleanDriverText(obs.detail),
                    color = TextSecondary,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    maxLines = if (isExpanded) Int.MAX_VALUE else 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = cleanDriverText("${obs.timingLabel} · ${obs.freshness}"),
                    color = TextMuted,
                    fontSize = 11.sp,
                    modifier = Modifier.weight(1f),
                )
                if (obs.kind != "highway_alert" && obs.layer != "weather") {
                    Surface(
                        color = RadarDim,
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.clickable { onOpenMaps() },
                    ) {
                        Text(
                            text = "🗺 Area Map",
                            color = RadarBlue,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ShiftTabScreen(
    shiftState: ShiftLedgerState?,
    odometerInput: String,
    odometerNote: String,
    onOdometerInputChange: (String) -> Unit,
    onOdometerNoteChange: (String) -> Unit,
    onStartShift: () -> Unit,
    onEndShift: () -> Unit,
    onLogTrip: (Double, Double, String) -> Unit,
) {
    var tripFareInput by rememberSaveable { mutableStateOf("") }
    var tripMilesInput by rememberSaveable { mutableStateOf("") }
    var tripNoteInput by rememberSaveable { mutableStateOf("") }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 1. State-Driven Shift Status & Odometer Card (UI-16: lead with state, show only valid action)
        item {
            val hasActive = !shiftState?.activeShiftId.isNullOrBlank()
            val elapsedMin = shiftState?.activeElapsedMinutes ?: 0.0
            val elapsedHours = (elapsedMin / 60).toInt()
            val elapsedRemMin = (elapsedMin % 60).toInt()
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCardElevated),
                border = BorderStroke(1.5.dp, if (hasActive) EmeraldCyan else BorderSubtle),
                shape = RoundedCornerShape(16.dp),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = if (hasActive) "ACTIVE SHIFT IN PROGRESS" else "SHIFT STATUS · NO ACTIVE SHIFT",
                                color = if (hasActive) EmeraldCyan else TextSecondary,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.ExtraBold,
                                letterSpacing = 0.8.sp,
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            Text(
                                text = if (hasActive) {
                                    "Started at ${shiftState?.activeStartOdometer ?: "--"} mi"
                                } else {
                                    "Track earnings, time and miles"
                                },
                                color = TextPrimary,
                                fontSize = 18.sp,
                                fontWeight = FontWeight.ExtraBold,
                            )
                        }
                        if (hasActive) {
                            Surface(
                                color = EmeraldDim,
                                shape = RoundedCornerShape(8.dp),
                            ) {
                                Text(
                                    text = "⏱ ${elapsedHours}h ${elapsedRemMin}m",
                                    color = EmeraldCyan,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                )
                            }
                        }
                    }

                    if (!hasActive) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Tracks online time and start/end mileage so waiting time and empty repositioning miles are included in your estimated earnings per hour.",
                            color = TextSecondary,
                            fontSize = 12.sp,
                            lineHeight = 17.sp,
                        )
                    }

                    if (hasActive && shiftState != null) {
                        Spacer(modifier = Modifier.height(10.dp))
                        Surface(
                            color = BgCard,
                            shape = RoundedCornerShape(10.dp),
                            border = BorderStroke(1.dp, BorderSubtle),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column {
                                    Text(
                                        text = "${shiftState.activeTripCount} rides · $${String.format(Locale.US, "%.2f", shiftState.activeRunningGross)} gross",
                                        color = TextPrimary,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 14.sp,
                                    )
                                    Text(
                                        text = "${String.format(Locale.US, "%.1f", shiftState.activeRunningMiles)} paid mi logged this shift",
                                        color = TextSecondary,
                                        fontSize = 11.sp,
                                    )
                                }
                                Column(horizontalAlignment = Alignment.End) {
                                    Text(
                                        text = "$${String.format(Locale.US, "%.2f", shiftState.activeRunningNetPerHour)}/hr est. net",
                                        color = if (shiftState.activeRunningNetPerHour >= 22.0) EmeraldCyan else AmberGold,
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 15.sp,
                                        fontFamily = FontFamily.Monospace,
                                    )
                                    Text(
                                        text = "$${String.format(Locale.US, "%.2f", shiftState.activeRunningGrossPerHour)}/hr gross",
                                        color = TextMuted,
                                        fontSize = 11.sp,
                                    )
                                }
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    OutlinedTextField(
                        value = odometerInput,
                        onValueChange = onOdometerInputChange,
                        placeholder = {
                            Text(
                                text = if (hasActive) {
                                    "Ending mileage (optional, e.g. 42285.0)"
                                } else {
                                    "Starting mileage (optional, e.g. 42150.4)"
                                },
                                color = TextMuted,
                            )
                        },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Decimal,
                            imeAction = ImeAction.Done,
                        ),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = EmeraldCyan,
                            unfocusedBorderColor = BorderSubtle,
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = odometerNote,
                        onValueChange = onOdometerNoteChange,
                        placeholder = { Text("Optional note (e.g. Friday Eastside shift)", color = TextMuted) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = EmeraldCyan,
                            unfocusedBorderColor = BorderSubtle,
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(modifier = Modifier.height(10.dp))

                    // Single valid primary shift button depending on whether shift is active (UI-16 / N11)
                    if (!hasActive) {
                        Button(
                            onClick = onStartShift,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = EmeraldCyan,
                                contentColor = Color(0xFF041410),
                            ),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("▶ Start shift", fontWeight = FontWeight.ExtraBold, fontSize = 14.sp)
                        }
                    } else {
                        OutlinedButton(
                            onClick = onEndShift,
                            border = BorderStroke(1.5.dp, AmberGold),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("■ End shift", color = AmberGold, fontWeight = FontWeight.ExtraBold, fontSize = 14.sp)
                        }
                    }

                    if (hasActive) {
                        Spacer(modifier = Modifier.height(12.dp))
                        HorizontalDivider(color = BorderSubtle.copy(alpha = 0.5f))
                        Spacer(modifier = Modifier.height(10.dp))
                        Text(
                            text = "LOG COMPLETED RIDE TO THIS SHIFT",
                            color = TextSecondary,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.7.sp,
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedTextField(
                                value = tripFareInput,
                                onValueChange = { tripFareInput = it },
                                placeholder = { Text("Fare $ (e.g. 24.50)", color = TextMuted, fontSize = 12.sp) },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(
                                    keyboardType = KeyboardType.Decimal,
                                    imeAction = ImeAction.Next,
                                ),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = EmeraldCyan,
                                    unfocusedBorderColor = BorderSubtle,
                                    focusedTextColor = TextPrimary,
                                    unfocusedTextColor = TextPrimary,
                                ),
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = tripMilesInput,
                                onValueChange = { tripMilesInput = it },
                                placeholder = { Text("Miles (e.g. 8.2)", color = TextMuted, fontSize = 12.sp) },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(
                                    keyboardType = KeyboardType.Decimal,
                                    imeAction = ImeAction.Done,
                                ),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = EmeraldCyan,
                                    unfocusedBorderColor = BorderSubtle,
                                    focusedTextColor = TextPrimary,
                                    unfocusedTextColor = TextPrimary,
                                ),
                                modifier = Modifier.weight(1f),
                            )
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = {
                                val fare = tripFareInput.toDoubleOrNull()
                                val miles = tripMilesInput.toDoubleOrNull() ?: 0.0
                                if (fare != null && fare > 0.0) {
                                    onLogTrip(fare, miles, tripNoteInput)
                                    tripFareInput = ""
                                    tripMilesInput = ""
                                    tripNoteInput = ""
                                }
                            },
                            border = BorderStroke(1.dp, EmeraldCyan),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("+ Log Completed Ride ($)", color = EmeraldCyan, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }

        // 2. Estimated Earnings After Driving Costs & Past Sessions (UI-01, UI-16, N11)
        shiftState?.let { ledger ->
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "ESTIMATED EARNINGS AFTER DRIVING COSTS PER ONLINE HOUR",
                                    color = TextSecondary,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    letterSpacing = 0.8.sp,
                                )
                                Text(
                                    text = if (ledger.calibratedMedianNetPerHour != null) {
                                        "Includes unpaid waiting & empty driving miles"
                                    } else {
                                        "Not available yet — log start and end mileage on a shift to calculate"
                                    },
                                    color = TextPrimary,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                            ledger.calibratedMedianNetPerHour?.let { med ->
                                Text(
                                    text = "$${String.format(Locale.US, "%.2f", med)}/hr",
                                    color = EmeraldCyan,
                                    fontWeight = FontWeight.ExtraBold,
                                    fontSize = 16.sp,
                                    fontFamily = FontFamily.Monospace,
                                )
                            } ?: Text(
                                text = "Not logged",
                                color = AmberGold,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp,
                            )
                        }
                    }
                }
            }

            if (ledger.sessions.isNotEmpty()) {
                item {
                    Text(
                        text = "PAST SHIFT ARCHIVE",
                        color = TextSecondary,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 0.8.sp,
                        modifier = Modifier.padding(start = 4.dp, top = 2.dp),
                    )
                }
            }

            items(ledger.sessions, key = { it.date }) { sess ->
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, BorderSubtle),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(
                            modifier = Modifier
                                .weight(1f)
                                .padding(end = 10.dp),
                        ) {
                            Text(
                                text = "${sess.weekday} · ${sess.date}",
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 15.sp,
                            )
                            Text(
                                text = "${sess.trips} rides · ${String.format(Locale.US, "%.1f", sess.paidMiles)} paid mi",
                                color = TextSecondary,
                                fontSize = 12.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = sess.deadheadMiles?.let {
                                    "${String.format(Locale.US, "%.1f", it)} empty mi logged"
                                } ?: "Mileage not logged",
                                color = TextMuted,
                                fontSize = 11.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(
                                text = "$${String.format(Locale.US, "%.2f", sess.grossEarnings)}",
                                color = EmeraldCyan,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 16.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            sess.netPerCommittedHour?.let { netHr ->
                                Text(
                                    text = "$${String.format(Locale.US, "%.2f", netHr)}/hr est. net",
                                    color = RadarBlue,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            } ?: if (sess.trips > 0 && sess.grossEarnings > 0.0) {
                                Text(
                                    text = "$${String.format(Locale.US, "%.2f", sess.grossEarnings / sess.trips)}/ride",
                                    color = RadarBlue,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            } else {
                                Text(
                                    text = "Trip earnings",
                                    color = TextMuted,
                                    fontSize = 11.sp,
                                )
                            }
                            if (sess.paidMiles > 0.0 && sess.grossEarnings > 0.0) {
                                Text(
                                    text = "$${String.format(Locale.US, "%.2f", sess.grossEarnings / sess.paidMiles)}/paid mi",
                                    color = TextSecondary,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun RouteBasisPill(basis: String) {
    val isLive = basis.contains("live", ignoreCase = true)
    Surface(
        color = if (isLive) EmeraldDim else BgCardElevated,
        shape = RoundedCornerShape(6.dp),
    ) {
        Text(
            text = if (isLive) "LIVE TRAFFIC" else basis.uppercase(),
            color = if (isLive) EmeraldCyan else TextSecondary,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

private fun isUsableGpsFix(loc: Location?): Boolean {
    if (loc == null) return false
    val ageMs = System.currentTimeMillis() - loc.time
    if (loc.time <= 0L || ageMs > 120_000L || ageMs < -30_000L) return false
    if (loc.hasAccuracy() && loc.accuracy > 250f) return false
    return true
}

@SuppressLint("MissingPermission")
private suspend fun readDeviceLocation(context: Context): Location? =
    suspendCancellableCoroutine { cont ->
        val mgr = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
        if (mgr == null) {
            cont.resume(null)
            return@suspendCancellableCoroutine
        }
        val provider = when {
            mgr.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            mgr.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            else -> null
        }
        if (provider == null) {
            val fallback = runCatching {
                mgr.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.takeIf { isUsableGpsFix(it) }
                    ?: mgr.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.takeIf { isUsableGpsFix(it) }
            }.getOrNull()
            cont.resume(fallback)
            return@suspendCancellableCoroutine
        }
        val signal = CancellationSignal()
        cont.invokeOnCancellation { signal.cancel() }
        runCatching {
            mgr.getCurrentLocation(
                provider,
                signal,
                context.mainExecutor
            ) { loc ->
                if (cont.isActive) {
                    val validLoc = loc?.takeIf { isUsableGpsFix(it) }
                        ?: runCatching { mgr.getLastKnownLocation(provider)?.takeIf { isUsableGpsFix(it) } }.getOrNull()
                    cont.resume(validLoc)
                }
            }
        }.onFailure {
            if (cont.isActive) {
                cont.resume(runCatching { mgr.getLastKnownLocation(provider)?.takeIf { isUsableGpsFix(it) } }.getOrNull())
            }
        }
    }
