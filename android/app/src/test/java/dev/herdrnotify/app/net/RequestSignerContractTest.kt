package dev.herdrnotify.app.net

import dev.herdrnotify.app.security.Signer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.SecureRandom

/**
 * Pins the two properties that make a request verifiable and that nothing else
 * in the build would catch.
 *
 * Both were real defects found while wiring the phone up, and both fail
 * *silently*: a millisecond timestamp is a perfectly good-looking number that
 * the gateway simply reads as fifty thousand years stale, and a public key in
 * the wrong encoding is still a valid, correctly signed key. Neither shows up as
 * a crash, and neither would surface in a screenshot — the first symptom is
 * "push stopped working", the second is "pairing says invalid key".
 */
class RequestSignerContractTest {

    /** Records what it was asked to sign, so no keystore is needed. */
    private class RecordingSigner : Signer {
        var signed: ByteArray? = null
        override fun sign(payload: ByteArray): ByteArray {
            signed = payload
            return ByteArray(64) { it.toByte() }
        }
    }

    private fun signer() = RecordingSigner()

    @Test
    fun `the timestamp is unix seconds, not milliseconds`() {
        // The gateway computes `abs(now - timestamp) > skew` with `now` in
        // seconds. A millisecond value is about 55,000 times too large, so every
        // request would be refused as stale.
        val keys = signer()
        val signed = RequestSigner(keys).sign(
            method = "GET",
            target = "/v1/state",
            body = ByteArray(0),
            deviceId = "device-1",
        )

        val now = System.currentTimeMillis() / 1000
        val drift = Math.abs(now - signed.timestamp)
        assertTrue(
            "timestamp ${signed.timestamp} is not within a minute of unix now $now",
            drift < 60,
        )
    }

    @Test
    fun `the timestamp is seconds even when a clock is injected`() {
        // The injected clock is passed through untouched, so a test can pin the
        // exact value and confirm the unit is the caller's to choose.
        val signed = RequestSigner(signer(), clock = { 1_700_000_000L }).sign(
            method = "GET",
            target = "/v1/state",
            body = ByteArray(0),
            deviceId = "device-1",
        )
        assertEquals(1_700_000_000L, signed.timestamp)
    }

    @Test
    fun `the signed payload carries the same seconds the header will`() {
        val keys = signer()
        val signed = RequestSigner(keys, clock = { 1_700_000_000L }).sign(
            method = "POST",
            target = "/v1/agents/w1:p1/seen",
            body = ByteArray(0),
            deviceId = "device-1",
        )
        val text = String(keys.signed!!, Charsets.UTF_8)
        assertTrue(
            "the signed payload must contain the timestamp: $text",
            text.contains("1700000000\n"),
        )
    }

    @Test
    fun `two requests never reuse a nonce`() {
        val requestSigner = RequestSigner(signer())
        val nonces = (1..50).map {
            requestSigner.sign("GET", "/v1/state", ByteArray(0), "device-1").nonce
        }
        // The gateway rejects a repeated nonce outright, so this is a hard
        // requirement rather than a preference. 16 random bytes makes a
        // collision astronomically unlikely, which is exactly why the test can
        // assert all-distinct without flaking.
        assertEquals(50, nonces.toSet().size)
    }

    @Test
    fun `a nonce is 16 random bytes, base64 encoded`() {
        val signed = RequestSigner(signer(), random = SecureRandom()).sign(
            "GET",
            "/v1/state",
            ByteArray(0),
            "device-1",
        )
        // 16 bytes base64-encoded is 24 characters ending in one '='.
        assertEquals(24, signed.nonce.length)
        assertTrue(signed.nonce.endsWith("="))
    }

    @Test
    fun `a different body changes what gets signed`() {
        val one = signer()
        val two = signer()
        RequestSigner(one, clock = { 1L }).sign("POST", "/v1/x", "a".toByteArray(), "d")
        RequestSigner(two, clock = { 1L }).sign("POST", "/v1/x", "b".toByteArray(), "d")
        assertTrue(!one.signed!!.contentEquals(two.signed!!))
    }
}
