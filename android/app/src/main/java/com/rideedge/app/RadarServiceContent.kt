package com.rideedge.app

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.util.Locale

@Composable internal fun RadarServiceGrid(health: JSONObject) {
    val collector = health.optJSONObject("collector")
    val values = listOf(
        "Backend" to health.optString("backend").ifBlank { "unknown" },
        "Collector" to if (collector == null || collector.isNull("running")) "unknown" else if (collector.optBoolean("running")) "running" else "stopped",
        "Local Qwen" to when {
            health.optBoolean("qwen_loaded") -> "loaded"
            health.optBoolean("model_server_reachable") -> "loads on demand"
            health.isNull("model_server_reachable") -> "unknown"
            else -> "unavailable"
        })
    @Composable fun cell(label: String, value: String, modifier: Modifier = Modifier) {
        Column(modifier.drawBehind { drawLine(Edge.Rule, Offset.Zero, Offset(0f, size.height), 1.dp.toPx()) }
            .padding(start = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(label.uppercase(Locale.US), style = Edge.Meta.copy(fontSize = 9.6.sp, letterSpacing = 1.sp))
            Text(value, style = Edge.Meta.copy(fontSize = 17.sp, lineHeight = 23.sp, fontWeight = FontWeight.SemiBold), color = Edge.Ink)
        }
    }
    if (LocalDensity.current.fontScale > 1.3f) Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        values.forEach { (label, value) -> cell(label, value) }
    } else Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        values.forEach { (label, value) -> cell(label, value, Modifier.weight(1f)) }
    }
}

@Composable internal fun RadarSourceTag(value: String) {
    val dashed = value.contains("estimat", true) || value.contains("forecast", true)
    Text(value.ifBlank { "unknown" }.replace('_', ' ').uppercase(Locale.US), Modifier.widthIn(max = 130.dp).drawBehind {
        drawRect(if (dashed) Edge.Soft else Edge.Ink, style = Stroke(1.dp.toPx(),
            pathEffect = if (dashed) PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())) else null))
    }.padding(horizontal = 8.dp, vertical = 5.dp), style = Edge.Meta.copy(fontSize = 10.sp), color = Edge.Ink)
}
