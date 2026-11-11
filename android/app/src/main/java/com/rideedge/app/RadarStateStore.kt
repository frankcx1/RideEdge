package com.rideedge.app

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import java.time.Instant

data class RadarViewState(
    val received: ReceivedRadar? = null,
    val errorCode: String? = null,
    val message: String? = null,
    val connected: Boolean = false,
    val changingOrigin: Boolean = false,
    val requestGeneration: Long = 0,
    val lastContactAt: Instant? = null,
)

/** The repository owns this state; both surfaces observe the same immutable values. */
class RadarStateStore(private val elapsedMs: () -> Long, private val bootId: () -> Int) {
    private val mutable = MutableStateFlow(RadarViewState())
    val state: StateFlow<RadarViewState> = mutable.asStateFlow()

    @Synchronized fun beginOriginChange(): Long {
        val generation = mutable.value.requestGeneration + 1
        mutable.value = mutable.value.copy(changingOrigin = true, requestGeneration = generation,
            errorCode = null, message = null)
        return generation
    }

    @Synchronized fun accept(json: JSONObject, generation: Long): Boolean {
        if (generation != mutable.value.requestGeneration) return false
        return try {
            val snapshot = RadarParser.parse(json)
            mutable.value = RadarViewState(ReceivedRadar(snapshot, elapsedMs(), bootId()),
                connected = true, requestGeneration = generation, lastContactAt = Instant.now())
            true
        } catch (error: RadarContractException) {
            // Preserve the old receipt, including its original expiry clock.
            mutable.value = mutable.value.copy(errorCode = error.code, message = error.message, connected = true, lastContactAt = Instant.now())
            false
        }
    }

    @Synchronized fun disconnected(generation: Long) {
        if (generation == mutable.value.requestGeneration) {
            mutable.value = mutable.value.copy(connected = false, errorCode = "disconnected",
                message = "Connection lost. The last decision expires normally; reconnect to refresh.")
        }
    }

    @Synchronized fun accessRequired(generation: Long) {
        if (generation == mutable.value.requestGeneration) mutable.value = mutable.value.copy(
            connected = false, errorCode = "access_required",
            message = "While parked, open Connection on your phone and reconnect to workstation.")
    }

    /** Resolve by ID against CURRENT state at tap time, not a captured card object. */
    @Synchronized fun navigationTarget(id: String): RadarPlace? {
        val current = mutable.value
        if (current.changingOrigin || current.errorCode in setOf("schema_mismatch", "invalid_contract", "access_required")) return null
        val received = current.received ?: return null
        val snapshot = received.snapshot
        return (snapshot.now + snapshot.further + snapshot.nearby).firstOrNull { it.id == id }
            ?.takeIf { received.eligible(it, elapsedMs(), bootId()) }
    }

    @Synchronized fun primary(): RadarPlace? {
        val id = mutable.value.received?.snapshot?.now?.firstOrNull()?.id ?: return null
        return navigationTarget(id)?.takeIf { it.withinNowRadius && it.radiusMiles <= 5.0 }
    }
}
