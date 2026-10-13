package dev.herdrnotify.app.push

import android.content.Context
import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dev.herdrnotify.app.HerdrNotifyApplication

/**
 * Receives push from the gateway.
 *
 * Everything in [RemoteMessage] is untrusted input. The payload arrives over a
 * network, and a compromised or spoofed sender would otherwise get to decide
 * which notification a person sees and what it says. So every field is treated
 * as a hint: the pane id must look like a pane id, the status must be one the
 * gateway can actually produce, and anything unrecognised is dropped rather than
 * rendered.
 */
class HerdrMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        // FCM rotates the token on reinstall and on some app updates. The
        // gateway has to be told, or pushes stop arriving after the first
        // update and the cause is invisible from the phone. Parked first so a
        // process death cannot lose it, then handed to the sync layer — which
        // registers it now if there is a connection to carry it, or on the next
        // one if there is not.
        Log.i(TAG, "FCM token rotated; parking it and handing it to the sync layer")
        TokenRelay.park(applicationContext, token)
        (applicationContext as? HerdrNotifyApplication)
            ?.container?.repository?.flushPendingToken()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val status = message.data["status"].orEmpty()
        val paneId = message.data["pane_id"].orEmpty()
        if (!PANE_ID.matches(paneId)) {
            Log.w(TAG, "dropping a push with an unusable pane id")
            return
        }
        if (status !in KNOWN_STATUSES) {
            Log.w(TAG, "dropping a push with an unknown status: $status")
            return
        }
        val title = message.notification?.title?.take(MAX_TITLE) ?: return
        val body = message.notification?.body?.take(MAX_BODY).orEmpty()

        NotificationChannels.build(
            context = applicationContext,
            title = title,
            body = body,
            status = status,
            agentLabel = message.data["project"].orEmpty().take(MAX_LABEL),
            paneId = paneId,
        ).let { notification ->
            notificationManager.notify(paneId.hashCode(), notification)
        }
    }

    private val notificationManager
        get() = androidx.core.app.NotificationManagerCompat.from(this)

    companion object {
        private const val TAG = "HerdrMessaging"

        /** Mirrors the gateway's pane id shape: see api/actions.py. */
        internal val PANE_ID = Regex("^[A-Za-z0-9]{1,32}:p[0-9A-Za-z]{1,32}$")
        private val KNOWN_STATUSES = setOf("blocked", "done")

        private const val MAX_TITLE = 80
        private const val MAX_BODY = 240
        private const val MAX_LABEL = 40
    }
}

/**
 * Carries a rotated token to whatever owns the sync loop.
 *
 * `onNewToken` can fire before the app has finished pairing, so there may be no
 * gateway to send it to yet. The token is parked **persistently**: a copy that
 * only lived in memory would be lost by the next process death — exactly when a
 * re-registration is most needed. The next paired, reachable connection reports
 * it, and only then is the parked copy cleared.
 *
 * A `SharedPreferences` write with `commit()` rather than DataStore: this runs
 * from the service's callback thread, where the write has to complete before
 * the process can die, and one blocking write of one short string is the
 * honest tool for that. Losing the pairing costs one CLI command; losing a
 * parked token costs every push until the app reconnects.
 */
object TokenRelay {
    private const val PREFS = "push"
    private const val KEY = "pending_token"

    /** The in-memory mirror of what was last parked. */
    @Volatile
    var pending: String? = null
        private set

    /** Persist the token so a process death cannot lose it, and park it. */
    fun park(context: Context, token: String) {
        prefs(context).edit().putString(KEY, token).commit()
        pending = token
    }

    /** The parked token, read from disk so a restarted process finds it. */
    fun parked(context: Context): String? = prefs(context).getString(KEY, null)

    /** Drop the parked token after the gateway accepted a registration. */
    fun clear(context: Context) {
        prefs(context).edit().remove(KEY).commit()
        pending = null
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
