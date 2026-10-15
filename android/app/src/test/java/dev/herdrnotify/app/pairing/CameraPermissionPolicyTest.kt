package dev.herdrnotify.app.pairing

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The camera permission decision table.
 *
 * The subtle case is the one a naive `rationale` check gets wrong: before the
 * very first request `shouldShowRequestPermissionRationale` is already false, so
 * it cannot tell "never asked" from "permanently denied". [asked] is consulted
 * first, and this pins that order.
 */
class CameraPermissionPolicyTest {

    private fun step(granted: Boolean, asked: Boolean, rationale: Boolean) =
        CameraPermissionPolicy.step(granted, asked, rationale)

    @Test
    fun `granted shows the preview`() {
        assertEquals(CameraPermissionStep.GRANTED, step(granted = true, asked = false, rationale = false))
    }

    @Test
    fun `the first ask is offered even though rationale is already false`() {
        assertEquals(CameraPermissionStep.ASK, step(granted = false, asked = false, rationale = false))
    }

    @Test
    fun `a plain refusal can be asked again`() {
        assertEquals(CameraPermissionStep.ASK, step(granted = false, asked = true, rationale = true))
    }

    @Test
    fun `a permanent refusal routes to settings, not another dialog`() {
        assertEquals(
            CameraPermissionStep.OPEN_SETTINGS,
            step(granted = false, asked = true, rationale = false),
        )
    }
}
