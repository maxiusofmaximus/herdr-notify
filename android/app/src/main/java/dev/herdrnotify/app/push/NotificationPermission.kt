package dev.herdrnotify.app.push

/**
 * What the app should do about the notification permission right now.
 *
 * Android 13 gatekeeps notifications behind `POST_NOTIFICATIONS`. A push that is
 * silently dropped looks exactly like a broken backend, so the app asks — but
 * it must not nag: a postponement is not a denial, and a dialog the system will
 * not show again is a button that does nothing.
 */
enum class NotificationPermissionStep {
    /** Nothing to do: older than 13, or already granted. */
    NOT_NEEDED,

    /** Postponed recently: show nothing until the cooldown ages out. */
    SUPPRESSED,

    /** Ask with the neutral dialog: not yet asked, postponable, or plainly refused. */
    ASK,

    /** Permanently denied: the only way forward is the app's settings page. */
    OPEN_SETTINGS,
}

/**
 * The permission decision, as a pure function so it is testable without an
 * Activity.
 *
 * [requested] means the *system* dialog has been launched at least once (the
 * launcher's result), not that our own pre-permission dialog was shown —
 * conflating the two reads a postponement as a permanent denial. [rationale] is
 * `shouldShowRequestPermissionRationale`: after a plain "no" Android returns
 * true (the dialog can be shown again), while after "don't allow" it returns
 * false — and it is *also* false before the very first ask, which is why
 * [requested] has to be consulted first, not [rationale] alone.
 *
 * [dismissedAtMs] is when the prompt was last postponed ("Ahora no" / outside
 * tap). Within the cooldown that wins over every ask, so the dialog does not
 * come back on each recomposition or app opening; it returns after the cooldown
 * or when an explicit attempt at the permission retires the postponement.
 */
internal object NotificationPermissionPolicy {
    const val REQUIRED_SDK = 33

    /** How long a postponement keeps the prompt quiet. */
    const val DISMISS_COOLDOWN_MS = 7L * 24 * 60 * 60 * 1000

    fun step(
        sdkInt: Int,
        granted: Boolean,
        requested: Boolean,
        rationale: Boolean,
        dismissedAtMs: Long?,
        nowMs: Long,
    ): NotificationPermissionStep = when {
        sdkInt < REQUIRED_SDK -> NotificationPermissionStep.NOT_NEEDED
        granted -> NotificationPermissionStep.NOT_NEEDED
        dismissedAtMs != null && nowMs - dismissedAtMs < DISMISS_COOLDOWN_MS ->
            NotificationPermissionStep.SUPPRESSED
        !requested -> NotificationPermissionStep.ASK
        rationale -> NotificationPermissionStep.ASK
        else -> NotificationPermissionStep.OPEN_SETTINGS
    }
}
