package com.rideedge.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Locale
import java.util.UUID

/**
 * Experimental manual Uber Assistant (Beta) intelligence intake, deterministic parser,
 * validator, review-before-save state, deterministic second-opinion comparison evaluator,
 * and corruption-safe local storage repository.
 *
 * Design references:
 * - docs/UberTRAC_Uber_Assistant_Intelligence_Design_Reference_v1.md
 * - docs/RideEdge_Uber_Intelligence_Argon_Review_and_Directive_2026-10-21.md
 *
 * Guardrails:
 * - Strictly isolated from production scoring (UBER_ASSISTANT_SCORING_INTEGRATION_ENABLED = false).
 * - Local-first on device: pasting, parsing, reviewing, comparing, and saving make zero network calls.
 * - Preserves raw response, structured assertions, per-field provenance, and original extracted values when edited.
 * - Never treats '30+' as exact 30; never defaults waitStatistic to 'p90' from 'etr_p90_min' alone;
 *   never converts N/A or missing values to 0.
 */
object UberIntelligence {
    const val PARSER_VERSION = "1.1.0"
    const val COMPARISON_POLICY_VERSION = "1.0.0"

    const val UBER_ASSISTANT_INTELLIGENCE_EXPERIMENTAL = true
    const val UBER_ASSISTANT_COMPARISON_DISPLAY_ENABLED = true
    const val UBER_ASSISTANT_SCORING_INTEGRATION_ENABLED = false

    const val PROMPT_SOFT_CHAR_WARN = 150
    const val PROMPT_SOFT_CHAR_CAP = 200

    const val DEFAULT_MAX_REQUESTS_30M = 5000
    const val DEFAULT_MAX_WAIT_MINUTES = 240.0
    const val DEFAULT_MAX_DRIVE_MINUTES = 180.0
    const val DEFAULT_MAX_SOURCE_AGE_MINUTES = 15L

    const val FLAG_MISSING_METRIC = "MISSING_METRIC"
    const val FLAG_WAIT_BUCKET_NOT_EXACT = "WAIT_BUCKET_NOT_EXACT"
    const val FLAG_WAIT_STATISTIC_UNKNOWN = "WAIT_STATISTIC_UNKNOWN"
    const val FLAG_UNVERIFIED_BACKEND_FIELD = "UNVERIFIED_BACKEND_FIELD"
    const val FLAG_SOURCE_TIMESTAMP_UNAVAILABLE = "SOURCE_TIMESTAMP_UNAVAILABLE"
    const val FLAG_AREA_BOUNDARY_UNKNOWN = "AREA_BOUNDARY_UNKNOWN"
    const val FLAG_CARD_NARRATIVE_CONFLICT = "CARD_NARRATIVE_CONFLICT"
    const val FLAG_CROSS_SNAPSHOT_CHANGE = "CROSS_SNAPSHOT_CHANGE"
    const val FLAG_OVERLAPPING_ROLLING_WINDOW = "OVERLAPPING_ROLLING_WINDOW"
    const val FLAG_DUPLICATE_IMPORT = "DUPLICATE_IMPORT"
    const val FLAG_OUT_OF_RANGE_VALUE = "OUT_OF_RANGE_VALUE"
    const val FLAG_DRIVE_TIME_CONTEXT_CHANGED = "DRIVE_TIME_CONTEXT_CHANGED"
    const val FLAG_PROMPT_INJECTION_IGNORED = "PROMPT_INJECTION_IGNORED"
    const val FLAG_SUPPORT_FLOW_DETECTED = "SUPPORT_FLOW_DETECTED"
    const val FLAG_SENSITIVE_TEXT_DETECTED = "SENSITIVE_TEXT_DETECTED"
    const val FLAG_AMBIGUOUS_WAIT_VALUES = "AMBIGUOUS_WAIT_VALUES"
    const val FLAG_AMBIGUOUS_REQUEST_VALUES = "AMBIGUOUS_REQUEST_VALUES"
    const val FLAG_NON_30M_REQUEST_WINDOW = "NON_30M_REQUEST_WINDOW"

    const val VERDICT_SUPPORTS = "Supports RideEdge"
    const val VERDICT_CHALLENGES = "Challenges RideEdge"
    const val VERDICT_INSUFFICIENT = "Not enough information"

    data class PromptTemplate(
        val id: String,
        val title: String,
        val purpose: String,
        val defaultText: String,
    )

    data class PromptLengthStatus(
        val charCount: Int,
        val level: String,
        val note: String,
    )

    data class UberAssistantAssertion(
        val id: String = "ast-${UUID.randomUUID().toString().replace("-", "").take(10)}",
        val areaLabel: String,
        val areaKey: String?,
        val metric: String, // "requests", "wait_exact", "wait_lower_bound", "drive_time", "source_time"
        val numericValue: Double?,
        val unit: String,
        val windowMinutes: Int? = null,
        val statistic: String = "unknown",
        val origin: String, // "ui_card", "assistant_narrative", "user_correction"
        val sourceSpan: String,
    )

    data class UberAssistantObservation(
        val id: String,
        val importId: String = "",
        val areaLabel: String,
        val areaKey: String?,
        val requests30m: Int?,
        val requestsWindowMinutes: Int? = null,
        val requestsOtherWindowCount: Int? = null,
        val candidateRequests30m: List<Int> = emptyList(),
        val requestsIsApproximate: Boolean,
        val waitMinutesExact: Double?,
        val waitMinutesLowerBound: Double?,
        val candidateExactWaits: List<Double> = emptyList(),
        val candidateLowerBoundWaits: List<Double> = emptyList(),
        val waitStatistic: String = "unknown",
        val driveMinutes: Double?,
        val reportedSourceTime: String?,
        val reportedSourceTimeRaw: String?,
        val claimedSourceField: String?,
        val claimedSourceFieldVerified: Boolean = false,
        val claimedStatisticHint: String? = null,
        val textOrigin: String,
        val provenance: String,
        val verificationLevel: String,
        val freshness: String,
        val metricSemantics: List<String>,
        val fieldEvidence: Map<String, String>,
        val fieldSpans: Map<String, String>,
        val warnings: List<String>,
        val sourceSpan: String,
        val assertions: List<UberAssistantAssertion> = emptyList(),
        val editedByUser: Boolean = false,
        val originalExtractedJson: String? = null,
    )

    data class UberAssistantImport(
        val id: String,
        val createdAt: String,
        val displayTimezone: String = "America/Los_Angeles",
        val userPrompt: String?,
        val promptStatus: String = "unconfirmed", // "none", "suggested_or_copied_unconfirmed", "user_confirmed"
        val rawResponse: String,
        val sourceApp: String = "uber_assistant_beta",
        val captureMethod: String = "manual_paste",
        val replyDisplayTime: String? = null,
        val reportedSourceTime: String? = null,
        val reportedSourceTimeRaw: String? = null,
        val parserVersion: String = PARSER_VERSION,
        val parseStatus: String,
        val draftRevision: String = "",
        val consentConfirmed: Boolean = true,
        val notes: String? = null,
        val fingerprint: String,
        val warnings: List<String>,
        val observations: List<UberAssistantObservation>,
        val isDemoSample: Boolean = false,
        val suspectedLegacySample: Boolean = false,
    )

    data class ObservationEdit(
        val areaLabel: String? = null,
        val requests30m: Int? = null,
        val requests30mCleared: Boolean = false,
        val waitMinutesExact: Double? = null,
        val waitMinutesExactCleared: Boolean = false,
        val waitMinutesLowerBound: Double? = null,
        val waitMinutesLowerBoundCleared: Boolean = false,
        val waitStatistic: String? = null,
        val driveMinutes: Double? = null,
        val driveMinutesCleared: Boolean = false,
        val declined: Boolean = false,
        val userConfirmed: Boolean = false,
    )

    data class ObservationComparison(
        val areaLabel: String,
        val earlierWaitDisplay: String,
        val laterWaitDisplay: String,
        val waitStatisticMismatch: Boolean,
        val waitComparable: Boolean,
        val waitDeltaMinutes: Double?,
        val earlierRequests30m: Int?,
        val laterRequests30m: Int?,
        val earlierDriveMinutes: Double?,
        val laterDriveMinutes: Double?,
        val flags: List<String>,
        val notes: List<String>,
    )

    data class DecisionTargetContext(
        val targetType: String = "now", // "now" or "plan_stop"
        val recommendationId: String,
        val evidenceVersion: String = "v2",
        val issuedAt: String = "",
        val action: String, // "MOVE", "WAIT", "STAY", "WATCH"
        val decisionState: String = "",
        val originZone: String,
        val targetZone: String,
        val targetLabel: String,
        val destinationId: String = "",
        val stopId: String? = null,
        val stopHourOffset: Int = 0,
        val structuredPremise: String, // "short_wait_expected", "local_demand_active", "local_live_activity", "local_scheduled_activity", "reposition_advantage", "positioning_from_residential", "positioned_pickup_center", "no_premise_watch"
        val repositionMinutes: Double? = null,
        val moveCostDollars: Double? = null,
    )

    data class DecisionComparisonRecord(
        val id: String = "cmp-${UUID.randomUUID().toString().replace("-", "").take(12)}",
        val importId: String,
        val importDraftRevision: String = "",
        val observationIds: List<String>,
        val recommendationId: String,
        val evidenceVersion: String,
        val targetType: String,
        val stopId: String? = null,
        val action: String,
        val decisionState: String = "",
        val originZone: String,
        val targetZone: String,
        val targetLabel: String,
        val destinationId: String = "",
        val structuredPremise: String,
        val verdict: String, // VERDICT_SUPPORTS, VERDICT_CHALLENGES, VERDICT_INSUFFICIENT
        val reasonCode: String,
        val headline: String,
        val explanation: String,
        val scopeNote: String? = null,
        val sourceTime: String? = null,
        val sourceAgeMinutesAtEval: Long? = null,
        val expiresAt: String? = null,
        val evaluatedAt: String = Instant.now().toString(),
        val policyVersion: String = COMPARISON_POLICY_VERSION,
        val seenBeforeEpisodeStart: Boolean = true,
        val driverChoice: String = "unknown", // "stayed", "moved", "unknown"
        val linkedEpisodeId: String? = null,
        val outcomeStatus: String = "unknown", // "request_within_15m", "request_after_15m", "accepted_ride", "no_request_after_15m", "observed_15m_no_request", "incomplete_or_interrupted", "unknown"
        val waitMinutesToRequest: Double? = null,
        val acceptedRide: Boolean = false,
        val emptyDriveMinutes: Double? = null,
        val emptyDriveMiles: Double? = null,
        val userPerceivedUseful: Boolean? = null,
    )

    data class HistoryUsefulSummary(
        val totalUniqueImports: Int,
        val usableForComparisonCount: Int,
        val unusableMissingTimestampCount: Int,
        val unusableStaleCount: Int,
        val unusableAreaMismatchCount: Int,
        val unusableContradictoryCount: Int,
        val excludedDemoOrDuplicateCount: Int,
        val supportsCount: Int,
        val challengesCount: Int,
        val insufficientCount: Int,
        val linkedEpisodesTotal: Int,
        val adequatelyLoggedCount: Int,
        val incompleteOrUnknownCount: Int,
        val seenMidWaitExcludedCount: Int,
        val requestWithin15mCount: Int,
        val verifiedDryWait15mCount: Int,
        val acceptedRideCount: Int,
        val medianMinutesToRequestCompletedOnly: Double?,
        val stayedAfterChallengeCount: Int,
        val stayedAfterChallengeRequestWithin15mCount: Int,
        val movedWithSupportCount: Int,
    )

    data class SaveImportResult(
        val saved: Boolean,
        val duplicate: Boolean,
        val existingImportId: String?,
        val warnings: List<String>,
        val importRecord: UberAssistantImport,
    )

    val PROMPT_CATALOG: List<PromptTemplate> = listOf(
        PromptTemplate(
            id = "P1",
            title = "P1 — Local demand",
            purpose = "Multi-area last-30-min request counts and waits with explicit N/A.",
            defaultText = "Bellevue, Redmond, Kirkland, Bothell, Woodinville: last-30-min requests and driver waits. Use N/A if unavailable.",
        ),
        PromptTemplate(
            id = "P2",
            title = "P2 — Exact waits",
            purpose = "Ask for exact wait minutes and statistic type in Bellevue & Redmond.",
            defaultText = "Bellevue and Redmond: exact driver wait minutes and statistic type, if available. If missing, say N/A.",
        ),
        PromptTemplate(
            id = "P3",
            title = "P3 — Validate source",
            purpose = "Check source update time and whether figures are estimates.",
            defaultText = "For Bellevue, give current requests, estimated wait, source update time, and whether figures are estimates. No guesses.",
        ),
        PromptTemplate(
            id = "P4",
            title = "P4 — Nearby shortest wait",
            purpose = "Top 3 areas with shortest available waits, requests, and drive times.",
            defaultText = "Which 3 nearby areas have the shortest available driver waits? Give waits, recent requests and drive times. Exclude N/A waits.",
        ),
        PromptTemplate(
            id = "P5",
            title = "P5 — Tonight (qualitative)",
            purpose = "Qualitative demand windows, waits, and uncertainty for tonight.",
            defaultText = "What nearby areas have the best earning opportunity tonight? Include known demand windows, waits, and uncertainty.",
        ),
    )

    fun buildDecisionContextPrompt(here: HereState?): String {
        if (here == null) {
            return PROMPT_CATALOG.first().defaultText
        }
        val cur = WorkingLocationController.cleanZoneDisplayName(here.zone).replace(" / Kingsgate", "")
        val alt = here.destinationLabel.ifBlank {
            WorkingLocationController.cleanZoneDisplayName(here.bestRow?.zone ?: "")
        }.replace(" / Town Center", "").replace(" / Marina", "")
        val areas = if (alt.isNotBlank() && !alt.equals(cur, ignoreCase = true)) {
            "$cur and $alt"
        } else {
            "$cur, Kirkland, and Bellevue"
        }
        val candidate = "$areas: last-30-min requests, exact driver wait minutes, statistic type, and source update time. Say N/A if unavailable."
        return if (candidate.length <= PROMPT_SOFT_CHAR_CAP) candidate else candidate.take(PROMPT_SOFT_CHAR_CAP)
    }

    private val KNOWN_AREA_NAMES = listOf(
        "Village at Totem Lake",
        "Totem Lake / Kingsgate",
        "Totem Lake",
        "Kingsgate",
        "Kirkland Waterfront",
        "Downtown Kirkland",
        "Kirkland Rose Hill",
        "Rose Hill",
        "Kirkland",
        "Bellevue Core",
        "Downtown Bellevue",
        "Bellevue",
        "Redmond Downtown",
        "Downtown Redmond",
        "Redmond",
        "Woodinville Wine Country",
        "Woodinville",
        "Bothell",
        "Kenmore",
        "Sammamish",
        "Issaquah",
        "Renton",
        "Tukwila",
        "Marymoor",
        "Cottage Lake",
        "Sea-Tac Airport",
        "SeaTac Airport",
        "SeaTac",
        "SEA Airport",
        "Capitol Hill",
        "Seattle Center",
        "Queen Anne",
        "South Lake Union",
        "SLU",
        "University District",
        "U District",
        "UW District",
        "SoDo",
        "SODO",
        "Downtown Seattle",
        "Seattle Core",
        "Fremont",
        "Ballard",
        "Belltown",
        "West Seattle",
        "Columbia City",
        "Rainier Beach",
        "Lake City",
        "Greenwood",
        "Phinney",
        "Magnolia",
        "Northgate",
        "Central District",
        "Beacon Hill",
        "Georgetown",
        "Seattle",
    ).sortedByDescending { it.length }

    private val AREA_ALT = KNOWN_AREA_NAMES.joinToString("|") { Regex.escape(it) }

    private val INJECTION_RE = Regex(
        "(?i)\\b(ignore\\s+(?:all\\s+)?previous\\s+instructions|" +
            "run\\s+a\\s+shell\\s+command|" +
            "system\\s+prompt|" +
            "execute\\s+command|" +
            "upload\\s+your\\s+data|" +
            "rm\\s+-rf|" +
            "curl\\s+https?://|" +
            "invoke-webrequest)\\b"
    )

    private val SUPPORT_FLOW_RE = Regex(
        "(?i)\\b(awaiting\\s+your\\s+reply|send\\s+us\\s+a\\s+message!?|connect(?:ing)?\\s+you\\s+with\\s+support)\\b"
    )

    private val SENSITIVE_EMAIL_RE = Regex("\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b")
    private val SENSITIVE_PHONE_RE = Regex("(?<!\\d)(?:\\+?1[-.\\s]?)?\\(?\\d{3}\\)?[-.\\s]\\d{3}[-.\\s]\\d{4}(?!\\d)")
    private val SENSITIVE_COORD_RE = Regex("(?<!\\d)4[78]\\.\\d{4,}\\s*,\\s*-12[123]\\.\\d{4,}(?!\\d)")

    private val BACKEND_FIELD_RE = Regex("(?i)\\b(etr_(?:p\\d+|mean|median|exact)?[a-z0-9_]*)\\b")
    private val EXPLICIT_P90_RE = Regex("(?i)(?:\\b90th[\\s-]*percentile\\b|(?<!etr_)\\bp90\\b)")
    private val EXPLICIT_P50_RE = Regex("(?i)(?:\\b50th[\\s-]*percentile\\b|\\bmedian\\b|(?<!etr_)\\bp50\\b)")
    private val EXPLICIT_MEAN_RE = Regex("(?i)(?:\\baverage\\s+wait\\b|\\bmean\\s+wait\\b)")
    private val NEGATION_PREFIX_RE = Regex("(?i)\\b(?:not|no|never|isn't|isnt|aren't|arent|without|neither|nor|non|unverified|cannot\\s+confirm|can't\\s+confirm)\\b[^.!?]{0,20}$")

    fun evaluatePromptLength(text: String): PromptLengthStatus {
        val len = text.length
        return when {
            len == 0 -> PromptLengthStatus(0, "empty", "Prompt is empty.")
            len <= PROMPT_SOFT_CHAR_WARN -> PromptLengthStatus(
                len,
                "ok",
                "$len chars — compact (under $PROMPT_SOFT_CHAR_WARN-char practical target)."
            )
            len <= PROMPT_SOFT_CHAR_CAP -> PromptLengthStatus(
                len,
                "warn",
                "$len chars — above $PROMPT_SOFT_CHAR_WARN-char target but within $PROMPT_SOFT_CHAR_CAP-char soft cap (Uber's exact limit is unverified)."
            )
            else -> PromptLengthStatus(
                len,
                "over_soft_cap",
                "$len chars — exceeds $PROMPT_SOFT_CHAR_CAP-char soft cap; Uber Assistant's input box may truncate this prompt."
            )
        }
    }

    fun computeFingerprint(rawResponse: String): String {
        val normalized = rawResponse.trim().replace(Regex("\\s+"), " ")
        val digest = MessageDigest.getInstance("SHA-256").digest(normalized.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun detectSensitiveText(rawText: String): List<String> {
        val out = mutableListOf<String>()
        if (SENSITIVE_EMAIL_RE.containsMatchIn(rawText)) out.add("email_address")
        if (SENSITIVE_PHONE_RE.containsMatchIn(rawText)) out.add("phone_number")
        if (SENSITIVE_COORD_RE.containsMatchIn(rawText)) out.add("precise_coordinates")
        return out
    }

    fun redactSensitiveText(rawText: String): String {
        var r = SENSITIVE_EMAIL_RE.replace(rawText, "[REDACTED_EMAIL]")
        r = SENSITIVE_PHONE_RE.replace(r, "[REDACTED_PHONE]")
        r = SENSITIVE_COORD_RE.replace(r, "[REDACTED_COORDS]")
        return r
    }

    fun resolveAreaKey(areaLabel: String): String? {
        return when (areaLabel.trim().lowercase(Locale.US)) {
            "bellevue", "bellevue core", "downtown bellevue" -> "bellevue_core"
            "redmond", "redmond downtown", "downtown redmond" -> "redmond_downtown"
            "kirkland", "kirkland waterfront", "downtown kirkland" -> "kirkland_waterfront"
            "kirkland rose hill", "rose hill" -> "kirkland_rose_hill"
            "totem lake", "totem lake / kingsgate", "kingsgate", "village at totem lake" -> "totem_lake"
            "woodinville", "woodinville wine country" -> "woodinville_wine"
            "bothell" -> "bothell"
            "kenmore" -> "kenmore"
            "sammamish" -> "sammamish"
            "issaquah" -> "issaquah"
            "renton" -> "renton"
            "tukwila" -> "tukwila"
            "marymoor" -> "marymoor"
            "cottage lake" -> "cottage_lake"
            "sea-tac airport", "seatac airport", "seatac", "sea airport" -> "sea_airport"
            "capitol hill" -> "capitol_hill"
            "seattle center", "queen anne" -> "seattle_center"
            "university district", "u district", "uw district" -> "uw_district"
            "sodo", "sodo stadiums" -> "sodo_stadiums"
            "seattle", "downtown seattle", "seattle core", "south lake union", "slu" -> "seattle_core"
            "fremont", "ballard" -> "fremont_ballard"
            "belltown" -> "belltown"
            "west seattle" -> "west_seattle"
            "columbia city" -> "columbia_city"
            "rainier beach" -> "rainier_beach"
            "lake city" -> "lake_city"
            "phinney", "greenwood" -> "phinney_greenwood"
            "magnolia" -> "magnolia"
            "northgate" -> "northgate"
            "central district" -> "central_district"
            "beacon hill" -> "beacon_hill"
            "georgetown" -> "georgetown"
            else -> null
        }
    }

    private fun parseValidIsoTimestamp(rawIso: String): String? {
        val normalized = rawIso.trim().replace(" ", "T")
        return runCatching {
            OffsetDateTime.parse(normalized)
            rawIso.trim()
        }.getOrElse {
            runCatching {
                Instant.parse(normalized)
                rawIso.trim()
            }.getOrNull()
        }
    }

    private data class TimestampExtraction(
        val reportedSourceTime: String? = null,
        val reportedSourceTimeRaw: String? = null,
        val replyDisplayTime: String? = null,
        val explicitNa: Boolean = false,
    )

    private val REPLY_TIME_PREFIX_RE = Regex(
        "(?i)\\b(?:reply|replied|sent|message\\s+sent|captured|pasted|displayed|chat\\s+time)(?:\\s+(?:at|on|time))?\\s*[:=-]?\\s*$"
    )

    private fun extractTimestampsFromScope(rawText: String): TimestampExtraction {
        val naRe = Regex("(?i)\\b(?:update\\s+time|source\\s+(?:update\\s+)?time|updated|source\\s+window)\\s*[:=-]?\\s*N/?A\\b")
        val hasExplicitNa = naRe.containsMatchIn(rawText)

        var validSourceIso: String? = null
        var rawSourceClaim: String? = null
        var replyIso: String? = null

        val isoRe = Regex("\\b(\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}(?::\\d{2})?(?:Z|[+-]\\d{2}:?\\d{2}))\\b")
        for (m in isoRe.findAll(rawText)) {
            val candidate = m.groupValues[1]
            val prefixStart = (m.range.first - 45).coerceAtLeast(0)
            val prefix = rawText.substring(prefixStart, m.range.first)
            val isReplyTimestamp = REPLY_TIME_PREFIX_RE.containsMatchIn(prefix)
            val validated = parseValidIsoTimestamp(candidate)
            if (isReplyTimestamp) {
                if (validated != null && replyIso == null) {
                    replyIso = validated
                }
            } else {
                if (rawSourceClaim == null) {
                    rawSourceClaim = candidate
                }
                if (validated != null && validSourceIso == null) {
                    validSourceIso = validated
                }
            }
        }

        if (validSourceIso != null || rawSourceClaim != null) {
            return TimestampExtraction(
                reportedSourceTime = validSourceIso,
                reportedSourceTimeRaw = rawSourceClaim,
                replyDisplayTime = replyIso,
                explicitNa = hasExplicitNa,
            )
        }

        val humanRe = Regex(
            "(?i)\\b(?:latest\\s+source\\s+window\\s+started\\s+at|source\\s+(?:update\\s+)?time\\s*[:=-]?|updated\\s+(?:at\\s+)?)\\s*" +
                "([0-9]{1,2}:[0-9]{2}\\s*(?:AM|PM)?(?:\\s*(?:local\\s+time|PDT|PST|UTC|[+-]\\d{2}:\\d{2}))?(?:\\s+on\\s+[A-Za-z]+\\s+\\d{1,2},\\s+\\d{4})?)"
        )
        humanRe.find(rawText)?.let { m ->
            val claimed = m.groupValues[1].trim().trimEnd('.')
            return TimestampExtraction(
                reportedSourceTime = null,
                reportedSourceTimeRaw = claimed,
                replyDisplayTime = replyIso,
                explicitNa = hasExplicitNa,
            )
        }

        return TimestampExtraction(
            reportedSourceTime = null,
            reportedSourceTimeRaw = null,
            replyDisplayTime = replyIso,
            explicitNa = hasExplicitNa,
        )
    }

    private fun detectExplicitStatistic(segment: String): Pair<String, String?> {
        fun isNegated(match: MatchResult): Boolean {
            val start = (match.range.first - 35).coerceAtLeast(0)
            val prefix = segment.substring(start, match.range.first)
            return NEGATION_PREFIX_RE.containsMatchIn(prefix)
        }
        for (m in EXPLICIT_P90_RE.findAll(segment)) {
            if (!isNegated(m)) return "p90" to m.value
        }
        for (m in EXPLICIT_P50_RE.findAll(segment)) {
            if (!isNegated(m)) return "p50" to m.value
        }
        for (m in EXPLICIT_MEAN_RE.findAll(segment)) {
            if (!isNegated(m)) return "mean" to m.value
        }
        return "unknown" to null
    }

    private class ObsBuilder(val areaLabel: String) {
        val areaKey: String? = resolveAreaKey(areaLabel)
        var requests30m: Int? = null
        var requestsWindowMinutes: Int? = null
        var requestsOtherWindowCount: Int? = null
        var requestsIsApproximate: Boolean = false
        var waitMinutesExact: Double? = null
        var waitMinutesLowerBound: Double? = null
        var waitStatistic: String = "unknown"
        var driveMinutes: Double? = null
        var reportedSourceTime: String? = null
        var reportedSourceTimeRaw: String? = null
        var claimedSourceField: String? = null
        var claimedSourceFieldVerified: Boolean = false
        var claimedStatisticHint: String? = null
        val textOriginSet = mutableSetOf<String>()
        val fieldEvidence = mutableMapOf<String, String>()
        val fieldSpans = mutableMapOf<String, String>()
        val narrativeExactWaits = mutableListOf<Double>()
        val cardExactWaits = mutableListOf<Double>()
        val lowerBoundWaits = mutableListOf<Double>()
        val cardRequestsList = mutableListOf<Int>()
        val narrativeRequestsList = mutableListOf<Int>()
        val assertions = mutableListOf<UberAssistantAssertion>()
        var explicitWaitNa: Boolean = false
        var explicitNoMeasurement: Boolean = false
        val warnings = mutableListOf<String>()
        val sourceSpans = mutableListOf<String>()
    }

    private fun MutableList<String>.addUnique(flag: String) {
        if (!contains(flag)) add(flag)
    }

    private fun extractNarrativeSegmentIntoBuilder(
        b: ObsBuilder,
        segment: String,
        fullClause: String,
        fullSentence: String,
    ) {
        b.textOriginSet.add("narrative")
        if (!b.sourceSpans.contains(fullSentence)) {
            b.sourceSpans.add(fullSentence)
        }

        val reqMatch = Regex(
            "(?i)(about|approx\\.?|approximately|~)?\\s*(?:has\\s+)?(-?\\d+)\\s+requests?(?:\\s+in\\s+(?:the\\s+)?(?:last|past)\\s+(\\d+)\\s*(min|minutes?|hr|hours?))?"
        ).find(segment) ?: Regex(
            "(?i)(about|approx\\.?|approximately|~)?\\s*(?:has\\s+)?(-?\\d+)\\b"
        ).find(segment)?.takeIf { m ->
            val after = segment.substring((m.range.last + 1).coerceAtMost(segment.length)).take(18).lowercase(Locale.US)
            val before = segment.substring(0, m.range.first).lowercase(Locale.US)
            val looksLikeMinutes = after.startsWith(" min") || after.startsWith("-min") || after.startsWith("+ min") ||
                before.contains("wait") || before.contains("drive") || before.contains("time")
            !looksLikeMinutes && fullClause.lowercase(Locale.US).contains("request")
        }

        if (reqMatch != null) {
            val approx = reqMatch.groupValues[1].isNotEmpty()
            val rVal = reqMatch.groupValues[2].toIntOrNull()
            val winValRaw = reqMatch.groupValues.getOrNull(3)?.toIntOrNull()
            val winUnit = reqMatch.groupValues.getOrNull(4)?.lowercase(Locale.US).orEmpty()
            val winMins = when {
                winValRaw == null -> 30
                winUnit.startsWith("h") -> winValRaw * 60
                else -> winValRaw
            }
            if (rVal != null) {
                if (winMins == 30) {
                    b.narrativeRequestsList.add(rVal)
                    b.requestsWindowMinutes = 30
                    if (b.requests30m == null) {
                        b.requests30m = rVal
                        b.requestsIsApproximate = approx
                        b.fieldEvidence["requests_30m"] = "assistant_narrative"
                        b.fieldSpans["requests_30m"] = fullClause
                    }
                } else {
                    b.requestsWindowMinutes = winMins
                    b.requestsOtherWindowCount = rVal
                    b.warnings.addUnique(FLAG_NON_30M_REQUEST_WINDOW)
                }
                b.assertions.add(
                    UberAssistantAssertion(
                        areaLabel = b.areaLabel,
                        areaKey = b.areaKey,
                        metric = "requests",
                        numericValue = rVal.toDouble(),
                        unit = "requests",
                        windowMinutes = winMins,
                        origin = "assistant_narrative",
                        sourceSpan = fullClause,
                    )
                )
            }
        }

        val driveRe = Regex(
            "(?i)(?:(?:drive|driving|travel|route)(?:\\s+time)?\\s*(?:is|of|:|=)?\\s*(-?\\d+(?:\\.\\d+)?)\\s*(?:min|minute|minutes)|(-?\\d+(?:\\.\\d+)?)\\s*(?:min|minute|minutes)\\s+(?:away|drive|driving))"
        )
        for (md in driveRe.findAll(segment)) {
            val dNum = (md.groupValues[1].ifEmpty { md.groupValues[2] }).toDoubleOrNull() ?: continue
            if (b.driveMinutes == null) {
                b.driveMinutes = dNum
                b.fieldEvidence["drive_minutes"] = "assistant_narrative"
                b.fieldSpans["drive_minutes"] = fullClause
            }
            b.assertions.add(
                UberAssistantAssertion(
                    areaLabel = b.areaLabel,
                    areaKey = b.areaKey,
                    metric = "drive_time",
                    numericValue = dNum,
                    unit = "minutes",
                    origin = "assistant_narrative",
                    sourceSpan = fullClause,
                )
            )
        }

        val minTokenRe = Regex("(?i)(-?\\d+(?:\\.\\d+)?)(\\+)?[\\s-]*(?:min|minute|minutes)\\b")
        for (mw in minTokenRe.findAll(segment)) {
            val wNum = mw.groupValues[1].toDoubleOrNull() ?: continue
            val isPlus = mw.groupValues[2].isNotEmpty()
            val localPrefixStart = (mw.range.first - 32).coerceAtLeast(0)
            val localPrefix = segment.substring(localPrefixStart, mw.range.first).lowercase(Locale.US)
            val localSuffixEnd = (mw.range.last + 1 + 24).coerceAtMost(segment.length)
            val localSuffix = segment.substring(mw.range.last + 1, localSuffixEnd).lowercase(Locale.US)

            val isLookbackWindow = Regex("\\b(?:in\\s+(?:the\\s+)?(?:last|past)|(?:last|past|previous|within)\\s+)\\s*$")
                .containsMatchIn(localPrefix)
            if (isLookbackWindow) continue

            val isDriveTime = Regex("\\b(?:drive|driving|travel|route)(?:\\s+time)?\\s*(?:is|of|:|=)?\\s*$")
                .containsMatchIn(localPrefix) ||
                Regex("^\\s*(?:away|drive|driving)\\b").containsMatchIn(localSuffix)
            if (isDriveTime) continue

            if (isPlus) {
                b.waitMinutesLowerBound = wNum
                b.lowerBoundWaits.add(wNum)
                b.fieldEvidence["wait_minutes_lower_bound"] = "assistant_narrative"
                b.fieldSpans["wait_minutes_lower_bound"] = fullClause
                b.assertions.add(
                    UberAssistantAssertion(
                        areaLabel = b.areaLabel,
                        areaKey = b.areaKey,
                        metric = "wait_lower_bound",
                        numericValue = wNum,
                        unit = "minutes",
                        origin = "assistant_narrative",
                        sourceSpan = fullClause,
                    )
                )
            } else {
                b.waitMinutesExact = wNum
                b.narrativeExactWaits.add(wNum)
                b.fieldEvidence["wait_minutes_exact"] = "assistant_narrative"
                b.fieldSpans["wait_minutes_exact"] = fullClause
                b.assertions.add(
                    UberAssistantAssertion(
                        areaLabel = b.areaLabel,
                        areaKey = b.areaKey,
                        metric = "wait_exact",
                        numericValue = wNum,
                        unit = "minutes",
                        origin = "assistant_narrative",
                        sourceSpan = fullClause,
                    )
                )
            }
        }

        val (stat, statSpan) = detectExplicitStatistic(segment)
        if (stat != "unknown") {
            b.waitStatistic = stat
            b.fieldEvidence["wait_statistic"] = "assistant_narrative"
            b.fieldSpans["wait_statistic"] = statSpan ?: fullClause
        }

        BACKEND_FIELD_RE.find(segment)?.let { mbf ->
            val fieldName = mbf.groupValues[1]
            b.claimedSourceField = fieldName
            b.claimedSourceFieldVerified = false
            if (fieldName.lowercase(Locale.US).contains("p90")) {
                b.claimedStatisticHint = "p90"
            }
            b.fieldEvidence["claimed_source_field"] = "assistant_narrative"
            b.fieldSpans["claimed_source_field"] = fullClause
        }

        val segTs = extractTimestampsFromScope(segment)
        if (segTs.reportedSourceTime != null) {
            b.reportedSourceTime = segTs.reportedSourceTime
        }
        if (segTs.reportedSourceTimeRaw != null) {
            b.reportedSourceTimeRaw = segTs.reportedSourceTimeRaw
        }
    }

    fun parseAssistantResponse(
        rawResponse: String,
        userPrompt: String? = null,
        displayTimezone: String = "America/Los_Angeles",
        createdAt: String = Instant.now().toString(),
        maxRequests30m: Int = DEFAULT_MAX_REQUESTS_30M,
        maxWaitMinutes: Double = DEFAULT_MAX_WAIT_MINUTES,
        maxDriveMinutes: Double = DEFAULT_MAX_DRIVE_MINUTES,
    ): UberAssistantImport {
        val raw = rawResponse
        val fingerprint = computeFingerprint(raw)
        val importWarnings = mutableListOf<String>()

        if (INJECTION_RE.containsMatchIn(raw)) {
            importWarnings.addUnique(FLAG_PROMPT_INJECTION_IGNORED)
        }
        if (SUPPORT_FLOW_RE.containsMatchIn(raw)) {
            importWarnings.addUnique(FLAG_SUPPORT_FLOW_DETECTED)
        }
        if (detectSensitiveText(raw).isNotEmpty()) {
            importWarnings.addUnique(FLAG_SENSITIVE_TEXT_DETECTED)
        }

        val builders = linkedMapOf<String, ObsBuilder>()
        fun getBuilder(name: String): ObsBuilder {
            val key = name.trim().lowercase(Locale.US)
            return builders.getOrPut(key) { ObsBuilder(name.trim()) }
        }

        val lines = raw.lines().map { it.trim() }
        val cardHeaderRe = Regex(
            "(?i)^($AREA_ALT)(?:\\s*\\(\\s*~?(-?\\d+(?:\\.\\d+)?)\\s*(?:min|minutes?)\\s+away\\s*\\))?$"
        )
        val cardReqRe = Regex(
            "(?i)^(about|approx\\.?|approximately|~)?\\s*(-?\\d+)\\s+requests?\\s+in\\s+(?:the\\s+)?last\\s+(\\d+)\\s*(?:min|minutes?)$"
        )
        val cardWaitRe = Regex(
            "(?i)^(?:est\\.?|estimated|driver\\s+wait\\s*[:=-]?|wait\\s*[:=-]?)?\\s*~?(?:(n/?a|unavailable)|(-?\\d+(?:\\.\\d+)?)(\\+)?\\s*(?:min|minutes?))(?:\\s*wait)?$"
        )

        val consumedLines = mutableSetOf<Int>()
        var idx = 0
        while (idx < lines.size) {
            val line = lines[idx]
            if (line.isBlank()) {
                idx++
                continue
            }
            val mHead = cardHeaderRe.matchEntire(line)
            if (mHead != null) {
                val next1 = lines.getOrNull(idx + 1).orEmpty()
                val next2 = lines.getOrNull(idx + 2).orEmpty()
                val mReq = cardReqRe.matchEntire(next1)
                val mWait1 = cardWaitRe.matchEntire(next1)
                val mWait2 = if (mReq != null) cardWaitRe.matchEntire(next2) else null
                val driveStr = mHead.groupValues[2]

                if (mReq != null || mWait1 != null || driveStr.isNotEmpty()) {
                    val areaName = mHead.groupValues[1]
                    val b = getBuilder(areaName)
                    b.textOriginSet.add("card")
                    b.sourceSpans.add(line)
                    consumedLines.add(idx)

                    if (driveStr.isNotEmpty()) {
                        val dVal = driveStr.toDoubleOrNull()
                        b.driveMinutes = dVal
                        b.fieldEvidence["drive_minutes"] = "ui_card"
                        b.fieldSpans["drive_minutes"] = line
                        if (dVal != null) {
                            b.assertions.add(
                                UberAssistantAssertion(
                                    areaLabel = b.areaLabel,
                                    areaKey = b.areaKey,
                                    metric = "drive_time",
                                    numericValue = dVal,
                                    unit = "minutes",
                                    origin = "ui_card",
                                    sourceSpan = line,
                                )
                            )
                        }
                    }

                    if (mReq != null) {
                        consumedLines.add(idx + 1)
                        b.sourceSpans.add(next1)
                        val rVal = mReq.groupValues[2].toIntOrNull()
                        val winVal = mReq.groupValues[3].toIntOrNull() ?: 30
                        if (rVal != null) {
                            if (winVal == 30) {
                                b.requests30m = rVal
                                b.requestsWindowMinutes = 30
                                b.cardRequestsList.add(rVal)
                                b.requestsIsApproximate = mReq.groupValues[1].isNotEmpty()
                                b.fieldEvidence["requests_30m"] = "ui_card"
                                b.fieldSpans["requests_30m"] = next1
                            } else {
                                b.requestsWindowMinutes = winVal
                                b.requestsOtherWindowCount = rVal
                                b.warnings.addUnique(FLAG_NON_30M_REQUEST_WINDOW)
                            }
                            b.assertions.add(
                                UberAssistantAssertion(
                                    areaLabel = b.areaLabel,
                                    areaKey = b.areaKey,
                                    metric = "requests",
                                    numericValue = rVal.toDouble(),
                                    unit = "requests",
                                    windowMinutes = winVal,
                                    origin = "ui_card",
                                    sourceSpan = next1,
                                )
                            )
                        }
                    }

                    val waitMatch = mWait2 ?: mWait1
                    val waitLineIdx = if (mReq != null) idx + 2 else idx + 1
                    if (waitMatch != null) {
                        consumedLines.add(waitLineIdx)
                        val wSpan = lines[waitLineIdx]
                        b.sourceSpans.add(wSpan)
                        val naGroup = waitMatch.groupValues[1]
                        val valGroup = waitMatch.groupValues[2]
                        val plusGroup = waitMatch.groupValues[3]
                        if (naGroup.isNotEmpty()) {
                            b.explicitWaitNa = true
                        } else if (valGroup.isNotEmpty()) {
                            val wNum = valGroup.toDoubleOrNull()
                            if (wNum != null) {
                                if (plusGroup.isNotEmpty()) {
                                    b.waitMinutesLowerBound = wNum
                                    b.lowerBoundWaits.add(wNum)
                                    b.fieldEvidence["wait_minutes_lower_bound"] = "ui_card"
                                    b.fieldSpans["wait_minutes_lower_bound"] = wSpan
                                    b.assertions.add(
                                        UberAssistantAssertion(
                                            areaLabel = b.areaLabel,
                                            areaKey = b.areaKey,
                                            metric = "wait_lower_bound",
                                            numericValue = wNum,
                                            unit = "minutes",
                                            origin = "ui_card",
                                            sourceSpan = wSpan,
                                        )
                                    )
                                } else {
                                    b.waitMinutesExact = wNum
                                    b.cardExactWaits.add(wNum)
                                    b.fieldEvidence["wait_minutes_exact"] = "ui_card"
                                    b.fieldSpans["wait_minutes_exact"] = wSpan
                                    b.assertions.add(
                                        UberAssistantAssertion(
                                            areaLabel = b.areaLabel,
                                            areaKey = b.areaKey,
                                            metric = "wait_exact",
                                            numericValue = wNum,
                                            unit = "minutes",
                                            origin = "ui_card",
                                            sourceSpan = wSpan,
                                        )
                                    )
                                }
                            }
                        }
                    }
                    idx = if (waitMatch != null) waitLineIdx + 1 else if (mReq != null) idx + 2 else idx + 1
                    continue
                }
            }
            idx++
        }

        val narrativeLines = lines.mapIndexedNotNull { i, s ->
            if (i !in consumedLines && s.isNotBlank()) s else null
        }
        val narrativeText = narrativeLines.joinToString(" ")
        val sentences = narrativeText
            .split(Regex("(?<=[.!?])\\s+(?=[A-Z0-9])"))
            .map { it.trim() }
            .filter { it.isNotEmpty() }

        val preWaitPattern = Regex("(?i)\\b(-?\\d+(?:\\.\\d+)?)[\\s-]*(?:min|minute|minutes)\\s+($AREA_ALT)\\s+wait\\b")
        val areaAnyRe = Regex("(?i)\\b($AREA_ALT)\\b")
        val distinctAreasInRaw = areaAnyRe.findAll(raw)
            .map { it.groupValues[1] }
            .distinctBy { resolveAreaKey(it) ?: it.lowercase(Locale.US) }
            .toList()
        val singleAreaInRaw = distinctAreasInRaw.singleOrNull()

        var globalReportedSourceTime: String? = null
        var globalReportedSourceTimeRaw: String? = null
        var globalReplyDisplayTime: String? = null

        for (sent in sentences) {
            if (INJECTION_RE.containsMatchIn(sent)) continue
            if (Regex("(?i)^update\\s+time\\s*:\\s*n/?a\\.?$").matches(sent)) continue
            if (Regex("(?i)^these\\s+estimates\\s+are\\s+current\\.?$").matches(sent)) continue

            val mPreWait = preWaitPattern.find(sent)
            if (mPreWait != null && areaAnyRe.findAll(sent).count() == 1) {
                val wNum = mPreWait.groupValues[1].toDoubleOrNull()
                val areaName = mPreWait.groupValues[2]
                val b = getBuilder(areaName)
                b.textOriginSet.add("narrative")
                b.sourceSpans.add(sent)
                if (wNum != null) {
                    b.waitMinutesExact = wNum
                    b.narrativeExactWaits.add(wNum)
                    b.fieldEvidence["wait_minutes_exact"] = "assistant_narrative"
                    b.fieldSpans["wait_minutes_exact"] = sent
                    b.assertions.add(
                        UberAssistantAssertion(
                            areaLabel = b.areaLabel,
                            areaKey = b.areaKey,
                            metric = "wait_exact",
                            numericValue = wNum,
                            unit = "minutes",
                            origin = "assistant_narrative",
                            sourceSpan = sent,
                        )
                    )
                }
                val (stat, statSpan) = detectExplicitStatistic(sent)
                if (stat != "unknown") {
                    b.waitStatistic = stat
                    b.fieldEvidence["wait_statistic"] = "assistant_narrative"
                    b.fieldSpans["wait_statistic"] = statSpan ?: sent
                }
                BACKEND_FIELD_RE.find(sent)?.let { mbf ->
                    val fieldName = mbf.groupValues[1]
                    b.claimedSourceField = fieldName
                    b.claimedSourceFieldVerified = false
                    if (fieldName.lowercase(Locale.US).contains("p90")) {
                        b.claimedStatisticHint = "p90"
                    }
                    b.fieldEvidence["claimed_source_field"] = "assistant_narrative"
                    b.fieldSpans["claimed_source_field"] = sent
                }
                val sentTs = extractTimestampsFromScope(sent)
                if (sentTs.reportedSourceTime != null) b.reportedSourceTime = sentTs.reportedSourceTime
                if (sentTs.reportedSourceTimeRaw != null) b.reportedSourceTimeRaw = sentTs.reportedSourceTimeRaw
                if (sentTs.replyDisplayTime != null && globalReplyDisplayTime == null) {
                    globalReplyDisplayTime = sentTs.replyDisplayTime
                }
                continue
            }

            val areaMentions = areaAnyRe.findAll(sent).toList()
            if (areaMentions.isEmpty()) {
                val sentTs = extractTimestampsFromScope(sent)
                if (sentTs.reportedSourceTime != null && globalReportedSourceTime == null) {
                    globalReportedSourceTime = sentTs.reportedSourceTime
                }
                if (sentTs.reportedSourceTimeRaw != null && globalReportedSourceTimeRaw == null) {
                    globalReportedSourceTimeRaw = sentTs.reportedSourceTimeRaw
                }
                if (sentTs.replyDisplayTime != null && globalReplyDisplayTime == null) {
                    globalReplyDisplayTime = sentTs.replyDisplayTime
                }
                val probeBuilder = ObsBuilder(singleAreaInRaw ?: "Unassigned area")
                extractNarrativeSegmentIntoBuilder(probeBuilder, sent, sent, sent)
                val hasConcreteMetric = probeBuilder.assertions.isNotEmpty() ||
                    probeBuilder.waitStatistic != "unknown" ||
                    probeBuilder.claimedSourceField != null
                if (hasConcreteMetric) {
                    if (singleAreaInRaw != null) {
                        val targetB = getBuilder(singleAreaInRaw)
                        extractNarrativeSegmentIntoBuilder(targetB, sent, sent, sent)
                    } else if (probeBuilder.assertions.isNotEmpty()) {
                        val unassignedB = getBuilder("Unassigned area")
                        extractNarrativeSegmentIntoBuilder(unassignedB, sent, sent, sent)
                    }
                }
                continue
            }

            val clauses = sent.split(Regex("(?i);|\\bwhile\\b")).map { it.trim() }.filter { it.isNotEmpty() }
            var currentClauseAreaBuilder: ObsBuilder? = null
            for (clause in clauses) {
                val clauseAreas = areaAnyRe.findAll(clause).toList()
                if (clauseAreas.isEmpty()) {
                    val activeB = currentClauseAreaBuilder ?: if (areaMentions.size == 1) getBuilder(areaMentions[0].groupValues[1]) else null
                    if (activeB != null) {
                        extractNarrativeSegmentIntoBuilder(activeB, clause, clause, sent)
                    } else {
                        val cTs = extractTimestampsFromScope(clause)
                        if (cTs.reportedSourceTime != null && globalReportedSourceTime == null) {
                            globalReportedSourceTime = cTs.reportedSourceTime
                        }
                        if (cTs.reportedSourceTimeRaw != null && globalReportedSourceTimeRaw == null) {
                            globalReportedSourceTimeRaw = cTs.reportedSourceTimeRaw
                        }
                    }
                    continue
                }

                val clauseWaitUnavail = Regex("(?i)\\b(?:waits?\\s+(?:are|is)\\s+(?:unavailable|n/?a)|wait\\s*[:=]?\\s*(?:unavailable|n/?a))\\b")
                    .containsMatchIn(clause)
                val clauseNoMeas = Regex("(?i)\\bno\\s+current\\s+measurement\\b|\\bno\\s+data\\b|\\bunavailable\\b")
                    .containsMatchIn(clause)

                for (idxM in clauseAreas.indices) {
                    val mArea = clauseAreas[idxM]
                    val areaName = mArea.groupValues[1]
                    val segStart = mArea.range.last + 1
                    val segEnd = if (idxM + 1 < clauseAreas.size) clauseAreas[idxM + 1].range.first else clause.length
                    val segment = clause.substring(segStart, segEnd)

                    val b = getBuilder(areaName)
                    currentClauseAreaBuilder = b
                    extractNarrativeSegmentIntoBuilder(b, segment, clause, sent)

                    if (clauseWaitUnavail) b.explicitWaitNa = true
                    if (clauseNoMeas && b.requests30m == null && b.waitMinutesExact == null && b.waitMinutesLowerBound == null) {
                        b.explicitNoMeasurement = true
                    }
                }
            }
        }

        val importId = "imp-${UUID.randomUUID().toString().replace("-", "").take(12)}"
        val observations = builders.values.map { b ->
            if (b.reportedSourceTime == null && globalReportedSourceTime != null) {
                b.reportedSourceTime = globalReportedSourceTime
            }
            if (b.reportedSourceTimeRaw == null && globalReportedSourceTimeRaw != null) {
                b.reportedSourceTimeRaw = globalReportedSourceTimeRaw
            }

            val distinctExactWaits = (b.cardExactWaits + b.narrativeExactWaits).distinct()
            val distinctLowerBounds = b.lowerBoundWaits.distinct()
            val distinctReqs = (b.cardRequestsList + b.narrativeRequestsList).distinct()

            val textOrigin = when {
                b.textOriginSet.contains("card") && b.textOriginSet.contains("narrative") -> "both"
                b.textOriginSet.contains("card") -> "card"
                b.textOriginSet.contains("narrative") -> "narrative"
                else -> "unknown"
            }
            val provenance = when (textOrigin) {
                "both" -> "both"
                "card" -> "ui_card"
                "narrative" -> "assistant_narrative"
                else -> "unknown"
            }

            val rawObs = UberAssistantObservation(
                id = "obs-${UUID.randomUUID().toString().replace("-", "").take(12)}",
                importId = importId,
                areaLabel = b.areaLabel,
                areaKey = b.areaKey,
                requests30m = b.requests30m,
                requestsWindowMinutes = b.requestsWindowMinutes,
                requestsOtherWindowCount = b.requestsOtherWindowCount,
                candidateRequests30m = distinctReqs,
                requestsIsApproximate = b.requestsIsApproximate,
                waitMinutesExact = b.waitMinutesExact,
                waitMinutesLowerBound = b.waitMinutesLowerBound,
                candidateExactWaits = if (distinctExactWaits.size > 1) distinctExactWaits else emptyList(),
                candidateLowerBoundWaits = distinctLowerBounds,
                waitStatistic = b.waitStatistic,
                driveMinutes = b.driveMinutes,
                reportedSourceTime = b.reportedSourceTime,
                reportedSourceTimeRaw = b.reportedSourceTimeRaw,
                claimedSourceField = b.claimedSourceField,
                claimedSourceFieldVerified = b.claimedSourceFieldVerified,
                claimedStatisticHint = b.claimedStatisticHint,
                textOrigin = textOrigin,
                provenance = provenance,
                verificationLevel = "ai_reported_unverified",
                freshness = if (b.reportedSourceTime != null) "timestamp_known" else "capture_time_only",
                metricSemantics = emptyList(),
                fieldEvidence = b.fieldEvidence.toMap(),
                fieldSpans = b.fieldSpans.toMap(),
                warnings = b.warnings.toList(),
                sourceSpan = b.sourceSpans.joinToString("\n"),
                assertions = b.assertions.toList(),
            )
            revalidateObservation(
                obs = rawObs,
                maxRequests30m = maxRequests30m,
                maxWaitMinutes = maxWaitMinutes,
                maxDriveMinutes = maxDriveMinutes,
            )
        }

        val distinctObsSourceTimes = observations.mapNotNull { it.reportedSourceTime }.distinct()
        val importReportedSourceTime = when {
            distinctObsSourceTimes.size == 1 -> distinctObsSourceTimes.single()
            globalReportedSourceTime != null -> globalReportedSourceTime
            else -> distinctObsSourceTimes.firstOrNull()
        }
        val importReportedSourceTimeRaw = globalReportedSourceTimeRaw
            ?: observations.mapNotNull { it.reportedSourceTimeRaw }.firstOrNull()

        if (importReportedSourceTime == null) {
            importWarnings.addUnique(FLAG_SOURCE_TIMESTAMP_UNAVAILABLE)
        }

        val parseStatus = when {
            observations.isEmpty() -> "unparsed"
            observations.any { FLAG_MISSING_METRIC in it.warnings } -> "partial"
            else -> "parsed"
        }

        return UberAssistantImport(
            id = importId,
            createdAt = createdAt,
            displayTimezone = displayTimezone,
            userPrompt = userPrompt,
            promptStatus = if (userPrompt.isNullOrBlank()) "none" else "suggested_or_copied_unconfirmed",
            rawResponse = raw,
            replyDisplayTime = globalReplyDisplayTime,
            reportedSourceTime = importReportedSourceTime,
            reportedSourceTimeRaw = importReportedSourceTimeRaw,
            parseStatus = parseStatus,
            draftRevision = fingerprint.take(16),
            fingerprint = fingerprint,
            warnings = importWarnings,
            observations = observations,
        )
    }

    fun revalidateObservation(
        obs: UberAssistantObservation,
        userConfirmed: Boolean = false,
        maxRequests30m: Int = DEFAULT_MAX_REQUESTS_30M,
        maxWaitMinutes: Double = DEFAULT_MAX_WAIT_MINUTES,
        maxDriveMinutes: Double = DEFAULT_MAX_DRIVE_MINUTES,
    ): UberAssistantObservation {
        val obsWarnings = mutableListOf<String>()
        obsWarnings.addUnique(FLAG_AREA_BOUNDARY_UNKNOWN)
        if (FLAG_NON_30M_REQUEST_WINDOW in obs.warnings || (obs.requestsWindowMinutes != null && obs.requestsWindowMinutes != 30)) {
            obsWarnings.addUnique(FLAG_NON_30M_REQUEST_WINDOW)
        }
        if (obs.reportedSourceTime == null) {
            obsWarnings.addUnique(FLAG_SOURCE_TIMESTAMP_UNAVAILABLE)
        }
        if (obs.waitMinutesLowerBound != null && obs.waitMinutesExact == null) {
            obsWarnings.addUnique(FLAG_WAIT_BUCKET_NOT_EXACT)
        }
        if ((obs.waitMinutesExact != null || obs.waitMinutesLowerBound != null) && obs.waitStatistic == "unknown") {
            obsWarnings.addUnique(FLAG_WAIT_STATISTIC_UNKNOWN)
        }
        if (!obs.claimedSourceField.isNullOrBlank()) {
            obsWarnings.addUnique(FLAG_UNVERIFIED_BACKEND_FIELD)
        }
        if (obs.requests30m == null || (obs.waitMinutesExact == null && obs.waitMinutesLowerBound == null)) {
            obsWarnings.addUnique(FLAG_MISSING_METRIC)
        }

        val waitExactResolved = obs.fieldEvidence["wait_minutes_exact"] == "user_correction"
        val waitLowerResolved = obs.fieldEvidence["wait_minutes_lower_bound"] == "user_correction"
        val reqResolved = obs.fieldEvidence["requests_30m"] == "user_correction"

        var hasConflict = false
        if (
            obs.waitMinutesExact != null &&
            obs.waitMinutesLowerBound != null &&
            obs.waitMinutesExact < obs.waitMinutesLowerBound &&
            !(waitExactResolved && waitLowerResolved)
        ) {
            hasConflict = true
        }
        if (obs.candidateExactWaits.distinct().size > 1 && !waitExactResolved) {
            hasConflict = true
            obsWarnings.addUnique(FLAG_AMBIGUOUS_WAIT_VALUES)
        }
        if (obs.candidateLowerBoundWaits.distinct().size > 1 && !waitLowerResolved) {
            hasConflict = true
            obsWarnings.addUnique(FLAG_AMBIGUOUS_WAIT_VALUES)
        }
        if (obs.candidateRequests30m.distinct().size > 1 && !reqResolved) {
            hasConflict = true
            obsWarnings.addUnique(FLAG_AMBIGUOUS_REQUEST_VALUES)
        }
        if (hasConflict) {
            obsWarnings.addUnique(FLAG_CARD_NARRATIVE_CONFLICT)
        }

        obs.requests30m?.let { r ->
            if (r < 0 || r > maxRequests30m) obsWarnings.addUnique(FLAG_OUT_OF_RANGE_VALUE)
        }
        obs.waitMinutesExact?.let { w ->
            if (!w.isFinite() || w < 0.0 || w > maxWaitMinutes) obsWarnings.addUnique(FLAG_OUT_OF_RANGE_VALUE)
        }
        obs.waitMinutesLowerBound?.let { w ->
            if (!w.isFinite() || w < 0.0 || w > maxWaitMinutes) obsWarnings.addUnique(FLAG_OUT_OF_RANGE_VALUE)
        }
        obs.driveMinutes?.let { d ->
            if (!d.isFinite() || d < 0.0 || d > maxDriveMinutes) obsWarnings.addUnique(FLAG_OUT_OF_RANGE_VALUE)
        }

        val semantics = mutableListOf<String>()
        if (obs.requests30m != null) {
            semantics.add(if (obs.requestsIsApproximate) "request_count_approx" else "request_count_reported")
        }
        if (obs.waitMinutesLowerBound != null) {
            semantics.add("wait_lower_bound")
        }
        if (obs.waitMinutesExact != null) {
            val isUserEditedStat = obs.fieldEvidence["wait_statistic"] == "user_correction"
            when (obs.waitStatistic) {
                "p90" -> semantics.add(if (isUserEditedStat) "wait_p90_user_set" else "wait_p90_claimed")
                "unknown" -> semantics.add("wait_exact_statistic_unknown")
                else -> semantics.add(if (isUserEditedStat) "wait_${obs.waitStatistic}_user_set" else "wait_${obs.waitStatistic}_claimed")
            }
        }

        val verificationLevel = when {
            hasConflict -> "contradictory"
            userConfirmed -> "user_confirmed"
            obs.textOrigin == "card" && obs.claimedSourceField.isNullOrBlank() && !obs.editedByUser -> "directly_visible"
            else -> "ai_reported_unverified"
        }

        return obs.copy(
            verificationLevel = verificationLevel,
            freshness = if (obs.reportedSourceTime != null) "timestamp_known" else "capture_time_only",
            metricSemantics = semantics,
            warnings = obsWarnings,
        )
    }

    fun applyUserReviewEdits(
        importRecord: UberAssistantImport,
        edits: Map<String, ObservationEdit>,
        notes: String? = importRecord.notes,
    ): UberAssistantImport {
        var anyEdited = false
        val newObs = mutableListOf<UberAssistantObservation>()
        for (obs in importRecord.observations) {
            val edit = edits[obs.id]
            if (edit == null) {
                newObs.add(obs)
                continue
            }
            if (edit.declined) {
                anyEdited = true
                continue
            }
            edit.waitMinutesExact?.let {
                if (!it.isFinite()) throw IllegalArgumentException("waitMinutesExact must be a finite number")
            }
            edit.waitMinutesLowerBound?.let {
                if (!it.isFinite()) throw IllegalArgumentException("waitMinutesLowerBound must be a finite number")
            }
            edit.driveMinutes?.let {
                if (!it.isFinite()) throw IllegalArgumentException("driveMinutes must be a finite number")
            }

            val origJson = obs.originalExtractedJson ?: JSONObject()
                .put("area_label", obs.areaLabel)
                .put("requests_30m", obs.requests30m ?: JSONObject.NULL)
                .put("wait_minutes_exact", obs.waitMinutesExact ?: JSONObject.NULL)
                .put("wait_minutes_lower_bound", obs.waitMinutesLowerBound ?: JSONObject.NULL)
                .put("wait_statistic", obs.waitStatistic)
                .put("drive_minutes", obs.driveMinutes ?: JSONObject.NULL)
                .toString()

            val newEvidence = obs.fieldEvidence.toMutableMap()
            var changed = false

            val nextArea = if (edit.areaLabel != null && edit.areaLabel != obs.areaLabel) {
                newEvidence["area_label"] = "user_correction"
                changed = true
                edit.areaLabel
            } else obs.areaLabel

            val nextReq = when {
                edit.requests30mCleared -> {
                    if (obs.requests30m != null) {
                        newEvidence["requests_30m"] = "user_correction"
                        changed = true
                    }
                    null
                }
                edit.requests30m != null && edit.requests30m != obs.requests30m -> {
                    newEvidence["requests_30m"] = "user_correction"
                    changed = true
                    edit.requests30m
                }
                else -> obs.requests30m
            }

            val nextWaitExact = when {
                edit.waitMinutesExactCleared -> {
                    if (obs.waitMinutesExact != null) {
                        newEvidence["wait_minutes_exact"] = "user_correction"
                        changed = true
                    }
                    null
                }
                edit.waitMinutesExact != null && edit.waitMinutesExact != obs.waitMinutesExact -> {
                    newEvidence["wait_minutes_exact"] = "user_correction"
                    changed = true
                    edit.waitMinutesExact
                }
                else -> obs.waitMinutesExact
            }

            val nextWaitLower = when {
                edit.waitMinutesLowerBoundCleared -> {
                    if (obs.waitMinutesLowerBound != null) {
                        newEvidence["wait_minutes_lower_bound"] = "user_correction"
                        changed = true
                    }
                    null
                }
                edit.waitMinutesLowerBound != null && edit.waitMinutesLowerBound != obs.waitMinutesLowerBound -> {
                    newEvidence["wait_minutes_lower_bound"] = "user_correction"
                    changed = true
                    edit.waitMinutesLowerBound
                }
                else -> obs.waitMinutesLowerBound
            }

            val nextStat = if (edit.waitStatistic != null && edit.waitStatistic != obs.waitStatistic) {
                newEvidence["wait_statistic"] = "user_correction"
                changed = true
                edit.waitStatistic
            } else obs.waitStatistic

            val nextDrive = when {
                edit.driveMinutesCleared -> {
                    if (obs.driveMinutes != null) {
                        newEvidence["drive_minutes"] = "user_correction"
                        changed = true
                    }
                    null
                }
                edit.driveMinutes != null && edit.driveMinutes != obs.driveMinutes -> {
                    newEvidence["drive_minutes"] = "user_correction"
                    changed = true
                    edit.driveMinutes
                }
                else -> obs.driveMinutes
            }

            if (changed || edit.userConfirmed) {
                anyEdited = true
            }

            val updatedObs = obs.copy(
                areaLabel = nextArea,
                areaKey = resolveAreaKey(nextArea),
                requests30m = nextReq,
                waitMinutesExact = nextWaitExact,
                waitMinutesLowerBound = nextWaitLower,
                waitStatistic = nextStat,
                driveMinutes = nextDrive,
                provenance = if (changed) "user_correction" else obs.provenance,
                fieldEvidence = newEvidence,
                editedByUser = changed || obs.editedByUser,
                originalExtractedJson = if (changed) origJson else obs.originalExtractedJson,
            )
            newObs.add(revalidateObservation(updatedObs, userConfirmed = edit.userConfirmed))
        }

        val nextStatus = if (anyEdited || edits.values.any { it.userConfirmed }) {
            "reviewed"
        } else {
            importRecord.parseStatus
        }

        return importRecord.copy(
            parseStatus = nextStatus,
            notes = notes,
            observations = newObs,
        )
    }

    fun validateImportForSave(
        importRecord: UberAssistantImport,
        maxRequests30m: Int = DEFAULT_MAX_REQUESTS_30M,
        maxWaitMinutes: Double = DEFAULT_MAX_WAIT_MINUTES,
        maxDriveMinutes: Double = DEFAULT_MAX_DRIVE_MINUTES,
    ) {
        for (obs in importRecord.observations) {
            obs.requests30m?.let { r ->
                if (r < 0 || r > maxRequests30m) {
                    throw IllegalArgumentException("Invalid requests30m value ($r) for ${obs.areaLabel}: must be in 0..$maxRequests30m")
                }
            }
            obs.waitMinutesExact?.let { w ->
                if (!w.isFinite() || w < 0.0 || w > maxWaitMinutes) {
                    throw IllegalArgumentException("Invalid waitMinutesExact value ($w) for ${obs.areaLabel}: must be finite and in 0..$maxWaitMinutes")
                }
            }
            obs.waitMinutesLowerBound?.let { w ->
                if (!w.isFinite() || w < 0.0 || w > maxWaitMinutes) {
                    throw IllegalArgumentException("Invalid waitMinutesLowerBound value ($w) for ${obs.areaLabel}: must be finite and in 0..$maxWaitMinutes")
                }
            }
            obs.driveMinutes?.let { d ->
                if (!d.isFinite() || d < 0.0 || d > maxDriveMinutes) {
                    throw IllegalArgumentException("Invalid driveMinutes value ($d) for ${obs.areaLabel}: must be finite and in 0..$maxDriveMinutes")
                }
            }
            if (FLAG_OUT_OF_RANGE_VALUE in obs.warnings) {
                throw IllegalArgumentException("Observation for ${obs.areaLabel} has out-of-range metric values")
            }
        }
    }

    private fun formatNum(v: Double): String {
        return if (v % 1.0 == 0.0) v.toInt().toString() else String.format(Locale.US, "%.1f", v)
    }

    fun formatWaitDisplay(obs: UberAssistantObservation): String {
        val isUserStat = obs.fieldEvidence["wait_statistic"] == "user_correction" ||
            obs.fieldEvidence["wait_minutes_exact"] == "user_correction"
        val statLabel = when (obs.waitStatistic) {
            "p90" -> if (isUserStat) "driver-entered P90" else "AI-claimed P90"
            "p50" -> if (isUserStat) "driver-entered median (P50)" else "AI-claimed median (P50)"
            "mean" -> if (isUserStat) "driver-entered mean" else "AI-claimed mean"
            else -> "unknown statistic"
        }
        val parts = mutableListOf<String>()
        obs.waitMinutesExact?.let { parts.add("${formatNum(it)} min ($statLabel)") }
        obs.waitMinutesLowerBound?.let {
            val lbEvidence = obs.fieldEvidence["wait_minutes_lower_bound"] ?: obs.provenance
            val bucketDesc = when (lbEvidence) {
                "ui_card" -> "${formatNum(it)}+ min card bucket (lower bound)"
                "user_correction" -> "${formatNum(it)}+ min driver-edited lower bound"
                else -> "${formatNum(it)}+ min lower-bound wait"
            }
            parts.add(bucketDesc)
        }
        return if (parts.isEmpty()) "N/A (unavailable)" else parts.joinToString(" · ")
    }

    fun compareObservations(
        earlier: UberAssistantObservation,
        later: UberAssistantObservation,
        earlierCreatedAt: String? = null,
        laterCreatedAt: String? = null,
    ): ObservationComparison {
        val flags = mutableListOf<String>()
        val notes = mutableListOf<String>()

        val eWaitLabel = formatWaitDisplay(earlier)
        val lWaitLabel = formatWaitDisplay(later)

        val eExact = earlier.waitMinutesExact
        val lExact = later.waitMinutesExact
        val eStat = earlier.waitStatistic
        val lStat = later.waitStatistic

        var waitStatisticMismatch = false
        var waitComparable = false
        var waitDeltaMinutes: Double? = null

        if (eExact != null && lExact != null) {
            if (eStat != lStat || eStat == "unknown" || lStat == "unknown") {
                waitStatisticMismatch = true
                flags.addUnique(FLAG_CROSS_SNAPSHOT_CHANGE)
                val diff = kotlin.math.abs(lExact - eExact).toInt()
                notes.add(
                    "Wait changed from $eWaitLabel to $lWaitLabel. Because statistic types are not both verified and identical ($eStat vs $lStat), this difference is NOT a verified $diff-minute drop/increase."
                )
            } else {
                waitComparable = true
                waitDeltaMinutes = lExact - eExact
                if (waitDeltaMinutes != 0.0) {
                    flags.addUnique(FLAG_CROSS_SNAPSHOT_CHANGE)
                }
            }
        }

        if (earlier.requests30m != null && later.requests30m != null && earlier.requests30m != later.requests30m) {
            flags.addUnique(FLAG_CROSS_SNAPSHOT_CHANGE)
        }
        flags.addUnique(FLAG_OVERLAPPING_ROLLING_WINDOW)
        notes.add(
            "Rolling 30-minute request counts overlap across consecutive checks and must not be added together."
        )

        if (earlier.driveMinutes != null && later.driveMinutes != null && earlier.driveMinutes != later.driveMinutes) {
            flags.addUnique(FLAG_DRIVE_TIME_CONTEXT_CHANGED)
            notes.add(
                "Drive time changed from ${formatNum(earlier.driveMinutes)} min to ${formatNum(later.driveMinutes)} min. Drive time depends on starting position and traffic at capture time; do not assume identical origin."
            )
        }

        return ObservationComparison(
            areaLabel = later.areaLabel.ifBlank { earlier.areaLabel },
            earlierWaitDisplay = eWaitLabel,
            laterWaitDisplay = lWaitLabel,
            waitStatisticMismatch = waitStatisticMismatch,
            waitComparable = waitComparable,
            waitDeltaMinutes = waitDeltaMinutes,
            earlierRequests30m = earlier.requests30m,
            laterRequests30m = later.requests30m,
            earlierDriveMinutes = earlier.driveMinutes,
            laterDriveMinutes = later.driveMinutes,
            flags = flags,
            notes = notes,
        )
    }

    val SUPPORTED_COMPARISON_PREMISES = setOf(
        "short_wait_expected",
        "positioning_from_residential",
        "positioned_pickup_center",
        "reposition_advantage",
        "local_demand_active",
        "local_live_activity",
        "local_scheduled_activity",
    )

    fun buildTargetContextFromHere(here: HereState): DecisionTargetContext {
        val rawDecision = here.decisionState.ifBlank { here.action }.trim().uppercase(Locale.US)
        val targetZone = if (rawDecision == "MOVE") {
            here.bestRow?.zone?.ifBlank { here.zone } ?: here.zone
        } else {
            here.zone
        }
        val targetLabel = if (rawDecision == "MOVE") {
            here.destinationLabel.ifBlank { WorkingLocationController.cleanZoneDisplayName(targetZone) }
        } else {
            here.label.ifBlank { WorkingLocationController.cleanZoneDisplayName(here.zone) }
        }
        val premise = when {
            rawDecision == "MOVE" && here.recommendationBasis.equals("positioning_heuristic", ignoreCase = true) ->
                "positioning_from_residential"
            rawDecision == "MOVE" ->
                "reposition_advantage"
            (rawDecision == "WAIT" || rawDecision == "STAY") && here.recommendationBasis.equals("positioned_pickup_center", ignoreCase = true) ->
                "positioned_pickup_center"
            (rawDecision == "WAIT" || rawDecision == "STAY") && here.localLiveEvidence ->
                "local_live_activity"
            (rawDecision == "WAIT" || rawDecision == "STAY") && here.localScheduledEvidence ->
                "local_scheduled_activity"
            rawDecision == "WAIT" || rawDecision == "STAY" ->
                "local_demand_active"
            else ->
                "no_premise_watch"
        }
        return DecisionTargetContext(
            targetType = "now",
            recommendationId = here.recommendationId.ifBlank { "here-${here.zone}" },
            evidenceVersion = here.evidenceVersion.ifBlank { "v2" },
            issuedAt = here.asOf,
            action = rawDecision,
            decisionState = here.decisionState,
            originZone = here.zone,
            targetZone = targetZone,
            targetLabel = targetLabel,
            destinationId = here.destinationId.ifBlank { targetZone },
            structuredPremise = premise,
            repositionMinutes = here.bestRow?.repositionMinutes,
            moveCostDollars = here.stayOrMoveMoveCostDollars,
        )
    }

    fun buildTargetContextFromPlanStop(
        stop: ShiftCourseStop,
        originZone: String,
        generatedAt: String,
    ): DecisionTargetContext {
        return DecisionTargetContext(
            targetType = "plan_stop",
            recommendationId = "plan-${stop.zone}-${stop.hourIndex}",
            evidenceVersion = "v2",
            issuedAt = generatedAt,
            action = if (stop.driveMinutesFromPrev > 0) "MOVE" else "WAIT",
            decisionState = if (stop.driveMinutesFromPrev > 0) "MOVE" else "STAY",
            originZone = originZone,
            targetZone = stop.zone,
            targetLabel = stop.zoneLabel.ifBlank { WorkingLocationController.cleanZoneDisplayName(stop.zone) },
            destinationId = stop.zone,
            stopId = "stop_${stop.hourIndex}",
            stopHourOffset = (stop.hourIndex - 1).coerceAtLeast(0),
            structuredPremise = if (stop.events.isNotEmpty() || stop.hotVenues.isNotEmpty()) {
                "local_scheduled_activity"
            } else {
                "local_demand_active"
            },
            repositionMinutes = stop.driveMinutesFromPrev.toDouble(),
        )
    }

    fun comparisonDeterministicId(
        importRecord: UberAssistantImport,
        target: DecisionTargetContext,
    ): String {
        val seed = "${importRecord.id}|${importRecord.draftRevision}|${target.recommendationId}|${target.evidenceVersion}|${target.targetType}|${target.stopId.orEmpty()}"
        return "cmp-${computeFingerprint(seed).take(12)}"
    }

    fun evaluateDecisionComparison(
        importRecord: UberAssistantImport,
        target: DecisionTargetContext,
        evalTime: Instant = Instant.now(),
        maxSourceAgeMinutes: Long = DEFAULT_MAX_SOURCE_AGE_MINUTES,
        seenBeforeEpisodeStart: Boolean = true,
    ): DecisionComparisonRecord {
        val deterministicId = comparisonDeterministicId(importRecord, target)
        if (importRecord.isDemoSample || importRecord.suspectedLegacySample) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = emptyList(),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "DEMO_DATA_EXCLUDED",
                headline = "Sample record excluded from comparison",
                explanation = "Demo or suspected sample imports are isolated from live recommendations and personal outcome analytics.",
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val issuedInstant = target.issuedAt.takeIf { it.isNotBlank() }?.let { s ->
            runCatching { OffsetDateTime.parse(s.trim().replace(" ", "T")).toInstant() }.getOrElse {
                runCatching { Instant.parse(s.trim()) }.getOrNull()
            }
        }
        if (issuedInstant != null) {
            val recAgeSeconds = Duration.between(issuedInstant, evalTime).seconds
            if (recAgeSeconds > maxSourceAgeMinutes * 60L * 2L || recAgeSeconds < -120L) {
                return DecisionComparisonRecord(
                    id = deterministicId,
                    importId = importRecord.id,
                    importDraftRevision = importRecord.draftRevision,
                    observationIds = emptyList(),
                    recommendationId = target.recommendationId,
                    evidenceVersion = target.evidenceVersion,
                    targetType = target.targetType,
                    stopId = target.stopId,
                    action = target.action,
                    decisionState = target.decisionState,
                    originZone = target.originZone,
                    targetZone = target.targetZone,
                    targetLabel = target.targetLabel,
                    destinationId = target.destinationId,
                    structuredPremise = target.structuredPremise,
                    verdict = VERDICT_INSUFFICIENT,
                    reasonCode = "RECOMMENDATION_EXPIRED",
                    headline = "Not enough information — recommendation is stale",
                    explanation = "The RideEdge recommendation being compared was issued at ${target.issuedAt} and is no longer current at evaluation time.",
                    evaluatedAt = evalTime.toString(),
                    seenBeforeEpisodeStart = seenBeforeEpisodeStart,
                )
            }
        }

        if (target.targetType == "plan_stop" && target.stopHourOffset >= 2) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = emptyList(),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "FUTURE_STOP_OUT_OF_HORIZON",
                headline = "Not enough information for future stop (+${target.stopHourOffset}h)",
                explanation = "A current Uber Assistant observation cannot substantiate or challenge a shift stop ${target.stopHourOffset} hours ahead.",
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val matchingObs = importRecord.observations.filter { obs ->
            obs.areaKey != null && obs.areaKey.equals(target.targetZone, ignoreCase = true)
        }
        if (matchingObs.isEmpty()) {
            val covered = importRecord.observations.map { it.areaLabel }.distinct().joinToString(", ").ifBlank { "none" }
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = emptyList(),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "AREA_MISMATCH",
                headline = "Not enough information for ${target.targetLabel}",
                explanation = "Imported reply covers $covered and does not report metrics for ${target.targetLabel}.",
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val obs = matchingObs.first()
        val isBroadVsSpecific = !obs.areaLabel.equals(target.targetLabel, ignoreCase = true)
        val scopeNote = if (isBroadVsSpecific) {
            "Area scope note: Uber's broad '${obs.areaLabel}' figure does not verify a specific curb or staging spot (${target.targetLabel})."
        } else null

        if (
            obs.verificationLevel == "contradictory" ||
            FLAG_CARD_NARRATIVE_CONFLICT in obs.warnings ||
            FLAG_AMBIGUOUS_WAIT_VALUES in obs.warnings ||
            FLAG_AMBIGUOUS_REQUEST_VALUES in obs.warnings
        ) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "CONTRADICTORY_ASSERTIONS",
                headline = "Not enough information — conflicting figures in reply",
                explanation = "The imported reply contains conflicting or ambiguous numbers for ${obs.areaLabel} (${formatWaitDisplay(obs)}). Second opinion only — RideEdge's recommendation is unchanged.",
                scopeNote = scopeNote,
                sourceTime = obs.reportedSourceTime,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val srcTimeStr = obs.reportedSourceTime ?: importRecord.reportedSourceTime
        val srcInstant = srcTimeStr?.let { s ->
            runCatching { OffsetDateTime.parse(s.trim().replace(" ", "T")).toInstant() }.getOrElse {
                runCatching { Instant.parse(s.trim()) }.getOrNull()
            }
        }
        if (srcInstant == null) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "SOURCE_TIME_UNKNOWN",
                headline = "Not enough information — source time unknown",
                explanation = "Uber's reply reports ${formatWaitDisplay(obs)} in ${obs.areaLabel}, but the underlying measurement timestamp is unknown. A recent paste does not establish fresh data. Second opinion only — RideEdge's recommendation is unchanged.",
                scopeNote = scopeNote,
                sourceTime = null,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val ageSeconds = Duration.between(srcInstant, evalTime).seconds
        if (ageSeconds < -120L) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "SOURCE_TIME_FUTURE_INVALID",
                headline = "Not enough information — implausible future source timestamp",
                explanation = "Reported source timestamp ($srcTimeStr) is in the future relative to evaluation time.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val ageMinutes = (ageSeconds.coerceAtLeast(0L)) / 60L
        val expiresInstant = srcInstant.plus(Duration.ofMinutes(maxSourceAgeMinutes))
        val expiresAt = expiresInstant.toString()
        if (ageSeconds > maxSourceAgeMinutes * 60L) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "SOURCE_STALE",
                headline = "Not enough information — source observation expired (${ageMinutes}m old)",
                explanation = "Uber's source timestamp is $ageMinutes minutes old (exceeds $maxSourceAgeMinutes-minute comparison window). Historical context: ${formatWaitDisplay(obs)} in ${obs.areaLabel}.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                sourceAgeMinutesAtEval = ageMinutes,
                expiresAt = expiresAt,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        if (target.targetType == "plan_stop" && target.stopHourOffset >= 1) {
            val stopStartInstant = (issuedInstant ?: evalTime).plus(Duration.ofHours(target.stopHourOffset.toLong()))
            if (expiresInstant.isBefore(stopStartInstant)) {
                return DecisionComparisonRecord(
                    id = deterministicId,
                    importId = importRecord.id,
                    importDraftRevision = importRecord.draftRevision,
                    observationIds = listOf(obs.id),
                    recommendationId = target.recommendationId,
                    evidenceVersion = target.evidenceVersion,
                    targetType = target.targetType,
                    stopId = target.stopId,
                    action = target.action,
                    decisionState = target.decisionState,
                    originZone = target.originZone,
                    targetZone = target.targetZone,
                    targetLabel = target.targetLabel,
                    destinationId = target.destinationId,
                    structuredPremise = target.structuredPremise,
                    verdict = VERDICT_INSUFFICIENT,
                    reasonCode = "FUTURE_STOP_OUT_OF_HORIZON",
                    headline = "Not enough information — observation expires before stop (+${target.stopHourOffset}h)",
                    explanation = "Uber's observation expires at $expiresAt, before the planned stop at +${target.stopHourOffset}h begins.",
                    scopeNote = scopeNote,
                    sourceTime = srcTimeStr,
                    sourceAgeMinutesAtEval = ageMinutes,
                    expiresAt = expiresAt,
                    evaluatedAt = evalTime.toString(),
                    seenBeforeEpisodeStart = seenBeforeEpisodeStart,
                )
            }
        }

        if (target.structuredPremise !in SUPPORTED_COMPARISON_PREMISES || target.structuredPremise == "no_premise_watch") {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "NO_RIDEEDGE_PREMISE",
                headline = "Not enough information — RideEdge made no move or short-wait claim",
                explanation = "RideEdge is in Watch for ${target.targetLabel} (no active move or short-wait premise). Imported context: ${formatWaitDisplay(obs)}, 30m requests: ${obs.requests30m ?: "N/A"}. Second opinion only — RideEdge's recommendation is unchanged.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                sourceAgeMinutesAtEval = ageMinutes,
                expiresAt = expiresAt,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val exactWait = obs.waitMinutesExact
        val lowerBound = obs.waitMinutesLowerBound
        val stat = obs.waitStatistic.lowercase(Locale.US)
        val isCentralWaitStat = stat in setOf("p50", "median", "mean", "typical")

        if (target.structuredPremise in setOf("positioning_from_residential", "positioned_pickup_center")) {
            val challengesPos = (lowerBound != null && lowerBound >= 25.0) ||
                (exactWait != null && exactWait >= 25.0 && stat != "p90")
            if (challengesPos) {
                return DecisionComparisonRecord(
                    id = deterministicId,
                    importId = importRecord.id,
                    importDraftRevision = importRecord.draftRevision,
                    observationIds = listOf(obs.id),
                    recommendationId = target.recommendationId,
                    evidenceVersion = target.evidenceVersion,
                    targetType = target.targetType,
                    stopId = target.stopId,
                    action = target.action,
                    decisionState = target.decisionState,
                    originZone = target.originZone,
                    targetZone = target.targetZone,
                    targetLabel = target.targetLabel,
                    destinationId = target.destinationId,
                    structuredPremise = target.structuredPremise,
                    verdict = VERDICT_CHALLENGES,
                    reasonCode = "CHALLENGES_POSITIONING_WAIT",
                    headline = "Uber's reply challenges positioning near ${target.targetLabel}",
                    explanation = "RideEdge suggested positioning near ${target.targetLabel} from a residential start (current demand unverified). Your imported reply reports ${formatWaitDisplay(obs)} in ${obs.areaLabel}. That weakens this positioning choice; it does not prove another area is better. Source updated $ageMinutes min ago · Second opinion only — RideEdge's recommendation is unchanged.",
                    scopeNote = scopeNote,
                    sourceTime = srcTimeStr,
                    sourceAgeMinutesAtEval = ageMinutes,
                    expiresAt = expiresAt,
                    evaluatedAt = evalTime.toString(),
                    seenBeforeEpisodeStart = seenBeforeEpisodeStart,
                )
            }
            val supportsPos = exactWait != null && exactWait <= 12.0 &&
                (isCentralWaitStat || (obs.requests30m != null && obs.requests30m >= 20))
            if (supportsPos) {
                return DecisionComparisonRecord(
                    id = deterministicId,
                    importId = importRecord.id,
                    importDraftRevision = importRecord.draftRevision,
                    observationIds = listOf(obs.id),
                    recommendationId = target.recommendationId,
                    evidenceVersion = target.evidenceVersion,
                    targetType = target.targetType,
                    stopId = target.stopId,
                    action = target.action,
                    decisionState = target.decisionState,
                    originZone = target.originZone,
                    targetZone = target.targetZone,
                    targetLabel = target.targetLabel,
                    destinationId = target.destinationId,
                    structuredPremise = target.structuredPremise,
                    verdict = VERDICT_SUPPORTS,
                    reasonCode = "SUPPORTS_POSITIONING_WAIT",
                    headline = "Uber's reply supports positioning near ${target.targetLabel}",
                    explanation = "RideEdge suggested positioning near ${target.targetLabel} from a residential start. Your imported reply reports ${formatWaitDisplay(obs)} in ${obs.areaLabel}. Source updated $ageMinutes min ago · Second opinion only — RideEdge's recommendation is unchanged.",
                    scopeNote = scopeNote,
                    sourceTime = srcTimeStr,
                    sourceAgeMinutesAtEval = ageMinutes,
                    expiresAt = expiresAt,
                    evaluatedAt = evalTime.toString(),
                    seenBeforeEpisodeStart = seenBeforeEpisodeStart,
                )
            }
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_INSUFFICIENT,
                reasonCode = "REQUESTS_ONLY_NO_WAIT",
                headline = "Not enough information for ${target.targetLabel}",
                explanation = "Imported reply reports 30m requests=${obs.requests30m ?: "N/A"} and wait=${formatWaitDisplay(obs)} in ${obs.areaLabel}. Without a compatible wait statistic or request volume, it cannot confirm or challenge positioning.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                sourceAgeMinutesAtEval = ageMinutes,
                expiresAt = expiresAt,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        // Premise is short_wait_expected, local_demand_active, local_live_activity, local_scheduled_activity, or reposition_advantage
        val challengesPremise = (lowerBound != null && lowerBound >= 20.0) ||
            (exactWait != null && exactWait >= 20.0 && stat != "p90" && (target.structuredPremise != "short_wait_expected" || isCentralWaitStat))
        if (challengesPremise) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_CHALLENGES,
                reasonCode = "LONG_WAIT_CHALLENGES_PREMISE",
                headline = "Uber's reply challenges the ${target.targetLabel} recommendation",
                explanation = "RideEdge's ${target.targetLabel} recommendation relies on active pickup conditions (${target.structuredPremise.replace('_', ' ')}). Your imported reply reports ${formatWaitDisplay(obs)} there. That weakens this reason; it does not establish another area is better. Source updated $ageMinutes min ago · Second opinion only — RideEdge's recommendation is unchanged.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                sourceAgeMinutesAtEval = ageMinutes,
                expiresAt = expiresAt,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        val supportsPremise = exactWait != null && exactWait <= 12.0 && (
            if (target.structuredPremise == "short_wait_expected") {
                isCentralWaitStat
            } else {
                isCentralWaitStat || (stat != "p90" && obs.requests30m != null && obs.requests30m >= 25)
            }
        )
        if (supportsPremise) {
            return DecisionComparisonRecord(
                id = deterministicId,
                importId = importRecord.id,
                importDraftRevision = importRecord.draftRevision,
                observationIds = listOf(obs.id),
                recommendationId = target.recommendationId,
                evidenceVersion = target.evidenceVersion,
                targetType = target.targetType,
                stopId = target.stopId,
                action = target.action,
                decisionState = target.decisionState,
                originZone = target.originZone,
                targetZone = target.targetZone,
                targetLabel = target.targetLabel,
                destinationId = target.destinationId,
                structuredPremise = target.structuredPremise,
                verdict = VERDICT_SUPPORTS,
                reasonCode = "SHORT_WAIT_SUPPORTS_PREMISE",
                headline = "Uber's reply supports the ${target.targetLabel} recommendation",
                explanation = "RideEdge's ${target.targetLabel} recommendation (${target.structuredPremise.replace('_', ' ')}) is consistent with the imported ${formatWaitDisplay(obs)} in ${obs.areaLabel}. Source updated $ageMinutes min ago · Second opinion only — RideEdge's recommendation is unchanged.",
                scopeNote = scopeNote,
                sourceTime = srcTimeStr,
                sourceAgeMinutesAtEval = ageMinutes,
                expiresAt = expiresAt,
                evaluatedAt = evalTime.toString(),
                seenBeforeEpisodeStart = seenBeforeEpisodeStart,
            )
        }

        return DecisionComparisonRecord(
            id = deterministicId,
            importId = importRecord.id,
            importDraftRevision = importRecord.draftRevision,
            observationIds = listOf(obs.id),
            recommendationId = target.recommendationId,
            evidenceVersion = target.evidenceVersion,
            targetType = target.targetType,
            stopId = target.stopId,
            action = target.action,
            decisionState = target.decisionState,
            originZone = target.originZone,
            targetZone = target.targetZone,
            targetLabel = target.targetLabel,
            destinationId = target.destinationId,
            structuredPremise = target.structuredPremise,
            verdict = VERDICT_INSUFFICIENT,
            reasonCode = "INSUFFICIENT_WAIT_EVIDENCE",
            headline = "Not enough information for ${target.targetLabel}",
            explanation = "Imported reply reports wait=${formatWaitDisplay(obs)} and 30m requests=${obs.requests30m ?: "N/A"} in ${obs.areaLabel}. Wait statistic ($stat) or request evidence is insufficient to validate ${target.structuredPremise.replace('_', ' ')}.",
            scopeNote = scopeNote,
            sourceTime = srcTimeStr,
            sourceAgeMinutesAtEval = ageMinutes,
            expiresAt = expiresAt,
            evaluatedAt = evalTime.toString(),
            seenBeforeEpisodeStart = seenBeforeEpisodeStart,
        )
    }

    fun summarizeHistoryUsefulness(
        imports: List<UberAssistantImport>,
        comparisons: List<DecisionComparisonRecord>,
    ): HistoryUsefulSummary {
        val nonDemoImports = imports.filterNot { it.isDemoSample || it.suspectedLegacySample }
        val excludedCount = imports.size - nonDemoImports.size +
            nonDemoImports.count { FLAG_DUPLICATE_IMPORT in it.warnings }
        val uniqueImports = nonDemoImports.distinctBy { it.fingerprint }

        val nonDemoComparisons = comparisons.filterNot { it.reasonCode == "DEMO_DATA_EXCLUDED" }
        val nowComparisonsByImport = nonDemoComparisons
            .filter { it.targetType == "now" }
            .groupBy { it.importId }

        var usableCount = 0
        var missingTsCount = 0
        var staleCount = 0
        var areaMismatchCount = 0
        var contradictoryCount = 0

        for (imp in uniqueImports) {
            val cmps = nowComparisonsByImport[imp.id].orEmpty()
            val primary = cmps.firstOrNull()
            when {
                primary != null && primary.verdict in setOf(VERDICT_SUPPORTS, VERDICT_CHALLENGES) -> usableCount++
                primary?.reasonCode == "SOURCE_TIME_UNKNOWN" || imp.reportedSourceTime == null -> missingTsCount++
                primary?.reasonCode == "SOURCE_STALE" -> staleCount++
                primary?.reasonCode == "AREA_MISMATCH" -> areaMismatchCount++
                primary?.reasonCode == "CONTRADICTORY_ASSERTIONS" || imp.observations.any { it.verificationLevel == "contradictory" } -> contradictoryCount++
                else -> {}
            }
        }

        val uniqueDecisionCmps = nonDemoComparisons
            .filter { it.targetType == "now" }
            .distinctBy { "${it.importId}::${it.recommendationId}::${it.linkedEpisodeId.orEmpty()}" }

        val supportsCount = uniqueDecisionCmps.count { it.verdict == VERDICT_SUPPORTS }
        val challengesCount = uniqueDecisionCmps.count { it.verdict == VERDICT_CHALLENGES }
        val insufficientCount = uniqueDecisionCmps.count { it.verdict == VERDICT_INSUFFICIENT }

        val linkedAll = uniqueDecisionCmps.filter { !it.linkedEpisodeId.isNullOrBlank() }
        val seenMidWaitExcluded = linkedAll.count { !it.seenBeforeEpisodeStart }
        val preDecisionEpisodes = linkedAll
            .filter { it.seenBeforeEpisodeStart }
            .distinctBy { it.linkedEpisodeId }

        val dryWaitStatuses = setOf("observed_15m_no_request", "no_request_after_15m", "dry_wait_15m")
        val adequate = preDecisionEpisodes.filter {
            it.outcomeStatus in setOf("request_within_15m", "request_after_15m") ||
                it.outcomeStatus in dryWaitStatuses ||
                (it.outcomeStatus == "accepted_ride" && it.waitMinutesToRequest != null)
        }
        val incomplete = preDecisionEpisodes.size - adequate.size
        val reqWithin15 = adequate.count {
            (it.outcomeStatus == "request_within_15m" && (it.waitMinutesToRequest == null || it.waitMinutesToRequest <= 15.0)) ||
                (it.outcomeStatus in setOf("accepted_ride", "request_after_15m") && it.waitMinutesToRequest != null && it.waitMinutesToRequest <= 15.0)
        }
        val dry15 = adequate.count { it.outcomeStatus in dryWaitStatuses }
        val acceptedCount = preDecisionEpisodes.count { it.acceptedRide || it.outcomeStatus == "accepted_ride" }

        val completedWaits = adequate.mapNotNull { it.waitMinutesToRequest }.sorted()
        val medianWait = if (completedWaits.isEmpty()) {
            null
        } else if (completedWaits.size % 2 == 1) {
            completedWaits[completedWaits.size / 2]
        } else {
            val mid = completedWaits.size / 2
            (completedWaits[mid - 1] + completedWaits[mid]) / 2.0
        }

        val stayedAfterChallenge = adequate.filter {
            it.verdict == VERDICT_CHALLENGES && it.driverChoice == "stayed"
        }
        val stayedAfterChallengeReq15 = stayedAfterChallenge.count {
            (it.outcomeStatus == "request_within_15m" && (it.waitMinutesToRequest == null || it.waitMinutesToRequest <= 15.0)) ||
                (it.outcomeStatus in setOf("accepted_ride", "request_after_15m") && it.waitMinutesToRequest != null && it.waitMinutesToRequest <= 15.0)
        }
        val movedWithSupport = adequate.count {
            it.verdict == VERDICT_SUPPORTS && it.driverChoice == "moved"
        }

        return HistoryUsefulSummary(
            totalUniqueImports = uniqueImports.size,
            usableForComparisonCount = usableCount,
            unusableMissingTimestampCount = missingTsCount,
            unusableStaleCount = staleCount,
            unusableAreaMismatchCount = areaMismatchCount,
            unusableContradictoryCount = contradictoryCount,
            excludedDemoOrDuplicateCount = excludedCount,
            supportsCount = supportsCount,
            challengesCount = challengesCount,
            insufficientCount = insufficientCount,
            linkedEpisodesTotal = preDecisionEpisodes.size,
            adequatelyLoggedCount = adequate.size,
            incompleteOrUnknownCount = incomplete,
            seenMidWaitExcludedCount = seenMidWaitExcluded,
            requestWithin15mCount = reqWithin15,
            verifiedDryWait15mCount = dry15,
            acceptedRideCount = acceptedCount,
            medianMinutesToRequestCompletedOnly = medianWait,
            stayedAfterChallengeCount = stayedAfterChallenge.size,
            stayedAfterChallengeRequestWithin15mCount = stayedAfterChallengeReq15,
            movedWithSupportCount = movedWithSupport,
        )
    }

    fun comparisonToJson(c: DecisionComparisonRecord): JSONObject {
        return JSONObject()
            .put("id", c.id)
            .put("import_id", c.importId)
            .put("import_draft_revision", c.importDraftRevision)
            .put("observation_ids", JSONArray(c.observationIds))
            .put("recommendation_id", c.recommendationId)
            .put("evidence_version", c.evidenceVersion)
            .put("target_type", c.targetType)
            .put("stop_id", c.stopId ?: JSONObject.NULL)
            .put("action", c.action)
            .put("decision_state", c.decisionState)
            .put("origin_zone", c.originZone)
            .put("target_zone", c.targetZone)
            .put("target_label", c.targetLabel)
            .put("destination_id", c.destinationId)
            .put("structured_premise", c.structuredPremise)
            .put("verdict", c.verdict)
            .put("reason_code", c.reasonCode)
            .put("headline", c.headline)
            .put("explanation", c.explanation)
            .put("scope_note", c.scopeNote ?: JSONObject.NULL)
            .put("source_time", c.sourceTime ?: JSONObject.NULL)
            .put("source_age_minutes_at_eval", c.sourceAgeMinutesAtEval ?: JSONObject.NULL)
            .put("expires_at", c.expiresAt ?: JSONObject.NULL)
            .put("evaluated_at", c.evaluatedAt)
            .put("policy_version", c.policyVersion)
            .put("seen_before_episode_start", c.seenBeforeEpisodeStart)
            .put("driver_choice", c.driverChoice)
            .put("linked_episode_id", c.linkedEpisodeId ?: JSONObject.NULL)
            .put("outcome_status", c.outcomeStatus)
            .put("wait_minutes_to_request", c.waitMinutesToRequest ?: JSONObject.NULL)
            .put("accepted_ride", c.acceptedRide)
            .put("empty_drive_minutes", c.emptyDriveMinutes ?: JSONObject.NULL)
            .put("empty_drive_miles", c.emptyDriveMiles ?: JSONObject.NULL)
            .put("user_perceived_useful", c.userPerceivedUseful ?: JSONObject.NULL)
    }

    fun comparisonFromJson(o: JSONObject): DecisionComparisonRecord {
        val obsIdsArr = o.optJSONArray("observation_ids") ?: JSONArray()
        val obsIds = (0 until obsIdsArr.length()).mapNotNull { obsIdsArr.optString(it).takeIf { s -> s.isNotEmpty() } }
        return DecisionComparisonRecord(
            id = o.optString("id", "cmp-unknown"),
            importId = o.optString("import_id", ""),
            importDraftRevision = o.optString("import_draft_revision", ""),
            observationIds = obsIds,
            recommendationId = o.optString("recommendation_id", ""),
            evidenceVersion = o.optString("evidence_version", "v2"),
            targetType = o.optString("target_type", "now"),
            stopId = if (o.isNull("stop_id")) null else o.optString("stop_id"),
            action = o.optString("action", "WATCH"),
            decisionState = o.optString("decision_state", ""),
            originZone = o.optString("origin_zone", ""),
            targetZone = o.optString("target_zone", ""),
            targetLabel = o.optString("target_label", ""),
            destinationId = o.optString("destination_id", ""),
            structuredPremise = o.optString("structured_premise", "no_premise_watch"),
            verdict = o.optString("verdict", VERDICT_INSUFFICIENT),
            reasonCode = o.optString("reason_code", "UNKNOWN"),
            headline = o.optString("headline", ""),
            explanation = o.optString("explanation", ""),
            scopeNote = if (o.isNull("scope_note")) null else o.optString("scope_note"),
            sourceTime = if (o.isNull("source_time")) null else o.optString("source_time"),
            sourceAgeMinutesAtEval = if (o.isNull("source_age_minutes_at_eval")) null else o.optLong("source_age_minutes_at_eval"),
            expiresAt = if (o.isNull("expires_at")) null else o.optString("expires_at"),
            evaluatedAt = o.optString("evaluated_at", ""),
            policyVersion = o.optString("policy_version", COMPARISON_POLICY_VERSION),
            seenBeforeEpisodeStart = o.optBoolean("seen_before_episode_start", true),
            driverChoice = o.optString("driver_choice", "unknown"),
            linkedEpisodeId = if (o.isNull("linked_episode_id")) null else o.optString("linked_episode_id"),
            outcomeStatus = o.optString("outcome_status", "unknown"),
            waitMinutesToRequest = if (o.isNull("wait_minutes_to_request")) null else o.optDouble("wait_minutes_to_request"),
            acceptedRide = o.optBoolean("accepted_ride", false),
            emptyDriveMinutes = if (o.isNull("empty_drive_minutes")) null else o.optDouble("empty_drive_minutes"),
            emptyDriveMiles = if (o.isNull("empty_drive_miles")) null else o.optDouble("empty_drive_miles"),
            userPerceivedUseful = if (o.isNull("user_perceived_useful")) null else o.optBoolean("user_perceived_useful"),
        )
    }

    fun importToJson(imp: UberAssistantImport): JSONObject {
        val obsArr = JSONArray()
        for (o in imp.observations) {
            val evObj = JSONObject()
            o.fieldEvidence.forEach { (k, v) -> evObj.put(k, v) }
            val spObj = JSONObject()
            o.fieldSpans.forEach { (k, v) -> spObj.put(k, v) }
            val astArr = JSONArray()
            for (a in o.assertions) {
                astArr.put(
                    JSONObject()
                        .put("id", a.id)
                        .put("area_label", a.areaLabel)
                        .put("area_key", a.areaKey ?: JSONObject.NULL)
                        .put("metric", a.metric)
                        .put("numeric_value", if (a.numericValue != null && a.numericValue.isFinite()) a.numericValue else JSONObject.NULL)
                        .put("unit", a.unit)
                        .put("window_minutes", a.windowMinutes ?: JSONObject.NULL)
                        .put("statistic", a.statistic)
                        .put("origin", a.origin)
                        .put("source_span", a.sourceSpan)
                )
            }

            obsArr.put(
                JSONObject()
                    .put("id", o.id)
                    .put("import_id", o.importId.ifBlank { imp.id })
                    .put("area_label", o.areaLabel)
                    .put("area_key", o.areaKey ?: JSONObject.NULL)
                    .put("requests_30m", o.requests30m ?: JSONObject.NULL)
                    .put("requests_window_minutes", o.requestsWindowMinutes ?: JSONObject.NULL)
                    .put("requests_other_window_count", o.requestsOtherWindowCount ?: JSONObject.NULL)
                    .put("candidate_requests_30m", JSONArray(o.candidateRequests30m))
                    .put("requests_is_approximate", o.requestsIsApproximate)
                    .put("wait_minutes_exact", if (o.waitMinutesExact != null && o.waitMinutesExact.isFinite()) o.waitMinutesExact else JSONObject.NULL)
                    .put("wait_minutes_lower_bound", if (o.waitMinutesLowerBound != null && o.waitMinutesLowerBound.isFinite()) o.waitMinutesLowerBound else JSONObject.NULL)
                    .put("candidate_exact_waits", JSONArray(o.candidateExactWaits.filter { it.isFinite() }))
                    .put("candidate_lower_bound_waits", JSONArray(o.candidateLowerBoundWaits.filter { it.isFinite() }))
                    .put("wait_statistic", o.waitStatistic)
                    .put("drive_minutes", if (o.driveMinutes != null && o.driveMinutes.isFinite()) o.driveMinutes else JSONObject.NULL)
                    .put("reported_source_time", o.reportedSourceTime ?: JSONObject.NULL)
                    .put("reported_source_time_raw", o.reportedSourceTimeRaw ?: JSONObject.NULL)
                    .put("claimed_source_field", o.claimedSourceField ?: JSONObject.NULL)
                    .put("claimed_source_field_verified", o.claimedSourceFieldVerified)
                    .put("claimed_statistic_hint", o.claimedStatisticHint ?: JSONObject.NULL)
                    .put("text_origin", o.textOrigin)
                    .put("provenance", o.provenance)
                    .put("verification_level", o.verificationLevel)
                    .put("freshness", o.freshness)
                    .put("metric_semantics", JSONArray(o.metricSemantics))
                    .put("field_evidence", evObj)
                    .put("field_spans", spObj)
                    .put("warnings", JSONArray(o.warnings))
                    .put("source_span", o.sourceSpan)
                    .put("assertions", astArr)
                    .put("edited_by_user", o.editedByUser)
                    .put("original_extracted_json", o.originalExtractedJson ?: JSONObject.NULL)
            )
        }
        return JSONObject()
            .put("id", imp.id)
            .put("created_at", imp.createdAt)
            .put("display_timezone", imp.displayTimezone)
            .put("user_prompt", imp.userPrompt ?: JSONObject.NULL)
            .put("prompt_status", imp.promptStatus)
            .put("raw_response", imp.rawResponse)
            .put("source_app", imp.sourceApp)
            .put("capture_method", imp.captureMethod)
            .put("reply_display_time", imp.replyDisplayTime ?: JSONObject.NULL)
            .put("reported_source_time", imp.reportedSourceTime ?: JSONObject.NULL)
            .put("reported_source_time_raw", imp.reportedSourceTimeRaw ?: JSONObject.NULL)
            .put("parser_version", imp.parserVersion)
            .put("parse_status", imp.parseStatus)
            .put("draft_revision", imp.draftRevision)
            .put("consent_confirmed", imp.consentConfirmed)
            .put("notes", imp.notes ?: JSONObject.NULL)
            .put("fingerprint", imp.fingerprint)
            .put("warnings", JSONArray(imp.warnings))
            .put("observations", obsArr)
            .put("is_demo_sample", imp.isDemoSample)
            .put("suspected_legacy_sample", imp.suspectedLegacySample)
    }

    private val KNOWN_SAMPLE_TIMESTAMPS = setOf("2026-10-21T23:55:00Z", "2026-10-22T00:05:00Z")

    fun importFromJson(obj: JSONObject): UberAssistantImport {
        val impId = obj.optString("id", "imp-unknown")
        val warnArr = obj.optJSONArray("warnings") ?: JSONArray()
        val warnings = (0 until warnArr.length()).mapNotNull { warnArr.optString(it).takeIf { s -> s.isNotEmpty() } }

        val obsArr = obj.optJSONArray("observations") ?: JSONArray()
        val observations = mutableListOf<UberAssistantObservation>()
        for (i in 0 until obsArr.length()) {
            val o = obsArr.optJSONObject(i) ?: continue
            val evObj = o.optJSONObject("field_evidence") ?: JSONObject()
            val evMap = mutableMapOf<String, String>()
            evObj.keys().forEach { k -> evMap[k] = evObj.optString(k) }

            val spObj = o.optJSONObject("field_spans") ?: JSONObject()
            val spMap = mutableMapOf<String, String>()
            spObj.keys().forEach { k -> spMap[k] = spObj.optString(k) }

            val wArr = o.optJSONArray("warnings") ?: JSONArray()
            val obsWarnings = (0 until wArr.length()).mapNotNull { wArr.optString(it).takeIf { s -> s.isNotEmpty() } }

            val semArr = o.optJSONArray("metric_semantics") ?: JSONArray()
            val semantics = (0 until semArr.length()).mapNotNull { semArr.optString(it).takeIf { s -> s.isNotEmpty() } }

            val candArr = o.optJSONArray("candidate_exact_waits") ?: JSONArray()
            val candWaits = (0 until candArr.length()).map { candArr.optDouble(it) }.filter { !it.isNaN() }

            val candLbArr = o.optJSONArray("candidate_lower_bound_waits") ?: JSONArray()
            val candLbWaits = (0 until candLbArr.length()).map { candLbArr.optDouble(it) }.filter { !it.isNaN() }

            val candReqArr = o.optJSONArray("candidate_requests_30m") ?: JSONArray()
            val candReqs = (0 until candReqArr.length()).map { candReqArr.optInt(it) }

            val astArr = o.optJSONArray("assertions") ?: JSONArray()
            val assertions = mutableListOf<UberAssistantAssertion>()
            for (j in 0 until astArr.length()) {
                val a = astArr.optJSONObject(j) ?: continue
                assertions.add(
                    UberAssistantAssertion(
                        id = a.optString("id", "ast-$j"),
                        areaLabel = a.optString("area_label", ""),
                        areaKey = if (a.isNull("area_key")) null else a.optString("area_key"),
                        metric = a.optString("metric", ""),
                        numericValue = if (a.isNull("numeric_value")) null else a.optDouble("numeric_value"),
                        unit = a.optString("unit", ""),
                        windowMinutes = if (a.isNull("window_minutes")) null else a.optInt("window_minutes"),
                        statistic = a.optString("statistic", "unknown"),
                        origin = a.optString("origin", "unknown"),
                        sourceSpan = a.optString("source_span", ""),
                    )
                )
            }

            observations.add(
                UberAssistantObservation(
                    id = o.optString("id", "obs-$i"),
                    importId = o.optString("import_id", impId),
                    areaLabel = o.optString("area_label", ""),
                    areaKey = if (o.isNull("area_key")) null else o.optString("area_key"),
                    requests30m = if (o.isNull("requests_30m")) null else o.optInt("requests_30m"),
                    requestsWindowMinutes = if (o.isNull("requests_window_minutes")) null else o.optInt("requests_window_minutes"),
                    requestsOtherWindowCount = if (o.isNull("requests_other_window_count")) null else o.optInt("requests_other_window_count"),
                    candidateRequests30m = candReqs,
                    requestsIsApproximate = o.optBoolean("requests_is_approximate", false),
                    waitMinutesExact = if (o.isNull("wait_minutes_exact")) null else o.optDouble("wait_minutes_exact"),
                    waitMinutesLowerBound = if (o.isNull("wait_minutes_lower_bound")) null else o.optDouble("wait_minutes_lower_bound"),
                    candidateExactWaits = candWaits,
                    candidateLowerBoundWaits = candLbWaits,
                    waitStatistic = o.optString("wait_statistic", "unknown"),
                    driveMinutes = if (o.isNull("drive_minutes")) null else o.optDouble("drive_minutes"),
                    reportedSourceTime = if (o.isNull("reported_source_time")) null else o.optString("reported_source_time"),
                    reportedSourceTimeRaw = if (o.isNull("reported_source_time_raw")) null else o.optString("reported_source_time_raw"),
                    claimedSourceField = if (o.isNull("claimed_source_field")) null else o.optString("claimed_source_field"),
                    claimedSourceFieldVerified = o.optBoolean("claimed_source_field_verified", false),
                    claimedStatisticHint = if (o.isNull("claimed_statistic_hint")) null else o.optString("claimed_statistic_hint"),
                    textOrigin = o.optString("text_origin", "unknown"),
                    provenance = o.optString("provenance", "unknown"),
                    verificationLevel = o.optString("verification_level", "ai_reported_unverified"),
                    freshness = o.optString("freshness", "capture_time_only"),
                    metricSemantics = semantics,
                    fieldEvidence = evMap,
                    fieldSpans = spMap,
                    warnings = obsWarnings,
                    sourceSpan = o.optString("source_span", ""),
                    assertions = assertions,
                    editedByUser = o.optBoolean("edited_by_user", false),
                    originalExtractedJson = if (o.isNull("original_extracted_json")) null else o.optString("original_extracted_json"),
                )
            )
        }

        val createdAt = obj.optString("created_at", "")
        val isDemo = obj.optBoolean("is_demo_sample", false) || obj.optString("source_app") == "demo_seed"
        val suspectedSample = obj.optBoolean("suspected_legacy_sample", false) ||
            createdAt in KNOWN_SAMPLE_TIMESTAMPS

        return UberAssistantImport(
            id = impId,
            createdAt = createdAt,
            displayTimezone = obj.optString("display_timezone", "America/Los_Angeles"),
            userPrompt = if (obj.isNull("user_prompt")) null else obj.optString("user_prompt"),
            promptStatus = obj.optString("prompt_status", "unconfirmed"),
            rawResponse = obj.optString("raw_response", ""),
            sourceApp = obj.optString("source_app", "uber_assistant_beta"),
            captureMethod = obj.optString("capture_method", "manual_paste"),
            replyDisplayTime = if (obj.isNull("reply_display_time")) null else obj.optString("reply_display_time"),
            reportedSourceTime = if (obj.isNull("reported_source_time")) null else obj.optString("reported_source_time"),
            reportedSourceTimeRaw = if (obj.isNull("reported_source_time_raw")) null else obj.optString("reported_source_time_raw"),
            parserVersion = obj.optString("parser_version", PARSER_VERSION),
            parseStatus = obj.optString("parse_status", "parsed"),
            draftRevision = obj.optString("draft_revision", ""),
            consentConfirmed = obj.optBoolean("consent_confirmed", true),
            notes = if (obj.isNull("notes")) null else obj.optString("notes"),
            fingerprint = obj.optString("fingerprint", computeFingerprint(obj.optString("raw_response", ""))),
            warnings = warnings,
            observations = observations,
            isDemoSample = isDemo,
            suspectedLegacySample = suspectedSample,
        )
    }
}

class UberIntelligenceRepository(private val storageFile: File) {
    data class StorageHealth(
        val ok: Boolean,
        val errorMessage: String? = null,
        val rawByteCount: Long = 0L,
    )

    private data class PendingEpisodeInfo(
        val recommendationId: String,
        val episodeId: String,
        val driverChoice: String,
        val outcomeStatus: String,
        val snapshots: Map<String, UberIntelligence.DecisionComparisonRecord> = emptyMap(),
    )

    private data class StoreEnvelope(
        val imports: List<UberIntelligence.UberAssistantImport>,
        val comparisons: List<UberIntelligence.DecisionComparisonRecord>,
        val pendingEpisodes: Map<String, PendingEpisodeInfo> = emptyMap(),
        val currentComparisons: Map<String, UberIntelligence.DecisionComparisonRecord> = emptyMap(),
        val stagedTapComparisons: Map<String, UberIntelligence.DecisionComparisonRecord> = emptyMap(),
    )

    private fun comparisonSlotKey(
        importId: String,
        recommendationId: String,
        targetType: String,
        stopId: String?,
    ): String = "$importId|$recommendationId|$targetType|${stopId.orEmpty()}"

    @Synchronized
    fun inspectStorageHealth(): StorageHealth {
        if (!storageFile.exists()) return StorageHealth(ok = true, rawByteCount = 0L)
        return try {
            readEnvelopeStrict()
            StorageHealth(ok = true, rawByteCount = storageFile.length())
        } catch (e: Exception) {
            StorageHealth(
                ok = false,
                errorMessage = e.message ?: "Malformed JSON in storage file",
                rawByteCount = storageFile.length(),
            )
        }
    }

    @Synchronized
    private fun readEnvelopeStrict(): StoreEnvelope {
        if (!storageFile.exists()) {
            return StoreEnvelope(emptyList(), emptyList(), emptyMap(), emptyMap())
        }
        val rawText = storageFile.readText(Charsets.UTF_8)
        if (rawText.isBlank()) {
            throw IllegalStateException("Uber Intelligence storage file is empty or unreadable; refusing to overwrite.")
        }
        val root = try {
            JSONObject(rawText)
        } catch (e: Exception) {
            throw IllegalStateException("Corrupt Uber Intelligence storage file; refusing to overwrite existing bytes.", e)
        }
        if (!root.has("imports") || root.optJSONArray("imports") == null) {
            throw IllegalStateException("Uber Intelligence storage file is missing 'imports' array; refusing to overwrite.")
        }
        val arr = root.getJSONArray("imports")
        val imports = (0 until arr.length()).map { i ->
            val item = arr.optJSONObject(i)
                ?: throw IllegalStateException("Corrupt import entry at index $i")
            UberIntelligence.importFromJson(item)
        }
        val cmpArr = root.optJSONArray("comparisons") ?: JSONArray()
        val comparisons = (0 until cmpArr.length()).mapNotNull { i ->
            cmpArr.optJSONObject(i)?.let { UberIntelligence.comparisonFromJson(it) }
        }
        val currentCmpArr = root.optJSONArray("current_comparisons")
        val currentComparisons = mutableMapOf<String, UberIntelligence.DecisionComparisonRecord>()
        if (currentCmpArr != null) {
            for (i in 0 until currentCmpArr.length()) {
                val c = currentCmpArr.optJSONObject(i)?.let { UberIntelligence.comparisonFromJson(it) } ?: continue
                currentComparisons[comparisonSlotKey(c.importId, c.recommendationId, c.targetType, c.stopId)] = c
            }
        }
        val stagedTapArr = root.optJSONArray("staged_tap_comparisons")
        val stagedTapComparisons = mutableMapOf<String, UberIntelligence.DecisionComparisonRecord>()
        if (stagedTapArr != null) {
            for (i in 0 until stagedTapArr.length()) {
                val c = stagedTapArr.optJSONObject(i)?.let { UberIntelligence.comparisonFromJson(it) } ?: continue
                stagedTapComparisons[comparisonSlotKey(c.importId, c.recommendationId, c.targetType, c.stopId)] = c
            }
        }
        val pendingObj = root.optJSONObject("pending_episodes")
        val pendingMap = mutableMapOf<String, PendingEpisodeInfo>()
        if (pendingObj != null) {
            for (epKey in pendingObj.keys()) {
                val po = pendingObj.optJSONObject(epKey) ?: continue
                val snapArr = po.optJSONArray("snapshots")
                val snapMap = mutableMapOf<String, UberIntelligence.DecisionComparisonRecord>()
                if (snapArr != null) {
                    for (i in 0 until snapArr.length()) {
                        val s = snapArr.optJSONObject(i)?.let { UberIntelligence.comparisonFromJson(it) } ?: continue
                        snapMap[s.importId] = s
                    }
                }
                pendingMap[epKey] = PendingEpisodeInfo(
                    recommendationId = po.optString("recommendation_id", ""),
                    episodeId = po.optString("episode_id", epKey),
                    driverChoice = po.optString("driver_choice", "unknown"),
                    outcomeStatus = po.optString("outcome_status", "waiting"),
                    snapshots = snapMap,
                )
            }
        }
        return StoreEnvelope(imports, comparisons, pendingMap, currentComparisons, stagedTapComparisons)
    }

    @Synchronized
    fun listImports(): List<UberIntelligence.UberAssistantImport> {
        return runCatching { readEnvelopeStrict().imports }.getOrDefault(emptyList())
    }

    @Synchronized
    fun listComparisons(): List<UberIntelligence.DecisionComparisonRecord> {
        return runCatching { readEnvelopeStrict().comparisons }.getOrDefault(emptyList())
    }

    @Synchronized
    private fun writeEnvelope(envelope: StoreEnvelope) {
        storageFile.parentFile?.mkdirs()
        val arr = JSONArray()
        envelope.imports.forEach { arr.put(UberIntelligence.importToJson(it)) }
        val cmpArr = JSONArray()
        envelope.comparisons.forEach { cmpArr.put(UberIntelligence.comparisonToJson(it)) }
        val root = JSONObject()
            .put("schema_version", 2)
            .put("experimental", true)
            .put("scoring_integration_enabled", UberIntelligence.UBER_ASSISTANT_SCORING_INTEGRATION_ENABLED)
            .put("imports", arr)
            .put("comparisons", cmpArr)
        if (envelope.currentComparisons.isNotEmpty()) {
            val currArr = JSONArray()
            envelope.currentComparisons.values.forEach { currArr.put(UberIntelligence.comparisonToJson(it)) }
            root.put("current_comparisons", currArr)
        }
        if (envelope.stagedTapComparisons.isNotEmpty()) {
            val stagedArr = JSONArray()
            envelope.stagedTapComparisons.values.forEach { stagedArr.put(UberIntelligence.comparisonToJson(it)) }
            root.put("staged_tap_comparisons", stagedArr)
        }
        if (envelope.pendingEpisodes.isNotEmpty()) {
            val pendingObj = JSONObject()
            envelope.pendingEpisodes.forEach { (epKey, p) ->
                val pJson = JSONObject()
                    .put("recommendation_id", p.recommendationId)
                    .put("episode_id", p.episodeId)
                    .put("driver_choice", p.driverChoice)
                    .put("outcome_status", p.outcomeStatus)
                if (p.snapshots.isNotEmpty()) {
                    val snapArr = JSONArray()
                    p.snapshots.values.forEach { snapArr.put(UberIntelligence.comparisonToJson(it)) }
                    pJson.put("snapshots", snapArr)
                }
                pendingObj.put(epKey, pJson)
            }
            root.put("pending_episodes", pendingObj)
        }
        val tmp = File(storageFile.parentFile, "${storageFile.name}.tmp")
        tmp.writeText(root.toString(2), Charsets.UTF_8)
        if (!tmp.renameTo(storageFile)) {
            storageFile.writeText(root.toString(2), Charsets.UTF_8)
            tmp.delete()
        }
    }

    @Synchronized
    fun quarantineCorruptStore(): File? {
        if (!storageFile.exists()) return null
        val backup = File(
            storageFile.parentFile,
            "${storageFile.nameWithoutExtension}.corrupt-${System.currentTimeMillis()}.json"
        )
        storageFile.copyTo(backup, overwrite = true)
        writeEnvelope(StoreEnvelope(emptyList(), emptyList()))
        return backup
    }

    @Synchronized
    fun saveImport(
        importRecord: UberIntelligence.UberAssistantImport,
        allowDuplicate: Boolean = false,
    ): UberIntelligence.SaveImportResult {
        UberIntelligence.validateImportForSave(importRecord)
        val envelope = readEnvelopeStrict()
        val current = envelope.imports.toMutableList()
        val fp = importRecord.fingerprint.ifBlank { UberIntelligence.computeFingerprint(importRecord.rawResponse) }
        val existing = current.firstOrNull { it.fingerprint == fp }

        if (existing != null && !allowDuplicate) {
            val warns = (importRecord.warnings + UberIntelligence.FLAG_DUPLICATE_IMPORT).distinct()
            return UberIntelligence.SaveImportResult(
                saved = false,
                duplicate = true,
                existingImportId = existing.id,
                warnings = warns,
                importRecord = existing,
            )
        }

        val finalId = if (existing != null && allowDuplicate) {
            "imp-${UUID.randomUUID().toString().replace("-", "").take(12)}"
        } else {
            importRecord.id
        }
        val finalWarnings = if (existing != null) {
            (importRecord.warnings + UberIntelligence.FLAG_DUPLICATE_IMPORT).distinct()
        } else {
            importRecord.warnings
        }
        val toSave = importRecord.copy(
            id = finalId,
            fingerprint = fp,
            warnings = finalWarnings,
            observations = importRecord.observations.map { it.copy(importId = finalId) },
        )
        current.add(0, toSave)
        writeEnvelope(envelope.copy(imports = current))
        return UberIntelligence.SaveImportResult(
            saved = true,
            duplicate = existing != null,
            existingImportId = existing?.id,
            warnings = finalWarnings,
            importRecord = toSave,
        )
    }

    @Synchronized
    fun saveComparison(record: UberIntelligence.DecisionComparisonRecord): UberIntelligence.DecisionComparisonRecord {
        val envelope = readEnvelopeStrict()
        val cmps = envelope.comparisons.toMutableList()
        val currentCmps = envelope.currentComparisons.toMutableMap()
        val stagedTapCmps = envelope.stagedTapComparisons.toMutableMap()
        val slotKey = comparisonSlotKey(record.importId, record.recommendationId, record.targetType, record.stopId)

        val existingIdx = cmps.indexOfFirst {
            it.importId == record.importId &&
                it.recommendationId == record.recommendationId &&
                it.targetType == record.targetType &&
                it.stopId == record.stopId &&
                (it.linkedEpisodeId == null || record.linkedEpisodeId == null || it.linkedEpisodeId == record.linkedEpisodeId)
        }
        val priorSeenBefore = (currentCmps[slotKey]?.seenBeforeEpisodeStart == true) ||
            (existingIdx >= 0 && cmps[existingIdx].seenBeforeEpisodeStart)
        val effectiveRecord = record.copy(
            seenBeforeEpisodeStart = priorSeenBefore || record.seenBeforeEpisodeStart
        )
        currentCmps[slotKey] = effectiveRecord

        // R5-03: Preserve eligible pre-tap comparison snapshot across a delayed HTTP waiting acknowledgement
        // that crosses the 15-minute source expiry boundary.
        if (effectiveRecord.verdict != UberIntelligence.VERDICT_INSUFFICIENT && effectiveRecord.seenBeforeEpisodeStart) {
            stagedTapCmps[slotKey] = effectiveRecord
        }

        val savedRecord = if (existingIdx >= 0) {
            val prev = cmps[existingIdx]
            val merged = if (!prev.linkedEpisodeId.isNullOrBlank()) {
                prev.copy(
                    driverChoice = if (record.driverChoice != "unknown") record.driverChoice else prev.driverChoice,
                    outcomeStatus = if (record.outcomeStatus != "unknown") record.outcomeStatus else prev.outcomeStatus,
                    waitMinutesToRequest = record.waitMinutesToRequest ?: prev.waitMinutesToRequest,
                    acceptedRide = record.acceptedRide || prev.acceptedRide,
                    emptyDriveMinutes = record.emptyDriveMinutes ?: prev.emptyDriveMinutes,
                    emptyDriveMiles = record.emptyDriveMiles ?: prev.emptyDriveMiles,
                    userPerceivedUseful = record.userPerceivedUseful ?: prev.userPerceivedUseful,
                )
            } else {
                record.copy(
                    id = prev.id,
                    linkedEpisodeId = record.linkedEpisodeId ?: prev.linkedEpisodeId,
                    seenBeforeEpisodeStart = prev.seenBeforeEpisodeStart || record.seenBeforeEpisodeStart,
                    driverChoice = if (record.driverChoice != "unknown") record.driverChoice else prev.driverChoice,
                    outcomeStatus = if (record.outcomeStatus != "unknown") record.outcomeStatus else prev.outcomeStatus,
                    waitMinutesToRequest = record.waitMinutesToRequest ?: prev.waitMinutesToRequest,
                    acceptedRide = record.acceptedRide || prev.acceptedRide,
                    emptyDriveMinutes = record.emptyDriveMinutes ?: prev.emptyDriveMinutes,
                    emptyDriveMiles = record.emptyDriveMiles ?: prev.emptyDriveMiles,
                    userPerceivedUseful = record.userPerceivedUseful ?: prev.userPerceivedUseful,
                )
            }
            cmps[existingIdx] = merged
            if (prev.linkedEpisodeId.isNullOrBlank()) {
                currentCmps[slotKey] = merged
                merged
            } else {
                val currentIdSuffix = UberIntelligence.computeFingerprint(
                    "${effectiveRecord.evaluatedAt}|${effectiveRecord.verdict}|${effectiveRecord.reasonCode}"
                ).take(6)
                val baseId = effectiveRecord.id.substringBefore("-cur-")
                val distinctCurrent = effectiveRecord.copy(
                    id = "$baseId-cur-$currentIdSuffix",
                    linkedEpisodeId = null,
                    userPerceivedUseful = record.userPerceivedUseful,
                )
                currentCmps[slotKey] = distinctCurrent
                distinctCurrent
            }
        } else {
            val newRec = effectiveRecord
            currentCmps[slotKey] = newRec
            if (newRec.verdict != UberIntelligence.VERDICT_INSUFFICIENT && newRec.seenBeforeEpisodeStart) {
                stagedTapCmps[slotKey] = newRec
            }
            cmps.add(0, newRec)
            newRec
        }
        writeEnvelope(
            envelope.copy(
                comparisons = cmps,
                currentComparisons = currentCmps,
                stagedTapComparisons = stagedTapCmps,
            )
        )
        return savedRecord
    }

    @Synchronized
    fun stageEpisodeStart(
        recommendationId: String,
        episodeId: String,
        driverChoice: String = "unknown",
        tapComparison: UberIntelligence.DecisionComparisonRecord? = null,
    ) {
        val envelope = readEnvelopeStrict()
        val cmps = envelope.comparisons
        val pending = envelope.pendingEpisodes.toMutableMap()
        val currentCmps = envelope.currentComparisons.toMutableMap()
        val stagedTapCmps = envelope.stagedTapComparisons.toMutableMap()

        val existingPending = pending[episodeId]
        if (existingPending != null && existingPending.snapshots.isNotEmpty()) {
            return
        }

        if (tapComparison != null) {
            val slotKey = comparisonSlotKey(
                tapComparison.importId,
                tapComparison.recommendationId,
                tapComparison.targetType,
                tapComparison.stopId,
            )
            currentCmps[slotKey] = tapComparison.copy(userPerceivedUseful = null)
            if (tapComparison.verdict != UberIntelligence.VERDICT_INSUFFICIENT && tapComparison.seenBeforeEpisodeStart) {
                stagedTapCmps[slotKey] = tapComparison.copy(userPerceivedUseful = null)
            } else {
                stagedTapCmps.remove(slotKey)
            }
        }

        val templateRowsByImport = cmps
            .filter { it.recommendationId == recommendationId && it.targetType == "now" }
            .distinctBy { it.importId }
        val snapshots = mutableMapOf<String, UberIntelligence.DecisionComparisonRecord>()
        for (template in templateRowsByImport) {
            val slotKey = comparisonSlotKey(template.importId, template.recommendationId, template.targetType, template.stopId)
            val snap = if (tapComparison != null && tapComparison.importId == template.importId) {
                tapComparison
            } else {
                val cur = currentCmps[slotKey] ?: template
                if (cur.verdict == UberIntelligence.VERDICT_INSUFFICIENT) {
                    stagedTapCmps.remove(slotKey)
                }
                cur
            }
            snapshots[template.importId] = snap.copy(userPerceivedUseful = null)
        }
        if (tapComparison != null && snapshots.isEmpty()) {
            snapshots[tapComparison.importId] = tapComparison.copy(userPerceivedUseful = null)
        }
        pending[episodeId] = PendingEpisodeInfo(
            recommendationId = recommendationId,
            episodeId = episodeId,
            driverChoice = driverChoice,
            outcomeStatus = "waiting",
            snapshots = snapshots,
        )
        writeEnvelope(
            envelope.copy(
                pendingEpisodes = pending,
                currentComparisons = currentCmps,
                stagedTapComparisons = stagedTapCmps,
            )
        )
    }

    @Synchronized
    fun linkEpisodeOutcome(
        recommendationId: String,
        episodeId: String,
        driverChoice: String,
        outcomeStatus: String,
        waitMinutesToRequest: Double? = null,
        acceptedRide: Boolean = false,
        emptyDriveMinutes: Double? = null,
        emptyDriveMiles: Double? = null,
    ) {
        val envelope = readEnvelopeStrict()
        val cmps = envelope.comparisons.toMutableList()
        val pending = envelope.pendingEpisodes.toMutableMap()
        val currentCmps = envelope.currentComparisons
        val stagedTapCmps = envelope.stagedTapComparisons.toMutableMap()
        val terminalStatuses = setOf(
            "accepted_ride",
            "request_within_15m",
            "request_after_15m",
            "no_request_after_15m",
            "observed_15m_no_request",
            "dry_wait_15m",
            "left_area",
        )
        if (outcomeStatus in terminalStatuses) {
            val keysToRemove = stagedTapCmps.filterValues { it.recommendationId == recommendationId }.keys.toList()
            keysToRemove.forEach { stagedTapCmps.remove(it) }
        }

        val matchingRecIndices = cmps.indices.filter { idx ->
            cmps[idx].recommendationId == recommendationId && cmps[idx].targetType == "now"
        }
        if (matchingRecIndices.isEmpty()) return

        val exactEpisodeIndices = matchingRecIndices.filter { idx ->
            cmps[idx].linkedEpisodeId == episodeId
        }
        val unboundIndices = matchingRecIndices.filter { idx ->
            cmps[idx].linkedEpisodeId.isNullOrBlank()
        }

        fun updateRow(
            cmp: UberIntelligence.DecisionComparisonRecord,
            fallbackChoice: String? = null,
        ): UberIntelligence.DecisionComparisonRecord {
            val nextStatus = if (cmp.outcomeStatus in terminalStatuses && outcomeStatus == "waiting") {
                cmp.outcomeStatus
            } else {
                outcomeStatus
            }
            // Preserve time-to-first-request if already recorded; ride acceptance must not overwrite it
            val preservedWaitToFirstRequest = if (outcomeStatus == "accepted_ride" && cmp.waitMinutesToRequest != null) {
                cmp.waitMinutesToRequest
            } else {
                cmp.waitMinutesToRequest ?: waitMinutesToRequest
            }
            val resolvedChoice = when {
                driverChoice != "unknown" -> driverChoice
                !fallbackChoice.isNullOrBlank() && fallbackChoice != "unknown" -> fallbackChoice
                else -> cmp.driverChoice
            }
            return cmp.copy(
                linkedEpisodeId = episodeId,
                driverChoice = resolvedChoice,
                outcomeStatus = nextStatus,
                waitMinutesToRequest = preservedWaitToFirstRequest,
                acceptedRide = acceptedRide || cmp.acceptedRide,
                emptyDriveMinutes = emptyDriveMinutes ?: cmp.emptyDriveMinutes,
                emptyDriveMiles = emptyDriveMiles ?: cmp.emptyDriveMiles,
            )
        }

        if (exactEpisodeIndices.isNotEmpty()) {
            val priorPending = pending.remove(episodeId)
            for (idx in exactEpisodeIndices) {
                cmps[idx] = updateRow(cmps[idx], priorPending?.driverChoice)
            }
            writeEnvelope(
                envelope.copy(
                    comparisons = cmps,
                    pendingEpisodes = pending,
                    stagedTapComparisons = stagedTapCmps,
                )
            )
            return
        }

        if (unboundIndices.isNotEmpty()) {
            val priorPending = pending.remove(episodeId)
            for (idx in unboundIndices) {
                val baseRow = cmps[idx]
                val slotKey = comparisonSlotKey(baseRow.importId, baseRow.recommendationId, baseRow.targetType, baseRow.stopId)
                val tapSnap = priorPending?.snapshots?.get(baseRow.importId)
                    ?: if (outcomeStatus == "waiting") stagedTapCmps.remove(slotKey) else null
                val restoredBase = if (tapSnap != null) {
                    tapSnap.copy(
                        id = baseRow.id.substringBefore("-cur-"),
                        seenBeforeEpisodeStart = tapSnap.seenBeforeEpisodeStart || baseRow.seenBeforeEpisodeStart,
                        userPerceivedUseful = baseRow.userPerceivedUseful,
                    )
                } else {
                    baseRow
                }
                cmps[idx] = updateRow(restoredBase, priorPending?.driverChoice)
            }
            writeEnvelope(
                envelope.copy(
                    comparisons = cmps,
                    pendingEpisodes = pending,
                    stagedTapComparisons = stagedTapCmps,
                )
            )
            return
        }

        val templateRowsByImport = matchingRecIndices
            .map { cmps[it] }
            .distinctBy { it.importId }

        // All comparison rows for this recommendationId are already bound to earlier episode(s) != episodeId.
        // Stage a newly started wait episode with the tap-time or current evaluation snapshot without mutating or duplicating completed episode rows yet.
        if (outcomeStatus == "waiting") {
            val existingPending = pending[episodeId]
            val snapshots = mutableMapOf<String, UberIntelligence.DecisionComparisonRecord>()
            for (template in templateRowsByImport) {
                val slotKey = comparisonSlotKey(template.importId, template.recommendationId, template.targetType, template.stopId)
                val latestEval = existingPending?.snapshots?.get(template.importId)
                    ?: stagedTapCmps.remove(slotKey)
                    ?: currentCmps[slotKey]
                    ?: template
                snapshots[template.importId] = latestEval.copy(userPerceivedUseful = null)
            }
            pending[episodeId] = PendingEpisodeInfo(
                recommendationId = recommendationId,
                episodeId = episodeId,
                driverChoice = if (driverChoice != "unknown") driverChoice else existingPending?.driverChoice ?: "unknown",
                outcomeStatus = outcomeStatus,
                snapshots = snapshots,
            )
            writeEnvelope(
                envelope.copy(
                    pendingEpisodes = pending,
                    stagedTapComparisons = stagedTapCmps,
                )
            )
            return
        }

        val priorPending = pending.remove(episodeId)
        for (template in templateRowsByImport) {
            val slotKey = comparisonSlotKey(template.importId, template.recommendationId, template.targetType, template.stopId)
            val baseEval = priorPending?.snapshots?.get(template.importId)
                ?: stagedTapCmps.remove(slotKey)
                ?: currentCmps[slotKey]
                ?: template
            val resolvedChoice = when {
                driverChoice != "unknown" -> driverChoice
                priorPending != null && priorPending.driverChoice != "unknown" -> priorPending.driverChoice
                baseEval.driverChoice != "unknown" -> baseEval.driverChoice
                template.driverChoice != "unknown" -> template.driverChoice
                else -> "unknown"
            }
            val episodeHash = UberIntelligence.computeFingerprint(episodeId).take(6)
            val baseId = baseEval.id.substringBefore("-cur-")
            val cloned = baseEval.copy(
                id = "$baseId-$episodeHash",
                linkedEpisodeId = episodeId,
                driverChoice = resolvedChoice,
                outcomeStatus = outcomeStatus,
                waitMinutesToRequest = waitMinutesToRequest,
                acceptedRide = acceptedRide,
                emptyDriveMinutes = emptyDriveMinutes,
                emptyDriveMiles = emptyDriveMiles,
                userPerceivedUseful = null,
            )
            cmps.add(cloned)
        }
        writeEnvelope(
            envelope.copy(
                comparisons = cmps,
                pendingEpisodes = pending,
                stagedTapComparisons = stagedTapCmps,
            )
        )
    }

    @Synchronized
    fun recordPerceivedUsefulness(comparisonId: String, useful: Boolean) {
        val envelope = readEnvelopeStrict()
        val nextCmps = envelope.comparisons.map { cmp ->
            if (cmp.id == comparisonId) cmp.copy(userPerceivedUseful = useful) else cmp
        }
        val nextCurrentCmps = envelope.currentComparisons.mapValues { (_, cmp) ->
            if (cmp.id == comparisonId) cmp.copy(userPerceivedUseful = useful) else cmp
        }
        writeEnvelope(
            envelope.copy(
                comparisons = nextCmps,
                currentComparisons = nextCurrentCmps,
            )
        )
    }

    @Synchronized
    fun deleteImport(importId: String): Boolean {
        val envelope = readEnvelopeStrict()
        val filtered = envelope.imports.filterNot { it.id == importId }
        if (filtered.size == envelope.imports.size) return false
        val filteredCmps = envelope.comparisons.filterNot { it.importId == importId }
        val filteredCurrent = envelope.currentComparisons.filterValues { it.importId != importId }
        writeEnvelope(StoreEnvelope(imports = filtered, comparisons = filteredCmps, currentComparisons = filteredCurrent))
        return true
    }

    @Synchronized
    fun deleteSuspectedSamples(): Int {
        val envelope = readEnvelopeStrict()
        val remaining = envelope.imports.filterNot { it.isDemoSample || it.suspectedLegacySample }
        val removedIds = envelope.imports.filter { it.isDemoSample || it.suspectedLegacySample }.map { it.id }.toSet()
        val remainingCmps = envelope.comparisons.filterNot { it.importId in removedIds }
        val remainingCurrent = envelope.currentComparisons.filterValues { it.importId !in removedIds }
        val removedCount = envelope.imports.size - remaining.size
        if (removedCount > 0) {
            writeEnvelope(StoreEnvelope(imports = remaining, comparisons = remainingCmps, currentComparisons = remainingCurrent))
        }
        return removedCount
    }

    @Synchronized
    fun deleteAllImports(): Int {
        val envelope = readEnvelopeStrict()
        writeEnvelope(StoreEnvelope(emptyList(), emptyList()))
        return envelope.imports.size
    }

    @Synchronized
    fun exportJson(): String {
        val envelope = readEnvelopeStrict()
        val arr = JSONArray()
        envelope.imports.forEach { arr.put(UberIntelligence.importToJson(it)) }
        val cmpArr = JSONArray()
        envelope.comparisons.forEach { cmpArr.put(UberIntelligence.comparisonToJson(it)) }
        return JSONObject()
            .put("schema_version", 2)
            .put("experimental", true)
            .put("scoring_integration_enabled", UberIntelligence.UBER_ASSISTANT_SCORING_INTEGRATION_ENABLED)
            .put("imports", arr)
            .put("comparisons", cmpArr)
            .toString(2)
    }
}
