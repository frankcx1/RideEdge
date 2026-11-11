package com.rideedge.app

import androidx.car.app.CarContext
import androidx.car.app.model.*
import java.time.Instant

internal class RadarCarLaterPlan(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val plan = repo.state.value.received?.snapshot?.plan.orEmpty()
        return carList("Hours 4–6", (3..5).map { index ->
            val slot = plan.getOrNull(index)
            carRow("Hour ${index+1}", slot?.selected?.name ?: "No supported option",
                slot?.let { "${carTime(it.startsAt)} – ${carTime(it.endsAt)} · ${it.selectionBasis}" },
                slot?.let { { pushScreen(RadarCarPlanWindow(carContext, repo, it.startsAt)) } })
        } + carRow("Re-plan now", carReviewStatus(repo)) { repo.refresh(); invalidate() })
    }
}

internal class RadarCarPlanWindow(context: CarContext, repo: RadarRepository, private val start: Instant) :
    ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val receipt = repo.state.value.received ?: return message("Plan unavailable", "Refresh from Plan.", true)
        val slot = receipt.snapshot.plan.firstOrNull { it.startsAt == start }
            ?: return message("Plan window changed", "Go back to the current plan.", true)
        val now = receipt.snapshot.serverTime.plusMillis((repo.currentElapsedMs() - receipt.receivedElapsedMs).coerceAtLeast(0))
        val phase = when { now < slot.startsAt -> "Future window"; now >= slot.endsAt -> "Past window"; else -> "Current window" }
        val selected = slot.selected
        val pane = Pane.Builder()
            .addRow(carRow("Window and selection", selected?.name ?: "No supported option", "$phase · ${carTime(slot.startsAt)} – ${carTime(slot.endsAt)} · ${slot.selectionBasis}"))
            .addRow(carRow("Reason and timing", selected?.qwenReason ?: selected?.supportingEvidence?.text ?: "No supporting observation available",
                selected?.let { "${it.route.minutes} min ${if (slot.routeReference == "current_origin_reference") "reference from current location" else if (slot == receipt.snapshot.plan.first()) "from starting point" else "from prior area"} · ${it.route.basis}" }))
            .addRow(carRow("Review", carReviewStatus(repo),
                if (slot.repeatArea) "Same area reassessed; compare alternatives. This is not an instruction to wait." else slot.note.ifBlank { "Provisional positioning; reassess after each ride." }))
            .addAction(Action.Builder().setTitle("Alternatives").setOnClickListener {
                pushScreen(RadarCarPlanOptions(carContext, repo, start))
            }.build())
        selected?.let { place -> pane.addAction(Action.Builder().setTitle("Evidence").setOnClickListener {
            pushScreen(RadarCarEvidence(carContext, repo, place, receipt, "Plan · ${carTime(start)}"))
        }.build()) }
        return PaneTemplate.Builder(pane.build()).setTitle("Plan window").setHeaderAction(Action.BACK).build()
    }
}

internal class RadarCarPlanOptions(context: CarContext, repo: RadarRepository, private val start: Instant) :
    ObservingRadarCarScreen(context, repo) {
    private var page = 0
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val receipt = repo.state.value.received
        val slot = receipt?.snapshot?.plan?.firstOrNull { it.startsAt == start }
            ?: return message("Plan window changed", "Go back to the latest plan.", true)
        val options = slot.options.filter { it.id != slot.selectedId && it.reachable }
        page = page.coerceAtMost(((options.size-1)/4).coerceAtLeast(0))
        return carList("Plan alternatives", (0..3).map { index ->
            val p = options.getOrNull(page*4+index)
            carRow("Alternative ${index+1}", p?.name ?: "No other supported, reachable option", p?.strength,
                p?.let { { pushScreen(RadarCarPlace(carContext, repo, it.id, it, true, "Plan · ${carTime(start)} · route from plan origin", retainedReceipt = receipt)) } })
        } + listOf(
            carRow("Previous page", "Page ${page+1}", click = if (page > 0) ({ page--; invalidate() }) else null),
            carRow("Next page", "${options.size} alternatives", click = if ((page+1)*4 < options.size) ({ page++; invalidate() }) else null)
        ))
    }
}

internal class RadarCarPlanComparison(context: CarContext, repo: RadarRepository) : ObservingRadarCarScreen(context, repo) {
    override fun onGetTemplate(): Template {
        carSessionGate(repo)?.let { return message(it.first, it.second, true) }
        val data = repo.state.value.received!!.snapshot
        return carList("Plan comparison", (0..5).map { index ->
            val chosen = data.plan.getOrNull(index)
            val algorithm = data.algorithmPlan.firstOrNull { it.startsAt == chosen?.startsAt }
            carRow("Hour ${index+1}", "${chosen?.selectionBasis ?: "Unavailable"}: ${chosen?.selected?.name ?: "No option"}",
                "Algorithm: ${algorithm?.selected?.name ?: "No option"}", chosen?.let { { pushScreen(RadarCarPlanWindow(carContext, repo, it.startsAt)) } })
        })
    }
}
