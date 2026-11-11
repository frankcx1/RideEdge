package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SeaTacReportTest {
    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("seatac-v1.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }

    @Test fun sharedFixturePreservesUnknownCountsTimingAndRepeatedHour() {
        val report = SeaTacParser.parse(fixture())
        assertEquals(6, report.hours.size)
        assertTrue(seaClock(report.hours[2].startsAt).contains("PDT"))
        assertTrue(seaClock(report.hours[3].startsAt).contains("PST"))
        assertNull(report.hours[4].sampled)
        assertEquals(0, report.hours[5].sampled)
        assertTrue(report.hours[0].flights.all { it.timeBasis == "scheduled_gate" && it.timeField == "scheduled_in" })
        assertTrue(report.hours[1].flights.all { it.timeBasis == "estimated_landing" })
    }

    @Test fun peakExcludesUnavailableAndStaleWindowsAndExpiresOnElapsedClock() {
        val receipt = SeaTacReceipt(SeaTacParser.parse(fixture()), 1000, 7)
        assertEquals(receipt.report.hours[1], receipt.peak(1000, 7))
        assertFalse(receipt.usable(receipt.report.hours[3], 1000, 7))
        assertFalse(receipt.usable(receipt.report.hours[4], 1000, 7))
        assertNull(receipt.peak(1000+1800000, 7))
        assertNull(receipt.peak(999, 7))
        assertNull(receipt.peak(1000, 8))
        // No device wall-clock parameter exists: DST and manual clock changes
        // cannot renew the receipt's original provider validity.
    }

    @Test fun oldOrMalformedReportDoesNotInventZeros() {
        assertTrue(runCatching { SeaTacParser.parse(JSONObject()) }.isFailure)
        val bad = fixture()
        bad.getJSONArray("hours").getJSONObject(0).put("sampled_flights", "30+")
        assertTrue(runCatching { SeaTacParser.parse(bad) }.isFailure)
        assertTrue(runCatching { SeaTacParser.parse(fixture().put("report_schema_version", 2)) }.isFailure)
    }
}
