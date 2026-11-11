package com.rideedge.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import androidx.car.app.CarContext
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.common.OnCarDataAvailableListener
import androidx.car.app.hardware.info.CarHardwareLocation
import androidx.car.app.hardware.info.CarSensors
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/** Permissioned host-location feasibility path. Never silently starts phone GPS. */
class CarRadarLocation : RadarLocationSource {
    private var host: CarContext? = null
    var status: String = "Car location has not been tested"
        private set

    fun attach(context: CarContext) { host = context }
    fun detach(context: CarContext) { if (host === context) host = null }

    @SuppressLint("MissingPermission")
    override suspend fun currentFix(): RadarFix? {
        if (BuildConfig.BUILD_TYPE == "preview") return null
        val context = host ?: run { status = "Car location host unavailable"; return null }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            status = "Precise location permission required"; return null
        }
        val sensors = runCatching { context.getCarService(CarHardwareManager::class.java).carSensors }.getOrNull()
            ?: run { status = "Car location is unsupported"; return null }
        status = "Waiting for car location"
        val result = withTimeoutOrNull(15000) {
            suspendCancellableCoroutine<RadarFix?> { continuation ->
                lateinit var listener: OnCarDataAvailableListener<CarHardwareLocation>
                fun remove() { runCatching { sensors.removeCarHardwareLocationListener(listener) } }
                listener = OnCarDataAvailableListener { data ->
                    if (continuation.isActive) {
                        val value = data.location
                        // Unknown can precede a fix. Unsupported/permission failures are terminal.
                        if (value.status == CarValue.STATUS_SUCCESS) {
                            val fix = value.value?.toRadarFix()
                            status = if (fix == null) "Car location is stale or imprecise" else "Car location available"
                            remove(); continuation.resume(fix)
                        } else if (value.status != CarValue.STATUS_UNKNOWN) {
                            status = "Car location unavailable (status ${value.status})"
                            remove(); continuation.resume(null)
                        }
                    }
                }
                continuation.invokeOnCancellation { remove() }
                runCatching { sensors.addCarHardwareLocationListener(CarSensors.UPDATE_RATE_NORMAL, context.mainExecutor, listener) }
                    .onFailure { remove(); status = "Car location request failed"; if (continuation.isActive) continuation.resume(null) }
            }
        }
        if (result == null && status == "Waiting for car location") status = "Car location timed out"
        return result
    }
}
