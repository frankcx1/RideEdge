package com.rideedge.app

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.Locale

@Composable internal fun EdgeHeading(text: String, modifier: Modifier = Modifier, size: Int = 24) {
    Text(text, modifier.semantics { heading() }, style = Edge.Heading.copy(fontSize = size.sp))
}

@Composable internal fun EdgeMeta(text: String, modifier: Modifier = Modifier, color: Color = Edge.Soft) {
    Text(text, modifier, style = Edge.Meta, color = color)
}

@Composable internal fun EdgePanel(modifier: Modifier = Modifier, cap: Color? = null, dashed: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().background(Edge.Card).then(if (dashed) Modifier.drawBehind {
        drawRect(Edge.Ink, style = Stroke(1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))))
    } else Modifier.border(1.dp, Edge.Rule))) {
        if (cap != null) Spacer(Modifier.fillMaxWidth().height(3.dp).background(cap))
        Column(Modifier.padding(horizontal = 18.dp, vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
    }
}

@Composable internal fun EdgeCaveat(text: String, modifier: Modifier = Modifier) {
    Text(text, modifier.fillMaxWidth().background(Edge.Paper).drawBehind {
        drawRect(Edge.Soft, style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))))
    }.padding(horizontal = 12.dp, vertical = 10.dp), style = Edge.Meta)
}

internal enum class EdgeButtonKind { Primary, Secondary, Outline, Link }

@Composable internal fun EdgeButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier,
                                    enabled: Boolean = true, kind: EdgeButtonKind = EdgeButtonKind.Secondary) {
    val interactions = remember { MutableInteractionSource() }
    val pressed by interactions.collectIsPressedAsState()
    val focused by interactions.collectIsFocusedAsState()
    val accent = when (kind) { EdgeButtonKind.Primary -> Edge.Orange; EdgeButtonKind.Outline -> Edge.Ink; else -> Edge.Blue }
    // Compose's animation clock honors the platform animator duration scale, including zero.
    val fill by animateColorAsState(when {
        !enabled -> Edge.Rule
        kind == EdgeButtonKind.Primary -> if (pressed) Edge.Pressed else Edge.Orange
        pressed && kind != EdgeButtonKind.Link -> accent
        else -> Color.Transparent
    }, tween(150), label = "button color")
    val textColor = when {
        !enabled -> Edge.Soft
        kind == EdgeButtonKind.Primary || (pressed && kind != EdgeButtonKind.Link) -> Edge.Paper
        pressed -> Edge.Orange
        else -> accent
    }
    Box(modifier.defaultMinSize(minWidth = 48.dp, minHeight = 48.dp).then(if (focused) Modifier.border(3.dp, Edge.Blue, RoundedCornerShape(4.dp)) else Modifier)
        .clickable(interactionSource = interactions, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
        .padding(vertical = 5.dp), contentAlignment = Alignment.Center) {
        Box(Modifier.background(fill, RoundedCornerShape(4.dp))
            .then(if (kind != EdgeButtonKind.Link) Modifier.border(1.dp, if (enabled) accent else Edge.Rule, RoundedCornerShape(4.dp)) else Modifier)
            .padding(horizontal = if (kind == EdgeButtonKind.Link) 2.dp else 12.dp, vertical = 9.dp)) {
            Text(text.uppercase(Locale.US), style = Edge.Meta.copy(fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold, letterSpacing = .4.sp), color = textColor)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable internal fun EdgeActions(content: @Composable FlowRowScope.() -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(0.dp), content = content)
}

@Composable internal fun EdgeTabBar(selected: Int, onSelect: (Int) -> Unit) {
    Column(Modifier.background(Edge.Paper).navigationBarsPadding()) {
        HorizontalDivider(thickness = 2.dp, color = Edge.Ink)
        Row(Modifier.fillMaxWidth().selectableGroup()) {
            listOf("Now", "Nearby", "Plan").forEachIndexed { index, title ->
                Box(Modifier.weight(1f).heightIn(min = 56.dp)
                    .background(if (selected == index) Edge.Ink else Edge.Paper).border(.5.dp, Edge.Rule)
                    .edgeSelectable(selected == index, Role.Tab) { onSelect(index) }
                    .padding(horizontal = 8.dp, vertical = 18.dp), contentAlignment = Alignment.Center) {
                    Text(title.uppercase(Locale.US), style = Edge.Meta.copy(letterSpacing = 1.4.sp,
                        fontWeight = if (selected == index) FontWeight.SemiBold else FontWeight.Normal), color = if (selected == index) Edge.Paper else Edge.Soft)
                }
            }
        }
    }
}

@Composable internal fun Modifier.edgeSelectable(selected: Boolean, role: Role, onClick: () -> Unit): Modifier {
    val interactions = remember { MutableInteractionSource() }
    val focused by interactions.collectIsFocusedAsState()
    return this.then(if (focused) Modifier.border(3.dp, Edge.Blue) else Modifier)
        .selectable(selected, interactionSource = interactions, indication = null, role = role, onClick = onClick)
}

/** A drawing extent only. Callers retain the actual displayed number and its basis. */
@Composable internal fun EdgeDataBar(fraction: Float, modifier: Modifier = Modifier, color: Color = Edge.Ink) {
    Box(modifier.fillMaxWidth().height(6.dp).border(1.dp, Edge.Ink)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0f, 1f)).background(color))
    }
}
