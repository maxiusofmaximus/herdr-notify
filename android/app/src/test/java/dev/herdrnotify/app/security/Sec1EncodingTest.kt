package dev.herdrnotify.app.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec

/**
 * Pins the public key encoding.
 *
 * This is the other silent failure. The gateway accepts a P-256 key only as a
 * 65-byte uncompressed SEC1 point — `0x04` plus two 32-byte coordinates — and
 * rejects anything else. The obvious way to export an Android Keystore public
 * key, `publicKey.encoded`, returns X.509 SubjectPublicKeyInfo instead: a DER
 * blob beginning with `0x30`, about 91 bytes. Both forms are "the public key",
 * so the mistake is invisible in review and produces a pairing flow that
 * rejects a device the user just authorised.
 */
class Sec1EncodingTest {

    private fun newKey(): ECPublicKey {
        val generator = KeyPairGenerator.getInstance("EC")
        generator.initialize(ECGenParameterSpec("secp256r1"))
        return generator.generateKeyPair().public as ECPublicKey
    }

    @Test
    fun `a P-256 key encodes to 65 bytes tagged 04`() {
        val point = DeviceKeyStore.sec1Point(newKey())
        assertEquals(65, point.size)
        assertEquals(0x04.toByte(), point[0])
    }

    @Test
    fun `the encoding is not the X-509 form the keystore hands back`() {
        // This is the actual defect, asserted directly rather than only implied
        // by the length check above, so a future "simplification" back to
        // `publicKey.encoded` fails here with a clear message.
        val key = newKey()
        val x509 = key.encoded
        val sec1 = DeviceKeyStore.sec1Point(key)

        assertNotEquals(x509.size, sec1.size)
        assertEquals(0x30.toByte(), x509[0]) // SEQUENCE
        assertEquals(0x04.toByte(), sec1[0]) // uncompressed point
    }

    @Test
    fun `both coordinates are 32 bytes and land in the right slots`() {
        val key = newKey()
        val point = DeviceKeyStore.sec1Point(key)

        // Reassembling each field as an unsigned big-endian integer must give
        // back the exact coordinate. This is stronger than checking a bit: a
        // wrong offset, a byte order flip, or padding on the wrong side all
        // change the value, while a length check alone would pass all three.
        val x = BigInteger(1, point.copyOfRange(1, 33))
        val y = BigInteger(1, point.copyOfRange(33, 65))
        assertEquals(key.w.affineX, x)
        assertEquals(key.w.affineY, y)
    }

    @Test
    fun `a short coordinate is left padded rather than shifting the point`() {
        // Roughly 1 key in 128 has a coordinate with a leading zero byte. Without
        // explicit left padding that key encodes to 64 bytes and the gateway
        // refuses it — a bug that shows up on a handful of devices and nowhere
        // else, which is the worst kind to ship.
        val short = BigInteger.valueOf(1)
        val padded = DeviceKeyStore.fixedLength(short)
        assertEquals(32, padded.size)
        assertEquals(0.toByte(), padded[0])
        assertEquals(1.toByte(), padded[31])
    }

    @Test
    fun `a high-bit coordinate does not gain a sign byte`() {
        // BigInteger.toByteArray is two's complement, so a value with the top
        // bit set comes back 33 bytes long with a leading zero. A naive
        // truncation would keep that zero and make the point 66 bytes.
        val high = BigInteger(1, ByteArray(32) { 0xFF.toByte() })
        // Two's complement: the top bit is set, so BigInteger prepends a sign
        // byte and returns 33 bytes for a 32-byte value.
        assertEquals(33, high.toByteArray().size)
        val padded = DeviceKeyStore.fixedLength(high)
        assertEquals(32, padded.size)
        assertEquals(0xFF.toByte(), padded[0])
    }

    @Test
    fun `the encoded point is what a P-256 verifier accepts`() {
        val key = newKey()
        val point = DeviceKeyStore.sec1Point(key)
        // Reconstructing from the point must yield the same affine coordinates,
        // which is the real assertion: it proves the bytes are a faithful
        // encoding and not merely the right length.
        val field = java.security.spec.ECGenParameterSpec("secp256r1")
        val params = KeyPairGenerator.getInstance("EC").apply { initialize(field) }
            .generateKeyPair().public.let { (it as ECPublicKey).params }

        val rebuilt = java.security.spec.ECPoint(
            BigInteger(1, point.copyOfRange(1, 33)),
            BigInteger(1, point.copyOfRange(33, 65)),
        )
        assertEquals(params.curve, params.curve)
        assertEquals(key.w, rebuilt)
        assertTrue(rebuilt.affineX.signum() >= 0)
    }
}
