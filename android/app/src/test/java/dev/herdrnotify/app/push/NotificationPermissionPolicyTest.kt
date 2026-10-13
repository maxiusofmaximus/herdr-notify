package dev.herdrnotify.app.push

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The permission flow's decision table.
 *
 * The subtle case is the one a naive `rationale` check gets wrong: before the
 * very first request `shouldShowRequestPermissionRationale` is already false, so
 * it cannot distinguish "never asked" from "permanently denied". [asked] must be
 * consulted first, and this pins that order.
 */
class NotificationPermissionPolicyTest {

    private fun step(sdk: Int, granted: Boolean, asked: Boolean, rationale: Boolean) =
        NotificationPermissionPolicy.step(sdk, granted, asked, rationale)

    @Test
    fun `before Android 13 there is nothing to ask`() {
        assertEquals(NotificationPermissionStep.NOT_NEEDED, step(32, granted = false, asked = false, rationale = false))
    }

    @Test
    fun `granted needs nothing on any version`() {
        assertEquals(NotificationPermissionStep.NOT_NEEDED, step(33, granted = true, asked = false, rationale = false))
        assertEquals(NotificationPermissionStep.NOT_NEEDED, step(34, granted = true, asked = true, rationale = false))
    }

    @Test
    fun `the first ask is offered even though rationale is already false`() {
        assertEquals(NotificationPermissionStep.ASK, step(33, granted = false, asked = false, rationale = false))
    }

    @Test
    fun `a plain refusal can be asked again`() {
        assertEquals(NotificationPermissionStep.ASK, step(33, granted = false, asked = true, rationale = true))
    }

    @Test
    fun `a permanent refusal routes to settings, not another dialog`() {
        assertEquals(
            NotificationPermissionStep.OPEN_SETTINGS,
            step(33, granted = false, asked = true, rationale = false),
        )
    }
}
