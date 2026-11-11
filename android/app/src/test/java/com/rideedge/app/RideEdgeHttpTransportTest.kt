package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL

class RideEdgeHttpTransportTest {
    private val token = "re_" + "t".repeat(43)
    private class Connection(url: URL, val status: Int = 200, val result: String = "{}", val timeout: Boolean = false) : HttpURLConnection(url) {
        val sent = ByteArrayOutputStream()
        var closed = false
        override fun connect() {}
        override fun disconnect() { closed = true }
        override fun usingProxy() = false
        override fun getOutputStream() = sent
        override fun getInputStream() = ByteArrayInputStream(result.toByteArray())
        override fun getErrorStream() = ByteArrayInputStream(result.toByteArray())
        override fun getResponseCode(): Int {
            if (timeout) throw SocketTimeoutException("sensitive provider echo")
            return status
        }
    }

    @Test fun sendsBearerOnlyToFixedHttpsOriginAndClosesConnection() {
        var connection: Connection? = null
        val transport = RideEdgeHttpTransport { url -> Connection(url, result = "{\"authenticated\":true}").also { connection = it } }
        assertTrue(transport.request("/auth/check", "GET", null, 1000, token).getBoolean("authenticated"))
        val actual = connection!!
        assertEquals(RideEdgeConnection.origin + "/auth/check", actual.url.toString())
        assertEquals("Bearer $token", actual.getRequestProperty("Authorization"))
        assertFalse(actual.instanceFollowRedirects)
        assertTrue(actual.closed)
    }

    @Test fun redirectsAndTimedOutMutationsAreNeverReplayed() {
        for (status in listOf(307, 308, 200)) {
            var calls = 0
            lateinit var connection: Connection
            val transport = RideEdgeHttpTransport { url ->
                calls++
                Connection(url, status, timeout = status == 200).also { connection = it }
            }
            val result = runCatching { transport.request("/api/feeds/refresh", "POST", JSONObject(), 1000, token) }
            assertTrue(result.isFailure)
            assertEquals(1, calls)
            assertEquals("{}", connection.sent.toString("UTF-8"))
            assertTrue(connection.closed)
            assertFalse(result.exceptionOrNull()!!.message!!.contains("sensitive"))
        }
    }

    @Test fun authenticationAndUnconfiguredBackendHaveActionableSafeErrors() {
        for ((status, payload) in listOf(401 to "private echo", 503 to "{\"code\":\"setup_required\"}")) {
            val transport = RideEdgeHttpTransport { url -> Connection(url, status, payload) }
            val result = runCatching { transport.request("/auth/check", "GET", null, 1000, token) }
            assertTrue(result.exceptionOrNull() is AccessRequiredException)
            assertFalse(result.exceptionOrNull()!!.message!!.contains("private echo"))
        }
    }
}
