package com.rideedge.app

import android.app.Application
import android.location.Location
import android.os.SystemClock
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock
import java.time.Duration

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneCarLocationTest {
    @Test fun expiryHarnessAdvancesOnlyPreviewClockAndNeverAndroidClock() {
        val app = RideEdgeApplication()
        val androidBefore = SystemClock.elapsedRealtime()
        val before = app.radarElapsedMs()
        app.advancePreviewSessionClock()
        assertEquals(androidBefore, SystemClock.elapsedRealtime())
        val expectedAdvance = if (BuildConfig.BUILD_TYPE == "preview") 6 * 60 * 60 * 1000L else 0L
        assertEquals(expectedAdvance, app.radarElapsedMs() - before)
    }

    @Test fun lockedPhoneNeedsActiveConnectedSessionAndForegroundService() {
        val active = RadarSession(followPhone = true, carActive = true, carConnected = true)
        assertFalse(phoneLocationAllowed(active, false))
        assertTrue(phoneLocationAllowed(active, true))
        assertFalse(phoneLocationAllowed(active.copy(carConnected = false), true))
        assertFalse(phoneLocationAllowed(active.copy(carActive = false), true))
        assertFalse(phoneLocationAllowed(active.copy(followPhone = false), true))
        assertTrue(phoneLocationAllowed(RadarSession(phoneVisible = true), false))
    }

    @Test fun phoneFixRejectsOldImpreciseAndOutOfRegionLocations() {
        ShadowSystemClock.advanceBy(Duration.ofMinutes(10))
        val fix = Location("fused").apply {
            latitude = 47.6205; longitude = -122.3509
            accuracy = 10f; time = System.currentTimeMillis()
            elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        }
        assertNotNull(fix.toRadarFix(maxAgeMs = 60000))
        fix.accuracy = 201f
        assertNull(fix.toRadarFix(maxAgeMs = 60000))
        fix.accuracy = 10f
        fix.latitude = 0.0
        assertNull(fix.toRadarFix(maxAgeMs = 60000))
        fix.latitude = 47.6205
        ShadowSystemClock.advanceBy(Duration.ofSeconds(61))
        assertNull(fix.toRadarFix(maxAgeMs = 60000))
    }
}
