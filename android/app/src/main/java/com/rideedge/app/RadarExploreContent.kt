package com.rideedge.app

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable internal fun RadarCategoryFilter(selected: String, select: (String) -> Unit) {
    val large = LocalDensity.current.fontScale > 1.15f
    Row(Modifier.fillMaxWidth().then(if (large) Modifier.horizontalScroll(rememberScrollState()) else Modifier).selectableGroup()) {
        listOf("All", "Places", "Events", "Activity", "Areas").forEach { name ->
            Box((if (large) Modifier else Modifier.weight(1f)).heightIn(min = 48.dp)
                .background(if (selected == name) Edge.Ink else Edge.Paper).border(.75.dp, Edge.Blue)
                .edgeSelectable(selected == name, Role.RadioButton) { select(name) }
                .padding(horizontal = 8.dp, vertical = 12.dp), contentAlignment = Alignment.Center) {
                Text(name.uppercase(Locale.US), style = Edge.Meta.copy(fontSize = 10.5.sp,
                    fontWeight = if (selected == name) FontWeight.SemiBold else FontWeight.Normal),
                    color = if (selected == name) Edge.Paper else Edge.Blue)
            }
        }
    }
}

@Composable internal fun RadarPlaceRow(place: RadarPlace, navigate: (() -> Unit)?, distanceLabel: String,
                                       ask: (() -> Unit)? = null) {
    val context = LocalContext.current
    var expanded by rememberEdgeExpansion("place:${place.id}")
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        HorizontalDivider(color = Edge.Rule)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            EdgeHeading(place.name, Modifier.weight(1f), size = 21)
            place.busyness?.let { Text("${edgeNumber(it)}%", style = Edge.Meta.copy(fontSize = 23.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink) }
        }
        EdgeMeta("${edgeDistance(place)} · $distanceLabel · ${place.busynessBasis ?: place.strength}")
        place.busyness?.let {
            EdgeDataBar((it / 100).toFloat())
            if (it > 100) EdgeMeta("Above usual peak")
        }
        EdgeActions {
            if (navigate != null) EdgeButton("Navigate", navigate, kind = EdgeButtonKind.Primary)
            else EdgeButton("View place", {
                if (BuildConfig.BUILD_TYPE != "preview") runCatching {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("geo:${place.latitude},${place.longitude}?q=${place.latitude},${place.longitude}(${Uri.encode(place.name)})")))
                }
            })
            EdgeButton(if (expanded) "Less detail" else "Why here?", { expanded = !expanded })
            if (ask != null) EdgeButton("Ask Qwen", ask)
        }
        if (expanded) {
            EdgeCaveat(activityCaveat(place))
            RadarEvidence(place)
        }
    }
}

internal fun isCurrentInterval(slot: RadarInterval, now: Instant): Boolean = !now.isBefore(slot.startsAt) && now.isBefore(slot.endsAt)

@Composable internal fun RadarTimelineSlot(slot: RadarInterval, first: Boolean, now: Instant) {
    var expanded by rememberEdgeExpansion("plan:${slot.startsAt}")
    val current = isCurrentInterval(slot, now)
    val routeLabel = if (slot.routeReference == "current_origin_reference") "reference from current location" else if (first) "from starting point" else "from prior area"
    val fontScale = LocalDensity.current.fontScale
    val timeFormat = remember { DateTimeFormatter.ofPattern("h:mm a z", Locale.US).withZone(ZoneId.of("America/Los_Angeles")) }
    @Composable fun card() {
        EdgePanel(cap = if (current) Edge.Orange else Edge.Ink) {
            EdgeHeading(slot.selected?.name ?: "No supported option in this window.", size = 21)
            slot.selected?.let { place ->
                EdgeMeta("${edgeNumber(place.route.minutes)} min $routeLabel · ${place.route.basis} · ${place.strength}")
                Text(place.qwenReason ?: place.supportingEvidence?.text ?: "No supported opportunity at the estimated arrival time.", style = Edge.Prose)
            }
            EdgeMeta("Selection: ${slot.selectionBasis}")
            EdgeCaveat(if (slot.repeatArea) "Same area reassessed. Compare alternatives at this time." else "Reassess after your next ride.")
            val alternatives = slot.options.filter { it.id != slot.selectedId && it.reachable }
            EdgeButton("${if (expanded) "Hide" else "Inspect"} alternatives (${alternatives.size})", { expanded = !expanded }, kind = EdgeButtonKind.Link)
            if (expanded) {
                if (slot.note.isNotBlank()) Text(slot.note, style = Edge.Prose)
                slot.selected?.let { RadarEvidence(it) }
                if (alternatives.isEmpty()) Text("No other supported, reachable option in this coverage.", style = Edge.Prose)
                alternatives.forEach { RadarPlaceRow(it, null, routeLabel) }
            }
        }
    }
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        if (fontScale > 1.25f || maxWidth < 340.dp) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                EdgeMeta("${edgeTime(slot.startsAt)} – ${edgeTime(slot.endsAt)}${if (current) " · Current interval" else ""}", color = if (current) Edge.Orange else Edge.Ink)
                card()
            }
        } else Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Column(Modifier.width(64.dp).fillMaxHeight().drawBehind {
                drawLine(Edge.Rule, Offset(size.width, 0f), Offset(size.width, size.height), 1.dp.toPx())
                drawCircle(if (current) Edge.Orange else Edge.Ink, 3.5.dp.toPx(), Offset(size.width, 22.dp.toPx()))
            }.padding(top = 12.dp, end = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(timeFormat.format(slot.startsAt), Modifier.fillMaxWidth(), style = Edge.Meta.copy(fontWeight = FontWeight.SemiBold), color = Edge.Ink, textAlign = TextAlign.End)
                Text(timeFormat.format(slot.endsAt), Modifier.fillMaxWidth(), style = Edge.Meta, textAlign = TextAlign.End)
            }
            Box(Modifier.weight(1f)) { card() }
        }
    }
}
