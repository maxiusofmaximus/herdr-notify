package dev.herdrnotify.app.sync

import android.app.Notification
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat

/**
 * Holds the live event stream open.
 *
 * A plain background coroutine would be killed whenever Android decides the app
 * is idle, which is exactly the moment the app most needs to be current. A
 * foreground service with a low-priority, silent notification is the supported
 * way to keep a long-lived connection without the user seeing anything
 * alarming.
 *
 * The notification is deliberately not dismissible and carries no text about
 * agents: it says the connection is live, which is honest, and nothing more.
 */
class LiveStreamService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat()
        return START_STICKY
    }

    private fun startForegroundCompat() {
        val notification: Notification = androidx.core.app.NotificationCompat.Builder(
            this,
            dev.herdrnotify.app.push.NotificationChannels.DONE,
        )
            .setSmallIcon(dev.herdrnotify.app.R.drawable.ic_launcher_foreground)
            .setContentTitle(getString(dev.herdrnotify.app.R.string.app_name))
            .setContentText(getString(dev.herdrnotify.app.R.string.state_connecting))
            .setOngoing(true)
            .setSilent(true)
            .setPriority(androidx.core.app.NotificationCompat.PRIORITY_MIN)
            .setCategory(androidx.core.app.NotificationCompat.CATEGORY_SERVICE)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val NOTIFICATION_ID = 1001
    }
}
