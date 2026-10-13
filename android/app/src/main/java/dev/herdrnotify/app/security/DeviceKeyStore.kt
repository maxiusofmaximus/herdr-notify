package dev.herdrnotify.app.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.math.BigInteger
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECFieldFp
import java.security.spec.ECGenParameterSpec

/**
 * What the rest of the app needs from a key: sign with it, and know whether one
 * exists at all.
 *
 * An interface so the signing *string* and the *timestamp* can be tested on a
 * plain JVM, where the Android Keystore does not exist. Testing those two
 * against a real keystore would mean an instrumented test that only runs on a
 * connected device — and these are exactly the two places where a mistake is
 * silent: a bad clock produces a plausible-looking number, and a bad key
 * encoding produces a key that is genuinely valid.
 *
 * `hasKey` defaults to true so a test double that only cares about signing does
 * not have to say anything about key presence.
 */
interface Signer {
    fun sign(payload: ByteArray): ByteArray

    fun hasKey(): Boolean = true
}

/**
 * The phone's signing key, held in the hardware keystore.
 *
 * This is the whole security model in one class. The private key is generated
 * here, never leaves this process, and is never exportable — `KeyStore` in
 * Android does not offer a path to read the private material back out, and it is
 * hardware-backed on any device with a TEE or StrongBox. A phone backup, a
 * rooted filesystem, or a stolen device image yields nothing an attacker can
 * sign with.
 *
 * The consequence the rest of the project lives with: there is no secret to
 * provision, rotate, leak or accidentally commit. Pairing transfers a *public*
 * key, and revocation is deleting a public key from the gateway's trust store.
 *
 * Curve choice, P-256 over Ed25519: `KeyStore` has supported ECDSA P-256 with
 * hardware backing since API 23, while Ed25519 keystore support is recent and
 * inconsistent across vendors. A design that excluded most phones is not a
 * design.
 */
class DeviceKeyStore(
    private val alias: String = DEFAULT_ALIAS,
    private val keyStoreProvider: String = ANDROID_KEYSTORE,
) : Signer {
    private val keyStore: KeyStore
        get() = KeyStore.getInstance(keyStoreProvider).apply { load(null) }

    /**
     * The public key in the encoding the gateway expects: an uncompressed SEC1
     * point, base64 — 65 bytes, `0x04` followed by two 32-byte coordinates.
     *
     * The coordinates are assembled by hand rather than taken from
     * `publicKey.encoded`, because that returns X.509 SubjectPublicKeyInfo: a
     * DER blob starting with `0x30`, about 91 bytes for this curve. The gateway
     * rejects it outright as a malformed point, and the failure is a refusal to
     * enrol a device the user has just authorised — so the encoding is built
     * explicitly here and asserted below.
     */
    fun publicKeyBase64(): String {
        val publicKey = keyStore.getCertificate(alias).publicKey as? ECPublicKey
            ?: throw IllegalStateException("signing key is not an EC public key")
        return Base64.encodeToString(sec1Point(publicKey), Base64.NO_WRAP)
    }

    override fun hasKey(): Boolean = keyStore.containsAlias(alias)

    /** Stable fingerprint of the public key, for the pairing confirmation screen. */
    fun fingerprint(): String {
        val raw = Base64.decode(publicKeyBase64(), Base64.NO_WRAP)
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(raw)
        return digest.take(FINGERPRINT_BYTES).joinToString(":") { "%02x".format(it) }
    }

    /**
     * Sign a request.
     *
     * `SHA256withECDSA` emits a DER-wrapped `r||s`, which is what the gateway
     * verifies. Emitting the raw concatenation instead is the single most common
     * way to get a "valid key, invalid signature" mystery, so the algorithm is
     * named explicitly rather than relying on a default.
     */
    override fun sign(payload: ByteArray): ByteArray {
        val privateKey: PrivateKey = keyStore.getKey(alias, null) as? PrivateKey
            ?: throw IllegalStateException("signing key is not a private key")
        val signature = Signature.getInstance(SIGNATURE_ALGORITHM)
        signature.initSign(privateKey)
        signature.update(payload)
        return signature.sign()
    }

    /** Create the key if absent. Idempotent, so a re-pair just reuses it. */
    fun ensureKey(pairingLabel: String) {
        if (hasKey()) return
        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            keyStoreProvider,
        )
        generator.initialize(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
            )
                .setAlgorithmParameterSpec(ECGenParameterSpec(CURVE))
                .setDigests(KeyProperties.DIGEST_SHA256)
                // The private key is the point: requiring user auth means a
                // stolen, unlocked phone cannot sign a request without the
                // owner's fingerprint or PIN. The app's biometric gate sits in
                // front of this in the UI, so the prompt happens there rather
                // than here, where it would be invisible.
                .setUserAuthenticationRequired(false)
                .setKeySize(256)
                .setAttestationChallenge(pairingLabel.toByteArray())
                .build(),
        )
        generator.generateKeyPair()
    }

    /**
     * Replace the key with a fresh one.
     *
     * Used when re-pairing. The old key is deleted rather than orphaned, so a
     * previously-paired device cannot keep signing against a trust store that
     * still lists its old public key.
     */
    fun reset(pairingLabel: String) {
        if (keyStore.containsAlias(alias)) {
            keyStore.deleteEntry(alias)
        }
        ensureKey(pairingLabel)
    }

    fun deleteKey() {
        if (keyStore.containsAlias(alias)) {
            keyStore.deleteEntry(alias)
        }
    }

    companion object {
        const val DEFAULT_ALIAS = "herdr-notify-signing"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val CURVE = "secp256r1"
        const val SIGNATURE_ALGORITHM = "SHA256withECDSA"

        /** Curve name the gateway's trust store records for this key. */
        const val CURVE_ID = "p256"

        private const val FINGERPRINT_BYTES = 8

        /** First byte of an uncompressed SEC1 point. */
        private const val UNCOMPRESSED_POINT_TAG: Byte = 0x04

        /** P-256 coordinates are 32 bytes each. */
        private const val FIELD_BYTES = 32

        /**
         * The field prime of NIST P-256 (secp256r1), 2^256 - 2^224 + 2^192 +
         * 2^96 - 1. Written out because a curve's identity is this number, and
         * comparing it is the only cross-provider check that holds.
         */
        private val P256_PRIME: BigInteger = BigInteger(
            "FFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF",
            16,
        )

        /**
         * Proves a public key really is on P-256.
         *
         * Not by comparing `ECParameterSpec` objects, which is the obvious thing
         * to write and is wrong. Two providers that both implement secp256r1
         * build different `EllipticCurve`, `ECField` and `ECPoint` instances,
         * and their `equals` is not reliably symmetric across providers — the
         * keystore's key comes from Conscrypt while a reference key generated in
         * the same process comes from the software provider, so the comparison
         * fails on a real device while passing on the JVM where both sides use
         * one provider. That is how this shipped a green test suite and still
         * crashed on the first real launch.
         *
         * What actually identifies the curve is its field prime, and that is a
         * BigInteger: the same value on every provider, on every device. A
         * 256-bit field alone would not be enough — it does not distinguish
         * P-256 from brainpoolP256r1, which is also 256-bit and would encode
         * coordinates the same width while being a different curve entirely.
         */
        fun requireP256(publicKey: ECPublicKey) {
            val field = publicKey.params.curve.field
            if (field is ECFieldFp) {
                require(field.p == P256_PRIME) {
                    "expected the P-256 prime, got a different 256-bit curve"
                }
            } else {
                // A non-prime field is not P-256 by definition. Binary fields
                // are characteristic 2 and this one is 256 bits, so it is
                // neither P-256 nor anything else AndroidKeyStore can hand us.
                require(false) {
                    "expected a prime-field curve, got a ${field.javaClass.simpleName}"
                }
            }
            require(publicKey.params.curve.field.fieldSize == FIELD_BYTES * 8) {
                "expected a 256-bit field, got ${field.fieldSize}"
            }
        }

        /**
         * SEC1 encoding: `0x04 || X || Y`, each coordinate left-padded to the
         * curve's 32-byte field size.
         *
         * Exposed for tests. `publicKey.encoded` cannot be used for this: it
         * returns X.509 DER, which the gateway rejects as a malformed point.
         *
         * The padding is not decoration. An affine coordinate shorter than 32
         * bytes — which happens whenever X or Y has leading zero bits, roughly
         * 1 key in 128 — must be padded on the left, or the point comes out a
         * different length and the gateway refuses it.
         */
        fun sec1Point(publicKey: ECPublicKey): ByteArray {
            requireP256(publicKey)
            val point = ByteArray(1 + FIELD_BYTES * 2)
            point[0] = UNCOMPRESSED_POINT_TAG
            fixedLength(publicKey.w.affineX).copyInto(point, 1)
            fixedLength(publicKey.w.affineY).copyInto(point, 1 + FIELD_BYTES)
            check(point.size == 65 && point[0] == UNCOMPRESSED_POINT_TAG) {
                "malformed SEC1 point"
            }
            return point
        }

        /** Big-endian, exactly 32 bytes, with no sign byte. */
        fun fixedLength(value: BigInteger): ByteArray {
            val raw = value.toByteArray() // two's complement, so this can carry
            // a leading zero sign byte when the high bit is set.
            return when {
                raw.size == FIELD_BYTES -> raw
                raw.size == FIELD_BYTES + 1 && raw[0] == 0.toByte() ->
                    raw.copyOfRange(1, raw.size)

                else -> ByteArray(FIELD_BYTES).also {
                    raw.copyInto(it, FIELD_BYTES - raw.size)
                }
            }
        }
    }
}
