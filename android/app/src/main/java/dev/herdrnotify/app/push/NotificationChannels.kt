package dev.herdrnotify.app.push

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import dev.herdrnotify.app.MainActivity
import dev.herdrnotify.app.R

/**
 * Two channels, because the two kinds of alert are not the same thing.
 *
 * A blocked agent is someone waiting on a decision, so it gets its own
 * high-importance channel that may make a sound and show a heads-up view. A
 * finished task is information, so it lives on a low-importance channel that
 * arrives quietly.
 *
 * This is not a detail of taste. If both shared one channel, the user would
 * have to choose between being woken for a finished build and not being woken
 * for an agent that needs an answer. Splitting them is the only way both survive
 * the user's channel settings.
 */
object NotificationChannels {
    const val BLOCKED = "agents"
    const val DONE = "agents-review"

    fun createAll(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return

        val blocked = NotificationChannel(
            BLOCKED,
            context.getString(R.string.channel_blocked_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = context.getString(R.string.channel_blocked_description)
            enableVibration(true)
            enableLights(true)
            setShowBadge(true)
        }

        val done = NotificationChannel(
            DONE,
            context.getString(R.string.channel_done_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = context.getString(R.string.channel_done_description)
            enableVibration(false)
            setShowBadge(true)
        }

        manager.createNotificationChannel(blocked)
        manager.createNotificationChannel(done)
    }

    fun channelFor(status: String): String =
        if (status == "blocked") BLOCKED else DONE

    /**
     * Build a notification.
     *
     * `tag` is the collapse key, so a newer state for the same agent replaces
     * its old notification instead of stacking another copy in the shade. The
     * tray ends up showing one card per agent, which is what a person scanning
     * it can actually use.
     */
    fun build(
        context: Context,
        title: String,
        body: String,
        status: String,
        agentLabel: String,
        paneId: String? = null,
    ): Notification {
        val channel = channelFor(status)
        val priority = if (status == "blocked") {
            NotificationCompat.PRIORITY_HIGH
        } else {
            NotificationCompat.PRIORITY_DEFAULT
        }

        return NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setSubText(agentLabel)
            .setPriority(priority)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            // Content is a project name and a task title. Redacted on a locked
            // screen by default, which is the right default for a notification
            // that says which repository someone is working on.
            .setDefaults(0)
            .setAutoCancel(true)
            .apply { paneId?.let { setContentIntent(openAgentIntent(context, it)) } }
            .build()
    }

    /**
     * Tapping opens the app on the agent that raised the notification.
     *
     * An explicit intent to [MainActivity]: no custom action or scheme, so there
     * is still no deep link an outside app can drive, and the pane id travels as
     * an extra that the activity validates before use.
     */
    private fun openAgentIntent(context: Context, paneId: String): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_PANE_ID, paneId)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(
            context,
            paneId.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }
}
