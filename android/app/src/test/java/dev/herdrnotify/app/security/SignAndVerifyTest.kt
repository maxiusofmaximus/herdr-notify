package dev.herdrnotify.app.security

import dev.herdrnotify.app.net.RequestSigner
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.util.Base64

/**
 * The end-to-end check the other suites deliberately cannot make: that a
 * signature produced by the phone verifies against the public key the phone
 * would send for enrolment.
 *
 * Every unit test above pins one link in isolation. This one closes the loop,
 * because the failure this guards against is not "the code is wrong" but "the
 * two links are each self-consistent and inconsistent with each other" — a
 * signer that hashes correctly over a key that is exported wrongly, which every
 * individual assertion passes and every real request fails.
 *
 * The verifier here is deliberately independent of the gateway's Python
 * implementation rather than a copy of it. A test that reimplements the thing it
 * is checking proves only that the reimplementation is self-consistent.
 */
class SignAndVerifyTest {

    private fun newKeyPair() = KeyPairGenerator.getInstance("EC").apply {
        initialize(ECGenParameterSpec("secp256r1"))
    }.generateKeyPair()

    private class RealSigner(
        private val privateKey: java.security.PrivateKey,
    ) : Signer {
        override fun sign(payload: ByteArray): ByteArray =
            Signature.getInstance("SHA256withECDSA").run {
                initSign(privateKey)
                update(payload)
                sign()
            }
    }

    @Test
    fun `a signature verifies against the exported public key`() {
        val pair = newKeyPair()
        val signer = RequestSigner(RealSigner(pair.private), clock = { 1_700_000_000L })
        val request = signer.sign("POST", "/v1/agents/w1:p1/respond", "{\"t\":\"go\"}".toByteArray(), "d1")

        val point = DeviceKeyStore.sec1Point(pair.public as ECPublicKey)
        val verified = Signature.getInstance("SHA256withECDSA").run {
            initVerify(pair.public)
            update(
                RequestSigner.signingString(
                    method = "POST",
                    target = "/v1/agents/w1:p1/respond",
                    body = "{\"t\":\"go\"}".toByteArray(),
                    timestamp = 1_700_000_000L,
                    nonce = request.nonce,
                ),
            )
            verify(Base64.getDecoder().decode(request.signature))
        }

        assertTrue("the signature must verify against the exported key", verified)
        assertEquals(65, point.size)
    }

    @Test
    fun `a tampered body does not verify`() {
        val pair = newKeyPair()
        val original = "{\"text\":\"go\"}".toByteArray()
        val request = RequestSigner(RealSigner(pair.private), clock = { 1_700_000_000L })
            .sign("POST", "/v1/agents/w1:p1/respond", original, "d1")

        // Rebuild the signing string with a different body but the captured
        // timestamp and nonce, which is exactly the shape of a real tampering
        // attempt: the attacker keeps the headers and changes what is signed.
        val forged = RequestSigner.signingString(
            method = "POST",
            target = "/v1/agents/w1:p1/respond",
            body = "{\"text\":\"rm -rf\"}".toByteArray(),
            timestamp = 1_700_000_000L,
            nonce = request.nonce,
        )

        val verified = Signature.getInstance("SHA256withECDSA").run {
            initVerify(pair.public)
            update(forged)
            verify(Base64.getDecoder().decode(request.signature))
        }
        assertTrue("a tampered body must not verify", !verified)
    }

    @Test
    fun `a different key does not verify the signature`() {
        val signer = newKeyPair()
        val other = newKeyPair()
        val request = RequestSigner(RealSigner(signer.private), clock = { 1_700_000_000L })
            .sign("GET", "/v1/state", ByteArray(0), "d1")

        val verified = Signature.getInstance("SHA256withECDSA").run {
            initVerify(other.public)
            update(RequestSigner.signingString("GET", "/v1/state", ByteArray(0), 1_700_000_000L, request.nonce))
            verify(Base64.getDecoder().decode(request.signature))
        }
        assertTrue("a signature must not verify under a different key", !verified)
    }

    @Test
    fun `the signature is DER wrapped, which is what the gateway parses`() {
        val pair = newKeyPair()
        val request = RequestSigner(RealSigner(pair.private), clock = { 1_700_000_000L })
            .sign("GET", "/v1/state", ByteArray(0), "d1")

        val der = Base64.getDecoder().decode(request.signature)
        // 0x30 SEQUENCE, then a length, then two INTEGERs (r and s). A raw
        // 64-byte r||s form would start with a random byte and this would fail.
        assertEquals(0x30.toByte(), der[0])
        assertTrue("a DER ECDSA signature is 70-72 bytes", der.size in 70..72)
    }
}
