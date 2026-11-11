package com.rideedge.app

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject

class RadarConnectionPresentationTest {
    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }

    @Test fun reachableInvalidDataIsNotAnUnreachableServer() {
        val view = radarConnectionPresentation(RadarViewState(connected = true, errorCode = "invalid_contract"), null, false, true)!!
        assertEquals("Data unavailable", view.title)
        assertFalse(view.settingsRequired)
        assertFalse(view.retrying)
    }

    @Test fun authenticationAndFirstLaunchHaveActionableSetupWithoutInventedReview() {
        val first = radarConnectionPresentation(RadarViewState(), null, false, true)!!
        assertTrue(first.settingsRequired)
        assertTrue(first.detail.contains("No recommendation"))
        val rejected = radarConnectionPresentation(RadarViewState(errorCode = "access_required"), "Key rejected", false, true)!!
        assertEquals("Key rejected", rejected.detail)
        assertTrue(rejected.settingsRequired)
        assertFalse(rejected.retrying)
    }

    @Test fun successfulContactDoesNotChangeOnDisconnectOrEnableExpiredNavigation() {
        var elapsed = 1000L
        val store = RadarStateStore({ elapsed }, { 1 })
        store.accept(fixture(), 0)
        val receipt = store.state.value.received
        val contact = store.state.value.lastContactAt
        val id = store.primary()!!.id
        elapsed += 5000
        store.disconnected(0)
        assertSame(receipt, store.state.value.received)
        assertEquals(contact, store.state.value.lastContactAt)
        assertNotNull(store.navigationTarget(id))
        assertTrue(radarConnectionPresentation(store.state.value, null, false, true)!!.retrying)
        assertFalse(radarConnectionPresentation(store.state.value, null, false, false)!!.retrying)
        elapsed += 20 * 60 * 1000
        assertNull(store.navigationTarget(id))
        assertSame(receipt, store.state.value.received)
    }

    @Test fun modelStatusDoesNotInventAConnectionFailure() {
        val store = RadarStateStore({ 1L }, { 1 })
        store.accept(fixture().apply { getJSONObject("qwen").put("state", "unavailable") }, 0)
        assertNull(radarConnectionPresentation(store.state.value, null, false, true))
    }
}
