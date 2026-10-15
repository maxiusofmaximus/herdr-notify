package dev.herdrnotify.app.pairing

/**
 * What the app should do about the camera permission right now.
 *
 * The scanner needs the camera, but the permission is asked for at the moment of
 * scanning and never at first launch: a phone paired by hand should never see it.
 * After a refusal that Android will not show a dialog for again, asking again is a
 * button that does nothing, so the honest route is the app's settings page.
 */
enum class CameraPermissionStep {
    /** Already granted: show the preview. */
    GRANTED,

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
internal object CameraPermissionPolicy {
    fun step(
        granted: Boolean,
        asked: Boolean,
        rationale: Boolean,
    ): CameraPermissionStep = when {
        granted -> CameraPermissionStep.GRANTED
        !asked || rationale -> CameraPermissionStep.ASK
        else -> CameraPermissionStep.OPEN_SETTINGS
    }
}
