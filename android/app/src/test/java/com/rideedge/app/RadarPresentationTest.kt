package com.rideedge.app

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.time.Instant

class RadarPresentationTest {
    @Test fun missingReportCountsRemainUnknownAndZeroRemainsZero() {
        val report = JSONObject().put("zero", 0).put("missing", JSONObject.NULL)
        assertEquals("0", report.countText("zero"))
        assertEquals("unknown", report.countText("missing"))
        assertEquals("unknown", report.countText("absent"))
    }
    @Test fun seaTacRangePreservesTheRepeatedHourAcrossDaylightSavingTime() {
        assertEquals("1:00 AM PDT – 1:00 AM PST", seaRange(Instant.parse("2026-11-01T08:00:00Z"), Instant.parse("2026-11-01T09:00:00Z")))
        assertEquals("12:00 – 1:00 AM PDT", seaRange(Instant.parse("2026-11-01T07:00:00Z"), Instant.parse("2026-11-01T08:00:00Z")))
    }
    private fun snapshot(): RadarSnapshot = RadarParser.parse(javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader().use { JSONObject(it.readText()) })

    @Test fun currentIntervalUsesTimeAndExclusiveEndInsteadOfListPosition() {
        val slots = snapshot().plan
        val first = slots.first()
        assertFalse(isCurrentInterval(first, first.startsAt.minusSeconds(1)))
        assertTrue(isCurrentInterval(first, first.startsAt))
        assertFalse(isCurrentInterval(first, first.endsAt))
        assertTrue(isCurrentInterval(slots[1], slots[1].startsAt))
    }

    @Test fun activityBasisNeverUpgradesTypicalOrUnknownToLive() {
        val place = snapshot().now.first()
        assertTrue(activityCaveat(place.copy(busyness = 55.0, busynessBasis = "typical weekly pattern")).contains("not a current crowd"))
        assertTrue(activityCaveat(place.copy(busyness = 0.0, busynessBasis = null)).contains("unspecified"))
        assertTrue(activityCaveat(place.copy(busyness = 120.0, busynessBasis = "live")).contains("not a rider count"))
        assertEquals("120", edgeNumber(120.0))
        assertEquals("0", edgeNumber(0.0))
    }
}
