package dev.herdrnotify.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The image-attachment rules, pinned without a picker.
 *
 * The transport to the host is still pending (`docs/contracts/api.md` has no
 * image endpoint), so what can be verified now is the client's half: which
 * images are accepted, and that a failure is a clear message rather than a
 * silent drop.
 */
class ImageAttachmentTest {

    @Test
    fun `a normal png is accepted`() {
        assertNull(ImageAttachment.problem("image/png", 1_000))
    }

    @Test
    fun `every supported type is accepted, case-insensitively`() {
        ImageAttachment.SUPPORTED_MIME.forEach { mime ->
            assertNull("$mime should be accepted", ImageAttachment.problem(mime, 1_000))
            assertNull("$mime should be accepted", ImageAttachment.problem(mime.uppercase(), 1_000))
        }
    }

    @Test
    fun `an unknown or missing type is refused`() {
        assertEquals(
            ImageAttachment.Problem.UNSUPPORTED_TYPE,
            ImageAttachment.problem("application/zip", 1_000),
        )
        assertEquals(
            ImageAttachment.Problem.UNSUPPORTED_TYPE,
            ImageAttachment.problem(null, 1_000),
        )
        assertEquals(
            ImageAttachment.Problem.UNSUPPORTED_TYPE,
            ImageAttachment.problem("", 1_000),
        )
    }

    @Test
    fun `an empty image is refused`() {
        assertEquals(ImageAttachment.Problem.EMPTY, ImageAttachment.problem("image/png", 0))
    }

    @Test
    fun `an oversized image is refused`() {
        assertEquals(
            ImageAttachment.Problem.TOO_LARGE,
            ImageAttachment.problem("image/png", ImageAttachment.MAX_BYTES + 1),
        )
        assertNull(ImageAttachment.problem("image/png", ImageAttachment.MAX_BYTES))
    }

    @Test
    fun `type is checked before size`() {
        // A wrong-kind file that is also huge should be reported as the wrong
        // kind: that is the fixable problem.
        assertEquals(
            ImageAttachment.Problem.UNSUPPORTED_TYPE,
            ImageAttachment.problem("application/zip", ImageAttachment.MAX_BYTES + 1),
        )
    }

    @Test
    fun `the pending gateway is reported as an unsupported feature, not a fault`() {
        assertEquals(
            "Este gateway todavía no admite imágenes.",
            imageFailureMessage(UnsupportedOperationException("no endpoint")),
        )
    }
}
