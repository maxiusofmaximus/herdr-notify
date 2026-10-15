package dev.herdrnotify.app.push

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The permission flow's decision table.
 *
 * Two subtleties pin the order of the inputs. Before the very first request
 * `shouldShowRequestPermissionRationale` is already false, so it cannot
 * distinguish "never asked" from "permanently denied": [requested] (the system
 * dialog was launched) must be consulted first. And a postponement is neither
 * state — it must suppress the prompt on its own, not route it to the
 * permanently-denied dialog, which is how the stuck "Avisos desactivados"
 * dialog came to be.
 */
class NotificationPermissionPolicyTest {

    private val now = 1_700_000_000_000L
    private val cooldown = NotificationPermissionPolicy.DISMISS_COOLDOWN_MS

    private fun step(
        sdk: Int = 33,
        granted: Boolean = false,
        requested: Boolean = false,
        rationale: Boolean = false,
        dismissedAtMs: Long? = null,
        nowMs: Long = now,
    ) = NotificationPermissionPolicy.step(sdk, granted, requested, rationale, dismissedAtMs, nowMs)

    @Test
    fun `before Android 13 there is nothing to ask`() {
        assertEquals(NotificationPermissionStep.NOT_NEEDED, step(sdk = 32))
    }

    @Test
    fun `granted needs nothing on any version`() {
        assertEquals(NotificationPermissionStep.NOT_NEEDED, step(sdk = 33, granted = true))
        assertEquals(
            NotificationPermissionStep.NOT_NEEDED,
            step(sdk = 34, granted = true, requested = true, rationale = false),
        )
    }

    @Test
    fun `the first ask is offered even though rationale is already false`() {
        assertEquals(NotificationPermissionStep.ASK, step(requested = false, rationale = false))
    }

    @Test
    fun `a plain refusal can be asked again`() {
        assertEquals(NotificationPermissionStep.ASK, step(requested = true, rationale = true))
    }

    @Test
    fun `a permanent refusal routes to settings, not another dialog`() {
        assertEquals(
            NotificationPermissionStep.OPEN_SETTINGS,
            step(requested = true, rationale = false),
        )
    }

    @Test
    fun `postponing before the system dialog suppresses instead of crying blocked`() {
        // The regression: declining our pre-prompt left rationale=false, which
        // the old policy read as a permanent denial.
        assertEquals(
            NotificationPermissionStep.SUPPRESSED,
            step(requested = false, rationale = false, dismissedAtMs = now - 1),
        )
    }

    @Test
    fun `postponing the settings dialog keeps it closed too`() {
        assertEquals(
            NotificationPermissionStep.SUPPRESSED,
            step(requested = true, rationale = false, dismissedAtMs = now - 1),
        )
    }

    @Test
    fun `a plain refusal is also suppressed once postponed`() {
        assertEquals(
            NotificationPermissionStep.SUPPRESSED,
            step(requested = true, rationale = true, dismissedAtMs = now - 1),
        )
    }

    @Test
    fun `a dismissal exactly at the cooldown boundary still suppresses`() {
        assertEquals(
            NotificationPermissionStep.SUPPRESSED,
            step(dismissedAtMs = now - cooldown + 1),
        )
    }

    @Test
    fun `after the cooldown the prompt returns as the state it deserves`() {
        val expired = now - cooldown
        assertEquals(NotificationPermissionStep.ASK, step(requested = false, dismissedAtMs = expired))
        assertEquals(
            NotificationPermissionStep.OPEN_SETTINGS,
            step(requested = true, rationale = false, dismissedAtMs = expired),
        )
    }

    @Test
    fun `granting outranks a pending dismissal`() {
        assertEquals(
            NotificationPermissionStep.NOT_NEEDED,
            step(granted = true, dismissedAtMs = now - 1),
        )
    }

    @Test
    fun `an explicit attempt forgets the dismissal`() {
        assertEquals(NotificationPermissionStep.ASK, step(requested = false, dismissedAtMs = null))
    }
}
