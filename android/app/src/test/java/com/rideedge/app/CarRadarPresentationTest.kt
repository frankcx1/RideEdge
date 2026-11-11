package com.rideedge.app

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class CarRadarPresentationTest {
    @Test fun evidenceGapIsDistinctFromConnectionAndFreshReviewDoesNotClaimFreshFeeds() = runTest {
        val json = fixture().put("now", org.json.JSONArray()).put("further", org.json.JSONArray())
            .put("decision_state", "none_supported").put("decision_message", "No supported immediate move. Nearby and Plan remain available.")
            .put("activity_coverage", "Venue activity unavailable. BestTime collection paused.")
        json.getJSONArray("plan").getJSONObject(0).put("selected_id", JSONObject.NULL)
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> error("No render I/O") },
            RadarLocationSource { null }, { 0L }, { 1 })
        assertTrue(repo.store.accept(json, 0))
        repo.setCarConnected(true); repo.startCarSession()
        assertTrue(carRadarView(repo).message!!.contains("No supported immediate move"))
        repo.store.disconnected(0)
        assertTrue(carRadarView(repo).message!!.contains("Connection lost"))
        repo.close()
    }

    @Test fun fallbackClassificationSurvivesParsingAndIsVisibleWithoutOpeningEvidence() = runTest {
        val json = fixture().put("decision_state", "contextual_fallback")
        json.getJSONArray("now").getJSONObject(0).put("decision_class", "contextual_fallback").put("hours_status", "unknown")
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> error("No render I/O") },
            RadarLocationSource { null }, { 0L }, { 1 })
        assertTrue(repo.store.accept(json, 0))
        repo.setCarConnected(true); repo.startCarSession()
        val place = carRadarView(repo).places.first()
        assertTrue(place.isPositioningFallback)
        assertEquals("unknown", place.hoursStatus)
        assertTrue(carRadarView(repo).status.contains("activity unverified"))
        assertTrue(activityCaveat(place).contains("opening hours"))
        repo.close()
    }
    private fun fixture(): JSONObject = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }.also {
            it.getJSONObject("origin").put("mode", "device").put("fix_at", it.getString("server_time"))
        }

    @Test fun accessFailureDirectsDriverToPhoneWithoutStartingIo() = runTest {
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> error("Render triggered I/O") },
            RadarLocationSource { null }, { 0L }, { 1 })
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        repo.store.accessRequired(0)
        val view = carRadarView(repo)
        assertEquals("Reconnect on your phone", view.title)
        assertTrue(view.places.isEmpty())
        assertTrue(view.message!!.contains("parked"))
        repo.close()
    }

    @Test fun noSessionDoesNotExposePhoneDecisionOrStartIo() = runTest {
        var calls = 0
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> calls++; fixture() },
            RadarLocationSource { error("Rendering requested location") }, { 0L }, { 1 })
        repo.store.accept(fixture(), 0)
        assertTrue(carRadarView(repo).places.isEmpty())
        repo.setCarConnected(true)
        repeat(20) { assertEquals("No active car session", carRadarView(repo).status) }
        assertEquals(0, calls)
        repo.close()
    }

    @Test fun carAndPhoneUseSamePrimaryAndExpiryAtNavigationTime() = runTest {
        var elapsed = 0L
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { elapsed }, { 1 })
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        val view = carRadarView(repo)
        assertEquals(repo.store.primary()!!.id, view.places.first().id)
        val capturedId = view.places.first().id
        elapsed = 21 * 60 * 1000L
        assertNull(repo.navigationTarget(capturedId))
        assertTrue(carRadarView(repo).places.isEmpty())
        repo.close()
    }

    @Test fun originChangeHidesCarDestinationsImmediately() = runTest {
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { 0L }, { 1 })
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        assertFalse(carRadarView(repo).places.isEmpty())
        repo.usePhone()
        assertTrue(carRadarView(repo).places.isEmpty())
        assertEquals("Updating location", carRadarView(repo).title)
        repo.close()
    }

    @Test fun cleanupWarningRetainsEligibleAnswerButDisconnectHidesIt() = runTest {
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { 0L }, { 1 })
        val json = fixture().put("runtime", JSONObject().put("cleanup", JSONObject().put("state", "restoration_failed")))
        repo.store.accept(json, 0)
        repo.setCarConnected(true); repo.startCarSession()
        assertFalse(carRadarView(repo).places.isEmpty())
        assertTrue(carRadarView(repo).status.contains("recovery"))
        repo.setCarConnected(false)
        assertTrue(carRadarView(repo).places.isEmpty())
        repo.close()
    }

    @Test fun selectedAreaCannotMasqueradeAsCurrentCarLocation() = runTest {
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { 0L }, { 1 })
        val area = fixture().also { it.getJSONObject("origin").put("mode", "selected_area") }
        repo.store.accept(area, 0)
        repo.setCarConnected(true); repo.startCarSession()
        assertTrue(carRadarView(repo).places.isEmpty())
        assertEquals("Use current location", carRadarView(repo).title)
        repo.close()
    }

    @Test fun sessionDeadlineIsCheckedEvenBeforePollingLoopUpdatesItsFlag() = runTest {
        var elapsed = 0L
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { elapsed }, { 1 })
        repo.setCarConnected(true); repo.startCarSession()
        elapsed = 6*60*60*1000L
        repo.store.accept(fixture(), 0) // fresh evidence cannot extend expired session consent
        assertTrue(repo.session.value.carActive) // timer coroutine has not run yet
        assertFalse(repo.hasActiveCarSession())
        assertTrue(carRadarView(repo).places.isEmpty())
        repo.close()
    }
}
