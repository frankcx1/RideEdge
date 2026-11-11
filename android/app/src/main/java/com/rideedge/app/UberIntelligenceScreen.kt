package com.rideedge.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Locale

private val UiBgDeep = Color(0xFF0A0E14)
private val UiBgCard = Color(0xFF121924)
private val UiBgCardElevated = Color(0xFF182232)
private val UiBorderSubtle = Color(0xFF26354A)
private val UiEmeraldCyan = Color(0xFF10B981)
private val UiEmeraldDim = Color(0xFF063E2E)
private val UiAmberGold = Color(0xFFF59E0B)
private val UiAmberDim = Color(0xFF422C06)
private val UiCoralRed = Color(0xFFEF4444)
private val UiCoralDim = Color(0xFF451212)
private val UiRadarBlue = Color(0xFF38BDF8)
private val UiRadarDim = Color(0xFF0C314E)
private val UiTextPrimary = Color(0xFFF1F5F9)
private val UiTextSecondary = Color(0xFF94A3B8)
private val UiTextMuted = Color(0xFF64748B)

@Composable
fun UberIntelligenceScreen(
    initialPasteText: String = "",
    initialSection: String = "all",
    seedHistoryForDemo: Boolean = false, // Ignored for personal storage safety (UIA07)
    storeFileName: String = "uber_assistant_imports_v1.json",
    initialEditDriveText: String? = null,
    initialEditWaitExactText: String? = null,
    initialClearPasteAfterParse: Boolean = false,
    currentHereState: HereState? = null,
    hasActiveWaitEpisode: Boolean = false,
    onComparisonSaved: ((UberIntelligence.DecisionComparisonRecord) -> Unit)? = null,
) {
    val context = LocalContext.current
    val repository = remember(context, storeFileName) {
        UberIntelligenceRepository(File(context.filesDir, storeFileName))
    }
    var storageHealth by remember { mutableStateOf(repository.inspectStorageHealth()) }
    var savedImports by remember { mutableStateOf(repository.listImports()) }
    var savedComparisons by remember { mutableStateOf(repository.listComparisons()) }
    var latestSavedComparison by remember { mutableStateOf(savedComparisons.lastOrNull { it.targetType == "now" }) }

    var selectedSection by rememberSaveable {
        mutableStateOf(
            if (initialPasteText.isNotBlank() && initialSection == "all") "review" else initialSection
        )
    }

    val catalog = UberIntelligence.PROMPT_CATALOG
    var selectedPromptId by rememberSaveable { mutableStateOf("CONTEXT") }
    var promptText by rememberSaveable {
        mutableStateOf(UberIntelligence.buildDecisionContextPrompt(currentHereState))
    }
    var promptConfirmedSent by rememberSaveable { mutableStateOf(false) }
    var howToUseExpanded by rememberSaveable { mutableStateOf(false) }

    val resolvedInitialPaste = if (initialPasteText == "__DEMO_REVIEW__") {
        ""
    } else {
        initialPasteText
    }
    val initialParsed = remember(resolvedInitialPaste) {
        if (resolvedInitialPaste.isNotBlank()) {
            UberIntelligence.parseAssistantResponse(
                rawResponse = resolvedInitialPaste,
                userPrompt = promptText,
            )
        } else {
            null
        }
    }
    var pastedText by rememberSaveable {
        mutableStateOf(if (initialClearPasteAfterParse) "" else resolvedInitialPaste)
    }
    var activeReviewImport by remember { mutableStateOf(initialParsed) }
    val observationEdits = remember {
        mutableStateMapOf<String, UberIntelligence.ObservationEdit>().apply {
            val firstObs = initialParsed?.observations?.firstOrNull()
            if (firstObs != null && (!initialEditDriveText.isNullOrBlank() || !initialEditWaitExactText.isNullOrBlank())) {
                val parsedDrive = initialEditDriveText?.trim()?.toDoubleOrNull()
                val parsedWait = initialEditWaitExactText?.trim()?.toDoubleOrNull()
                put(
                    firstObs.id,
                    UberIntelligence.ObservationEdit(
                        driveMinutes = parsedDrive ?: firstObs.driveMinutes,
                        waitMinutesExact = parsedWait ?: firstObs.waitMinutesExact,
                    ),
                )
            }
        }
    }
    val invalidFieldErrors = remember {
        mutableStateMapOf<String, String>().apply {
            val firstObs = initialParsed?.observations?.firstOrNull()
            if (firstObs != null) {
                val waitTrimmed = initialEditWaitExactText?.trim().orEmpty()
                if (waitTrimmed.isNotEmpty()) {
                    val v = waitTrimmed.toDoubleOrNull()
                    if (v == null || !v.isFinite() || v < 0.0) {
                        put(firstObs.id, "Exact wait must be a finite number >= 0 (got '$waitTrimmed').")
                    }
                }
            }
        }
    }
    var reviewNotes by rememberSaveable { mutableStateOf("") }
    var showRawInReview by rememberSaveable { mutableStateOf(false) }
    var editingObsId by rememberSaveable {
        mutableStateOf<String?>(
            initialParsed?.observations?.firstOrNull()?.id?.takeIf {
                !initialEditDriveText.isNullOrBlank() || !initialEditWaitExactText.isNullOrBlank()
            }
        )
    }

    var duplicateBlockedResult by remember { mutableStateOf<UberIntelligence.SaveImportResult?>(null) }
    var statusMessage by rememberSaveable { mutableStateOf<String?>(null) }
    var statusIsWarning by rememberSaveable { mutableStateOf(false) }
    var confirmDeleteAll by rememberSaveable { mutableStateOf(false) }
    var expandedHistoryIds by remember { mutableStateOf(setOf<String>()) }

    val promptStatus = UberIntelligence.evaluatePromptLength(promptText)
    val reviewEditResult = activeReviewImport?.let {
        runCatching {
            UberIntelligence.applyUserReviewEdits(it, observationEdits.toMap(), reviewNotes.ifBlank { null })
        }
    }
    val reviewEditException = reviewEditResult?.exceptionOrNull()
    val effectiveReviewImport = reviewEditResult?.getOrNull() ?: activeReviewImport

    val currentTextRevision = remember(pastedText) {
        if (pastedText.isBlank()) "" else UberIntelligence.computeFingerprint(pastedText).take(16)
    }
    val isDraftRevisionStale = activeReviewImport != null &&
        (pastedText.isBlank() || activeReviewImport?.draftRevision != currentTextRevision)

    val hasValidationBlocker = reviewEditException != null ||
        invalidFieldErrors.values.any { it.isNotBlank() } ||
        effectiveReviewImport?.observations?.any {
            UberIntelligence.FLAG_OUT_OF_RANGE_VALUE in it.warnings
        } == true

    val areaComparisons = remember(savedImports) {
        buildRecentAreaComparisons(savedImports.filterNot { it.isDemoSample || it.suspectedLegacySample })
    }
    val historySummary = remember(savedImports, savedComparisons) {
        UberIntelligence.summarizeHistoryUsefulness(savedImports, savedComparisons)
    }
    val suspectedSampleCount = remember(savedImports) {
        savedImports.count { it.isDemoSample || it.suspectedLegacySample }
    }

    fun copyToClipboard(label: String, text: String, feedback: String) {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
        cm?.setPrimaryClip(ClipData.newPlainText(label, text))
        statusMessage = feedback
        statusIsWarning = false
    }

    fun pasteFromClipboard() {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
        val clip = cm?.primaryClip
        val itemText = if (clip != null && clip.itemCount > 0) {
            clip.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
        } else {
            ""
        }
        if (itemText.isBlank()) {
            statusMessage = "Clipboard is empty — copy a reply from Uber Assistant or type below."
            statusIsWarning = true
        } else {
            pastedText = itemText
            observationEdits.clear()
            invalidFieldErrors.clear()
            duplicateBlockedResult = null
            activeReviewImport = UberIntelligence.parseAssistantResponse(
                rawResponse = itemText,
                userPrompt = promptText,
            )
            selectedSection = "review"
            statusMessage = "Pasted response into local review. Check parsed observations before saving."
            statusIsWarning = false
        }
    }

    fun performSaveImport(reviewImp: UberIntelligence.UberAssistantImport, allowDuplicate: Boolean) {
        if (isDraftRevisionStale) {
            statusMessage = if (pastedText.isBlank()) {
                "Source text was cleared after parsing. Clear draft or paste valid text before saving."
            } else {
                "Source text was changed after parsing. Tap 'Re-parse' before saving."
            }
            statusIsWarning = true
            return
        }
        if (hasValidationBlocker) {
            val detail = reviewEditException?.message
                ?: invalidFieldErrors.values.firstOrNull { it.isNotBlank() }
                ?: "one or more edited metrics are invalid or out of range"
            statusMessage = "Save blocked: $detail. Draft retained."
            statusIsWarning = true
            return
        }
        try {
            val finalized = reviewImp.copy(
                parseStatus = "reviewed",
                promptStatus = when {
                    reviewImp.userPrompt.isNullOrBlank() -> "none"
                    promptConfirmedSent -> "user_confirmed"
                    else -> "suggested_or_copied_unconfirmed"
                },
            )
            val res = repository.saveImport(finalized, allowDuplicate = allowDuplicate)
            if (!res.saved && res.duplicate) {
                duplicateBlockedResult = res
                statusMessage = "Duplicate import blocked — review warning below."
                statusIsWarning = true
            } else {
                savedImports = repository.listImports()
                if (currentHereState != null) {
                    val target = UberIntelligence.buildTargetContextFromHere(currentHereState)
                    val cmp = UberIntelligence.evaluateDecisionComparison(
                        importRecord = res.importRecord,
                        target = target,
                        seenBeforeEpisodeStart = !hasActiveWaitEpisode,
                    )
                    repository.saveComparison(cmp)
                    savedComparisons = repository.listComparisons()
                    latestSavedComparison = cmp
                    onComparisonSaved?.invoke(cmp)
                }
                duplicateBlockedResult = null
                activeReviewImport = null
                observationEdits.clear()
                invalidFieldErrors.clear()
                reviewNotes = ""
                selectedSection = "history"
                statusMessage = "Saved ${res.importRecord.observations.size} observation(s) and evaluated against RideEdge."
                statusIsWarning = false
            }
        } catch (e: Exception) {
            storageHealth = repository.inspectStorageHealth()
            statusMessage = "Save blocked: ${e.message ?: "invalid data or storage error"}. Draft retained."
            statusIsWarning = true
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Compact Header & Parked Safety Guardrail
        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = UiBgCardElevated),
                border = BorderStroke(1.dp, UiBorderSubtle),
                shape = RoundedCornerShape(12.dp),
            ) {
                Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "Uber second opinion",
                                color = UiTextPrimary,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.ExtraBold,
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            Text(
                                text = "Manual paste while parked. Does not change RideEdge recommendations.",
                                color = UiTextSecondary,
                                fontSize = 12.sp,
                            )
                        }
                        Surface(
                            color = UiBgCard,
                            border = BorderStroke(1.dp, UiBorderSubtle),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.clickable { howToUseExpanded = !howToUseExpanded },
                        ) {
                            Text(
                                text = if (howToUseExpanded) "Hide ▴" else "How it works ▾",
                                color = UiRadarBlue,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                            )
                        }
                    }

                    if (howToUseExpanded) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = UiBorderSubtle)
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "1. Copy the question for Uber Assistant.\n" +
                                "2. Paste it in Uber Assistant while parked and copy its reply.\n" +
                                "3. Paste the reply here, check the numbers, and save.\n" +
                                "4. RideEdge shows whether Uber's reply agrees, disagrees, or can't be compared yet.",
                            color = UiTextPrimary,
                            fontSize = 12.sp,
                            lineHeight = 17.sp,
                        )
                    }
                }
            }
        }

        // UIA08: Storage Corruption Recovery Banner
        if (!storageHealth.ok) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = UiCoralDim),
                    border = BorderStroke(1.5.dp, UiCoralRed),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = "⚠️ LOCAL HISTORY STORAGE UNREADABLE (FAIL-CLOSED)",
                            color = UiCoralRed,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.ExtraBold,
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Existing file (${storageHealth.rawByteCount} bytes) could not be parsed (${storageHealth.errorMessage}). Saving is blocked so your existing file is never overwritten automatically.",
                            color = UiTextPrimary,
                            fontSize = 12.sp,
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = {
                                val backup = repository.quarantineCorruptStore()
                                storageHealth = repository.inspectStorageHealth()
                                savedImports = repository.listImports()
                                savedComparisons = repository.listComparisons()
                                statusMessage = "Preserved corrupt bytes in ${backup?.name ?: "backup"} and initialized clean store."
                                statusIsWarning = false
                            },
                            border = BorderStroke(1.dp, UiAmberGold),
                            shape = RoundedCornerShape(8.dp),
                        ) {
                            Text("Backup corrupt file & start clean store", color = UiAmberGold, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }

        // UIA07: Suspected Legacy Sample Notice
        if (suspectedSampleCount > 0) {
            item {
                Surface(
                    color = UiAmberDim,
                    border = BorderStroke(1.dp, UiAmberGold),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "$suspectedSampleCount suspected demo/sample record(s) isolated",
                                color = UiAmberGold,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = "Excluded from live comparisons and outcome metrics. Review in History or remove.",
                                color = UiTextPrimary,
                                fontSize = 11.sp,
                            )
                        }
                        OutlinedButton(
                            onClick = {
                                val removed = repository.deleteSuspectedSamples()
                                savedImports = repository.listImports()
                                savedComparisons = repository.listComparisons()
                                statusMessage = "Removed $removed suspected sample record(s)."
                                statusIsWarning = false
                            },
                            border = BorderStroke(1.dp, UiAmberGold),
                            shape = RoundedCornerShape(8.dp),
                        ) {
                            Text("Remove samples", color = UiAmberGold, fontSize = 11.sp)
                        }
                    }
                }
            }
        }

        // Status Feedback Banner
        statusMessage?.let { msg ->
            item {
                Surface(
                    color = if (statusIsWarning) UiAmberDim else UiEmeraldDim,
                    border = BorderStroke(1.dp, if (statusIsWarning) UiAmberGold else UiEmeraldCyan),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 9.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = msg,
                            color = if (statusIsWarning) UiAmberGold else UiEmeraldCyan,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = "✕",
                            color = UiTextSecondary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier
                                .padding(start = 8.dp)
                                .clickable { statusMessage = null },
                        )
                    }
                }
            }
        }

        // Section selector bar: Add reply · Review · History
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                val reviewCount = effectiveReviewImport?.observations?.size ?: 0
                listOf(
                    "all" to "Add reply",
                    "review" to if (reviewCount > 0) "Review ($reviewCount)" else "Review",
                    "history" to if (savedImports.isNotEmpty()) "History (${savedImports.size})" else "History",
                ).forEach { (secKey, secLabel) ->
                    val isSel = selectedSection == secKey
                    Surface(
                        color = if (isSel) UiEmeraldDim else UiBgCard,
                        border = BorderStroke(1.dp, if (isSel) UiEmeraldCyan else UiBorderSubtle),
                        shape = RoundedCornerShape(9.dp),
                        modifier = Modifier
                            .weight(1f)
                            .clickable { selectedSection = secKey },
                    ) {
                        Text(
                            text = secLabel,
                            color = if (isSel) UiEmeraldCyan else UiTextSecondary,
                            fontSize = 12.sp,
                            fontWeight = if (isSel) FontWeight.ExtraBold else FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                        )
                    }
                }
            }
        }

        // Only show latest saved comparison on Add reply (never above a Review draft or on History)
        if (selectedSection == "all" && effectiveReviewImport == null) {
            latestSavedComparison?.let { cmp ->
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            text = "Latest saved reply",
                            color = UiTextMuted,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        CompactSecondOpinionBanner(
                            comparison = cmp,
                            onFeedbackUseful = { useful ->
                                repository.recordPerceivedUsefulness(cmp.id, useful)
                                savedComparisons = repository.listComparisons()
                                latestSavedComparison = savedComparisons.firstOrNull { it.id == cmp.id }
                            },
                        )
                    }
                }
            }
        }

        if (selectedSection == "all") {
            // Step 1 — Copy question for Uber Assistant
            item {
                var moreQuestionsExpanded by rememberSaveable { mutableStateOf(false) }
                Card(
                    colors = CardDefaults.cardColors(containerColor = UiBgCard),
                    border = BorderStroke(1.dp, UiBorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "Step 1 · Copy question for Uber Assistant",
                                color = UiTextPrimary,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.ExtraBold,
                            )
                            Text(
                                text = if (moreQuestionsExpanded) "Hide questions ▴" else "More questions ▾",
                                color = UiRadarBlue,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.clickable { moreQuestionsExpanded = !moreQuestionsExpanded },
                            )
                        }
                        if (moreQuestionsExpanded) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                FilterChip(
                                    selected = selectedPromptId == "CONTEXT",
                                    onClick = {
                                        selectedPromptId = "CONTEXT"
                                        promptText = UberIntelligence.buildDecisionContextPrompt(currentHereState)
                                        promptConfirmedSent = false
                                    },
                                    label = { Text("Current Now decision", fontSize = 12.sp) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = UiEmeraldDim,
                                        selectedLabelColor = UiEmeraldCyan,
                                        containerColor = UiBgCardElevated,
                                        labelColor = UiTextSecondary,
                                    ),
                                )
                                catalog.forEach { item ->
                                    val selected = selectedPromptId == item.id
                                    FilterChip(
                                        selected = selected,
                                        onClick = {
                                            selectedPromptId = item.id
                                            promptText = item.defaultText
                                            promptConfirmedSent = false
                                        },
                                        label = { Text(item.title, fontSize = 12.sp) },
                                        colors = FilterChipDefaults.filterChipColors(
                                            selectedContainerColor = UiEmeraldDim,
                                            selectedLabelColor = UiEmeraldCyan,
                                            containerColor = UiBgCardElevated,
                                            labelColor = UiTextSecondary,
                                        ),
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        OutlinedTextField(
                            value = promptText,
                            onValueChange = {
                                promptText = it
                                promptConfirmedSent = false
                            },
                            label = { Text("Question to ask Uber Assistant", fontSize = 11.sp) },
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = UiEmeraldCyan,
                                unfocusedBorderColor = UiBorderSubtle,
                                focusedTextColor = UiTextPrimary,
                                unfocusedTextColor = UiTextPrimary,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        )

                        if (promptStatus.level != "ok") {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = promptStatus.note,
                                color = if (promptStatus.level == "warn") UiAmberGold else UiCoralRed,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Button(
                                onClick = {
                                    copyToClipboard(
                                        "RideEdge Question",
                                        promptText,
                                        "Copied question. Paste it in Uber Assistant.",
                                    )
                                },
                                enabled = promptText.isNotBlank(),
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = UiEmeraldCyan,
                                    contentColor = Color(0xFF041410),
                                ),
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Copy question", fontWeight = FontWeight.ExtraBold, fontSize = 13.sp)
                            }
                            OutlinedButton(
                                onClick = {
                                    promptText = if (selectedPromptId == "CONTEXT") {
                                        UberIntelligence.buildDecisionContextPrompt(currentHereState)
                                    } else {
                                        catalog.firstOrNull { it.id == selectedPromptId }?.defaultText
                                            ?: catalog.first().defaultText
                                    }
                                    promptConfirmedSent = false
                                },
                                border = BorderStroke(1.dp, UiBorderSubtle),
                                shape = RoundedCornerShape(10.dp),
                            ) {
                                Text("Reset", color = UiTextSecondary, fontSize = 12.sp)
                            }
                        }
                    }
                }
            }

            // Step 2 — Paste Uber Assistant reply
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = UiBgCard),
                    border = BorderStroke(1.dp, UiBorderSubtle),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Text(
                            text = "Step 2 · Paste Uber Assistant reply",
                            color = UiTextPrimary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.ExtraBold,
                        )

                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Button(
                                onClick = { pasteFromClipboard() },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = UiRadarBlue,
                                    contentColor = Color(0xFF04141C),
                                ),
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Paste reply", fontWeight = FontWeight.ExtraBold, fontSize = 13.sp)
                            }
                            OutlinedButton(
                                onClick = {
                                    observationEdits.clear()
                                    invalidFieldErrors.clear()
                                    duplicateBlockedResult = null
                                    activeReviewImport = UberIntelligence.parseAssistantResponse(
                                        rawResponse = pastedText,
                                        userPrompt = promptText,
                                    )
                                    selectedSection = "review"
                                },
                                enabled = pastedText.isNotBlank(),
                                border = BorderStroke(1.dp, UiEmeraldCyan),
                                shape = RoundedCornerShape(10.dp),
                            ) {
                                Text("Review reply", color = UiEmeraldCyan, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            }
                            if (pastedText.isNotBlank() || activeReviewImport != null) {
                                OutlinedButton(
                                    onClick = {
                                        pastedText = ""
                                        activeReviewImport = null
                                        observationEdits.clear()
                                        invalidFieldErrors.clear()
                                        duplicateBlockedResult = null
                                        reviewNotes = ""
                                    },
                                    border = BorderStroke(1.dp, UiBorderSubtle),
                                    shape = RoundedCornerShape(10.dp),
                                ) {
                                    Text("Clear", color = UiTextSecondary, fontSize = 12.sp)
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedTextField(
                            value = pastedText,
                            onValueChange = { pastedText = it },
                            placeholder = {
                                Text(
                                    "Paste Uber Assistant reply here",
                                    color = UiTextMuted,
                                    fontSize = 12.sp,
                                )
                            },
                            minLines = 3,
                            maxLines = 7,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = UiRadarBlue,
                                unfocusedBorderColor = UiBorderSubtle,
                                focusedTextColor = UiTextPrimary,
                                unfocusedTextColor = UiTextPrimary,
                            ),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        }

        // Review before save
        if (selectedSection == "review") {
            if (effectiveReviewImport == null) {
                item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = UiBgCard),
                        border = BorderStroke(1.dp, UiBorderSubtle),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Text(
                            text = "No reply in review yet. Tap 'Add reply' to paste an Uber Assistant response.",
                            color = UiTextSecondary,
                            fontSize = 12.sp,
                            modifier = Modifier.padding(16.dp),
                        )
                    }
                }
            }
            effectiveReviewImport?.let { reviewImp ->
                item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = UiBgCardElevated),
                        border = BorderStroke(1.5.dp, UiAmberGold.copy(alpha = 0.75f)),
                        shape = RoundedCornerShape(14.dp),
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            val headerStateLabel = when {
                                isDraftRevisionStale -> "Reply text changed · Re-parse required"
                                reviewImp.parseStatus == "reviewed" -> "Edited · Ready to save"
                                else -> "Review extracted numbers"
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = headerStateLabel,
                                        color = if (isDraftRevisionStale) UiCoralRed else UiAmberGold,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                    Text(
                                        text = "${reviewImp.observations.size} area(s) found in this draft",
                                        color = UiTextPrimary,
                                        fontSize = 16.sp,
                                        fontWeight = FontWeight.ExtraBold,
                                    )
                                }
                                Surface(
                                    color = UiBgCard,
                                    border = BorderStroke(1.dp, UiBorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.clickable { showRawInReview = !showRawInReview },
                                ) {
                                    Text(
                                        text = if (showRawInReview) "Hide raw text ▴" else "Raw text ▾",
                                        color = UiTextSecondary,
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                                    )
                                }
                            }

                            if (isDraftRevisionStale) {
                                Spacer(modifier = Modifier.height(8.dp))
                                Surface(
                                    color = UiCoralDim,
                                    border = BorderStroke(1.dp, UiCoralRed),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Row(
                                        modifier = Modifier.padding(10.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = if (pastedText.isBlank()) {
                                                "Reply text was cleared after parsing. Clear draft before saving."
                                            } else {
                                                "Reply text changed after parsing. Re-parse before saving."
                                            },
                                            color = UiTextPrimary,
                                            fontSize = 11.sp,
                                            modifier = Modifier.weight(1f),
                                        )
                                        OutlinedButton(
                                            onClick = {
                                                observationEdits.clear()
                                                invalidFieldErrors.clear()
                                                duplicateBlockedResult = null
                                                activeReviewImport = if (pastedText.isBlank()) {
                                                    null
                                                } else {
                                                    UberIntelligence.parseAssistantResponse(
                                                        rawResponse = pastedText,
                                                        userPrompt = promptText,
                                                    )
                                                }
                                            },
                                            border = BorderStroke(1.dp, UiEmeraldCyan),
                                            shape = RoundedCornerShape(8.dp),
                                        ) {
                                            Text(
                                                if (pastedText.isBlank()) "Clear draft" else "Re-parse",
                                                color = UiEmeraldCyan,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(6.dp))
                            val sourceTimeSummary = when {
                                reviewImp.reportedSourceTime != null -> "Source time: ${reviewImp.reportedSourceTime}"
                                reviewImp.reportedSourceTimeRaw != null -> "Source time (unverified date/timezone): ${reviewImp.reportedSourceTimeRaw}"
                                else -> "Source time unknown"
                            }
                            Text(
                                text = sourceTimeSummary,
                                color = if (reviewImp.reportedSourceTime == null) UiAmberGold else UiTextSecondary,
                                fontSize = 12.sp,
                                fontWeight = if (reviewImp.reportedSourceTime == null) FontWeight.SemiBold else FontWeight.Normal,
                            )

                            if (reviewImp.warnings.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(6.dp))
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .horizontalScroll(rememberScrollState()),
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    reviewImp.warnings.forEach { w ->
                                        WarningBadge(w)
                                    }
                                }
                            }

                            if (UberIntelligence.FLAG_SENSITIVE_TEXT_DETECTED in reviewImp.warnings) {
                                Spacer(modifier = Modifier.height(6.dp))
                                OutlinedButton(
                                    onClick = {
                                        val redacted = UberIntelligence.redactSensitiveText(pastedText)
                                        pastedText = redacted
                                        observationEdits.clear()
                                        duplicateBlockedResult = null
                                        activeReviewImport = UberIntelligence.parseAssistantResponse(
                                            rawResponse = redacted,
                                            userPrompt = promptText,
                                        )
                                        statusMessage = "Redacted sensitive details and re-parsed draft."
                                        statusIsWarning = false
                                    },
                                    border = BorderStroke(1.dp, UiCoralRed),
                                    shape = RoundedCornerShape(8.dp),
                                ) {
                                    Text("🛡 Redact phone/email/coordinates before saving", color = UiCoralRed, fontSize = 12.sp)
                                }
                            }

                            if (showRawInReview) {
                                Spacer(modifier = Modifier.height(8.dp))
                                Surface(
                                    color = UiBgDeep,
                                    border = BorderStroke(1.dp, UiBorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Text(
                                            text = "RAW PASTED RESPONSE (PRESERVED VERBATIM)",
                                            color = UiTextMuted,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Spacer(modifier = Modifier.height(3.dp))
                                        Text(
                                            text = reviewImp.rawResponse,
                                            color = UiTextSecondary,
                                            fontSize = 12.sp,
                                            fontFamily = FontFamily.Monospace,
                                        )
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(10.dp))
                            if (reviewImp.observations.isEmpty()) {
                                Surface(
                                    color = UiBgCard,
                                    border = BorderStroke(1.dp, UiBorderSubtle),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text(
                                        text = "No structured area metrics matched automatically. You can still save the raw response snapshot with notes below.",
                                        color = UiTextSecondary,
                                        fontSize = 12.sp,
                                        modifier = Modifier.padding(12.dp),
                                    )
                                }
                            } else {
                                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    reviewImp.observations.forEach { obs ->
                                        ObservationReviewCard(
                                            obs = obs,
                                            isEditing = editingObsId == obs.id,
                                            onToggleEdit = {
                                                editingObsId = if (editingObsId == obs.id) null else obs.id
                                            },
                                            onUpdateEdit = { newEdit ->
                                                observationEdits[obs.id] = newEdit
                                            },
                                            onFieldValidationError = { errMsg ->
                                                if (errMsg.isNullOrBlank()) {
                                                    invalidFieldErrors.remove(obs.id)
                                                } else {
                                                    invalidFieldErrors[obs.id] = errMsg
                                                }
                                            },
                                            currentEdit = observationEdits[obs.id] ?: UberIntelligence.ObservationEdit(),
                                            fieldErrorMessage = invalidFieldErrors[obs.id],
                                        )
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(8.dp))
                            FilterChip(
                                selected = promptConfirmedSent,
                                onClick = { promptConfirmedSent = !promptConfirmedSent },
                                label = {
                                    Text(
                                        if (promptConfirmedSent) {
                                            "✓ Confirmed: I sent the prompt above verbatim"
                                        } else {
                                            "Prompt above is unconfirmed (tap if sent verbatim)"
                                        },
                                        fontSize = 11.sp,
                                    )
                                },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = UiEmeraldDim,
                                    selectedLabelColor = UiEmeraldCyan,
                                    containerColor = UiBgCard,
                                    labelColor = UiTextSecondary,
                                ),
                            )

                            Spacer(modifier = Modifier.height(6.dp))
                            OutlinedTextField(
                                value = reviewNotes,
                                onValueChange = { reviewNotes = it },
                                placeholder = { Text("Optional driver note", color = UiTextMuted, fontSize = 12.sp) },
                                singleLine = true,
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = UiEmeraldCyan,
                                    unfocusedBorderColor = UiBorderSubtle,
                                    focusedTextColor = UiTextPrimary,
                                    unfocusedTextColor = UiTextPrimary,
                                ),
                                modifier = Modifier.fillMaxWidth(),
                            )

                            if (hasValidationBlocker) {
                                val errDetail = reviewEditException?.message
                                    ?: invalidFieldErrors.values.firstOrNull { it.isNotBlank() }
                                    ?: "one or more edited metrics are negative, non-finite, or out of range (0..240 min wait, 0..5000 requests)"
                                Spacer(modifier = Modifier.height(6.dp))
                                Text(
                                    text = "⚠️ Cannot save: $errDetail.",
                                    color = UiCoralRed,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                            }

                            duplicateBlockedResult?.let { dup ->
                                Spacer(modifier = Modifier.height(8.dp))
                                Surface(
                                    color = UiCoralDim,
                                    border = BorderStroke(1.dp, UiCoralRed),
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Text(
                                            text = "⚠️ DUPLICATE IMPORT DETECTED",
                                            color = UiCoralRed,
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.ExtraBold,
                                        )
                                        Text(
                                            text = "This exact response text was already saved (${dup.existingImportId}). Duplicate imports do not multiply outcome evidence.",
                                            color = UiTextPrimary,
                                            fontSize = 12.sp,
                                        )
                                        Spacer(modifier = Modifier.height(6.dp))
                                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                            OutlinedButton(
                                                onClick = { performSaveImport(reviewImp, allowDuplicate = true) },
                                                border = BorderStroke(1.dp, UiAmberGold),
                                                shape = RoundedCornerShape(8.dp),
                                            ) {
                                                Text("Save duplicate anyway", color = UiAmberGold, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                            }
                                            OutlinedButton(
                                                onClick = { duplicateBlockedResult = null },
                                                border = BorderStroke(1.dp, UiBorderSubtle),
                                                shape = RoundedCornerShape(8.dp),
                                            ) {
                                                Text("Cancel", color = UiTextSecondary, fontSize = 12.sp)
                                            }
                                        }
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(10.dp))
                            Button(
                                onClick = { performSaveImport(reviewImp, allowDuplicate = false) },
                                enabled = !isDraftRevisionStale && !hasValidationBlocker && storageHealth.ok,
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = UiEmeraldCyan,
                                    contentColor = Color(0xFF041410),
                                ),
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text("Save reply", fontWeight = FontWeight.ExtraBold, fontSize = 14.sp)
                            }
                        }
                    }
                }
            }
        }

        if (selectedSection == "history") {
            val ratedCmps = savedComparisons.filter { it.userPerceivedUseful != null }
            val helpfulCount = ratedCmps.count { it.userPerceivedUseful == true }
            val linkedEpisodeCmps = savedComparisons
                .filter { !it.linkedEpisodeId.isNullOrBlank() && it.targetType == "now" }
                .distinctBy { it.linkedEpisodeId }

            // Simplified 4-line Summary Card + Expandable "How this is calculated" (Section 6)
            item {
                HistoryUsefulnessDashboardCard(
                    summary = historySummary,
                    helpfulCount = helpfulCount,
                    ratedCount = ratedCmps.size,
                )
            }

            // Tracked wait episodes (compact scannable rows with Helpful Yes/No and Details)
            if (linkedEpisodeCmps.isNotEmpty()) {
                item {
                    Text(
                        text = "Tracked waits (${linkedEpisodeCmps.size})",
                        color = UiTextPrimary,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                }
                items(linkedEpisodeCmps, key = { "ep-${it.id}-${it.linkedEpisodeId}" }) { epCmp ->
                    var epExpanded by rememberSaveable(epCmp.id) { mutableStateOf(false) }
                    val friendlyVerdict = when (epCmp.verdict) {
                        UberIntelligence.VERDICT_SUPPORTS -> "Agreed"
                        UberIntelligence.VERDICT_CHALLENGES -> "Disagreed"
                        else -> "Couldn't compare"
                    }
                    val verdictColor = when (epCmp.verdict) {
                        UberIntelligence.VERDICT_SUPPORTS -> UiEmeraldCyan
                        UberIntelligence.VERDICT_CHALLENGES -> UiAmberGold
                        else -> UiRadarBlue
                    }
                    val timeShort = epCmp.evaluatedAt.drop(11).take(5).ifBlank { "recent" }
                    val outcomeSummary = when {
                        epCmp.acceptedRide && epCmp.waitMinutesToRequest != null ->
                            "Request after ${epCmp.waitMinutesToRequest.toInt()} min · ride accepted"
                        epCmp.acceptedRide ->
                            "Ride accepted"
                        epCmp.outcomeStatus in setOf("request_within_15m", "request_after_15m") && epCmp.waitMinutesToRequest != null ->
                            "Request after ${epCmp.waitMinutesToRequest.toInt()} min"
                        epCmp.outcomeStatus in setOf("no_request_after_15m", "observed_15m_no_request", "dry_wait_15m") ->
                            "15 min wait · no request"
                        epCmp.outcomeStatus == "waiting" ->
                            "Wait in progress"
                        else ->
                            epCmp.outcomeStatus.replace('_', ' ')
                    }
                    Card(
                        colors = CardDefaults.cardColors(containerColor = UiBgCard),
                        border = BorderStroke(1.dp, UiBorderSubtle),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "${epCmp.targetLabel} · $timeShort · $friendlyVerdict",
                                        color = UiTextPrimary,
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    Text(
                                        text = outcomeSummary,
                                        color = verdictColor,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                }
                                Text(
                                    text = if (epExpanded) "Hide ▴" else "Details ▾",
                                    color = UiRadarBlue,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier
                                        .padding(start = 8.dp)
                                        .clickable { epExpanded = !epExpanded },
                                )
                            }
                            Spacer(modifier = Modifier.height(6.dp))
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Text("Helpful:", color = UiTextMuted, fontSize = 11.sp)
                                FilterChip(
                                    selected = epCmp.userPerceivedUseful == true,
                                    onClick = {
                                        repository.recordPerceivedUsefulness(epCmp.id, true)
                                        savedComparisons = repository.listComparisons()
                                    },
                                    label = { Text("Yes", fontSize = 11.sp) },
                                )
                                FilterChip(
                                    selected = epCmp.userPerceivedUseful == false,
                                    onClick = {
                                        repository.recordPerceivedUsefulness(epCmp.id, false)
                                        savedComparisons = repository.listComparisons()
                                    },
                                    label = { Text("No", fontSize = 11.sp) },
                                )
                            }
                            if (epExpanded) {
                                Spacer(modifier = Modifier.height(6.dp))
                                HorizontalDivider(color = UiBorderSubtle)
                                Spacer(modifier = Modifier.height(6.dp))
                                Text(
                                    text = epCmp.explanation,
                                    color = UiTextSecondary,
                                    fontSize = 12.sp,
                                )
                                Text(
                                    text = "Driver action: ${epCmp.driverChoice} · Source time: ${epCmp.sourceTime ?: "unknown"} · Evaluated: ${epCmp.evaluatedAt.take(19).replace('T', ' ')}",
                                    color = UiTextMuted,
                                    fontSize = 11.sp,
                                )
                            }
                        }
                    }
                }
            }

            // Saved replies header & actions
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "Saved replies (${savedImports.size})",
                        color = UiTextPrimary,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                    if (savedImports.isNotEmpty()) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Surface(
                                color = UiBgCardElevated,
                                border = BorderStroke(1.dp, UiBorderSubtle),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.clickable {
                                    runCatching { repository.exportJson() }
                                        .onSuccess { json ->
                                            copyToClipboard(
                                                "RideEdge Intelligence Export",
                                                json,
                                                "Copied ${savedImports.size} saved reply record(s) as JSON.",
                                            )
                                        }
                                        .onFailure { err ->
                                            statusMessage = "Export failed: ${err.message}"
                                            statusIsWarning = true
                                        }
                                },
                            ) {
                                Text(
                                    text = "Export",
                                    color = UiRadarBlue,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                                )
                            }
                            Surface(
                                color = UiCoralDim,
                                border = BorderStroke(1.dp, UiCoralRed.copy(alpha = 0.6f)),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.clickable { confirmDeleteAll = !confirmDeleteAll },
                            ) {
                                Text(
                                    text = if (confirmDeleteAll) "Cancel" else "Delete all",
                                    color = UiCoralRed,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                                )
                            }
                        }
                    }
                }
                if (confirmDeleteAll) {
                    Spacer(modifier = Modifier.height(6.dp))
                    OutlinedButton(
                        onClick = {
                            runCatching {
                                val deleted = repository.deleteAllImports()
                                savedImports = emptyList()
                                savedComparisons = emptyList()
                                latestSavedComparison = null
                                confirmDeleteAll = false
                                statusMessage = "Deleted all $deleted saved replies."
                                statusIsWarning = false
                            }.onFailure { err ->
                                statusMessage = "Delete failed: ${err.message}"
                                statusIsWarning = true
                            }
                        },
                        border = BorderStroke(1.dp, UiCoralRed),
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Confirm delete all (${savedImports.size})", color = UiCoralRed, fontWeight = FontWeight.ExtraBold)
                    }
                }
            }

            if (savedImports.isEmpty()) {
                item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = UiBgCard),
                        border = BorderStroke(1.dp, UiBorderSubtle),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Text(
                            text = "No Uber replies saved yet. Use 'Add reply' to copy a question and paste Uber Assistant's answer.",
                            color = UiTextSecondary,
                            fontSize = 13.sp,
                            modifier = Modifier.padding(16.dp),
                        )
                    }
                }
            } else {
                items(savedImports, key = { it.id }) { imp ->
                    val isExpanded = expandedHistoryIds.contains(imp.id)
                    val linkedCmp = savedComparisons.firstOrNull { it.importId == imp.id && it.targetType == "now" }
                    val areasLine = imp.observations.joinToString(" · ") { obs ->
                        "${obs.areaLabel}: ${UberIntelligence.formatWaitDisplay(obs)}"
                    }.ifBlank { "No structured area wait extracted" }
                    Card(
                        colors = CardDefaults.cardColors(containerColor = UiBgCard),
                        border = BorderStroke(
                            1.dp,
                            if (imp.isDemoSample || imp.suspectedLegacySample) UiAmberGold.copy(alpha = 0.6f) else UiBorderSubtle
                        ),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = areasLine,
                                        color = UiTextPrimary,
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.Bold,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    val srcLine = imp.reportedSourceTime?.take(16)?.replace('T', ' ') ?: "Source time unknown"
                                    val cmpShort = when (linkedCmp?.verdict) {
                                        UberIntelligence.VERDICT_SUPPORTS -> " · Agreed"
                                        UberIntelligence.VERDICT_CHALLENGES -> " · Disagreed"
                                        UberIntelligence.VERDICT_INSUFFICIENT -> " · Couldn't compare"
                                        else -> ""
                                    }
                                    Text(
                                        text = "$srcLine$cmpShort",
                                        color = UiTextSecondary,
                                        fontSize = 11.sp,
                                    )
                                }
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Surface(
                                        color = UiBgCardElevated,
                                        border = BorderStroke(1.dp, UiBorderSubtle),
                                        shape = RoundedCornerShape(6.dp),
                                        modifier = Modifier.clickable {
                                            expandedHistoryIds = if (isExpanded) {
                                                expandedHistoryIds - imp.id
                                            } else {
                                                expandedHistoryIds + imp.id
                                            }
                                        },
                                    ) {
                                        Text(
                                            text = if (isExpanded) "Hide ▴" else "Details ▾",
                                            color = UiRadarBlue,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        )
                                    }
                                    Surface(
                                        color = UiCoralDim,
                                        shape = RoundedCornerShape(6.dp),
                                        modifier = Modifier.clickable {
                                            runCatching {
                                                repository.deleteImport(imp.id)
                                                savedImports = repository.listImports()
                                                savedComparisons = repository.listComparisons()
                                                statusMessage = "Deleted reply."
                                                statusIsWarning = false
                                            }.onFailure { err ->
                                                statusMessage = "Delete failed: ${err.message}"
                                                statusIsWarning = true
                                            }
                                        },
                                    ) {
                                        Text(
                                            text = "Delete",
                                            color = UiCoralRed,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        )
                                    }
                                }
                            }

                            if (isExpanded) {
                                Spacer(modifier = Modifier.height(8.dp))
                                HorizontalDivider(color = UiBorderSubtle)
                                Spacer(modifier = Modifier.height(6.dp))
                                imp.observations.forEach { obs ->
                                    val reqText = obs.requests30m?.let {
                                        if (obs.requestsIsApproximate) "~$it requests (30m)" else "$it requests (30m)"
                                    } ?: "Requests: N/A"
                                    Text(
                                        text = "• ${obs.areaLabel}: $reqText · Wait: ${UberIntelligence.formatWaitDisplay(obs)}",
                                        color = UiTextSecondary,
                                        fontSize = 12.sp,
                                    )
                                }
                                Spacer(modifier = Modifier.height(6.dp))
                                Surface(
                                    color = UiBgDeep,
                                    border = BorderStroke(1.dp, UiBorderSubtle),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Text(
                                            text = "Raw reply text",
                                            color = UiTextMuted,
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Bold,
                                        )
                                        Text(
                                            text = imp.rawResponse,
                                            color = UiTextSecondary,
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
    }
}

@Composable
fun CompactSecondOpinionBanner(
    comparison: UberIntelligence.DecisionComparisonRecord,
    nowInstant: Instant = Instant.now(),
    onOpenIntelTab: (() -> Unit)? = null,
    onFeedbackUseful: ((Boolean) -> Unit)? = null,
) {
    if (!UberIntelligence.UBER_ASSISTANT_COMPARISON_DISPLAY_ENABLED) return

    // Live display-time freshness check (Section 5.2)
    val isExpiredNow = comparison.expiresAt?.let { exp ->
        runCatching { Instant.parse(exp).isBefore(nowInstant) }.getOrDefault(false)
    } ?: false

    val effectiveVerdict = if (isExpiredNow && comparison.verdict != UberIntelligence.VERDICT_INSUFFICIENT) {
        UberIntelligence.VERDICT_INSUFFICIENT
    } else {
        comparison.verdict
    }
    val plainVerdictWord = when (effectiveVerdict) {
        UberIntelligence.VERDICT_SUPPORTS -> "Agrees"
        UberIntelligence.VERDICT_CHALLENGES -> "Disagrees"
        else -> "Can't compare yet"
    }
    val sourceAgeLabel = comparison.sourceTime?.let { srcIso ->
        runCatching {
            val mins = Duration.between(OffsetDateTime.parse(srcIso).toInstant(), nowInstant).toMinutes().coerceAtLeast(0L)
            "${mins}m old"
        }.getOrNull()
    }
    val compactReason = when {
        isExpiredNow && comparison.verdict != UberIntelligence.VERDICT_INSUFFICIENT -> "Source expired (>15m old)"
        comparison.reasonCode == "SOURCE_STALE" -> "Source expired (${comparison.sourceAgeMinutesAtEval ?: 16}m old)"
        comparison.reasonCode == "SOURCE_TIME_UNKNOWN" -> "Source time unknown"
        comparison.reasonCode == "AREA_MISMATCH" -> "Different area reported"
        comparison.reasonCode == "CONTRADICTORY_ASSERTIONS" -> "Conflicting numbers in reply"
        sourceAgeLabel != null -> sourceAgeLabel
        else -> comparison.targetLabel
    }
    val effectiveExplanation = if (isExpiredNow && comparison.verdict != UberIntelligence.VERDICT_INSUFFICIENT) {
        "This Uber Assistant reply is older than ${UberIntelligence.DEFAULT_MAX_SOURCE_AGE_MINUTES} minutes and is no longer used for live comparison."
    } else {
        comparison.explanation
    }

    val (badgeBg, badgeFg) = when (effectiveVerdict) {
        UberIntelligence.VERDICT_SUPPORTS -> UiEmeraldDim to UiEmeraldCyan
        UberIntelligence.VERDICT_CHALLENGES -> UiAmberDim to UiAmberGold
        else -> UiRadarDim to UiRadarBlue
    }

    var detailsExpanded by rememberSaveable(comparison.id) { mutableStateOf(false) }

    Card(
        colors = CardDefaults.cardColors(containerColor = UiBgCardElevated),
        border = BorderStroke(1.dp, badgeFg.copy(alpha = 0.65f)),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .clickable { detailsExpanded = !detailsExpanded },
    ) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    color = badgeBg,
                    shape = RoundedCornerShape(6.dp),
                ) {
                    Text(
                        text = plainVerdictWord,
                        color = badgeFg,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.ExtraBold,
                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                    )
                }
                Text(
                    text = "Uber second opinion · $compactReason",
                    color = UiTextPrimary,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = if (detailsExpanded) "Hide ▴" else "Details ▾",
                    color = UiRadarBlue,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            if (detailsExpanded) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = effectiveExplanation,
                    color = UiTextSecondary,
                    fontSize = 12.sp,
                    lineHeight = 16.sp,
                )
                comparison.scopeNote?.let { note ->
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = note,
                        color = UiAmberGold,
                        fontSize = 11.sp,
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "Source time: ${comparison.sourceTime ?: "unknown"} · Checked: ${comparison.evaluatedAt.take(19).replace('T', ' ')}",
                    color = UiTextMuted,
                    fontSize = 11.sp,
                )
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 6.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (onFeedbackUseful != null) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("Helpful:", color = UiTextMuted, fontSize = 11.sp)
                            FilterChip(
                                selected = comparison.userPerceivedUseful == true,
                                onClick = { onFeedbackUseful(true) },
                                label = { Text("Yes", fontSize = 10.sp) },
                            )
                            FilterChip(
                                selected = comparison.userPerceivedUseful == false,
                                onClick = { onFeedbackUseful(false) },
                                label = { Text("No", fontSize = 10.sp) },
                            )
                        }
                    }
                    if (onOpenIntelTab != null) {
                        Text(
                            text = "Uber second opinion ›",
                            color = UiRadarBlue,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.clickable { onOpenIntelTab() },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun HistoryUsefulnessDashboardCard(
    summary: UberIntelligence.HistoryUsefulSummary,
    helpfulCount: Int = 0,
    ratedCount: Int = 0,
) {
    var rulesExpanded by rememberSaveable { mutableStateOf(false) }
    Card(
        colors = CardDefaults.cardColors(containerColor = UiBgCardElevated),
        border = BorderStroke(1.dp, UiBorderSubtle),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Summary",
                    color = UiTextPrimary,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.ExtraBold,
                )
                Text(
                    text = if (rulesExpanded) "Hide calculation ▴" else "How this is calculated ▾",
                    color = UiRadarBlue,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.clickable { rulesExpanded = !rulesExpanded },
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "Replies available for comparison: ${summary.usableForComparisonCount} of ${summary.totalUniqueImports}",
                color = UiTextPrimary,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "Agreed: ${summary.supportsCount} · Disagreed: ${summary.challengesCount} · Couldn't compare: ${summary.insufficientCount}",
                color = UiTextSecondary,
                fontSize = 12.sp,
            )
            Text(
                text = "Tracked waits with enough data: ${summary.adequatelyLoggedCount}",
                color = UiTextSecondary,
                fontSize = 12.sp,
            )
            val fourthLine = if (ratedCount > 0) {
                "You marked helpful: $helpfulCount of $ratedCount rated"
            } else {
                "Not enough tracked waits to judge usefulness yet"
            }
            Text(
                text = fourthLine,
                color = if (ratedCount > 0) UiEmeraldCyan else UiTextMuted,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
            )

            if (rulesExpanded) {
                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider(color = UiBorderSubtle)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Excluded from comparison: missing source time (${summary.unusableMissingTimestampCount}) · expired >15m (${summary.unusableStaleCount}) · different area (${summary.unusableAreaMismatchCount}) · conflicting figures (${summary.unusableContradictoryCount}) · sample/duplicate (${summary.excludedDemoOrDuplicateCount})",
                    color = UiTextSecondary,
                    fontSize = 11.sp,
                )
                val medText = summary.medianMinutesToRequestCompletedOnly?.let { "${it.toInt()} min" } ?: "N/A"
                Text(
                    text = "Outcomes (of ${summary.linkedEpisodesTotal} linked): request ≤15m (${summary.requestWithin15mCount}) · 15m no-request (${summary.verifiedDryWait15mCount}) · accepted ride (${summary.acceptedRideCount}) · median wait to request: $medText",
                    color = UiTextSecondary,
                    fontSize = 11.sp,
                )
                Text(
                    text = "Incomplete waits (${summary.incompleteOrUnknownCount}) and replies imported mid-wait (${summary.seenMidWaitExcludedCount}) are excluded from outcome totals.",
                    color = UiTextMuted,
                    fontSize = 11.sp,
                )
            }
        }
    }
}

@Composable
private fun ObservationReviewCard(
    obs: UberIntelligence.UberAssistantObservation,
    isEditing: Boolean,
    onToggleEdit: () -> Unit,
    onUpdateEdit: (UberIntelligence.ObservationEdit) -> Unit,
    onFieldValidationError: (String?) -> Unit = {},
    currentEdit: UberIntelligence.ObservationEdit,
    fieldErrorMessage: String? = null,
) {
    var provenanceExpanded by rememberSaveable(obs.id) { mutableStateOf(false) }
    Surface(
        color = UiBgCard,
        border = BorderStroke(
            1.dp,
            if (obs.verificationLevel == "contradictory" || UberIntelligence.FLAG_OUT_OF_RANGE_VALUE in obs.warnings) UiCoralRed else UiBorderSubtle
        ),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = obs.areaLabel,
                        color = UiTextPrimary,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                    Text(
                        text = "Source time: ${obs.reportedSourceTime ?: "unknown"}",
                        color = if (obs.reportedSourceTime == null) UiAmberGold else UiTextSecondary,
                        fontSize = 11.sp,
                    )
                }
                Text(
                    text = if (provenanceExpanded) "Hide details ▴" else "Details ▾",
                    color = UiRadarBlue,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.clickable { provenanceExpanded = !provenanceExpanded },
                )
            }

            Spacer(modifier = Modifier.height(6.dp))
            val reqDisplay = obs.requests30m?.let {
                if (obs.requestsIsApproximate) "About $it in last 30 min" else "$it in last 30 min"
            } ?: obs.requestsOtherWindowCount?.let {
                "$it in last ${obs.requestsWindowMinutes ?: "?"} min (not 30 min)"
            } ?: "Not reported"
            val driveDisplay = obs.driveMinutes?.let { "${it.toInt()} min away" } ?: "Not reported"

            Text(
                text = "Requests: $reqDisplay",
                color = UiTextPrimary,
                fontSize = 12.sp,
            )
            Text(
                text = "Reported wait: ${UberIntelligence.formatWaitDisplay(obs)}",
                color = UiTextPrimary,
                fontSize = 12.sp,
            )
            Text(
                text = "Drive time: $driveDisplay",
                color = UiTextSecondary,
                fontSize = 12.sp,
            )

            if (obs.candidateExactWaits.size > 1) {
                Text(
                    text = "Conflicting wait numbers: ${obs.candidateExactWaits.joinToString(" vs ") { "${it.toInt()} min" }}",
                    color = UiCoralRed,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            if (obs.candidateRequests30m.size > 1) {
                Text(
                    text = "Conflicting request counts: ${obs.candidateRequests30m.joinToString(" vs ")}",
                    color = UiCoralRed,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            if (obs.reportedSourceTime == null) {
                Text(
                    text = "Source time unknown",
                    color = UiAmberGold,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            if (provenanceExpanded) {
                Spacer(modifier = Modifier.height(6.dp))
                HorizontalDivider(color = UiBorderSubtle)
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "Provenance: ${obs.provenance} · Verification: ${obs.verificationLevel.replace('_', ' ')}",
                    color = UiTextMuted,
                    fontSize = 11.sp,
                )
                if (!obs.claimedSourceField.isNullOrBlank()) {
                    Text(
                        text = "Claimed field: ${obs.claimedSourceField} (unverified)",
                        color = UiAmberGold,
                        fontSize = 11.sp,
                    )
                }
                if (obs.editedByUser && !obs.originalExtractedJson.isNullOrBlank()) {
                    Text(
                        text = "Original extracted values: ${obs.originalExtractedJson}",
                        color = UiEmeraldCyan,
                        fontSize = 10.sp,
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onToggleEdit,
                    border = BorderStroke(1.dp, UiRadarBlue),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Text(if (isEditing) "Done" else "Edit", color = UiRadarBlue, fontSize = 11.sp)
                }
                OutlinedButton(
                    onClick = {
                        onUpdateEdit(currentEdit.copy(userConfirmed = !currentEdit.userConfirmed))
                    },
                    border = BorderStroke(
                        1.dp,
                        if (currentEdit.userConfirmed) UiEmeraldCyan else UiBorderSubtle
                    ),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Text(
                        if (currentEdit.userConfirmed) "✓ Reviewed" else "Mark reviewed",
                        color = if (currentEdit.userConfirmed) UiEmeraldCyan else UiTextSecondary,
                        fontSize = 11.sp,
                    )
                }
                OutlinedButton(
                    onClick = {
                        onUpdateEdit(currentEdit.copy(declined = true))
                    },
                    border = BorderStroke(1.dp, UiCoralRed.copy(alpha = 0.6f)),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Text("Exclude", color = UiCoralRed, fontSize = 11.sp)
                }
            }

            if (isEditing) {
                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider(color = UiBorderSubtle)
                Spacer(modifier = Modifier.height(8.dp))

                var reqInput by remember(obs.id) { mutableStateOf(obs.requests30m?.toString().orEmpty()) }
                var exactWaitInput by remember(obs.id) { mutableStateOf(obs.waitMinutesExact?.toInt()?.toString().orEmpty()) }
                var lowerWaitInput by remember(obs.id) { mutableStateOf(obs.waitMinutesLowerBound?.toInt()?.toString().orEmpty()) }
                var driveInput by remember(obs.id) { mutableStateOf(obs.driveMinutes?.toInt()?.toString().orEmpty()) }
                var statInput by remember(obs.id) { mutableStateOf(obs.waitStatistic) }

                fun validateEditorInputs(
                    reqStr: String = reqInput,
                    exactStr: String = exactWaitInput,
                    lowerStr: String = lowerWaitInput,
                    driveStr: String = driveInput,
                ) {
                    val rTrim = reqStr.trim()
                    if (rTrim.isNotEmpty()) {
                        val rVal = rTrim.toIntOrNull()
                        if (rVal == null || rVal < 0 || rVal > UberIntelligence.DEFAULT_MAX_REQUESTS_30M) {
                            onFieldValidationError("Requests (30m) '${rTrim}' for ${obs.areaLabel} must be an integer in 0..${UberIntelligence.DEFAULT_MAX_REQUESTS_30M}")
                            return
                        }
                    }
                    val eTrim = exactStr.trim()
                    if (eTrim.isNotEmpty()) {
                        val eVal = eTrim.toDoubleOrNull()
                        if (eVal == null || !eVal.isFinite() || eVal < 0.0 || eVal > UberIntelligence.DEFAULT_MAX_WAIT_MINUTES) {
                            onFieldValidationError("Exact wait '${eTrim}' for ${obs.areaLabel} must be a finite number in 0..${UberIntelligence.DEFAULT_MAX_WAIT_MINUTES.toInt()} min")
                            return
                        }
                    }
                    val lTrim = lowerStr.trim()
                    if (lTrim.isNotEmpty()) {
                        val lVal = lTrim.toDoubleOrNull()
                        if (lVal == null || !lVal.isFinite() || lVal < 0.0 || lVal > UberIntelligence.DEFAULT_MAX_WAIT_MINUTES) {
                            onFieldValidationError("Bucket lower bound '${lTrim}' for ${obs.areaLabel} must be a finite number in 0..${UberIntelligence.DEFAULT_MAX_WAIT_MINUTES.toInt()} min")
                            return
                        }
                    }
                    val dTrim = driveStr.trim()
                    if (dTrim.isNotEmpty()) {
                        val dVal = dTrim.toDoubleOrNull()
                        if (dVal == null || !dVal.isFinite() || dVal < 0.0 || dVal > UberIntelligence.DEFAULT_MAX_DRIVE_MINUTES) {
                            onFieldValidationError("Drive time '${dTrim}' for ${obs.areaLabel} must be a finite number in 0..${UberIntelligence.DEFAULT_MAX_DRIVE_MINUTES.toInt()} min")
                            return
                        }
                    }
                    onFieldValidationError(null)
                }

                if (!fieldErrorMessage.isNullOrBlank()) {
                    Text(
                        text = "⚠️ $fieldErrorMessage",
                        color = UiCoralRed,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = reqInput,
                        onValueChange = { v ->
                            reqInput = v
                            validateEditorInputs(reqStr = v)
                            val parsed = v.trim().toIntOrNull()
                            onUpdateEdit(
                                currentEdit.copy(
                                    requests30m = parsed,
                                    requests30mCleared = v.trim().isEmpty(),
                                )
                            )
                        },
                        label = { Text("Requests (30m)", fontSize = 10.sp) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = exactWaitInput,
                        onValueChange = { v ->
                            exactWaitInput = v
                            validateEditorInputs(exactStr = v)
                            val parsed = v.trim().toDoubleOrNull()
                            onUpdateEdit(
                                currentEdit.copy(
                                    waitMinutesExact = if (parsed != null && parsed.isFinite()) parsed else null,
                                    waitMinutesExactCleared = v.trim().isEmpty(),
                                )
                            )
                        },
                        label = { Text("Exact wait (m)", fontSize = 10.sp) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                }

                Spacer(modifier = Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = lowerWaitInput,
                        onValueChange = { v ->
                            lowerWaitInput = v
                            validateEditorInputs(lowerStr = v)
                            val parsed = v.trim().toDoubleOrNull()
                            onUpdateEdit(
                                currentEdit.copy(
                                    waitMinutesLowerBound = if (parsed != null && parsed.isFinite()) parsed else null,
                                    waitMinutesLowerBoundCleared = v.trim().isEmpty(),
                                )
                            )
                        },
                        label = { Text("Bucket lower (30+)", fontSize = 10.sp) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = driveInput,
                        onValueChange = { v ->
                            driveInput = v
                            validateEditorInputs(driveStr = v)
                            val parsed = v.trim().toDoubleOrNull()
                            onUpdateEdit(
                                currentEdit.copy(
                                    driveMinutes = if (parsed != null && parsed.isFinite()) parsed else null,
                                    driveMinutesCleared = v.trim().isEmpty(),
                                )
                            )
                        },
                        label = { Text("Drive min", fontSize = 10.sp) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                }

                Spacer(modifier = Modifier.height(6.dp))
                Text("Wait statistic:", color = UiTextSecondary, fontSize = 11.sp)
                Row(
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    listOf("unknown", "p90", "p50", "mean").forEach { st ->
                        FilterChip(
                            selected = statInput == st,
                            onClick = {
                                statInput = st
                                onUpdateEdit(currentEdit.copy(waitStatistic = st))
                            },
                            label = { Text(st.uppercase(Locale.US), fontSize = 11.sp) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ProvenancePill(provenance: String, verification: String) {
    val isContradictory = verification == "contradictory"
    val isCard = provenance == "ui_card"
    val bg = when {
        isContradictory -> UiCoralDim
        isCard -> UiEmeraldDim
        else -> UiRadarDim
    }
    val fg = when {
        isContradictory -> UiCoralRed
        isCard -> UiEmeraldCyan
        else -> UiRadarBlue
    }
    val label = when (provenance) {
        "ui_card" -> "UI CARD"
        "assistant_narrative" -> "AI NARRATIVE"
        "both" -> "CARD + NARRATIVE"
        "user_correction" -> "USER EDITED"
        else -> provenance.uppercase(Locale.US)
    }
    Surface(
        color = bg,
        shape = RoundedCornerShape(6.dp),
    ) {
        Text(
            text = label,
            color = fg,
            fontSize = 10.sp,
            fontWeight = FontWeight.ExtraBold,
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
        )
    }
}

@Composable
private fun WarningBadge(flag: String) {
    val isHigh = flag in setOf(
        UberIntelligence.FLAG_CARD_NARRATIVE_CONFLICT,
        UberIntelligence.FLAG_PROMPT_INJECTION_IGNORED,
        UberIntelligence.FLAG_OUT_OF_RANGE_VALUE,
        UberIntelligence.FLAG_AMBIGUOUS_WAIT_VALUES,
        UberIntelligence.FLAG_AMBIGUOUS_REQUEST_VALUES,
        UberIntelligence.FLAG_SENSITIVE_TEXT_DETECTED,
    )
    val friendlyFlag = when (flag) {
        UberIntelligence.FLAG_AREA_BOUNDARY_UNKNOWN -> "Area boundary unverified"
        UberIntelligence.FLAG_CARD_NARRATIVE_CONFLICT -> "Card vs. text conflict"
        UberIntelligence.FLAG_AMBIGUOUS_WAIT_VALUES -> "Conflicting wait numbers"
        UberIntelligence.FLAG_AMBIGUOUS_REQUEST_VALUES -> "Conflicting request counts"
        UberIntelligence.FLAG_OUT_OF_RANGE_VALUE -> "Value out of range"
        else -> flag.replace('_', ' ').lowercase(Locale.US).replaceFirstChar { it.titlecase(Locale.US) }
    }
    Surface(
        color = if (isHigh) UiCoralDim else UiAmberDim,
        shape = RoundedCornerShape(5.dp),
    ) {
        Text(
            text = friendlyFlag,
            color = if (isHigh) UiCoralRed else UiAmberGold,
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

private fun buildRecentAreaComparisons(
    imports: List<UberIntelligence.UberAssistantImport>,
): List<UberIntelligence.ObservationComparison> {
    if (imports.size < 2) return emptyList()
    val byAreaKey = linkedMapOf<String, MutableList<Pair<UberIntelligence.UberAssistantObservation, String>>>()
    for (imp in imports) {
        for (obs in imp.observations) {
            val k = (obs.areaKey ?: obs.areaLabel).lowercase(Locale.US)
            byAreaKey.getOrPut(k) { mutableListOf() }.add(obs to imp.createdAt)
        }
    }
    val out = mutableListOf<UberIntelligence.ObservationComparison>()
    for ((_, list) in byAreaKey) {
        if (list.size >= 2) {
            val (laterObs, laterTime) = list[0]
            val (earlierObs, earlierTime) = list[1]
            out.add(
                UberIntelligence.compareObservations(
                    earlier = earlierObs,
                    later = laterObs,
                    earlierCreatedAt = earlierTime,
                    laterCreatedAt = laterTime,
                )
            )
        }
    }
    return out
}
