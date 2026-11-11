package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class RadarStateStoreTest {
    private fun fixture(): JSONObject = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }

    @Test fun rejectedAccessWithholdsNavigationUntilAuthenticatedRefresh() {
        val store = RadarStateStore({ 1000L }, { 7 })
        store.accept(fixture(), 0)
        val primary = store.primary()!!
        store.accessRequired(0)
        assertNotNull(store.state.value.received)
        assertEquals("access_required", store.state.value.errorCode)
        assertNull(store.navigationTarget(primary.id))
        store.accept(fixture(), 0)
        assertNotNull(store.primary())
        store.accessRequired(-1)
        assertNotNull(store.primary())
    }

    @Test fun schemaFailureRetainsOriginalReceiptWithoutRenewingValidity() {
        var elapsed = 1000L
        val store = RadarStateStore({ elapsed }, { 7 })
        assertTrue(store.accept(fixture(), 0))
        val original = store.state.value.received
        elapsed += 10*60*1000
        assertFalse(store.accept(fixture().put("schema_version", 2), 0))
        assertSame(original, store.state.value.received)
        assertEquals("schema_mismatch", store.state.value.errorCode)
        assertNull(store.primary())
    }

    @Test fun oldOriginResponseCannotReplaceCurrentOriginOrEnableNavigation() {
        val store = RadarStateStore({ 1000 }, { 7 })
        store.accept(fixture(), 0)
        val oldPrimary = store.primary()!!
        val generation = store.beginOriginChange()
        assertNull(store.navigationTarget(oldPrimary.id))
        assertFalse(store.accept(fixture(), 0))
        assertTrue(store.state.value.changingOrigin)
        assertTrue(store.accept(fixture(), generation))
        assertNotNull(store.primary())
    }

    @Test fun offlineAndTapExpiryDoNotRequireNewServerResponse() {
        var elapsed = 1000L
        val store = RadarStateStore({ elapsed }, { 7 })
        store.accept(fixture(), 0)
        val capturedId = store.primary()!!.id
        store.disconnected(0)
        assertNotNull(store.navigationTarget(capturedId))
        elapsed += 20*60*1000
        assertNull(store.navigationTarget(capturedId))
        assertNotNull(store.state.value.received) // evidence remains inspectable
    }

    @Test fun newDecisionInvalidatesPreviouslyRenderedDestination() {
        val store = RadarStateStore({ 1000 }, { 7 })
        store.accept(fixture(), 0)
        val capturedId = store.primary()!!.id
        val changed = fixture()
        changed.getJSONArray("now").getJSONObject(0).put("actionable", false)
        store.accept(changed, 0)
        assertNull(store.navigationTarget(capturedId))
    }
}
