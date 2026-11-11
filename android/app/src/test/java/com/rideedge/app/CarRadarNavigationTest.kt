package com.rideedge.app

import android.app.Application
import android.annotation.SuppressLint
import androidx.car.app.CarContext
import androidx.car.app.HandshakeInfo
import androidx.car.app.ScreenManager
import androidx.car.app.OnDoneCallback
import androidx.car.app.model.*
import androidx.car.app.serialization.Bundleable
import androidx.car.app.testing.TestCarContext
import androidx.lifecycle.Lifecycle
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.runCurrent
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
@SuppressLint("RestrictedApi")
class CarRadarNavigationTest {
    private var elapsed = 0L
    private var calls = 0
    private val paths = mutableListOf<String>()
    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("radar-v1.json")!!.bufferedReader().use { JSONObject(it.readText()) }.also {
        it.getJSONObject("origin").put("mode", "device").put("fix_at", it.getString("server_time"))
    }
    private fun TestScope.repo(): RadarRepository = RadarRepository(backgroundScope,
        RadarTransport { path, _ -> calls++; paths += path; fixture() }, RadarLocationSource { error("Rendering requested GPS") }, { elapsed }, { 1 }).also {
        it.store.accept(fixture(), 0); it.setCarConnected(true); it.startCarSession()
    }
    private fun context(api: Int = 6) = TestCarContext.createCarContext(RuntimeEnvironment.getApplication()).also {
        it.updateHandshakeInfo(HandshakeInfo("fixture.host", api))
    }
    private val done = object : OnDoneCallback {
        override fun onSuccess(response: Bundleable?) {}
        override fun onFailure(response: Bundleable) { fail("Host callback failed") }
    }
    private fun rows(template: ListTemplate) = template.singleList!!.items.map { it as Row }
    private fun tabRows(template: TabTemplate) = rows(template.tabContents.template as ListTemplate)

    @Test fun tabsExposePhoneSectionsWithoutMapOrRenderSideEffects() = runTest {
        val repo = repo(); val screen = RadarCarHome(context(), repo)
        runCurrent()
        val beforeRender = calls
        val now = screen.onGetTemplate() as TabTemplate
        assertEquals(listOf("Now", "Nearby", "Plan"), now.tabs.map { it.title.toString() })
        assertEquals(repo.store.primary()!!.name, tabRows(now).first().texts.first().toString())
        now.tabCallbackDelegate.sendTabSelected("NEARBY", done)
        val nearby = screen.onGetTemplate() as TabTemplate
        assertEquals("NEARBY", nearby.activeTabContentId)
        assertEquals(repo.state.value.received!!.snapshot.nearby.first().name, tabRows(nearby).first().texts.first().toString())
        nearby.tabCallbackDelegate.sendTabSelected("PLAN", done)
        val plan = screen.onGetTemplate() as TabTemplate
        assertEquals("PLAN", plan.activeTabContentId)
        assertEquals(repo.state.value.received!!.snapshot.plan[0].selected!!.name, tabRows(plan)[0].texts[0].toString())
        assertEquals(6, tabRows(plan).size)
        runCurrent()
        assertEquals(beforeRender, calls)
        repo.close()
    }

    @Test fun apiThreeAndFiveHaveMenuAndUsableSections() = runTest {
        val repo = repo()
        for (api in listOf(3,5)) {
            val context = context(api)
            assertEquals(listOf("Now", "Nearby", "Plan"), rows(RadarCarHome(context, repo).onGetTemplate() as ListTemplate).map { it.title.toString() })
            for (tab in listOf("NOW", "NEARBY", "PLAN")) assertEquals(6, rows(RadarCarHome(context, repo, tab).onGetTemplate() as ListTemplate).size)
        }
        repo.close()
    }

    @Test fun legacyPlanDrillDownAndBackStayWithinFiveScreens() = runTest {
        val repo = repo(); val context = context(3)
        context.lifecycleOwner.registry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        val manager = context.getCarService(ScreenManager::class.java)
        manager.push(RadarCarHome(context, repo))
        rows(manager.top.onGetTemplate() as ListTemplate)[2].onClickDelegate!!.sendClick(done) // Plan
        rows(manager.top.onGetTemplate() as ListTemplate)[3].onClickDelegate!!.sendClick(done) // Later hours
        rows(manager.top.onGetTemplate() as ListTemplate)[0].onClickDelegate!!.sendClick(done) // Hour 4
        (manager.top.onGetTemplate() as PaneTemplate).pane.actions.first().onClickDelegate!!.sendClick(done) // Alternatives
        assertEquals(5, manager.stackSize)
        rows(manager.top.onGetTemplate() as ListTemplate)[0].onClickDelegate!!.sendClick(done)
        assertEquals(5, manager.stackSize)
        assertTrue(manager.top is RadarCarPlace)
        assertTrue((manager.top.onGetTemplate() as PaneTemplate).pane.actions.isEmpty())
        manager.pop()
        assertTrue(manager.top is RadarCarPlanWindow)
        manager.pop()
        assertTrue(manager.top is RadarCarLaterPlan)
        repo.close()
    }

    @Test fun newRevisionUpdatesNamesButPreservesRootStructure() = runTest {
        val repo = repo(); val screen = RadarCarHome(context(), repo)
        val first = tabRows(screen.onGetTemplate() as TabTemplate)
        val update = fixture().put("decision_revision", "new-review")
        update.getJSONArray("now").getJSONObject(0).put("name", "Updated recommendation")
        repo.store.accept(update, 0)
        val second = tabRows(screen.onGetTemplate() as TabTemplate)
        assertEquals(first.map { it.title.toString() }, second.map { it.title.toString() })
        assertEquals("Updated recommendation", second[0].texts[0].toString())
        assertTrue(second.any { it.title.toString() == "Refresh recommendations" && it.onClickDelegate != null })
        assertEquals(0, calls)
        repo.close()
    }

    @Test fun visibleRefreshRequestsOneSharedReviewForRepeatedTaps() = runTest {
        val repo = repo(); runCurrent()
        val screen = RadarCarHome(context(), repo)
        val refresh = tabRows(screen.onGetTemplate() as TabTemplate).first { it.title.toString() == "Refresh recommendations" }
        refresh.onClickDelegate!!.sendClick(done)
        refresh.onClickDelegate!!.sendClick(done)
        runCurrent()
        assertEquals(1, paths.count { it == "/refresh" })
        repo.close()
    }

    @Test fun capturedNavigationRevalidatesExpiryAndSession() = runTest {
        val repo = repo(); val context = context(); val place = repo.store.primary()!!
        val screen = RadarCarPlace(context, repo, place.id)
        val action = (screen.onGetTemplate() as PaneTemplate).pane.actions.first { it.title.toString() == "Navigate" }
        action.onClickDelegate!!.sendClick(done)
        assertEquals("geo:${place.latitude},${place.longitude}", context.startCarAppIntents.single().data.toString())
        elapsed = 21*60*1000L
        action.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        assertFalse((screen.onGetTemplate() as PaneTemplate).pane.actions.any { it.title.toString() == "Navigate" })
        repo.endCarSession()
        assertTrue(screen.onGetTemplate() is MessageTemplate)
        action.onClickDelegate!!.sendClick(done)
        assertEquals(1, context.startCarAppIntents.size)
        repo.close()
    }

    @Test fun explorationAndFuturePlanCannotNavigateEvenWhenIdMatchesCurrent() = runTest {
        val repo = repo(); val context = context(); val place = repo.store.primary()!!
        for (label in listOf("Exploration", "Future plan")) {
            val template = RadarCarPlace(context, repo, place.id, place, true, label).onGetTemplate() as PaneTemplate
            assertEquals(listOf("Evidence"), template.pane.actions.map { it.title.toString() })
        }
        repo.close()
    }

    @Test fun previewActionNeverLaunchesNavigation() = runTest {
        val repo = repo(); val context = context()
        val screen = RadarCarPlace(context, repo, repo.store.primary()!!.id, preview = true)
        val action = (screen.onGetTemplate() as PaneTemplate).pane.actions.first { it.title.toString() == "Preview only" }
        action.onClickDelegate!!.sendClick(done)
        assertTrue(context.startCarAppIntents.isEmpty())
        assertTrue((screen.onGetTemplate() as PaneTemplate).pane.rows.any { row -> row.texts.any { it.toString().contains("navigation disabled") } })
        repo.close()
    }

    @Test fun selectedAreaAndUnauthorizedStateWithholdNavigation() = runTest {
        val repo = repo(); val place = repo.store.primary()!!
        val data = fixture(); data.getJSONObject("origin").put("mode", "selected_area")
        repo.store.accept(data, 0)
        val context = context(); val screen = RadarCarPlace(context, repo, place.id)
        assertFalse((screen.onGetTemplate() as PaneTemplate).pane.actions.any { it.title.toString() == "Navigate" })
        repo.store.accessRequired(0)
        assertTrue(screen.onGetTemplate() is MessageTemplate)
        assertTrue(RadarCarHome(context, repo).onGetTemplate() is MessageTemplate)
        repo.close()
    }

    @Test fun allSixPlanHoursAndAlternativesUseSharedSnapshot() = runTest {
        val repo = repo(); val context = context(); val data = repo.state.value.received!!.snapshot
        val later = rows(RadarCarLaterPlan(context, repo).onGetTemplate() as ListTemplate)
        assertEquals(data.plan.drop(3).map { it.selected?.name ?: "No supported option" }, later.take(3).map { it.texts[0].toString() })
        data.plan.forEach { slot ->
            val pane = (RadarCarPlanWindow(context, repo, slot.startsAt).onGetTemplate() as PaneTemplate).pane
            assertFalse(pane.actions.any { it.title.toString() == "Navigate" })
            assertEquals(slot.selected?.name ?: "No supported option", pane.rows[0].texts[0].toString())
        }
        assertEquals(6, rows(RadarCarPlanComparison(context, repo).onGetTemplate() as ListTemplate).size)
        assertEquals(0, calls)
        repo.close()
    }

    @Test fun optionalMapHasNumberedMarkersAndVisibleRefreshOnModernHosts() = runTest {
        val repo = repo(); val template = RadarCarList(context(), repo).onGetTemplate() as PlaceListMapTemplate
        val places = template.itemList!!.items.map { it as Row }.filter { it.metadata?.place != null }
        assertTrue(places.isNotEmpty())
        assertEquals(places.indices.map { (it+1).toString() }, places.map { it.metadata!!.place!!.marker!!.label!!.toString() })
        assertEquals("Refresh", template.actionStrip!!.actions.single().title.toString())
        repo.close()
    }

    @Test fun mapHomeOpensNearbyAndNowReturnsToMap() = runTest {
        val repo = repo(); val context = context()
        context.lifecycleOwner.registry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        val manager = context.getCarService(ScreenManager::class.java)
        manager.push(RadarCarList(context, repo, isHome = true))
        val map = manager.top.onGetTemplate() as PlaceListMapTemplate
        assertEquals(Action.APP_ICON, map.headerAction)
        assertEquals(listOf("Nearby", "Plan", "More", "Refresh"), map.actionStrip!!.actions.map { it.title.toString() })
        map.actionStrip!!.actions[0].onClickDelegate!!.sendClick(done)
        val nearby = manager.top.onGetTemplate() as TabTemplate
        assertEquals("NEARBY", nearby.activeTabContentId)
        nearby.tabCallbackDelegate.sendTabSelected("NOW", done)
        assertEquals(1, manager.stackSize)
        assertTrue(manager.top.onGetTemplate() is PlaceListMapTemplate)
        map.actionStrip!!.actions[2].onClickDelegate!!.sendClick(done)
        val more = manager.top.onGetTemplate() as ListTemplate
        assertEquals(Action.BACK, more.headerAction)
        rows(more).first { it.title.toString() == "View on map" }.onClickDelegate!!.sendClick(done)
        assertEquals(1, manager.stackSize)
        repo.close()
    }

    @Test fun emptyMapRetainsRefreshAndSectionAccess() = runTest {
        val repo = repo()
        repo.store.accept(fixture().put("now", org.json.JSONArray()).put("further", org.json.JSONArray()), 0)
        val map = RadarCarList(context(), repo, isHome = true).onGetTemplate() as PlaceListMapTemplate
        val slots = map.itemList!!.items.map { it as Row }
        assertTrue(slots.isNotEmpty())
        assertTrue(slots.all { it.metadata?.place == null && it.isBrowsable })
        assertTrue(slots.first().texts.first().toString().contains("No supported immediate move"))
        assertFalse(slots.any { it.texts.first().toString() == "No eligible destination" })
        assertEquals(4, map.actionStrip!!.actions.size)
        repo.close()
    }

    @Test fun mapFollowsChangedReviewWithoutRetainingOldDestinationOrChangingStructure() = runTest {
        val repo = repo(); val screen = RadarCarList(context(), repo)
        val before = (screen.onGetTemplate() as PlaceListMapTemplate).itemList!!.items.map { it as Row }
        val update = fixture().put("decision_revision", "new-map-review")
        val first = update.getJSONArray("now").getJSONObject(0)
        first.put("id", "new-destination").put("name", "New current destination")
        update.getJSONArray("plan").getJSONObject(0)
            .put("selected_id", "new-destination").put("options", org.json.JSONArray().put(JSONObject(first.toString())))
        assertTrue(repo.store.accept(update, 0))
        val after = (screen.onGetTemplate() as PlaceListMapTemplate).itemList!!.items.map { it as Row }
        assertEquals(before.map { it.title.toString() }, after.map { it.title.toString() })
        assertEquals(repo.store.primary()!!.name, after.first().texts.first().toString())
        assertEquals("New current destination", after.first().texts.first().toString())
        repo.store.accept(fixture().put("now", org.json.JSONArray()).put("further", org.json.JSONArray()), 0)
        val empty = (screen.onGetTemplate() as PlaceListMapTemplate).itemList!!.items.map { it as Row }
        assertEquals(before.map { it.title.toString() }, empty.map { it.title.toString() })
        assertTrue(empty.all { it.metadata?.place == null })
        assertEquals(0, calls)
        repo.close()
    }

    @Test fun currentPositionRequiresPermissionAndIsDisabledInPreview() = runTest {
        val app = RuntimeEnvironment.getApplication()
        val shadow = org.robolectric.Shadows.shadowOf(app)
        shadow.denyPermissions(android.Manifest.permission.ACCESS_FINE_LOCATION, android.Manifest.permission.ACCESS_COARSE_LOCATION)
        val context = context()
        assertFalse(carMapLocationEnabled(context, preview = false))
        shadow.grantPermissions(android.Manifest.permission.ACCESS_FINE_LOCATION)
        assertTrue(carMapLocationEnabled(context, preview = false))
        assertFalse(carMapLocationEnabled(context, preview = true))
    }

    @Test fun mapAnchorUsesOnlyRecentDeviceFixAndNeverPreviewOrExploration() = runTest {
        val repo = repo()
        assertNotNull(carMapOrigin(repo, preview = false))
        assertNull(carMapOrigin(repo, preview = true))
        elapsed = 61000
        assertNull(carMapOrigin(repo, preview = false))
        elapsed = 0
        val selectedArea = fixture()
        selectedArea.getJSONObject("origin").put("mode", "selected_area")
        repo.store.accept(selectedArea, 0)
        assertNull(carMapOrigin(repo, preview = false))
        repo.store.accept(fixture().put("location_stale", true), 0)
        assertNull(carMapOrigin(repo, preview = false))
        repo.close()
    }

    @Test fun missingLocationAndEndedSessionGateEveryMainSection() = runTest {
        val repo = repo(); val context = context()
        repo.store.beginOriginChange()
        assertTrue(RadarCarHome(context, repo).onGetTemplate() is MessageTemplate)
        assertTrue(RadarCarPlaces(context, repo, CarPlaceGroup.NEARBY).onGetTemplate() is MessageTemplate)
        repo.endCarSession()
        assertTrue(RadarCarLaterPlan(context, repo).onGetTemplate() is MessageTemplate)
        assertTrue(RadarCarReports(context, repo).onGetTemplate() is MessageTemplate)
        repo.close()
    }

    @Test fun retainedReceiptAgesAndDoesNotBorrowNewQwenStatus() = runTest {
        val repo = repo()
        val retained = repo.state.value.received!!
        val previousQwen = retained.snapshot.qwen.state
        val next = fixture().put("decision_revision", "newer-review")
        next.getJSONObject("qwen").put("state", "ready")
        repo.store.accept(next, 0)
        val expired = carReceiptStatus(retained, 21*60*1000L)
        assertTrue(expired.contains("expired"))
        if (previousQwen != "ready") assertTrue(expired.contains("Qwen $previousQwen"))
        assertTrue(carReceiptStatus(retained.copy(receivedElapsedMs = 100), 0).contains("clock unavailable"))
        assertTrue(carReceiptStatus(null, 0).contains("time unavailable"))
        repo.close()
    }

    @Test fun responseBetweenClockTicksDoesNotReportClockFailure() = runTest {
        val repo = repo()
        elapsed = 125L
        repo.store.accept(fixture(), 0)
        assertEquals(0L, repo.clock.value)
        assertFalse(carReviewStatus(repo).contains("clock unavailable"))
        assertTrue(carReviewStatus(repo).contains("0 min old"))
        repo.close()
    }

    @Test fun evidenceScreenKeepsOriginalReceiptAfterReviewReplacement() = runTest {
        val repo = repo(); val context = context()
        val retained = repo.state.value.received!!
        val screen = RadarCarEvidence(context, repo, repo.store.primary()!!, retained, "Saved evidence")
        val replacement = fixture().put("decision_revision", "newer-review")
        replacement.getJSONObject("qwen").put("state", "ready")
        repo.store.accept(replacement, 0)
        val status = rows(screen.onGetTemplate() as ListTemplate)[4].texts[0].toString()
        assertTrue(status.contains(carReceiptStatus(retained, 0)))
        assertTrue(status.startsWith("Saved evidence"))
        assertEquals(0, calls)
        repo.close()
    }
}
