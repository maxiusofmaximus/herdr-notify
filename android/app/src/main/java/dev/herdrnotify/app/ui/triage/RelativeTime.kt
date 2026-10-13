package dev.herdrnotify.app.ui.triage

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay

/**
 * How long ago something happened, in the short form the subtitle uses.
 *
 * Seconds, then minutes, then hours, each rounded down. A stale screen should
 * say *how* stale it is, and the coarse units are the point: "hace 3 min" is
 * something a person can act on, a count of milliseconds is not.
 */
internal fun formatSince(elapsedMillis: Long): String {
    val seconds = (elapsedMillis / 1_000L).coerceAtLeast(0L)
    return when {
        seconds < 60L -> "hace $seconds s"
        seconds < 3_600L -> "hace ${seconds / 60L} min"
        else -> "hace ${seconds / 3_600L} h"
    }
}

/**
 * The current time, refreshed every [periodMillis] while the screen is visible.
 *
 * Tied to the lifecycle rather than to composition: a composable can stay in
 * memory while the activity is stopped, and a clock that keeps ticking behind a
 * closed app is work nobody sees. `repeatOnLifecycle(STARTED)` cancels the tick
 * on stop and restarts it on the next start.
 */
@Composable
internal fun rememberNowMillis(periodMillis: Long = 5_000L): Long {
    val now = remember { mutableLongStateOf(System.currentTimeMillis()) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                now.longValue = System.currentTimeMillis()
                delay(periodMillis)
            }
        }
    }
    return now.longValue
}
