package dev.herdrnotify.app

import android.util.Log

internal object DebugLog {
    private const val TAG = "HerdrNotify"

    fun d(message: String) {
        try {
            Log.d(TAG, message)
        } catch (_: Throwable) {
            // JVM unit tests have no android.util.Log — swallow silently.
        }
    }
}
