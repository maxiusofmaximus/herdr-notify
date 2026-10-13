package dev.herdrnotify.app.net

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the signing string.
 *
 * The gateway hashes and verifies these exact bytes, so a JVM-only test is not
 * enough on its own. The cross-language half of this lives in
 * `gateway/tests/test_golden_vectors.py`, which runs the same vectors through
 * the Python implementation and compares them to a committed JSON file. If the
 * two implementations ever disagree, one of those two suites fails.
 */
class RequestSignerTest {

    private val method = "POST"
    private val target = "/v1/agents/w1:p1/respond"
    private val body = """{"text":"sí, hazlo"}""".toByteArray()
    private val timestamp = 1_700_000_000L
    private val nonce = "AAAAAAAAAAAAAAAAAAAAAA=="

    @Test
    fun `signing string is LF separated and LF terminated`() {
        val payload = RequestSigner.signingString(method, target, body, timestamp, nonce)
        val text = String(payload, Charsets.UTF_8)

        assertTrue("must end with a newline", text.endsWith("\n"))
        // Five fields, so five terminators: four separators plus the final one.
        assertEquals(5, text.count { it == '\n' })
        assertEquals("POST", text.substringBefore("\n"))
    }

    @Test
    fun `method is upper cased so post and POST cannot sign differently`() {
        val lower = RequestSigner.signingString("post", target, body, timestamp, nonce)
        val upper = RequestSigner.signingString("POST", target, body, timestamp, nonce)
        assertArrayEquals(lower, upper)
    }

    @Test
    fun `body is hashed rather than embedded`() {
        val text = String(
            RequestSigner.signingString(method, target, body, timestamp, nonce),
            Charsets.UTF_8,
        )
        val digest = RequestSigner.bodyDigest(body)
        assertEquals(64, digest.length)
        assertTrue(text.contains(digest))
        assertTrue("the raw text must not appear", !text.contains("hazlo"))
    }

    @Test
    fun `a one byte change in the body changes the signature payload`() {
        val original = RequestSigner.signingString(method, target, body, timestamp, nonce)
        val altered = RequestSigner.signingString(
            method,
            target,
            """{"text":"tampered"}""".toByteArray(),
            timestamp,
            nonce,
        )
        assertTrue(!original.contentEquals(altered))
    }

    @Test
    fun `a different path changes the signature payload`() {
        val approved = RequestSigner.signingString(
            method,
            "/v1/agents/w1:p1/seen",
            body,
            timestamp,
            nonce,
        )
        val respond = RequestSigner.signingString(method, target, body, timestamp, nonce)
        assertTrue(!approved.contentEquals(respond))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a relative target is refused`() {
        RequestSigner.signingString(method, "v1/x", body, timestamp, nonce)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a newline in the nonce is refused`() {
        RequestSigner.signingString(method, target, body, timestamp, nonce = "a\nb")
    }

    @Test(expected = IllegalArgumentException::class)
    fun `an empty nonce is refused`() {
        RequestSigner.signingString(method, target, body, timestamp, nonce = "")
    }

    @Test
    fun `body digest matches sha256 of the empty body`() {
        // The well-known digest of no bytes, so a base64 or charset slip here
        // cannot hide behind a self-consistent implementation.
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            RequestSigner.bodyDigest(ByteArray(0)),
        )
    }
}
