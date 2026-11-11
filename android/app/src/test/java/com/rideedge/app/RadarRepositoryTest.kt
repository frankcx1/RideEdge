package com.rideedge.app

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

@OptIn(ExperimentalCoroutinesApi::class)
class RadarRepositoryTest {
    private fun fixture(): JSONObject = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }

    private fun repository(scope: TestScope, requests: MutableList<String>, location: RadarLocationSource = RadarLocationSource { null },
                           response: suspend (String, JSONObject?) -> JSONObject = { _, _ -> fixture() }): RadarRepository =
        RadarRepository(scope.backgroundScope, RadarTransport { path, body -> requests.add(path); response(path, body) },
            location, { scope.testScheduler.currentTime }, { 7 }, "Seattle Center")

    @Test fun phoneAndCarShareOneLoopAndRenderingDoesNotFetch() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        repo.setPhoneVisible(true); runCurrent()
        assertEquals(listOf("/context"), requests)
        repo.setCarConnected(true); repo.startCarSession(); runCurrent()
        repeat(20) { repo.state.value; repo.store.primary() }
        assertEquals(1, requests.size)
        advanceTimeBy(30000); runCurrent()
        assertEquals(listOf("/context", ""), requests)
        repo.setPhoneVisible(false)
        advanceTimeBy(30000); runCurrent()
        assertEquals(3, requests.size) // active car retains the same loop
        repo.setCarConnected(false)
        advanceTimeBy(60000); runCurrent()
        assertEquals(3, requests.size)
        repo.close()
    }

    @Test fun recreationAndReconnectDoNotDuplicateInitialContext() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        repo.setPhoneVisible(true); runCurrent()
        repo.setPhoneVisible(false); repo.setPhoneVisible(true); runCurrent()
        repo.setCarConnected(true); repo.startCarSession(); repo.setCarConnected(false); repo.setCarConnected(true); runCurrent()
        assertEquals(1, requests.size)
        repo.close()
    }

    @Test fun backgroundReconnectRequiresFreshCarSessionBeforePollingResumes() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        repo.setCarConnected(true); repo.startCarSession(); runCurrent()
        assertTrue(repo.hasActiveCarSession())
        repo.setCarConnected(false); runCurrent()
        assertFalse(repo.session.value.carActive)
        val atDisconnect = requests.size
        advanceTimeBy(60000)
        repo.setCarConnected(true); runCurrent()
        assertFalse(repo.hasActiveCarSession())
        advanceTimeBy(60000); runCurrent()
        assertEquals(atDisconnect, requests.size)
        repo.startCarSession(); runCurrent()
        assertTrue(repo.hasActiveCarSession())
        assertTrue(requests.size > atDisconnect)
        repo.close()
    }

    @Test fun oldActivityStoppingCannotDisableItsVisibleReplacement() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        val oldActivity = Any()
        val replacement = Any()
        repo.setPhoneVisible(true, oldActivity); runCurrent()
        repo.setPhoneVisible(true, replacement)
        repo.setPhoneVisible(false, oldActivity)
        repo.setPhoneVisible(false, oldActivity) // onStop followed by disposal
        assertTrue(repo.session.value.phoneVisible)
        advanceTimeBy(30000); runCurrent()
        assertEquals(listOf("/context", ""), requests)
        repo.setPhoneVisible(false, replacement)
        assertFalse(repo.session.value.phoneVisible)
        advanceTimeBy(60000); runCurrent()
        assertEquals(2, requests.size)
        repo.close()
    }

    @Test fun explorationDoesNotChangeDrivingOriginOrSelection() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests, response = { path, _ -> fixture().also {
            if (path == "/preview") it.getJSONObject("origin").put("label", "Ballard fixture")
        } })
        repo.setPhoneVisible(true); runCurrent()
        val origin = repo.state.value.received!!.snapshot.origin
        repo.explore("Ballard"); runCurrent()
        assertEquals(origin, repo.state.value.received!!.snapshot.origin)
        assertEquals("Ballard fixture", repo.exploration.value.area)
        assertEquals(listOf("/context", "/preview"), requests)
        repo.close()
    }

    @Test fun oldContextResponseIsRejectedBeforeNewOriginLoads() = runTest {
        val requests = mutableListOf<String>()
        val first = CompletableDeferred<Unit>()
        val repo = repository(this, requests, response = { _, body ->
            val area = body?.optString("area").orEmpty()
            if (area == "Seattle Center") first.await()
            fixture().also { it.getJSONObject("origin").put("label", area) }
        })
        repo.setPhoneVisible(true); runCurrent()
        repo.chooseArea("Ballard"); first.complete(Unit); runCurrent()
        assertNull(repo.state.value.received)
        advanceTimeBy(1000); runCurrent()
        assertEquals("Ballard", repo.state.value.received!!.snapshot.origin.label)
        repo.close()
    }

    @Test fun locationHasOneOwnerAndDisconnectCancelsCarOnlyRequest() = runTest {
        val requests = mutableListOf<String>()
        var fixes = 0; var cancelled = false
        val repo = repository(this, requests, RadarLocationSource {
            fixes++
            try { awaitCancellation() } finally { cancelled = true }
        })
        repo.usePhone(); repo.setCarConnected(true); repo.startCarSession(); runCurrent()
        assertEquals(1, fixes)
        repo.setPhoneVisible(true); runCurrent()
        assertEquals(1, fixes)
        repo.setPhoneVisible(false); repo.setCarConnected(false); runCurrent()
        assertTrue(cancelled)
        assertTrue(requests.isEmpty())
        repo.close()
    }

    @Test fun repeatedRefreshCoalescesAndPendingPollUsesFiveSeconds() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests, response = { path, _ ->
            if (path == "/refresh") delay(1000)
            fixture()
        })
        repo.setPhoneVisible(true); runCurrent()
        repo.refresh(); repo.refresh(); runCurrent()
        advanceTimeBy(6000); runCurrent()
        assertEquals(1, requests.count { it == "/refresh" })
        assertTrue(requests.count { it.isEmpty() } >= 1)
        repo.close()
    }

    @Test fun failuresBackOffAndDoNotSpin() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests, response = { _, _ -> error("offline") })
        repo.setPhoneVisible(true); runCurrent()
        advanceTimeBy(29000); runCurrent()
        assertEquals(1, requests.size)
        advanceTimeBy(1000); runCurrent()
        assertEquals(2, requests.size)
        assertFalse(repo.state.value.connected)
        repo.close()
    }

    @Test fun expiredOrRestartedBackendReceivesFreshContextAfterBoundedBackoff() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests, response = { path, _ ->
            if (path.isEmpty()) error("RideEdge request failed (HTTP 409).")
            fixture()
        })
        repo.setPhoneVisible(true); runCurrent()
        advanceTimeBy(30000); runCurrent()
        assertEquals(listOf("/context", ""), requests)
        assertFalse(repo.state.value.connected)
        advanceTimeBy(29000); runCurrent()
        assertEquals(2, requests.size)
        advanceTimeBy(1000); runCurrent()
        assertEquals(listOf("/context", "", "/context"), requests)
        assertTrue(repo.state.value.connected)
        repo.close()
    }

    @Test fun carSessionExpiresAfterSixHoursWithoutPhoneOrPersistedRestartConsent() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        repo.setCarConnected(true); repo.startCarSession(); runCurrent()
        advanceTimeBy(6*60*60*1000L); runCurrent()
        assertFalse(repo.session.value.carActive)
        val count = requests.size
        advanceTimeBy(60000); runCurrent()
        assertEquals(count, requests.size)
        assertTrue(count <= 721)
        repo.close()
        val restarted = repository(this, requests)
        restarted.setCarConnected(true); runCurrent()
        assertFalse(restarted.session.value.carActive)
        assertEquals(count, requests.size)
        restarted.close()
    }

    @Test fun phoneFixesAreBoundedWhileCarAndPhoneAreBothVisible() = runTest {
        val requests = mutableListOf<String>()
        var fixes = 0
        val repo = repository(this, requests, RadarLocationSource {
            fixes++; RadarFix(47.6205, -122.3509, 10.0, Instant.parse("2026-11-01T06:00:00Z"))
        }, response = { _, _ -> fixture().also { it.getJSONObject("origin").put("mode", "device") } })
        repo.usePhone(); repo.setPhoneVisible(true); repo.setCarConnected(true); repo.startCarSession(); runCurrent()
        advanceTimeBy(60000); runCurrent()
        assertEquals(2, fixes)
        assertEquals(2, requests.count { it == "/context" })
        repo.close()
    }

    @Test fun failedGpsCannotReactivatePreviousSelectedAreaAsPhoneLocation() = runTest {
        val requests = mutableListOf<String>()
        val repo = repository(this, requests)
        repo.setPhoneVisible(true); runCurrent()
        assertNotNull(repo.store.primary())
        repo.usePhone(); advanceTimeBy(1000); runCurrent()
        assertTrue(repo.state.value.changingOrigin)
        assertNull(repo.store.primary())
        advanceTimeBy(60000); runCurrent()
        assertEquals(listOf("/context"), requests)
        assertTrue(repo.state.value.changingOrigin)
        assertNull(repo.store.primary())
        repo.close()
    }
}
