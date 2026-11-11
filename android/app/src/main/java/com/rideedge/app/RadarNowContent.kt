package com.rideedge.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.clickable
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal fun edgeTime(time: Instant): String = DateTimeFormatter.ofPattern("h:mm a z", Locale.US)
    .withZone(ZoneId.of("America/Los_Angeles")).format(time)
internal fun edgeNumber(value: Double): String = if (value == value.toLong().toDouble()) value.toLong().toString() else String.format(Locale.US, "%.1f", value)
internal fun edgeDistance(place: RadarPlace): String = String.format(Locale.US, "%.1f mi · %.1f min %s", place.radiusMiles, place.route.minutes,
    if (place.route.basis == "live traffic") "with traffic" else "estimated drive")

internal fun activityCaveat(place: RadarPlace): String {
    val basis = place.busynessBasis.orEmpty()
    return when {
        place.isPositioningFallback -> "Current activity and opening hours are unverified. This commercial area is an option to explore; shorter travel is preferred."
        place.busyness == null -> place.supportingEvidence?.text ?: "No current activity observation is available."
        basis.contains("forecast", true) || basis.contains("typical", true) || basis.contains("weekly", true) ->
            "Typical weekly pattern, not a current crowd observation."
        basis.contains("live", true) -> "Provider-reported activity relative to this venue's own weekly peak. It is not a rider count."
        else -> "Activity basis: ${basis.ifBlank { "unspecified" }}. This is not a rider count."
    }
}

@Composable internal fun RadarConnectionBanner(presentation: RadarConnectionPresentation, contact: Instant?,
                                               busy: Boolean, connect: () -> Unit, settings: () -> Unit) {
    EdgePanel(dashed = true) {
        Text(presentation.title.uppercase(Locale.US), style = Edge.Eyebrow, color = Edge.Pressed)
        Text(presentation.detail, style = Edge.Prose)
        EdgeMeta(listOfNotNull(contact?.let { "Last contact ${edgeTime(it)}" },
            if (presentation.retrying) "Retrying automatically" else null).joinToString(" · ").ifBlank { "No successful contact recorded" })
        EdgeActions {
            EdgeButton(presentation.action, connect, enabled = !busy, kind = EdgeButtonKind.Primary)
            EdgeButton("Connection settings", settings)
        }
    }
}

@Composable internal fun RadarNowHero(place: RadarPlace, saved: Boolean, expired: Boolean,
                                      eligible: Boolean, navigate: () -> Unit, ask: () -> Unit) {
    var expanded by rememberEdgeExpansion("now:${place.id}")
    EdgePanel(cap = if (saved || expired) Edge.Soft else Edge.Orange) {
        val heading = if (place.isPositioningFallback) "Area to consider" else "Best nearby option"
        Text(when { expired -> "$heading · stale"; saved -> "$heading · saved review"; else -> heading }.uppercase(Locale.US),
            style = Edge.Eyebrow, color = if (saved || expired) Edge.Soft else Edge.Pressed)
        EdgeHeading(place.name, size = 34)
        EdgeMeta(edgeDistance(place))
        HorizontalDivider(color = Edge.Rule)
        val value = place.busyness
        if (value != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.clearAndSetSemantics {
                contentDescription = "${edgeNumber(value)} percent of this venue's own weekly peak"
            }) {
                Text("${edgeNumber(value)}%", style = Edge.Meta.copy(fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink)
                Text("OF THIS VENUE'S\nOWN WEEKLY PEAK", Modifier.weight(1f), style = Edge.Meta.copy(letterSpacing = 1.sp))
            }
            if (value > 100) EdgeMeta("Above usual peak")
        } else EdgeMeta(place.strength, color = Edge.Ink)
        EdgeCaveat(activityCaveat(place))
        EdgeActions {
            EdgeButton("Navigate", navigate, enabled = eligible, kind = EdgeButtonKind.Primary)
            EdgeButton(if (expanded) "Less detail" else "Why here?", { expanded = !expanded })
            EdgeButton("Ask Qwen", ask)
        }
        if (!eligible) EdgeMeta("Navigation unavailable. Refresh the review, reconnect or update your location.")
        if (expanded) RadarEvidence(place)
    }
}

@Composable internal fun RadarEvidence(place: RadarPlace) {
    if (place.activityCoverage.isNotBlank()) EdgeCaveat(place.activityCoverage)
    place.qwenReason?.let { Text(it, style = Edge.Prose) }
    EdgeMeta("${place.pinBasis} · ${place.navigationNote}")
    place.evidence.forEach { evidence ->
        HorizontalDivider(color = Edge.Rule)
        EdgeMeta("${evidence.source} · ${evidence.basis}", color = Edge.Blue)
        Text(evidence.text, style = Edge.Prose)
        if (!evidence.arrivalRelevant) EdgeCaveat("Outside the estimated arrival window. Retained for inspection.")
        evidence.startsAt?.let { EdgeMeta("Activity starts ${edgeTime(it)}") }
        evidence.endsAt?.let { EdgeMeta("Activity ends ${edgeTime(it)}") }
        evidence.measurementTime?.let { EdgeMeta("Measured $it") }
        evidence.timingNote?.let { EdgeMeta(it) }
        evidence.fetchedAt?.let { EdgeMeta("Retrieved ${edgeTime(it)}") }
        EdgeMeta("Evidence ${evidence.id}")
    }
}

@Composable internal fun RadarAlternative(place: RadarPlace, navigate: (() -> Unit)?) {
    var expanded by rememberEdgeExpansion("alternative:${place.id}")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        HorizontalDivider(color = Edge.Rule)
        Row(Modifier.fillMaxWidth().heightIn(min = 48.dp)
            .clickable(role = Role.Button, onClickLabel = if (expanded) "Hide evidence" else "Inspect option") { expanded = !expanded }
            .padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f)) {
                EdgeHeading(place.name, size = 17)
                EdgeMeta(edgeDistance(place))
                if (place.isPositioningFallback) EdgeMeta("Area to consider · activity / hours unverified")
            }
            place.busyness?.let { Text("${edgeNumber(it)}%", style = Edge.Meta.copy(fontSize = 18.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink) }
        }
        if (expanded) {
            EdgeCaveat(activityCaveat(place))
            EdgeButton("Navigate", { navigate?.invoke() }, enabled = navigate != null, kind = EdgeButtonKind.Primary)
            RadarEvidence(place)
        }
    }
}
