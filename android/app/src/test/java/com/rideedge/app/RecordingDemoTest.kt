package com.rideedge.app

import android.app.Application
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class RecordingDemoTest {
    @Test fun capturedSessionCannotFabricateRefreshQuestionsOrExploration() {
        if (BuildConfig.BUILD_TYPE != "preview") return
        val context = RuntimeEnvironment.getApplication() as Application
        val fixture = javaClass.classLoader!!.getResourceAsStream("recording-demo.json")!!.bufferedReader().use { JSONObject(it.readText()) }
        val stage = fixture.getJSONArray("stages").getJSONObject(0)
        stage.put("source_details", JSONObject().put("besttime_busyness", JSONObject().put("records", org.json.JSONArray())))
        val captured = JSONObject().put("kind", "captured_session").put("schema_version", 1).put("capture_id", "test-capture")
            .put("stages", org.json.JSONArray().put(stage)).put("cues", org.json.JSONArray().put(JSONObject()
                .put("scene", 0).put("shot", "now").put("title", "Actual evaluation").put("seconds", 20)))
        val file = java.io.File(context.filesDir, "captured-session.json")
        try {
            file.writeText(captured.toString())
            val demo = RecordingDemo(context)
            assertTrue(demo.isCaptured)
            assertEquals(1, demo.cues.size)
            val before = demo.request(0, "").toString()
            demo.request(0, "/refresh")
            assertEquals(before, demo.request(0, "").toString())
            for (path in listOf("/ask", "/ask/jobs/anything", "/preview")) {
                assertTrue(runCatching { demo.request(0, path) }.isFailure)
            }
            assertEquals(0, demo.report(0, "/api/feeds/besttime_busyness/detail").getJSONArray("records").length())
        } finally { file.delete() }
    }
    @Test fun allRecordingScenesHaveConsistentPhoneCarAndAirportContracts() {
        val data = javaClass.classLoader!!.getResourceAsStream("recording-demo.json")!!.bufferedReader().use { JSONObject(it.readText()) }
        val scenes = data.getJSONArray("stages")
        val winners = mutableSetOf<String>()
        for (i in 0 until scenes.length()) {
            val scene = scenes.getJSONObject(i)
            val radar = RadarParser.parse(scene.getJSONObject("radar"))
            winners += radar.now.first().id
            assertEquals(6, radar.plan.size)
            assertEquals(23, radar.feeds.size)
            assertEquals("demo", radar.qwen.state)
            assertTrue(radar.now.first().qwenReason!!.isNotBlank())
            assertTrue(scene.getJSONObject("radar").getBoolean("synthetic"))
            assertTrue(radar.now.all { it.radiusMiles <= 5 })
            val store = RadarStateStore({ 100000L }, { 1 })
            assertTrue(store.accept(scene.getJSONObject("radar"), 0))
            assertNotNull(store.navigationTarget(radar.now.first().id))
            val airport = SeaTacParser.parse(scene.getJSONObject("seatac"))
            assertEquals(6, airport.hours.size)
        }
        assertEquals(8, scenes.length())
        assertEquals(8, winners.size)
    }

    @Test fun previewRecordingTransportIsDeterministicAndExplorationCannotNavigate() {
        if (BuildConfig.BUILD_TYPE != "preview") return
        val demo = RecordingDemo(RuntimeEnvironment.getApplication())
        assertEquals(demo.request(0, "").toString(), demo.request(0, "/context").toString())
        val explored = RadarParser.parse(demo.request(0, "/preview", JSONObject().put("area", "Capitol Hill")))
        assertTrue(explored.origin.label.contains("Capitol Hill"))
        assertTrue(explored.nearby.none { it.actionable })
        assertEquals("ready", demo.request(0, "/ask/jobs/scripted-demo-0").getString("state"))
        assertTrue(demo.report(1, "/api/feeds/besttime_busyness/detail").getBoolean("synthetic"))
        val before = demo.request(0, "").getString("decision_revision")
        demo.request(0, "/refresh")
        assertNotEquals(before, demo.request(0, "").getString("decision_revision"))
    }
}
