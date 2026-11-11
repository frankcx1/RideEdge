package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class CarRefreshTest {
    private fun state(): RadarViewState {
        val json = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
            .bufferedReader().use { JSONObject(it.readText()) }
        return RadarViewState(received = ReceivedRadar(RadarParser.parse(json), 0, 1), connected = true)
    }
    private fun key(s: RadarViewState, tick: Long = 0, session: RadarSession = RadarSession()) =
        carRefreshKey(s, session, RadarExploration(), tick, true)

    @Test fun unchangedPollAndBusyToggleDoNotResubmitTemplate() {
        val first = state()
        val receipt = first.received!!
        val polled = first.copy(lastContactAt = Instant.now(), received = receipt.copy(
            receivedElapsedMs = 5000, snapshot = receipt.snapshot.copy(
                serverTime = receipt.snapshot.serverTime.plusSeconds(5))))
        assertEquals(key(first), key(polled, 5000, RadarSession(busy = true)))
    }

    @Test fun locationDecisionDisconnectAndExpiryStillRefresh() {
        val first = state()
        val receipt = first.received!!
        assertNotEquals(key(first), key(first.copy(connected = false)))
        assertNotEquals(key(first), key(first.copy(received = receipt.copy(snapshot =
            receipt.snapshot.copy(decisionRevision = "new-review")))))
        assertNotEquals(key(first), key(first.copy(received = receipt.copy(snapshot =
            receipt.snapshot.copy(origin = receipt.snapshot.origin.copy(latitude = 47.65))))))
        val soon = first.copy(received = receipt.copy(snapshot = receipt.snapshot.copy(
            validUntil = receipt.snapshot.serverTime.plusSeconds(10))))
        assertNotEquals(key(soon, 9000), key(soon, 10000))
    }
}
