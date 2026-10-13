package dev.herdrnotify.app.ui

import androidx.compose.foundation.ScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow

/**
 * Keeps a tail view at its newest line **only while the person is reading the
 * tail**.
 *
 * The pane detail is polled, so the same conversation is re-read every 15
 * seconds and a fresh list of entries is produced each time. Jumping to the end
 * on every read is what made the screen flicker and, worse, yanked the view back
 * down while a person was scrolling up through history: the read lands, the
 * effect fires, and the text they were reading is gone.
 *
 * The rule here is the one a chat uses. Follow the newest line when the view is
 * already at the bottom; leave the position alone the moment the person drags
 * away. [TailFollow.isAtBottom] is the decision, pure and so testable; the
 * composable only feeds it the scroll state.
 */
internal object TailFollow {
    /**
     * How close to the bottom still counts as "at the bottom".
     *
     * A finger rarely lands exactly on the last pixel, and a short flick leaves a
     * few pixels of slack; without a tolerance the view would silently stop
     * following after an almost-at-the-end gesture.
     */
    const val THRESHOLD_PX = 64

    fun isAtBottom(value: Int, maxValue: Int): Boolean =
        maxValue <= 0 || value >= maxValue - THRESHOLD_PX
}

/**
 * Drives [scroll] to the bottom as new content arrives, but stops as soon as the
 * person scrolls away, and only resumes when they return to the bottom.
 *
 * Following is tracked from *scroll gestures*, not from the content size: after
 * new entries land the list is temporarily taller than the finger left it, so a
 * size-based check would read "no longer at the bottom" and refuse to follow on
 * the very update it is meant to follow.
 */
@Composable
internal fun AutoScrollToBottom(scroll: ScrollState) {
    var following by remember(scroll) { mutableStateOf(true) }

    // A drag (or a fling) is the only moment the person's intent is readable.
    // Programmatic scrolls pass through here too and simply reaffirm the bottom.
    LaunchedEffect(scroll) {
        snapshotFlow { scroll.isScrollInProgress to scroll.value }
            .collect { (inProgress, value) ->
                if (inProgress) following = TailFollow.isAtBottom(value, scroll.maxValue)
            }
    }

    // maxValue moves when the content grows or the viewport is laid out, which
    // covers both "the first frame measured" and "a new read added lines".
    LaunchedEffect(scroll) {
        snapshotFlow { scroll.maxValue }
            .collect { if (following) scroll.scrollTo(scroll.maxValue) }
    }
}
