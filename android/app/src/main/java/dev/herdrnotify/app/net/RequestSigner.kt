package dev.herdrnotify.app.net

import dev.herdrnotify.app.security.Signer
import java.security.MessageDigest
import java.util.Base64
import java.security.SecureRandom
import java.util.Locale

/**
 * Builds the exact bytes the gateway verifies, and signs them.
 *
 * The two sides must agree byte for byte or every request fails with a
 * signature error, which looks like an attack rather than a disagreement about a
 * newline. The rules the gateway enforces are therefore mirrored here literally:
 *
 *  * the body is hashed, never signed raw, so a re-serialisation cannot diverge
 *  * the target is the raw request target, query string included
 *  * the method is upper-cased
 *  * every field is newline-terminated, including the last
 *  * no field may contain a newline, so two requests cannot produce one string
 *
 * A JVM unit test asserts these bytes against a golden value; the gateway's own
 * test suite asserts the same bytes from the other end.
 */
class RequestSigner(
    private val keys: Signer,
    private val random: SecureRandom = SecureRandom(),
    // Seconds, not milliseconds. The gateway compares the signed timestamp
    // against its own clock in seconds, so a millisecond value is a number
    // roughly fifty-five thousand times too large and every request is rejected
    // as stale. Converting here rather than at the call site keeps the unit out
    // of every caller's hands.
    private val clock: () -> Long = { System.currentTimeMillis() / 1000L },
) {
    data class Signed(
        val deviceId: String,
        val timestamp: Long,
        val nonce: String,
        val signature: String,
    )

    fun sign(
        method: String,
        target: String,
        body: ByteArray,
        deviceId: String,
    ): Signed {
        val timestamp = clock()
        val nonceBytes = ByteArray(NONCE_BYTES).also(random::nextBytes)
        val nonce = ENCODER.encodeToString(nonceBytes)

        val payload = signingString(method, target, body, timestamp, nonce)
        val signature = ENCODER.encodeToString(keys.sign(payload))
        return Signed(
            deviceId = deviceId,
            timestamp = timestamp,
            nonce = nonce,
            signature = signature,
        )
    }

    companion object {
        const val NONCE_BYTES = 16

        /**
         * `java.util.Base64`, not `android.util.Base64`.
         *
         * The Android variant is a stub in unit tests and returns null there, so
         * using it would make every signing test fail for a reason that has
         * nothing to do with signing. The platform class is available from API
         * 26, and minSdk here is 26.
         */
        private val ENCODER: Base64.Encoder = Base64.getEncoder()

        /**
         * The signing string. Kept as a pure function so a unit test can pin its
         * output without a device, a keystore, or a network.
         */
        fun signingString(
            method: String,
            target: String,
            body: ByteArray,
            timestamp: Long,
            nonce: String,
        ): ByteArray {
            require(target.startsWith("/")) { "target must be an absolute path: $target" }
            require('\n' !in target && '\r' !in target) { "target must not contain a newline" }
            require('\n' !in nonce && '\r' !in nonce) { "nonce must not contain a newline" }
            require(nonce.isNotEmpty()) { "nonce is required" }

            val fields = listOf(
                method.uppercase(Locale.ROOT),
                target,
                bodyDigest(body),
                timestamp.toString(),
                nonce,
            )
            return (fields.joinToString("\n", postfix = "\n")).toByteArray(Charsets.UTF_8)
        }

        fun bodyDigest(body: ByteArray): String {
            val digest = MessageDigest.getInstance("SHA-256").digest(body)
            return buildString(digest.size * 2) {
                for (byte in digest) {
                    append("%02x".format(byte))
                }
            }
        }
    }
}
