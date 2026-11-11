package com.rideedge.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal fun seaClock(at: Instant): String = DateTimeFormatter.ofPattern("h:mm a z", Locale.US)
    .withZone(ZoneId.of("America/Los_Angeles")).format(at)

internal fun seaRange(start: Instant, end: Instant): String {
    val zone = ZoneId.of("America/Los_Angeles")
    val from = start.atZone(zone)
    val to = end.atZone(zone)
    if (from.offset != to.offset) return "${seaClock(start)} – ${seaClock(end)}"
    val sameHalfDay = from.hour / 12 == to.hour / 12
    return "${DateTimeFormatter.ofPattern(if (sameHalfDay) "h:mm" else "h:mm a", Locale.US).format(from)} – ${seaClock(end)}"
}

internal fun LazyListScope.seatacReportContent(receipt: SeaTacReceipt, elapsed: Long, bootId: Int) {
    val report = receipt.report
    val hours = receipt.remaining(elapsed, bootId)
    val peak = receipt.peak(elapsed, bootId)
    val maxCount = hours.filter { receipt.usable(it, elapsed, bootId) }.mapNotNull { it.estimated }.maxOrNull()?.coerceAtLeast(1) ?: 1
    item {
        EdgePanel(cap = if (peak != null) Edge.Orange else Edge.Soft) {
            Text(if (peak != null) "STRONGEST AVAILABLE WINDOW" else "NO CURRENT PEAK IDENTIFIED", style = Edge.Eyebrow, color = Edge.Pressed)
            if (peak != null) Text(seaRange(peak.startsAt, peak.endsAt), style = Edge.Meta.copy(fontSize = 27.sp, lineHeight = 34.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink)
            Text(if (peak != null) "Most returned or estimated arrivals in the usable windows. Missing pages or unavailable hours can change the apparent peak."
                else "Empty, expired or unavailable evidence does not identify a best time to go.", color = RadarMuted, fontSize = 13.sp)
            EdgeMeta("Retrieved ${report.fetchedAt?.let(::seaClock) ?: "unknown"} · state at retrieval: ${report.state}", color = RadarMuted)
            EdgeCaveat("Queue wait and rematches are unknown. This is airport activity context, not an instruction to join the queue.")
            if (report.refreshing) Text("A refresh is already running. Reload shortly to inspect its result.", color = RadarMint)
        }
    }
    item { EdgeMeta("Bars share a scale of 0–$maxCount arrivals across usable windows. Partial windows are not full-hour rates.") }
    items(hours, key = { it.startsAt.toString() }) { hour ->
        val usable = receipt.usable(hour, elapsed, bootId)
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            HorizontalDivider(color = Edge.Rule)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(seaRange(hour.startsAt, hour.endsAt), Modifier.weight(1f), style = Edge.Meta.copy(fontSize = 13.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink)
                Text(if (!usable) "—" else "${if (hour.extrapolated) "~" else ""}${hour.estimated}",
                    style = Edge.Meta.copy(fontSize = 23.sp, fontWeight = FontWeight.SemiBold), color = if (hour == peak) Edge.Orange else Edge.Ink)
            }
            if (hour == peak) EdgeMeta("MOST AVAILABLE ARRIVALS", color = Edge.Orange)
            Text(when {
                !usable -> "Unavailable or stale · saved details only"
                hour.extrapolated -> "~${hour.estimated} arrivals estimated · ${hour.sampled} counted"
                hour.coverage == "partial_page" -> "${hour.sampled} arrivals counted · more may exist"
                else -> "${hour.sampled} arrivals in the returned page"
            }, style = Edge.Meta, color = if (usable) Edge.Ink else Edge.Soft)
            if (usable) EdgeDataBar((hour.estimated ?: 0).toFloat()/maxCount, Modifier.height(10.dp), color = if (hour == peak) Edge.Orange else Edge.Ink)
            if (hour.partialHour) EdgeCaveat("Partial window: ${String.format(Locale.US, "%.1f", hour.windowMinutes)} minutes. Count is not a full-hour rate.")
            EdgeMeta(hour.timingCounts.entries.joinToString(" · ") { "${it.value} ${it.key.replace('_', ' ')}" }.ifBlank { "Timing basis unavailable" }, color = RadarMuted)
            var details by rememberSaveable(hour.startsAt.toString()) { mutableStateOf(false) }
            EdgeButton(if (details) "Less detail" else "Flights, coverage and timing", { details = !details }, kind = EdgeButtonKind.Link)
            if (details) {
                EdgeMeta("Retrieved ${hour.fetchedAt?.let(::seaClock) ?: "unknown"} · ${hour.mode} · ${hour.coverage.replace('_', ' ')}", color = RadarMuted)
                EdgeMeta("Returned records: ${hour.returned ?: "unknown"} · counted: ${hour.sampled ?: "unknown"}", color = RadarMuted)
                EdgeMeta(hour.estimateMethod, color = RadarMuted)
                hour.excluded.filterValues { it > 0 }.takeIf { it.isNotEmpty() }?.let { excluded ->
                    EdgeMeta("Excluded: " + excluded.entries.joinToString(" · ") { "${it.value} ${it.key.replace('_', ' ')}" }, color = RadarAmber)
                }
                if (usable && hour.readinessStart != null && hour.readinessEnd != null) {
                    EdgeMeta("Illustrative passenger-ready window: ${seaClock(hour.readinessStart)} – ${seaClock(hour.readinessEnd)}", color = RadarMint)
                    EdgeMeta(hour.readinessBasis, color = RadarMuted)
                }
                EdgeMeta("${hour.longHaul ?: "Unknown"} long-haul origin matches in the sample; a limited airport-code heuristic.", color = RadarMuted)
                hour.flights.forEach { flight -> EdgeMeta("${flight.ident} · ${flight.origin} · ${seaClock(flight.arrivalAt)} · ${flight.timeBasis.replace('_', ' ')} (${flight.timeField})", color = RadarMuted) }
            }
        }
    }
    item {
        RadarPanel {
            EdgeHeading("Coverage and request usage.", size = 21)
            EdgeMeta(report.coverageNote, color = RadarMuted)
            EdgeMeta(report.timingNote, color = RadarMuted)
            EdgeMeta("Last refresh: ${report.attempts ?: "unknown"} HTTP attempts · ${report.cacheHits ?: "unknown"} cache hits · ${report.failures ?: "unknown"} failures", color = RadarMuted)
            EdgeMeta("Billed cost and remaining credits: unknown. Opening this report does not request new provider data.", color = RadarMuted)
        }
    }
}
