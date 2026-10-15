package dev.herdrnotify.app.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The QR parser is the only place an untrusted string becomes a pairing.
 *
 * The camera hands it whatever is on screen, so the contract
 * `herdr-notify://pair?u=<url>&c=<code>&v=1` is treated as an untrusted input and
 * every way it can be wrong — or hostile — is pinned here. The two rules that
 * also constrain the manual flow, a full scheme and a non-loopback address, are
 * enforced identically so a QR cannot do what the keyboard cannot.
 */
class PairingQrPayloadTest {

    private fun valid(raw: String): PairingQrPayload {
        val result = PairingQrPayload.parse(raw)
        assertTrue("esperaba válido pero fue $result", result is PairingQrResult.Valid)
        return (result as PairingQrResult.Valid).payload
    }

    private fun reason(raw: String): String {
        val result = PairingQrPayload.parse(raw)
        assertTrue("esperaba inválido pero fue $result", result is PairingQrResult.Invalid)
        return (result as PairingQrResult.Invalid).reason
    }

    @Test
    fun `a well formed payload yields the url and the code`() {
        val payload = valid(
            "herdr-notify://pair?u=http%3A%2F%2Fpc.tailnet.ts.net%3A8788&c=ABCD1234&v=1",
        )
        assertEquals("http://pc.tailnet.ts.net:8788", payload.baseUrl)
        assertEquals("ABCD1234", payload.code)
    }

    @Test
    fun `a tailnet ip is accepted too`() {
        val payload = valid(
            "herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=7QK3M2XP&v=1",
        )
        assertEquals("http://100.64.0.1:8788", payload.baseUrl)
    }

    @Test
    fun `an https address is accepted`() {
        val payload = valid("herdr-notify://pair?u=https%3A%2F%2Fpc.tailnet.ts.net&c=CODE&v=1")
        assertEquals("https://pc.tailnet.ts.net", payload.baseUrl)
    }

    @Test
    fun `the schema version is required to be the one we know`() {
        // v=1 as a sentinel that a future schema can change; anything else means
        // this build cannot be sure what the fields mean.
        val unknown = reason("herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=C&v=2")
        assertTrue(unknown.contains("versión"))
        assertEquals(
            "v=1 parses like a missing v",
            "CODE",
            valid("herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=CODE&v=1").code,
        )
    }

    @Test
    fun `a foreign scheme is refused`() {
        val text = reason("https://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=C&v=1")
        assertTrue(text.contains("herdr notify"))
    }

    @Test
    fun `a foreign host is refused`() {
        val text = reason("herdr-notify://login?u=http%3A%2F%2F100.64.0.1%3A8788&c=C&v=1")
        assertTrue(text.contains("emparejamiento"))
    }

    @Test
    fun `a missing url is refused`() {
        val text = reason("herdr-notify://pair?c=ABCD&v=1")
        assertTrue(text.contains("dirección"))
    }

    @Test
    fun `a missing code is refused`() {
        val text = reason("herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&v=1")
        assertTrue(text.contains("código"))
    }

    @Test
    fun `a url without a scheme is refused rather than guessed at`() {
        // The manual field guesses https:// for a bare name; a QR must not, because
        // the gateway always emits a full URL and guessing hides a broken emitter.
        val text = reason("herdr-notify://pair?u=pc.tailnet.ts.net%3A8788&c=C&v=1")
        assertTrue(text.contains("http"))
    }

    @Test
    fun `a loopback address is refused like the manual flow refuses it`() {
        assertTrue(
            reason("herdr-notify://pair?u=http%3A%2F%2F127.0.0.1%3A8788&c=C&v=1")
                .contains("este mismo teléfono"),
        )
        assertTrue(
            reason("herdr-notify://pair?u=http%3A%2F%2Flocalhost%3A8788&c=C&v=1")
                .contains("este mismo teléfono"),
        )
    }

    @Test
    fun `surrounding spaces and newlines from a scan are trimmed`() {
        val payload = valid(
            "\n  herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=CODE&v=1 \n",
        )
        assertEquals("http://100.64.0.1:8788", payload.baseUrl)
        assertEquals("CODE", payload.code)
    }

    @Test
    fun `leading and trailing spaces inside a value do not change it`() {
        val payload = valid(
            "herdr-notify://pair?u=%20http%3A%2F%2F100.64.0.1%3A8788%20&c=%20CODE%20&v=1",
        )
        assertEquals("http://100.64.0.1:8788", payload.baseUrl)
        assertEquals("CODE", payload.code)
    }

    @Test
    fun `an over long payload is refused before it is parsed`() {
        val text = reason("herdr-notify://pair?u=http%3A%2F%2F100.64.0.1&c=" + "A".repeat(5000))
        assertTrue(text.contains("demasiado grande"))
    }

    @Test
    fun `a duplicate key keeps the first value`() {
        // A payload cannot append a second u= or c= to override the real one.
        val payload = valid(
            "herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=REAL&c=FAKE&v=1",
        )
        assertEquals("REAL", payload.code)
    }

    @Test
    fun `extra parameters are ignored, not trusted`() {
        val payload = valid(
            "herdr-notify://pair?u=http%3A%2F%2F100.64.0.1%3A8788&c=CODE&v=1&evil=1",
        )
        assertEquals("http://100.64.0.1:8788", payload.baseUrl)
        assertEquals("CODE", payload.code)
    }

    @Test
    fun `an empty or blank payload is refused`() {
        assertTrue(reason("").contains("vacío"))
        assertTrue(reason("   \n ").contains("vacío"))
    }

    @Test
    fun `an unparseable string is refused instead of crashing`() {
        val text = reason("herdr-notify://pair?a=b c")
        assertTrue(text.isNotEmpty())
    }
}
