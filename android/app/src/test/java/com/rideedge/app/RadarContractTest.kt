package com.rideedge.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Duration
import java.time.ZoneId

class RadarContractTest {
    private fun fixture(): JSONObject = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }

    @Test fun sharedFixturePreservesSelectionAndSixElapsedHoursAcrossDst() {
        val value = RadarParser.parse(fixture())
        assertEquals(value.now.first().id, value.plan.first().selectedId)
        assertEquals(6L, Duration.between(value.plan.first().startsAt, value.plan.last().endsAt).toHours())
        val localHours = value.plan.map { it.startsAt.atZone(ZoneId.of("America/Los_Angeles")) }
        assertEquals(listOf(23, 0, 1, 1, 2, 3), localHours.map { it.hour })
        assertNotEquals(localHours[2].offset, localHours[3].offset)
    }

    @Test fun additiveAndOptionalFieldsAreCompatible() {
        val json = fixture().put("unknown_addition", "accepted")
        json.getJSONArray("now").getJSONObject(0).remove("busyness")
        val value = RadarParser.parse(json)
        assertNull(value.now.first().busyness)
    }

    @Test fun arrivalTimingKeepsFutureEvidenceInspectableWithoutUsingItAsTheReason() {
        val json = fixture()
        val evidence = json.getJSONArray("now").getJSONObject(0).getJSONArray("evidence")
        val current = JSONObject(evidence.getJSONObject(0).toString())
            .put("arrival_relevant", true).put("role", "opportunity").put("text", "Current activity")
        evidence.getJSONObject(0).put("arrival_relevant", false).put("text", "Future concert exit")
            .put("starts_at", "2026-11-01T07:30:00Z").put("ends_at", "2026-11-01T08:30:00Z")
        evidence.put(current)
        val place = RadarParser.parse(json).now.first()
        assertFalse(place.evidence.first().arrivalRelevant)
        assertNotNull(place.evidence.first().startsAt)
        assertEquals("Current activity", place.supportingEvidence?.text)
        assertEquals("Current activity", carEvidenceText(place))
        assertNull(place.copy(evidence = place.evidence.take(1)).supportingEvidence)
    }

    @Test fun missingRequiredAndWrongTypesFailVisibly() {
        val json = fixture()
        json.getJSONArray("now").getJSONObject(0).remove("latitude")
        assertEquals("invalid_contract", assertThrows(RadarContractException::class.java) { RadarParser.parse(json) }.code)
        assertEquals("invalid_contract", assertThrows(RadarContractException::class.java) {
            RadarParser.parse(fixture().put("schema_version", "1"))
        }.code)
        assertEquals("schema_mismatch", assertThrows(RadarContractException::class.java) {
            RadarParser.parse(fixture().put("schema_version", 2))
        }.code)
    }

    @Test fun localExpiryUsesElapsedTimeAndRebootIdentity() {
        val received = ReceivedRadar(RadarParser.parse(fixture()), 1000, 7)
        assertNotNull(received.primary(1000, 7))
        // Phone wall time is deliberately absent from this API.
        assertNull(received.primary(1000+20*60*1000, 7))
        assertNull(received.primary(999, 7))
        assertNull(received.primary(1000, 8))
    }

    @Test fun staleEvidenceAndLocationNeverPermitNavigation() {
        for (field in listOf("evidence_stale", "location_stale")) {
            val received = ReceivedRadar(RadarParser.parse(fixture().put(field, true)), 1000, 7)
            assertNull(received.primary(1000, 7))
        }
    }

    @Test fun futurePlanIsInspectableButNotAnImmediateNavigationAction() {
        val received = ReceivedRadar(RadarParser.parse(fixture()), 1000, 7)
        val future = received.snapshot.plan[1].selected!!
        assertFalse(received.eligible(future, 1000, 7))
    }
}
