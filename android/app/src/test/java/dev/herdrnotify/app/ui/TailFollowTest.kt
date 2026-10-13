package dev.herdrnotify.app.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The chat's follow rule, pinned without a UI harness.
 *
 * This is the decision that fixed the flicker: a poll re-reads the tail every
 * 15 seconds, and the screen must chase the newest line when the person is at
 * the bottom and leave them alone when they are not.
 */
class TailFollowTest {

    @Test
    fun `an empty or unmeasured list is treated as the bottom`() {
        assertTrue(TailFollow.isAtBottom(value = 0, maxValue = 0))
        assertTrue(TailFollow.isAtBottom(value = 0, maxValue = -1))
    }

    @Test
    fun `exactly at the bottom follows`() {
        assertTrue(TailFollow.isAtBottom(value = 1_000, maxValue = 1_000))
    }

    @Test
    fun `within the tolerance still counts as the bottom`() {
        assertTrue(TailFollow.isAtBottom(value = 1_000 - TailFollow.THRESHOLD_PX, maxValue = 1_000))
        assertTrue(TailFollow.isAtBottom(value = 1_000 - TailFollow.THRESHOLD_PX + 1, maxValue = 1_000))
    }

    @Test
    fun `scrolled away from the bottom does not follow`() {
        assertFalse(TailFollow.isAtBottom(value = 1_000 - TailFollow.THRESHOLD_PX - 1, maxValue = 1_000))
        assertFalse(TailFollow.isAtBottom(value = 0, maxValue = 1_000))
    }
}
