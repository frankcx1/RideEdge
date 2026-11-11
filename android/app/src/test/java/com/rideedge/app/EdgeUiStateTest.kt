package com.rideedge.app

import androidx.compose.runtime.saveable.SaverScope
import org.junit.Assert.*
import org.junit.Test

class EdgeUiStateTest {
    @Test fun savedExpansionsRestoreIndependentlyOfTheDisposedList() {
        val original = EdgeExpansionState(listOf("now:synthetic", "plan:synthetic-window"))
        val scope = object : SaverScope { override fun canBeSaved(value: Any) = value is String }
        val saved = with(EdgeExpansionState.Saver) { scope.save(original) }!!
        original.keys = emptyList()
        val restored = EdgeExpansionState.Saver.restore(saved)!!
        assertEquals(listOf("now:synthetic", "plan:synthetic-window"), restored.keys)
        assertTrue(original.keys.isEmpty())
    }
}
