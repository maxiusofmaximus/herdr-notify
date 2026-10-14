package dev.herdrnotify.app.pairing

import java.net.URI
import java.net.URISyntaxException
import java.net.URLDecoder

/**
 * The text a pairing QR carries, once it has been read and trusted to be ours.
 *
 * Only two facts survive parsing: where the gateway is, and the short code that
 * registers this phone with it. Everything the scanner saw is discarded, so a
 * payload with extra fields cannot smuggle anything past the app.
 */
data class PairingQrPayload(
    val baseUrl: String,
    val code: String,
) {
    companion object {

        const val SCHEME = "herdr-notify"
        const val HOST = "pair"
        const val VERSION = "1"

        /**
         * The most a pairing payload can be before it is refused outright.
         *
         * A real payload is a short URL and a code; anything much longer is not
         * one, and reading an arbitrarily large string off a QR only wastes
         * memory on a code that was never going to match.
         */
        const val MAX_LENGTH = 2048

        /**
         * The pure parser: a scanned string in, a payload or a reason out.
         *
         * The gateway prints a QR whose text is
         * `herdr-notify://pair?u=<url>&c=<code>&v=1`; the camera hands the app a
         * string and nothing else. That string is untrusted input — it can come
         * from any code on any screen — so it is checked against the contract and
         * against the same address rules the manual flow already enforces, rather
         * than passed through to the network as if it were typed by the operator.
         *
         * Pure and Context-free on purpose: every branch below is a case a
         * hostile or merely wrong QR can produce, and this is where they are
         * pinned down in a JVM test.
         */
        fun parse(raw: String): PairingQrResult {
            val text = raw.trim()
            if (text.isEmpty()) return invalid("El código QR está vacío.")
            if (text.length > MAX_LENGTH) {
                return invalid("El código QR es demasiado grande para procesarlo.")
            }

            val uri = try {
                URI(text)
            } catch (e: URISyntaxException) {
                return invalid("El código QR no se pudo leer.")
            }

            // The scheme and the host together are what make a payload ours. A
            // different app's QR, or a plain web link, is refused here and never
            // reaches the pairing request.
            if (!SCHEME.equals(uri.scheme, ignoreCase = true)) {
                return invalid("Este código QR no es de herdr notify.")
            }
            if (!HOST.equals(uri.host, ignoreCase = true)) {
                return invalid("Este código QR no es de emparejamiento.")
            }

            val params = queryParams(uri.rawQuery)

            // A newer schema would carry fields this build does not know how to
            // use; guessing at it is worse than telling the operator to update.
            val version = params["v"]
            if (version != null && version != VERSION) {
                return invalid("Este código QR es de una versión más nueva; actualiza la app.")
            }

            val url = params["u"]?.trim().orEmpty()
            val code = params["c"]?.trim().orEmpty()
            if (url.isEmpty()) return invalid("Al código QR le falta la dirección del equipo.")
            if (code.isEmpty()) return invalid("Al código QR le falta el código de emparejamiento.")

            // Unlike the manual field, a scanned URL is not guessed a scheme for:
            // the gateway always emits a full URL, so a bare host means the
            // payload is not the one we expect. Guessing here would hide a broken
            // emitter.
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                return invalid("La dirección del QR no empieza por http:// ni https://.")
            }

            // Same rule as the manual flow: an address that points at this phone
            // can only fail, and storing it would make the app look paired but
            // never connect.
            if (Pairing.isLoopbackUrl(url)) {
                return invalid("El código QR apunta a este mismo teléfono, no al equipo.")
            }

            return PairingQrResult.Valid(PairingQrPayload(baseUrl = url, code = code))
        }

        private fun invalid(reason: String): PairingQrResult = PairingQrResult.Invalid(reason)

        /**
         * The query as a map, first value winning, tolerant of a missing `=`.
         *
         * Written by hand rather than with `android.net.Uri` so the parser stays
         * pure and testable off-device; a duplicate key keeps the first value so
         * a payload cannot append a second `u=` or `c=` to override the real one.
         */
        private fun queryParams(rawQuery: String?): Map<String, String> {
            if (rawQuery.isNullOrEmpty()) return emptyMap()
            val result = LinkedHashMap<String, String>()
            for (pair in rawQuery.split('&')) {
                if (pair.isEmpty()) continue
                val eq = pair.indexOf('=')
                val key = if (eq < 0) pair else pair.substring(0, eq)
                val value = if (eq < 0) "" else pair.substring(eq + 1)
                val decodedKey = decode(key)
                if (decodedKey in result) continue
                result[decodedKey] = decode(value)
            }
            return result
        }

        /**
         * Best-effort percent-decoding.
         *
         * A malformed escape is left as-is rather than throwing: it will simply
         * fail to match the scheme or host checks above, which is the outcome a
         * bad payload deserves.
         */
        private fun decode(value: String): String = try {
            URLDecoder.decode(value, "UTF-8")
        } catch (e: IllegalArgumentException) {
            value
        }
    }
}

/** What [PairingQrPayload.parse] decided about a scanned string. */
sealed interface PairingQrResult {
    data class Valid(val payload: PairingQrPayload) : PairingQrResult
    data class Invalid(val reason: String) : PairingQrResult
}
