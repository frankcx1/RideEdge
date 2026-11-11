package com.rideedge.app

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.KeyGenerator

class AccessKeyTest {
    private val fixture = "re_" + "a".repeat(43)
    private fun key() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test fun authenticatedEncryptionRoundTripsAndChangesIv() {
        val key = key()
        val binding = RideEdgeConnection.origin.toByteArray()
        val first = AccessKeyCipher.encrypt(fixture, key, binding)
        val second = AccessKeyCipher.encrypt(fixture, key, binding)
        assertFalse(first.contentEquals(second))
        assertFalse(String(first, Charsets.ISO_8859_1).contains(fixture))
        assertEquals(fixture, AccessKeyCipher.decrypt(first, key, binding))
        assertTrue(RideEdgeConnection.validKey(fixture))
        assertFalse(RideEdgeConnection.validKey(fixture + "\n"))
    }

    @Test fun tamperingWrongKeyAndOriginChangeFailClosed() {
        val key = key()
        val binding = RideEdgeConnection.origin.toByteArray()
        val encrypted = AccessKeyCipher.encrypt(fixture, key, binding)
        val tampered = encrypted.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
        for (action in listOf<() -> Unit>(
            { AccessKeyCipher.decrypt(tampered, key, binding) },
            { AccessKeyCipher.decrypt(encrypted, key(), binding) },
            { AccessKeyCipher.decrypt(encrypted, key, "other-origin".toByteArray()) },
            { AccessKeyCipher.decrypt(byteArrayOf(1), key, binding) },
        )) assertTrue(runCatching(action).isFailure)
    }

    @Test fun connectionCannotChangeHostOrFallBackToCleartext() {
        assertEquals(listOf(RideEdgeConnection.origin), RideEdgeClient.CANDIDATE_URLS)
        assertEquals(RideEdgeConnection.origin + "/api/radar", RideEdgeConnection.url("/api/radar"))
        for (path in listOf("https://other.invalid", "//other.invalid", "/\\other.invalid")) {
            assertTrue(runCatching { RideEdgeConnection.url(path) }.isFailure)
        }
    }
}
