package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ActivityRadarStateTest {
    private fun pin(lat: Double = 47.61, lon: Double = -122.2, mode: String = "device") =
        JSONObject().put("latitude", lat).put("longitude", lon).put("mode", mode)

    @Test fun gpsTimestampRefreshDoesNotDiscardSlowQwenAnswer() {
        assertTrue(radarSameOrigin(pin().put("fix_at", "newer"), pin().put("fix_at", "older")))
        assertTrue(radarSameOrigin(pin(47.6101), pin()))
    }

    @Test fun movedOrMissingLocationRejectsOldAnswer() {
        assertFalse(radarSameOrigin(pin(47.64), pin()))
        assertFalse(radarSameOrigin(null, pin()))
        assertFalse(radarSameOrigin(JSONObject(), JSONObject()))
        assertFalse(radarSameOrigin(pin(mode = "selected_area"), pin()))
    }

}
