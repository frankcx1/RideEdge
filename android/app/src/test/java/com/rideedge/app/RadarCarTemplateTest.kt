package com.rideedge.app

import android.app.Application
import android.annotation.SuppressLint
import androidx.car.app.model.MessageTemplate
import androidx.car.app.model.PaneTemplate
import androidx.car.app.model.PlaceListMapTemplate
import androidx.car.app.model.Row
import androidx.car.app.CarContext
import androidx.car.app.HandshakeInfo
import androidx.car.app.OnDoneCallback
import androidx.car.app.serialization.Bundleable
import androidx.car.app.testing.TestCarContext
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@OptIn(ExperimentalCoroutinesApi::class)
class RadarCarTemplateTest {
    private fun fixture(): JSONObject = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }.also {
            it.getJSONObject("origin").put("mode", "device").put("fix_at", it.getString("server_time"))
        }

    @SuppressLint("RestrictedApi") // Establish the fake host's negotiated API in the test harness.
    @Test fun templatesValidateAndRetainSlotStructureAfterExpiry() = runTest {
        var elapsed = 0L
        var calls = 0
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> calls++; fixture() },
            RadarLocationSource { error("Rendering must not request GPS") }, { elapsed }, { 1 })
        val context = TestCarContext.createCarContext(RuntimeEnvironment.getApplication())
        context.updateHandshakeInfo(HandshakeInfo("fixture.host", 3))
        val screen = RadarCarList(context, repo)
        assertTrue(screen.onGetTemplate() is MessageTemplate)
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        val first = screen.onGetTemplate() as PlaceListMapTemplate
        val titles = first.itemList!!.items.map { (it as Row).title.toString() }
        assertFalse(titles.isEmpty())
        context.updateHandshakeInfo(HandshakeInfo("fixture.host", 5))
        assertTrue(screen.onGetTemplate() is PlaceListMapTemplate)
        val id = repo.store.primary()!!.id
        val detail = RadarCarPlace(context, repo, id)
        val action = (detail.onGetTemplate() as PaneTemplate).pane.actions.first { it.title.toString() == "Navigate" }
        val done = object : OnDoneCallback {
            override fun onSuccess(response: Bundleable?) {}
            override fun onFailure(response: Bundleable) { fail("Car action callback failed") }
        }
        action.onClickDelegate!!.sendClick(done)
        assertEquals(CarContext.ACTION_NAVIGATE, context.startCarAppIntents.single().action)
        assertEquals("geo", context.startCarAppIntents.single().data!!.scheme)
        elapsed = 21 * 60 * 1000L
        action.onClickDelegate!!.sendClick(done) // captured action must recheck current eligibility
        assertEquals(1, context.startCarAppIntents.size)
        val expired = screen.onGetTemplate() as PlaceListMapTemplate
        assertEquals(titles, expired.itemList!!.items.map { (it as Row).title.toString() })
        assertTrue(expired.itemList!!.items.all { (it as Row).metadata?.place == null && it.isBrowsable })
        assertFalse(expired.itemList!!.items.any { (it as Row).texts.first().toString() == "No eligible destination" })
        assertTrue((expired.itemList!!.items.first() as Row).texts.first().toString().contains("expired"))
        assertFalse((detail.onGetTemplate() as PaneTemplate).pane.actions.any { it.title.toString() == "Navigate" })
        assertEquals(0, calls)
        repo.close()
    }

    @SuppressLint("RestrictedApi")
    @Test fun nowRowHandsDestinationDirectlyToHostWithoutPushingDetailAndRevalidates() = runTest {
        var elapsed = 0L
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> error("Navigation must not fetch") },
            RadarLocationSource { null }, { elapsed }, { 1 })
        val context = TestCarContext.createCarContext(RuntimeEnvironment.getApplication())
        context.updateHandshakeInfo(HandshakeInfo("fixture.host", 3))
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        val target = repo.store.primary()!!
        val screen = RadarCarList(context, repo, isHome = true)
        val row = (screen.onGetTemplate() as PlaceListMapTemplate).itemList!!.items.first() as Row
        val done = object : OnDoneCallback {
            override fun onSuccess(response: Bundleable?) {}
            override fun onFailure(response: Bundleable) { fail("Callback failed") }
        }
        row.onClickDelegate!!.sendClick(done)
        assertEquals(carNavigationUri(target), context.startCarAppIntents.single().data)
        elapsed = 21*60*1000L
        row.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        repo.close()
    }

    @SuppressLint("RestrictedApi")
    @Test fun explicitRefreshWaitsForNewRevisionBeforeReplacingRows() = runTest {
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture() },
            RadarLocationSource { null }, { 0L }, { 1 })
        val context = TestCarContext.createCarContext(RuntimeEnvironment.getApplication())
        context.updateHandshakeInfo(HandshakeInfo("fixture.host", 3))
        repo.store.accept(fixture(), 0)
        repo.setCarConnected(true); repo.startCarSession()
        val screen = RadarCarList(context, repo)
        val original = screen.onGetTemplate() as PlaceListMapTemplate
        original.actionStrip!!.actions.single().onClickDelegate!!.sendClick(object : OnDoneCallback {
            override fun onSuccess(response: Bundleable?) {}
            override fun onFailure(response: Bundleable) { fail("Refresh callback failed") }
        })
        assertTrue((screen.onGetTemplate() as PlaceListMapTemplate).isLoading)
        val updated = fixture().put("decision_revision", "reviewed-fixture-v2")
        updated.getJSONArray("now").getJSONObject(0).put("name", "Reviewed fixture destination")
        repo.store.accept(updated, 0)
        val refreshed = screen.onGetTemplate() as PlaceListMapTemplate
        assertFalse(refreshed.isLoading)
        assertEquals("Reviewed fixture destination", (refreshed.itemList!!.items.first() as Row).texts.first().toString())
        repo.close()
    }
}
