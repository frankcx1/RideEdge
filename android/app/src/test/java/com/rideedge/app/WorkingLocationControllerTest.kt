package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkingLocationControllerTest {

    private fun sampleHereState(
        zone: String,
        label: String,
        recommendationId: String = "rec-$zone-1",
        evidenceVersion: String = "v2",
    ): HereState = HereState(
        zone = zone,
        label = label,
        matched = label,
        note = "",
        action = "WAIT",
        actionPlain = "Hold in $label",
        spoken = "Hold in $label",
        stayRow = null,
        bestRow = null,
        rankedHours = emptyList(),
        nearby = emptyList(),
        nearbyStations = emptyList(),
        warnings = emptyList(),
        recommendationId = recommendationId,
        evidenceVersion = evidenceVersion,
    )

    @Test
    fun g04_manualAreaChangeClearsGpsGuidanceBeforeAndAfterFailure() {
        val controller = WorkingLocationController()
        val t0 = 1_000_000L

        // 1. Load Seattle guidance from GPS
        val gpsReq = controller.beginGpsLoad()
        assertTrue(controller.onGpsFixAcquired(gpsReq, 47.6062, -122.3321, t0, t0, accuracyMeters = 12f))
        val seattleGps = sampleHereState("seattle_core", "Seattle Core", "rec-sea-gps")
        assertTrue(controller.completeGpsLoad(gpsReq, seattleGps, 47.6062, -122.3321, t0))
        assertEquals("seattle_core", controller.hereState?.zone)
        assertTrue(controller.hereFromGps)
        assertNotNull(controller.currentFreshGps(t0 + 10_000L))

        // 2. User selects Bellevue manually; request is in flight (delayed)
        val bellevueReq = controller.beginManualAreaLoad("Bellevue")
        // Old Seattle GPS guidance MUST NOT remain visible while Bellevue is loading
        assertNull(controller.hereState)
        assertFalse(controller.hereFromGps)
        assertNull(controller.lastGpsLat)
        assertNull(controller.currentFreshGps(t0 + 20_000L))

        // 3. Bellevue request fails; advance clock past 5-minute GPS expiry window
        assertTrue(controller.failManualAreaLoad(bellevueReq, "Server unreachable"))
        assertNull(controller.hereState)
        assertEquals("Server unreachable", controller.statusBanner)
        assertNull(controller.currentFreshGps(t0 + 600_000L))
        assertNull(controller.hereState)
    }

    @Test
    fun f06_delayedGpsCallbackCannotOverwriteNewerManualSelection() {
        val controller = WorkingLocationController()
        val t0 = 2_000_000L

        val gpsReq = controller.beginGpsLoad()
        val manualReq = controller.beginManualAreaLoad("Bellevue")
        val bellevue = sampleHereState("bellevue_core", "Bellevue Core", "rec-bel-1")
        assertTrue(controller.completeManualAreaLoad(manualReq, bellevue, "Bellevue", t0))

        // Delayed GPS fix arrives for the superseded gpsReq
        assertFalse(controller.onGpsFixAcquired(gpsReq, 47.6062, -122.3321, t0, t0, accuracyMeters = 8f))
        assertFalse(
            controller.completeGpsLoad(
                gpsReq,
                sampleHereState("seattle_core", "Seattle Core"),
                47.6062,
                -122.3321,
                t0,
            )
        )
        assertEquals("bellevue_core", controller.hereState?.zone)
        assertNull(controller.lastGpsLat)
        assertFalse(controller.hereFromGps)
    }

    @Test
    fun f06_gpsGuidanceExpiresAfterFiveMinutesWhileScreenOpen() {
        val controller = WorkingLocationController()
        val t0 = 3_000_000L

        val gpsReq = controller.beginGpsLoad()
        assertTrue(controller.onGpsFixAcquired(gpsReq, 47.6155, -122.2015, t0, t0, accuracyMeters = 10f))
        assertTrue(
            controller.completeGpsLoad(
                gpsReq,
                sampleHereState("bellevue_core", "Bellevue Core"),
                47.6155,
                -122.2015,
                t0,
            )
        )
        assertNotNull(controller.currentFreshGps(t0 + 240_000L))
        assertNotNull(controller.hereState)

        // Advance past 300,000 ms (5 minutes)
        assertNull(controller.currentFreshGps(t0 + 305_000L))
        assertNull(controller.hereState)
        assertFalse(controller.hereFromGps)
        assertTrue(controller.statusBanner.orEmpty().contains("expired"))
    }

    @Test
    fun g03_parseHereAndOutcomePayloadCarryRetainedRecommendationAttribution() {
        val rawHere = JSONObject()
            .put("place", JSONObject().put("zone", "bellevue_core").put("label", "Bellevue Core"))
            .put("action", "WAIT")
            .put("action_plain", "Stay in Bellevue Core")
            .put("recommendation_id", "rec-bellevue-initial")
            .put("evidence_version", "v2.4")
        val parsedInitial = RideEdgeClient.parseHere(rawHere)
        assertEquals("rec-bellevue-initial", parsedInitial.recommendationId)
        assertEquals("v2.4", parsedInitial.evidenceVersion)

        val controller = WorkingLocationController()
        val req1 = controller.beginManualAreaLoad("Bellevue")
        controller.completeManualAreaLoad(req1, parsedInitial, "Bellevue", 1_000L)

        // Driver starts waiting on initial advice
        val (waitRecId, waitVer) = controller.resolveOutcomeAttribution("waiting", controller.hereState)
        assertEquals("rec-bellevue-initial", waitRecId)
        assertEquals("v2.4", waitVer)

        // Background refresh in the same zone produces a new recommendation_id while driver is still waiting
        val refreshedHere = parsedInitial.copy(recommendationId = "rec-bellevue-refreshed", evidenceVersion = "v2.5")
        val (pingRecId, pingVer) = controller.resolveOutcomeAttribution("request_received", refreshedHere)
        val (rideRecId, rideVer) = controller.resolveOutcomeAttribution("accepted_ride", refreshedHere)
        assertEquals("rec-bellevue-initial", pingRecId)
        assertEquals("v2.4", pingVer)
        assertEquals("rec-bellevue-initial", rideRecId)
        assertEquals("v2.4", rideVer)

        val payload = RideEdgeClient.buildDriverOutcomePayload(
            status = "accepted_ride",
            zone = "bellevue_core",
            recommendedAction = "WAIT",
            recommendationId = rideRecId,
            evidenceVersion = rideVer,
            idempotencyKey = "idem-test-1",
        )
        assertEquals("accepted_ride", payload.getString("status"))
        assertEquals("bellevue_core", payload.getString("zone"))
        assertEquals("rec-bellevue-initial", payload.getString("recommendation_id"))
        assertEquals("v2.4", payload.getString("evidence_version"))
        assertEquals("idem-test-1", payload.getString("idempotency_key"))
    }

    @Test
    fun h02_twoConsecutiveRideCyclesInSameZoneSwitchAdviceOnNewWaitEpisode() {
        val controller = WorkingLocationController()
        val first = sampleHereState("bellevue_core", "Bellevue Core", "rec-first", "version-rec-first")
        val firstBg = sampleHereState("bellevue_core", "Bellevue Core", "rec-first-bg", "version-rec-first-bg")
        val second = sampleHereState("bellevue_core", "Bellevue Core", "rec-second", "version-rec-second")
        val secondBg = sampleHereState("bellevue_core", "Bellevue Core", "rec-second-bg", "version-rec-second-bg")

        val req = controller.beginManualAreaLoad("Bellevue")
        assertTrue(controller.completeManualAreaLoad(req, first, "Bellevue", 1_000L))

        // Cycle 1: Waiting -> repeated Waiting during background refresh -> Got Ping -> On Ride
        assertEquals("rec-first" to "version-rec-first", controller.resolveOutcomeAttribution("waiting", first))
        assertEquals("rec-first" to "version-rec-first", controller.resolveOutcomeAttribution("waiting", firstBg))
        assertEquals("rec-first" to "version-rec-first", controller.resolveOutcomeAttribution("request_received", firstBg))
        assertEquals("rec-first" to "version-rec-first", controller.resolveOutcomeAttribution("accepted_ride", firstBg))
        assertEquals("accepted", controller.activeEpisodeState)

        // Cycle 2: New waiting episode after accepted ride in the same zone must capture rec-second
        assertEquals("rec-second" to "version-rec-second", controller.resolveOutcomeAttribution("waiting", second))
        assertEquals("waiting", controller.activeEpisodeState)
        assertEquals("rec-second" to "version-rec-second", controller.resolveOutcomeAttribution("accepted_ride", secondBg))
        assertEquals("accepted", controller.activeEpisodeState)
    }

    @Test
    fun n01_n02_remoteSeattleOpportunityNeverCalledLocalAndWatchNeverCalledHoldForNow() {
        val seattleRemote = NearbyWindow(
            id = "nw-sea-1",
            zone = "seattle_core",
            action = "MOVE",
            actionPlain = "Move to Seattle Core",
            score = 2.5,
            headline = "Convention Center & SLU (5:00 PM - 8:00 PM)",
            detail = "Remote activity",
            startsAt = "2026-10-21T17:00:00-07:00",
            endsAt = "2026-10-21T20:00:00-07:00",
            minutesAway = 59.0,
            milesAway = 18.4,
            routeBasis = "live",
            mapsUrl = "",
            isSameZone = false,
            sourceType = "scheduled",
            windowLabel = "5:00 PM - 8:00 PM",
        )
        val totemState = sampleHereState("totem_lake", "Totem Lake / Kingsgate").copy(
            action = "WATCH",
            actionPlain = "No clear recommendation to move yet",
            decisionState = "WATCH",
            recheckMinutes = 10,
            nearby = listOf(seattleRemote),
        )

        val decision = WorkingLocationController.resolveHereDecision(totemState, repositionLimitMinutes = 20)
        assertEquals("WATCH", decision.stateCode)
        assertEquals("No clear recommendation to move yet", decision.headline)
        assertFalse(decision.headline.contains("Hold for now", ignoreCase = true))

        assertFalse(decision.whyText.contains("Active local window", ignoreCase = true))
        assertTrue(decision.whyText.contains("59 minutes away"))
        assertTrue(decision.whyText.contains("does not establish stronger pickup demand here in Totem Lake / Kingsgate"))
        assertFalse(decision.evidenceChipLabel.contains("Live local", ignoreCase = true))
    }

    @Test
    fun n04_outcomeFailureRollsBackWaitStateAndAllowsIdempotentRetry() {
        val controller = WorkingLocationController()
        val state = sampleHereState("totem_lake", "Totem Lake / Kingsgate", "rec-totem-1", "v3")
        val req = controller.beginManualAreaLoad("Totem Lake / Kingsgate")
        controller.completeManualAreaLoad(req, state, "Totem Lake / Kingsgate", 10_000L)

        // Start a wait log attempt that fails
        val (rec1, ver1, idem1) = controller.beginOutcomeSubmission(
            status = "waiting",
            currentHere = state,
            nowMs = 20_000L,
        )
        assertEquals("rec-totem-1", rec1)
        assertEquals("v3", ver1)
        assertEquals("waiting", controller.pendingOutcomeStatus)
        assertEquals("pending", controller.lastOutcomeDeliveryState)

        controller.failOutcomeSubmission("Network timeout")
        assertNull(controller.pendingOutcomeStatus)
        assertNull(controller.activeEpisodeStartedAtMs)
        assertEquals("none", controller.activeEpisodeState)
        assertEquals("failed", controller.lastOutcomeDeliveryState)
        assertTrue(controller.lastOutcomeMessage.contains("Network timeout"))

        // Retry reuses the same idempotency key and advances state on completion while preserving original start timestamp
        val (_, _, idem2) = controller.beginOutcomeSubmission(
            status = "waiting",
            currentHere = state,
            nowMs = 25_000L,
        )
        assertEquals(idem1, idem2)
        assertEquals(20_000L, controller.lastSubmittedEventAtMs)
        controller.completeOutcomeSubmission("waiting")
        assertEquals(20_000L, controller.activeEpisodeStartedAtMs)
        assertEquals("waiting", controller.activeEpisodeState)
        assertEquals("saved", controller.lastOutcomeDeliveryState)
    }

    @Test
    fun n06_venuePollZeroLiveAndFailedAwarenessRefreshGiveHonestMessages() {
        val emptyAwareness = AwarenessState(
            scope = "nearby",
            area = "totem_lake",
            locationLabel = "Totem Lake / Kingsgate",
            locationSource = "area",
            snapshotState = "fresh",
            snapshotAgeMinutes = 1.0,
            layers = emptyList(),
            observations = emptyList(),
            venueActivity = emptyList(),
            emptyNote = "",
        )
        val (msgZero, isErrZero) = WorkingLocationController.formatVenuePollStatus(
            polledCount = 25,
            refreshedAwareness = emptyAwareness,
        )
        assertFalse(isErrZero)
        assertEquals("Checked 25 venues; no fresh live readings available.", msgZero)
        assertFalse(msgZero.contains("Updated crowd readings", ignoreCase = true))

        val (failedFollowupMsg, isErrFail) = WorkingLocationController.formatVenuePollStatus(
            polledCount = 25,
            refreshedAwareness = null,
        )
        assertTrue(isErrFail)
        assertTrue(failedFollowupMsg.contains("refreshing the screen failed"))
        assertFalse(failedFollowupMsg.contains("Nearby list refreshed", ignoreCase = true))
    }

    @Test
    fun n10_compareExclusionsUseSpecificDriverLanguage() {
        val base = AskOptionRow(
            id = "opt-sea",
            area = "Seattle Core",
            venue = "Convention Center",
            score = 6.0,
            routeMinutes = null,
            routeStatus = "unavailable",
            eligible = false,
            reasons = listOf("Route time is unknown"),
        )
        assertEquals(
            "Route unavailable",
            WorkingLocationController.formatCompareExclusion(base, 20).first
        )
        assertEquals(
            "Exceeds your 20-minute drive limit",
            WorkingLocationController.formatCompareExclusion(
                base.copy(
                    routeMinutes = 28.0,
                    routeStatus = "live",
                    reasons = listOf("Drive exceeds reposition limit under 20 min"),
                ),
                20
            ).first
        )
        assertEquals(
            "Arrives after the useful window",
            WorkingLocationController.formatCompareExclusion(
                base.copy(
                    routeMinutes = 18.0,
                    routeStatus = "live",
                    reasons = listOf("Window ends before arrival"),
                ),
                20
            ).first
        )
    }

    @Test
    fun round7_planMinutesAvailableDefaultsTo360AndPersistsAcrossRestart() {
        val controller = WorkingLocationController()
        assertEquals(360, controller.planMinutesAvailable)
        controller.setPlanDurationMinutes(240)
        assertEquals(240, controller.planMinutesAvailable)

        val restored = WorkingLocationController()
        restored.restoreFromJson(controller.toJson())
        assertEquals(240, restored.planMinutesAvailable)
    }

    @Test
    fun round7_laterActionQueuesEarlierFailedRequestAndPreservesFirstRequestTime() {
        val controller = WorkingLocationController()
        val state = sampleHereState("totem_lake", "Totem Lake", "rec-r7-1", "v2")
        val req = controller.beginManualAreaLoad("Totem Lake")
        controller.completeManualAreaLoad(req, state, "Totem Lake", 0L)

        controller.beginOutcomeSubmission("waiting", currentHere = state, nowMs = 0L)
        controller.completeOutcomeSubmission("waiting")

        val (_, _, requestIdemKey) = controller.beginOutcomeSubmission(
            status = "request_received",
            currentHere = state,
            nowMs = 600_000L,
        )
        controller.failOutcomeSubmission("503 before commit")

        controller.beginOutcomeSubmission(
            status = "accepted_ride",
            currentHere = state,
            nowMs = 900_000L,
        )
        val persistedJson = controller.toJson().toString()
        assertTrue(persistedJson.contains(requestIdemKey))
        assertEquals(10.0, controller.lastSubmittedFirstRequestWaitMinutes!!, 0.0)
    }
}
