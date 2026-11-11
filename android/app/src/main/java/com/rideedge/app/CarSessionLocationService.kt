package com.rideedge.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Foreground privilege for the existing shared location loop, not a second collector. */
class CarSessionLocationService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val app get() = application as RideEdgeApplication

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "RideEdge car session", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val end = PendingIntent.getService(this, 1, Intent(this, CarSessionLocationService::class.java).setAction(END), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle("RideEdge car session")
            .setContentText("Using phone location for nearby recommendations")
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .addAction(0, "End session", end).build()
        try {
            startForeground(2401, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            app.phoneLocationServiceRunning = true
        } catch (_: SecurityException) {
            app.radar.endCarSession()
            stopSelf()
            return
        }
        scope.launch {
            app.radar.session.collect { session ->
                if (!carPhoneLocationSessionActive(session) || BuildConfig.BUILD_TYPE == "preview") stopSelf()
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == END) app.radar.endCarSession()
        if (intent?.action == END || !carPhoneLocationSessionActive(app.radar.session.value)) stopSelf()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        app.phoneLocationServiceRunning = false
        scope.cancel()
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL = "rideedge_car_location"
        private const val END = "com.rideedge.app.END_CAR_SESSION"
    }
}

internal fun carPhoneLocationSessionActive(session: RadarSession): Boolean =
    session.carActive && session.carConnected && session.followPhone

internal fun phoneLocationAllowed(session: RadarSession, foregroundService: Boolean): Boolean =
    session.phoneVisible || (carPhoneLocationSessionActive(session) && foregroundService)
