package com.rideedge.app

import androidx.car.app.CarContext
import androidx.car.app.HandshakeInfo
import androidx.car.app.OnDoneCallback
import androidx.car.app.model.*
import androidx.car.app.serialization.Bundleable
import androidx.car.app.testing.TestCarContext
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = RideEdgeApplication::class)
@OptIn(ExperimentalCoroutinesApi::class)
@android.annotation.SuppressLint("RestrictedApi")
class RecordingCarNavigationTest {
    private val done = object : OnDoneCallback {
        override fun onSuccess(response: Bundleable?) {}
        override fun onFailure(response: Bundleable) { fail("Car host callback failed") }
    }

    @Test fun recordingNavigationUsesSelectedPublicReferenceAndRechecksSceneAndExpiry() = runTest {
        if (BuildConfig.BUILD_TYPE != "preview") return@runTest
        val app = RuntimeEnvironment.getApplication() as RideEdgeApplication
        app.previewScenario = "recording"
        var elapsed = 0L
        val fixture = app.recordingDemo.request(0, "")
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture },
            RadarLocationSource { error("Demo must not request GPS") }, { elapsed }, { 1 })
        repo.store.accept(fixture, 0); repo.setCarConnected(true); repo.startCarSession()
        val context = TestCarContext.createCarContext(app).also { it.updateHandshakeInfo(HandshakeInfo("fixture.host", 6)) }
        val selected = repo.store.primary()!!
        val screen = RadarCarPlace(context, repo, selected.id)
        assertEquals("Now", (RadarCarList(context, repo, true).onGetTemplate() as PlaceListMapTemplate).title.toString())
        val action = (screen.onGetTemplate() as PaneTemplate).pane.actions.first { it.title.toString() == "Navigate" }
        action.onClickDelegate!!.sendClick(done)
        assertEquals(CarContext.ACTION_NAVIGATE, context.startCarAppIntents.single().action)
        assertEquals("geo:${selected.latitude},${selected.longitude}", context.startCarAppIntents.single().data.toString())
        app.recordingStep.value = 1
        action.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        app.recordingStep.value = 0
        elapsed = 21*60*1000L
        action.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        repo.endCarSession()
        action.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        repo.close()
    }

    @Test fun recordingDoesNotEnableNavigationForOtherScenariosOrInspectOnlyPlaces() = runTest {
        if (BuildConfig.BUILD_TYPE != "preview") return@runTest
        val app = RuntimeEnvironment.getApplication() as RideEdgeApplication
        app.previewScenario = "recording"
        val fixture = app.recordingDemo.request(0, "")
        val repo = RadarRepository(backgroundScope, RadarTransport { _, _ -> fixture },
            RadarLocationSource { null }, { 0L }, { 1 })
        repo.store.accept(fixture, 0); repo.setCarConnected(true); repo.startCarSession()
        val context = TestCarContext.createCarContext(app).also { it.updateHandshakeInfo(HandshakeInfo("fixture.host", 6)) }
        val place = repo.store.primary()!!
        val inspected = RadarCarPlace(context, repo, place.id, place, true).onGetTemplate() as PaneTemplate
        assertFalse(inspected.pane.actions.any { it.title.toString() == "Navigate" })
        val screen = RadarCarPlace(context, repo, place.id)
        val captured = (screen.onGetTemplate() as PaneTemplate).pane.actions.first { it.title.toString() == "Navigate" }
        app.previewScenario = "fallback"
        captured.onClickDelegate!!.sendClick(done)
        assertTrue(context.startCarAppIntents.isEmpty())
        assertFalse((screen.onGetTemplate() as PaneTemplate).pane.actions.any { it.title.toString() == "Navigate" })
        repo.close()
    }

    @Test fun bundledDestinationResolverRejectsAlteredCoordinatesNamesAndIds() {
        if (BuildConfig.BUILD_TYPE != "preview") return
        val demo = RecordingDemo(RuntimeEnvironment.getApplication())
        val place = RadarParser.parse(demo.request(0, "")).now.first()
        assertNotNull(demo.navigationTarget(0, place))
        assertNull(demo.navigationTarget(0, place.copy(latitude = 0.0)))
        assertNull(demo.navigationTarget(0, place.copy(name = "Different destination")))
        assertNull(demo.navigationTarget(0, place.copy(id = "untrusted-id")))
        assertNull(demo.navigationTarget(1, place))
    }
}
