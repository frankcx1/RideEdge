package com.rideedge.app

import android.app.Application
import android.location.Location
import android.os.SystemClock
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class RadarLocationValidationTest {
    private fun fix() = Location("fixture").apply {
        latitude = 47.6205; longitude = -122.3509; accuracy = 10f
        elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        time = 1793512800000L
    }

    @Test fun locationAgeUsesElapsedClockAndPreservesOriginalFixTime() {
        val location = fix()
        val original = location.toRadarFix()!!
        assertEquals(location.time, original.fixAt.toEpochMilli())
        location.elapsedRealtimeNanos -= 301_000_000_000L
        assertNull(location.toRadarFix())
        location.elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos() + 1_000_000_000L
        assertNull(location.toRadarFix())
    }

    @Test fun unavailableOrImpreciseLocationCannotBecomeACarOrigin() {
        assertNotNull(fix().toRadarFix())
        assertNull(fix().apply { removeAccuracy() }.toRadarFix())
        assertNull(fix().apply { accuracy = 201f }.toRadarFix())
        assertNull(fix().apply { accuracy = -1f }.toRadarFix())
        assertNull(fix().apply { latitude = 0.0 }.toRadarFix())
    }
}
