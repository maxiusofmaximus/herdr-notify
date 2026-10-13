package dev.herdrnotify.app.push

/**
 * What the app should do about the notification permission right now.
 *
 * Android 13 gatekeeps notifications behind `POST_NOTIFICATIONS`. A push that is
 * silently dropped looks exactly like a broken backend, so the app asks — but
 * only once, and it must not keep asking after a refusal that the system will
 * not show again: a dialog that never appears is a button that does nothing, and
 * the honest fix then is a route to system settings, not another request.
 */
enum class NotificationPermissionStep {
    /** Nothing to do: older than 13, or already granted. */
    NOT_NEEDED,

    /** Ask with the system dialog, reason first. */
    ASK,

    /** Permanently denied: the only way forward is the app's settings page. */
    OPEN_SETTINGS,
}

/**
 * The permission decision, as a pure function so it is testable without an
 * Activity.
 *
 * [asked] means the app has already shown the system dialog at least once this
 * install. [rationale] is `shouldShowRequestPermissionRationale`: after a plain
 * "no" Android returns true (the dialog can be shown again), while after "don't
 * allow" it returns false — and it is *also* false before the very first ask,
 * which is why [asked] has to be consulted first, not [rationale] alone.
 */
internal object NotificationPermissionPolicy {
    const val REQUIRED_SDK = 33

    fun step(
        sdkInt: Int,
        granted: Boolean,
        asked: Boolean,
        rationale: Boolean,
    ): NotificationPermissionStep = when {
        sdkInt < REQUIRED_SDK -> NotificationPermissionStep.NOT_NEEDED
        granted -> NotificationPermissionStep.NOT_NEEDED
        !asked -> NotificationPermissionStep.ASK
        rationale -> NotificationPermissionStep.ASK
        else -> NotificationPermissionStep.OPEN_SETTINGS
    }
}
