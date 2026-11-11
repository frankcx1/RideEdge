package com.rideedge.app

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.time.Instant

class ArgonRemediationRound2Test {

    @Test
    fun `NOW01 and NOW02 - parseHere maps STAY to WAIT and preserves positioning heuristic metadata`() {
        val stayJson = JSONObject()
            .put("place", JSONObject().put("zone", "bellevue_core").put("label", "Bellevue Core").put("matched", "Bellevue Core"))
            .put(
                "stay_or_move",
                JSONObject()
                    .put("action", "STAY")
                    .put("decision_state", "STAY")
                    .put("action_plain", "Stay in Bellevue Core")
                    .put("spoken", "Stay in Bellevue Core.")
                    .put("recommendation_basis", "local_live_evidence")
            )
            .put("sit_here", JSONObject().put("ranked", JSONArray()))
            .put("nearby", JSONArray())

        val parsedStay = RideEdgeClient.parseHere(stayJson)
        assertEquals("WAIT", parsedStay.action)
        assertEquals("STAY", parsedStay.decisionState)

        val posJson = JSONObject()
            .put(
                "place",
                JSONObject()
                    .put("zone", "totem_lake")
                    .put("label", "Public Totem Lake reference")
                    .put("matched", "13646 125th Ave NE, Kirkland, WA 98034")
                    .put("origin_kind", "residential_place")
                    .put("origin_place_id", "home")
            )
            .put(
                "stay_or_move",
                JSONObject()
                    .put("action", "MOVE")
                    .put("decision_state", "MOVE")
                    .put("recommendation_basis", "positioning_heuristic")
                    .put("destination_id", "village_at_totem_lake")
                    .put("destination_label", "Village at Totem Lake")
                    .put("suitability_reason", "Closest active commercial pickup hub from residential start")
                    .put("action_plain", "Position at Village at Totem Lake (~4 min) — current demand unverified")
                    .put("spoken", "Position at Village at Totem Lake, about 4 minutes away. Current demand is unverified.")
            )
            .put(
                "sit_here",
                JSONObject()
                    .put(
                        "best",
                        JSONObject()
                            .put("zone", "totem_lake")
                            .put("reposition_minutes", 4.0)
                            .put("reposition_miles", 1.1)
                            .put("route_basis", "google_live")
                            .put("maps_url", "https://www.google.com/maps/dir/?api=1&destination=47.7145,-122.1818")
                    )
                    .put("ranked", JSONArray())
            )
            .put("nearby", JSONArray())

        val parsedPos = RideEdgeClient.parseHere(posJson)
        assertEquals("MOVE", parsedPos.action)
        assertEquals("MOVE", parsedPos.decisionState)
        assertEquals("positioning_heuristic", parsedPos.recommendationBasis)
        assertEquals("Village at Totem Lake", parsedPos.destinationLabel)

        val card = WorkingLocationController.resolveHereDecision(
            here = parsedPos,
            repositionLimitMinutes = 20,
        )
        assertTrue(card.headline.contains("Village at Totem Lake"))
        assertTrue(card.badgeLabel.contains("POSITIONING SUGGESTION"))
        assertTrue(card.whyText.contains("unverified", ignoreCase = true))
    }

    @Test
    fun `UX03 - routine transit arrivals do not leak into Now nearby list or spoken summary`() {
        val json = JSONObject()
            .put("place", JSONObject().put("zone", "bellevue_core").put("label", "Bellevue Core"))
            .put(
                "stay_or_move",
                JSONObject()
                    .put("action", "WATCH")
                    .put("decision_state", "NO_CLEAR_MOVE")
                    .put("action_plain", "No clear move yet")
                    .put("spoken", "No clear move yet.")
            )
            .put("sit_here", JSONObject().put("ranked", JSONArray()))
            .put(
                "nearby",
                JSONArray()
                    .put(
                        JSONObject()
                            .put("id", "train-1")
                            .put("zone", "bellevue_core")
                            .put("action", "WATCH")
                            .put("score", 14.0)
                            .put("headline", "Link Light Rail arriving: Bellevue Downtown")
                            .put("detail", "2 Line train in 3m")
                            .put("minutes_away", 2.0)
                    )
                    .put(
                        JSONObject()
                            .put("id", "ferry-1")
                            .put("zone", "seattle_core")
                            .put("action", "WATCH")
                            .put("score", 14.0)
                            .put("headline", "WSF Bainbridge ferry arrival at Colman Dock")
                            .put("detail", "Scheduled arrival")
                            .put("minutes_away", 14.0)
                    )
            )
        val here = RideEdgeClient.parseHere(json)
        val card = WorkingLocationController.resolveHereDecision(
            here = here,
            repositionLimitMinutes = 20,
        )
        assertFalse(card.whyText.contains("Link Light Rail", ignoreCase = true))
        assertFalse(card.whyText.contains("ferry", ignoreCase = true))
    }

    @Test
    fun `Priority 3 - evaluateDecisionComparison covers Supports Challenges and NotEnoughInformation rules`() {
        val evalNow = Instant.parse("2026-10-21T18:50:00Z")
        val freshRaw = """
            Summary:
            - Bellevue: 65 requests in the last 30 mins, median wait 4 min, 5 mins away
            - Totem Lake: 8 requests in the last 30 mins, median wait 30+ min, 2 mins away
            As of 2026-10-21T18:45:00Z.
        """.trimIndent()
        val parsed = UberIntelligence.parseAssistantResponse(
            rawResponse = freshRaw,
            createdAt = "2026-10-21T18:48:00Z",
        )

        // 1. Supports MOVE to Bellevue Core when destination has short wait (<=8m) and >=30 requests
        val moveTarget = UberIntelligence.DecisionTargetContext(
            targetType = "now",
            recommendationId = "rec-move-bellevue",
            evidenceVersion = "v2",
            issuedAt = "2026-10-21T18:49:00Z",
            action = "MOVE",
            decisionState = "MOVE",
            originZone = "totem_lake",
            targetZone = "bellevue_core",
            targetLabel = "Bellevue Core",
            structuredPremise = "reposition_advantage",
            repositionMinutes = 10.0,
        )
        val cmpSupports = UberIntelligence.evaluateDecisionComparison(
            importRecord = parsed,
            target = moveTarget,
            evalTime = evalNow,
        )
        assertEquals(UberIntelligence.VERDICT_SUPPORTS, cmpSupports.verdict)

        // 2. Challenges STAY in Totem Lake when Totem Lake has 30+ min wait
        val stayTotemTarget = UberIntelligence.DecisionTargetContext(
            targetType = "now",
            recommendationId = "rec-stay-totem",
            evidenceVersion = "v2",
            issuedAt = "2026-10-21T18:49:00Z",
            action = "WAIT",
            decisionState = "STAY",
            originZone = "totem_lake",
            targetZone = "totem_lake",
            targetLabel = "Totem Lake",
            structuredPremise = "short_wait_expected",
        )
        val cmpChallenges = UberIntelligence.evaluateDecisionComparison(
            importRecord = parsed,
            target = stayTotemTarget,
            evalTime = evalNow,
        )
        assertEquals(UberIntelligence.VERDICT_CHALLENGES, cmpChallenges.verdict)

        // 3. Unknown source timestamp -> Not enough information (never treated as fresh just because pasted recently)
        val noTimestampParsed = UberIntelligence.parseAssistantResponse(
            rawResponse = "Bellevue: 80 requests in the last 30 mins, 3 min wait, 5 mins away",
            createdAt = "2026-10-21T18:49:30Z",
        )
        val cmpUnknownTime = UberIntelligence.evaluateDecisionComparison(
            importRecord = noTimestampParsed,
            target = moveTarget,
            evalTime = evalNow,
        )
        assertEquals(UberIntelligence.VERDICT_INSUFFICIENT, cmpUnknownTime.verdict)
        assertEquals("SOURCE_TIME_UNKNOWN", cmpUnknownTime.reasonCode)

        // 4. Stale source timestamp (>15m old) -> Not enough information
        val cmpStale = UberIntelligence.evaluateDecisionComparison(
            importRecord = parsed,
            target = moveTarget,
            evalTime = Instant.parse("2026-10-21T19:15:00Z"),
        )
        assertEquals(UberIntelligence.VERDICT_INSUFFICIENT, cmpStale.verdict)
        assertEquals("SOURCE_STALE", cmpStale.reasonCode)

        // 5. Future Plan stop (+2h or later) -> Not enough information
        val futureStopTarget = moveTarget.copy(
            targetType = "plan_stop",
            stopId = "stop_3",
            stopHourOffset = 2,
        )
        val cmpFutureStop = UberIntelligence.evaluateDecisionComparison(
            importRecord = parsed,
            target = futureStopTarget,
            evalTime = evalNow,
        )
        assertEquals(UberIntelligence.VERDICT_INSUFFICIENT, cmpFutureStop.verdict)
        assertEquals("FUTURE_STOP_OUT_OF_HORIZON", cmpFutureStop.reasonCode)
    }

    @Test
    fun `Priority 3 - summarizeHistoryUsefulness separates usability agreement and observed outcomes`() {
        val tmpDir = Files.createTempDirectory("uber_intel_round2_test").toFile()
        val storeFile = java.io.File(tmpDir, "imports.json")
        val repo = UberIntelligenceRepository(storeFile)

        val imp = UberIntelligence.parseAssistantResponse(
            rawResponse = "Bellevue: 60 requests in the last 30 mins, median wait 4 min, 5 mins away. As of 2026-10-21T18:45:00Z.",
            createdAt = "2026-10-21T18:46:00Z",
        )
        val saved = repo.saveImport(imp).importRecord
        val target = UberIntelligence.DecisionTargetContext(
            targetType = "now",
            recommendationId = "rec-100",
            evidenceVersion = "v2",
            issuedAt = "2026-10-21T18:46:00Z",
            action = "WAIT",
            decisionState = "STAY",
            originZone = "bellevue_core",
            targetZone = "bellevue_core",
            targetLabel = "Bellevue Core",
            structuredPremise = "short_wait_expected",
        )
        val cmp = UberIntelligence.evaluateDecisionComparison(
            importRecord = saved,
            target = target,
            evalTime = Instant.parse("2026-10-21T18:47:00Z"),
            seenBeforeEpisodeStart = true,
        )
        repo.saveComparison(cmp)
        repo.linkEpisodeOutcome(
            recommendationId = "rec-100",
            episodeId = "ep-100",
            driverChoice = "stayed",
            outcomeStatus = "request_within_15m",
            waitMinutesToRequest = 6.0,
            acceptedRide = true,
        )

        val summary = UberIntelligence.summarizeHistoryUsefulness(
            imports = repo.listImports(),
            comparisons = repo.listComparisons(),
        )
        assertEquals(1, summary.totalUniqueImports)
        assertEquals(1, summary.usableForComparisonCount)
        assertEquals(1, summary.supportsCount)
        assertEquals(1, summary.adequatelyLoggedCount)
        assertEquals(1, summary.requestWithin15mCount)
        assertEquals(6.0, summary.medianMinutesToRequestCompletedOnly ?: 0.0, 0.01)
    }

    @Test
    fun `UX01 and UX02 - parseHealth and parseFeedDetail expose reconciled counts and Ticketmaster records`() {
        val detailJson = JSONObject()
            .put("adapter", "ticketmaster_events")
            .put("label", "Ticketmaster Events")
            .put("category", "Events & Venues")
            .put("kind", "ticketmaster")
            .put("snapshot_id", "snap-123")
            .put("mode", "cache")
            .put("stoplight", "green")
            .put("detail_state", "ready")
            .put("summary", "7 mapped exits from 10 unique Ticketmaster events")
            .put("plain_summary", "7 mapped exits from 10 unique Ticketmaster events")
            .put("unique_events_count", 10)
            .put("mapped_signals_count", 7)
            .put("excluded_events_count", 3)
            .put("multi_query_duplicates", 5)
            .put(
                "events",
                JSONArray().put(
                    JSONObject()
                        .put("event_id", "tm-1")
                        .put("title", "Samia")
                        .put("venue", "Showbox SoDo")
                        .put("city", "Seattle")
                        .put("segment", "Music")
                        .put("status", "onsale")
                        .put("local_date", "2026-10-21")
                        .put("local_time", "20:00:00")
                        .put("source_start_time", "2026-10-21T20:00:00-07:00")
                        .put("source_end_basis", "not_reported_by_provider")
                        .put("estimated_departure_start", "2026-10-21T22:15:00-07:00")
                        .put("estimated_departure_end", "2026-10-21T23:00:00-07:00")
                        .put("exit_timing_basis", "estimated_from_start_plus_duration_135m_window_45m")
                        .put("zone", "sodo_stadiums")
                        .put("zone_label", "SoDo Stadiums")
                        .put("mapping_status", "mapped_signal")
                )
            )
        val parsed = RideEdgeClient.parseFeedDetail(detailJson)
        assertEquals("ready", parsed.detailState)
        assertEquals(10, parsed.uniqueEventsCount)
        assertEquals(7, parsed.mappedSignalsCount)
        assertEquals(3, parsed.excludedEventsCount)
        assertEquals(1, parsed.ticketmasterEvents.size)
        assertEquals("not_reported_by_provider", parsed.ticketmasterEvents[0].sourceEndBasis)
    }

    @Test
    fun `R2-03 - WorkingLocationController tracks driverMode repositionLimit and destination arrival persistence`() {
        val controller = WorkingLocationController(initialArea = "Home")
        controller.setDriverPosture("active_working")
        controller.setRepositionLimit(15)
        assertEquals("active_working", controller.driverMode)
        assertEquals(15, controller.repositionLimitMinutes)

        val homePos = HereState(
            zone = "totem_lake",
            label = "Public Totem Lake reference",
            matched = "Home",
            note = "",
            action = "MOVE",
            actionPlain = "Position near Village at Totem Lake (~4 min)",
            spoken = "",
            stayRow = null,
            bestRow = SitHereRow(
                zone = "totem_lake",
                hour = 19,
                weekday = "Wednesday",
                score = 0.0,
                meanEarnings = 0.0,
                netPerHour = 0.0,
                sampleTrips = 0,
                grain = "none",
                repositionMinutes = 4.0,
                repositionMiles = 1.1,
                routeBasis = "google_live",
                thin = true,
                mapsUrl = "https://www.google.com/maps/dir/?api=1&destination=47.7145,-122.1818",
            ),
            rankedHours = emptyList(),
            nearby = emptyList(),
            warnings = emptyList(),
            decisionState = "MOVE",
            originKind = "residential",
            originPlaceId = "home",
            recommendationBasis = "positioning_heuristic",
            destinationId = "village_at_totem_lake",
            destinationLabel = "Village at Totem Lake",
        )
        val req1 = controller.beginManualAreaLoad("Home")
        assertTrue(controller.completeManualAreaLoad(req1, homePos, "Home", 1_000L))
        assertEquals("suggested", controller.positioningState)
        assertEquals("village_at_totem_lake", controller.positioningTargetId)

        // Opening Maps alone must set en_route, never arrived
        controller.markPositioningNavigationOpened()
        assertEquals("en_route", controller.positioningState)

        // Confirming arrival marks arrived and returns destination label
        val confirmedDest = controller.confirmArrivalAtDestination(2_000L)
        assertEquals("Village at Totem Lake", confirmedDest)
        assertEquals("arrived", controller.positioningState)

        // Persistence round-trip
        val restored = WorkingLocationController(initialArea = "Bellevue")
        restored.restoreFromJson(controller.toJson())
        assertEquals("active_working", restored.driverMode)
        assertEquals(15, restored.repositionLimitMinutes)
        assertEquals("arrived", restored.positioningState)
        assertEquals("village_at_totem_lake", restored.positioningTargetId)

        // Positioned pickup center decision card
        val positionedHere = homePos.copy(
            label = "Village at Totem Lake",
            action = "WAIT",
            decisionState = "STAY",
            originKind = "pickup_center",
            originPlaceId = "village_at_totem_lake",
            recommendationBasis = "positioned_pickup_center",
            stayOrMoveReason = "Positioned at Village at Totem Lake. Hold for 15 minutes; current demand is unverified.",
        )
        val positionedCard = WorkingLocationController.resolveHereDecision(positionedHere, 15)
        assertEquals("WAIT", positionedCard.stateCode)
        assertTrue(positionedCard.badgeLabel.contains("POSITIONED AT PICKUP CENTER"))
        assertTrue(positionedCard.whyText.contains("unverified", ignoreCase = true))
    }

    @Test
    fun `R2-04 to R2-07 and R2-10 - premise honesty central wait stats and episode outcome isolation`() {
        val hereLive = HereState(
            zone = "bellevue_core",
            label = "Bellevue Core",
            matched = "Bellevue Core",
            note = "",
            action = "WAIT",
            actionPlain = "Stay in Bellevue Core",
            spoken = "",
            stayRow = null,
            bestRow = null,
            rankedHours = emptyList(),
            nearby = emptyList(),
            warnings = emptyList(),
            recommendationId = "rec-live-1",
            evidenceVersion = "v2",
            decisionState = "STAY",
            localLiveEvidence = true,
            recommendationBasis = "local_live_evidence",
        )
        val ctx = UberIntelligence.buildTargetContextFromHere(hereLive)
        assertEquals("local_live_activity", ctx.structuredPremise)

        // P90 wait must not trigger short_wait_expected challenge
        val p90Imp = UberIntelligence.parseAssistantResponse(
            rawResponse = "Bellevue: 40 requests in the last 30 mins, P90 wait 22 min, 4 mins away. As of 2026-10-21T18:45:00Z.",
            createdAt = "2026-10-21T18:46:00Z",
        )
        val shortWaitTarget = ctx.copy(structuredPremise = "short_wait_expected", issuedAt = "2026-10-21T18:46:00Z")
        val p90Cmp = UberIntelligence.evaluateDecisionComparison(
            importRecord = p90Imp,
            target = shortWaitTarget,
            evalTime = Instant.parse("2026-10-21T18:47:00Z"),
        )
        assertEquals(UberIntelligence.VERDICT_INSUFFICIENT, p90Cmp.verdict)
        assertEquals("INSUFFICIENT_WAIT_EVIDENCE", p90Cmp.reasonCode)

        // Editing driveMinutes must not clear unresolved wait conflicts
        val conflictImp = UberIntelligence.parseAssistantResponse(
            rawResponse = "Bellevue: 40 requests in the last 30 mins, 5 min wait, 22 min wait, 6 mins away. As of 2026-10-21T18:45:00Z.",
            createdAt = "2026-10-21T18:46:00Z",
        )
        val editedDriveOnly = UberIntelligence.applyUserReviewEdits(
            importRecord = conflictImp,
            edits = mapOf(
                conflictImp.observations.first().id to UberIntelligence.ObservationEdit(driveMinutes = 7.0, userConfirmed = true)
            ),
        )
        assertTrue(UberIntelligence.FLAG_CARD_NARRATIVE_CONFLICT in editedDriveOnly.observations.first().warnings)
        assertEquals("contradictory", editedDriveOnly.observations.first().verificationLevel)
    }

    @Test
    fun `R3-01 to R3-09 - refresh preserves wait and Home query multi-episode storage arrival isolation dry wait recreation and retry`() {
        val controller = WorkingLocationController(initialArea = "home")
        val homeState = HereState(
            zone = "totem_lake",
            label = "Totem Lake / Kingsgate",
            matched = "Home",
            note = "",
            action = "MOVE",
            actionPlain = "Position near Village at Totem Lake (~4 min)",
            spoken = "",
            stayRow = null,
            bestRow = null,
            rankedHours = emptyList(),
            nearby = emptyList(),
            warnings = emptyList(),
            recommendationId = "rec-r3-home",
            evidenceVersion = "v2",
            decisionState = "MOVE",
            originKind = "residential",
            originPlaceId = "home",
            recommendationBasis = "positioning_heuristic",
            destinationId = "village_at_totem_lake",
            destinationLabel = "Village at Totem Lake",
        )

        // R3-01 & R3-02: Home load + open wait survives manual refresh and retains "home" query
        val r1 = controller.beginManualAreaLoad("home")
        assertTrue(controller.completeManualAreaLoad(r1, homeState, "home", 1_000L))
        assertEquals("home", controller.areaQuery)
        controller.beginOutcomeSubmission("waiting", currentHere = homeState, nowMs = 2_000L)
        controller.completeOutcomeSubmission("waiting")
        assertEquals("waiting", controller.activeEpisodeState)

        val r2 = controller.beginManualAreaLoad(controller.areaQuery)
        assertTrue(controller.completeManualAreaLoad(r2, homeState, controller.areaQuery, 3_000L))
        assertEquals("home", controller.areaQuery)
        assertEquals("waiting", controller.activeEpisodeState)
        assertEquals(2_000L, controller.activeEpisodeStartedAtMs)

        // R3-06: Process recreation preserves open wait
        val recreated = WorkingLocationController(initialArea = "Bellevue")
        recreated.restoreFromJson(controller.toJson())
        assertEquals("home", recreated.areaQuery)
        assertEquals("waiting", recreated.activeEpisodeState)
        assertEquals(2_000L, recreated.activeEpisodeStartedAtMs)

        // R3-09: Failed request_received and accepted_ride preserve exact retry status and idempotency key
        val (_, _, reqIdem1) = recreated.beginOutcomeSubmission("request_received", currentHere = homeState, nowMs = 62_000L)
        recreated.failOutcomeSubmission("HTTP 503")
        assertEquals("request_received", recreated.pendingOutcomeStatus)
        assertEquals("request_received", recreated.failedOutcomeStatus)
        val (_, _, reqIdem2) = recreated.beginOutcomeSubmission(recreated.pendingOutcomeStatus ?: "waiting", currentHere = homeState, nowMs = 63_000L)
        assertEquals(reqIdem1, reqIdem2)
        recreated.completeOutcomeSubmission("request_received")
        assertEquals("pinged", recreated.activeEpisodeState)

        // R3-05: Explicit 15-minute dry wait terminates active episode
        val dryController = WorkingLocationController(initialArea = "Bellevue")
        val belState = homeState.copy(
            zone = "bellevue_core",
            label = "Bellevue Core",
            action = "WAIT",
            decisionState = "STAY",
            originKind = "commercial",
            originPlaceId = "bellevue_core",
            recommendationBasis = "local_live_evidence",
            destinationId = "bellevue_core",
            destinationLabel = "Bellevue Core",
        )
        val rb1 = dryController.beginManualAreaLoad("Bellevue")
        dryController.completeManualAreaLoad(rb1, belState, "Bellevue", 1_000L)
        dryController.beginOutcomeSubmission("waiting", currentHere = belState, nowMs = 2_000L)
        dryController.completeOutcomeSubmission("waiting")
        dryController.beginOutcomeSubmission("no_request_after_15m", currentHere = belState, nowMs = 2_000L + 16 * 60_000L)
        dryController.completeOutcomeSubmission("no_request")
        assertEquals("none", dryController.activeEpisodeState)
        assertNull(dryController.activeEpisodeStartedAtMs)

        // R3-03 & R3-08: Three consecutive episodes on the same recommendation + seenBeforeEpisodeStart freeze
        val tmpDir = Files.createTempDirectory("uber_intel_r3_test").toFile()
        val repo = UberIntelligenceRepository(java.io.File(tmpDir, "imports.json"))
        val imp = UberIntelligence.parseAssistantResponse(
            "Totem Lake: 38 requests in the last 30 minutes. Median wait 4 minutes. Source updated at 2026-10-21T20:10:00Z.",
            createdAt = "2026-10-21T20:12:00Z",
        )
        // R3-07 check on single-area separate-sentence wait
        val totemObs = imp.observations.single { it.areaKey == "totem_lake" }
        assertEquals(38, totemObs.requests30m)
        assertEquals(4.0, totemObs.waitMinutesExact ?: 0.0, 0.01)
        assertEquals("p50", totemObs.waitStatistic)

        val savedImp = repo.saveImport(imp).importRecord
        val target = UberIntelligence.DecisionTargetContext(
            recommendationId = "rec-multi-3",
            evidenceVersion = "v2",
            issuedAt = "2026-10-21T20:11:00Z",
            action = "MOVE",
            decisionState = "MOVE",
            originZone = "totem_lake",
            targetZone = "totem_lake",
            targetLabel = "Village at Totem Lake",
            destinationId = "village_at_totem_lake",
            structuredPremise = "positioning_from_residential",
        )
        repo.saveComparison(
            UberIntelligence.evaluateDecisionComparison(
                importRecord = savedImp,
                target = target,
                evalTime = Instant.parse("2026-10-21T20:12:00Z"),
                seenBeforeEpisodeStart = true,
            )
        )
        for ((epId, waitMin) in listOf("ep-1" to 4.0, "ep-2" to 7.0, "ep-3" to 11.0)) {
            repo.linkEpisodeOutcome("rec-multi-3", epId, "stayed", "waiting")
            // Re-evaluating during active wait (seenBeforeEpisodeStart=false) must not overwrite true
            repo.saveComparison(
                UberIntelligence.evaluateDecisionComparison(
                    importRecord = savedImp,
                    target = target,
                    evalTime = Instant.parse("2026-10-21T20:13:00Z"),
                    seenBeforeEpisodeStart = false,
                )
            )
            repo.linkEpisodeOutcome("rec-multi-3", epId, "stayed", "request_within_15m", waitMin)
            repo.linkEpisodeOutcome("rec-multi-3", epId, "unknown", "accepted_ride", waitMin + 3.0, acceptedRide = true)
        }
        val cmps = repo.listComparisons()
        assertEquals(setOf("ep-1", "ep-2", "ep-3"), cmps.mapNotNull { it.linkedEpisodeId }.toSet())
        assertTrue(cmps.all { it.seenBeforeEpisodeStart })
        val summary = UberIntelligence.summarizeHistoryUsefulness(repo.listImports(), cmps)
        assertEquals(3, summary.linkedEpisodesTotal)
        assertEquals(3, summary.adequatelyLoggedCount)
        assertEquals(3, summary.acceptedRideCount)
        assertEquals(7.0, summary.medianMinutesToRequestCompletedOnly ?: 0.0, 0.01)
    }
}
