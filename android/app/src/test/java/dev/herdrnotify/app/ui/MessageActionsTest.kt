package dev.herdrnotify.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The per-message action row's contract: what a message offers depends on who
 * wrote it and on whether there is a prompt to send again.
 */
class MessageActionsTest {

    @Test
    fun `a person's message offers copy, share and retry, but never raw`() {
        val actions = actionsFor(MessageRole.USER, hasRetryText = true, canViewRaw = true)

        assertEquals(
            listOf(MessageAction.COPY, MessageAction.SHARE, MessageAction.RETRY),
            actions,
        )
        assertFalse("the person's own words have no terminal tail to show", actions.contains(MessageAction.VIEW_RAW))
    }

    @Test
    fun `an agent message with a prompting turn offers raw and retry`() {
        assertEquals(
            listOf(
                MessageAction.COPY,
                MessageAction.SHARE,
                MessageAction.RETRY,
                MessageAction.VIEW_RAW,
            ),
            actionsFor(MessageRole.AGENT, hasRetryText = true, canViewRaw = true),
        )
    }

    @Test
    fun `an agent message with no preceding prompt hides retry`() {
        assertEquals(
            listOf(MessageAction.COPY, MessageAction.SHARE, MessageAction.VIEW_RAW),
            actionsFor(MessageRole.AGENT, hasRetryText = false, canViewRaw = true),
        )
    }
}
