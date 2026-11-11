package com.rideedge.app

import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable

/** UI identifiers only. Never stores credentials, provider records or answers. */
internal class EdgeExpansionState(initial: List<String> = emptyList()) {
    var keys by mutableStateOf(initial)
    companion object {
        val Saver = listSaver<EdgeExpansionState, String>(save = { it.keys }, restore = { EdgeExpansionState(it) })
    }
}

private val LocalExpansions = staticCompositionLocalOf<EdgeExpansionState?> { null }

@Composable internal fun EdgeExpansionProvider(content: @Composable () -> Unit) {
    val state = rememberSaveable(saver = EdgeExpansionState.Saver) { EdgeExpansionState() }
    CompositionLocalProvider(LocalExpansions provides state, content = content)
}

@Composable internal fun rememberEdgeExpansion(key: String): MutableState<Boolean> {
    val holder = LocalExpansions.current
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as? RideEdgeApplication
    if (BuildConfig.BUILD_TYPE == "preview" && app?.previewScenario == "recording" && holder != null) {
        val tour by app.recordingTour.state.collectAsState()
        LaunchedEffect(tour.revision, key) {
            val shot = tour.cue?.shot ?: return@LaunchedEffect
            val expand = (shot == "why" && key.startsWith("now:")) ||
                (shot == "plan_detail" && key.startsWith("plan:")) ||
                (shot == "comparison" && key == "comparison") || (shot == "further" && key == "further")
            holder.keys = if (expand) (holder.keys.filterNot { it == key } + key).takeLast(256) else holder.keys.filterNot { it == key }
        }
    }
    if (holder == null) return rememberSaveable(key) { mutableStateOf(false) }
    return remember(holder, key) {
        object : MutableState<Boolean> {
            override var value: Boolean
                get() = key in holder.keys
                set(value) { holder.keys = if (value) (holder.keys.filterNot { it == key } + key).takeLast(256) else holder.keys.filterNot { it == key } }
            override fun component1() = value
            override fun component2(): (Boolean) -> Unit = { value = it }
        }
    }
}
