package dev.herdrnotify.app.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The signed HTTP client.
 *
 * Every request carries the four `X-HN-*` headers, because the gateway's
 * authentication dependency runs before routing: there is no path in which a
 * request without them reaches a handler. That means the signing is not a
 * concern for individual call sites, and cannot be forgotten by one of them.
 *
 * Three failure modes get distinct types rather than a boolean, because the UI
 * has to react differently to each:
 *
 *  * [GatewayError.Unauthorised] — the device is not in the trust store, or the
 *    key does not match. Retrying cannot help; the user must pair again.
 *  * [GatewayError.NotPermitted] — the device is trusted but not allowed to do
 *    this: an authenticated request refused by the gateway's per-device
 *    authorization. Retrying cannot help either, but the pairing is intact —
 *    the fix is a host-side grant, never a re-pair.
 *  * everything else — the network or the host. Retrying is reasonable.
 */
class GatewayClient(
    private val baseUrl: String,
    private val deviceId: String,
    private val signer: RequestSigner,
    private val http: OkHttpClient = defaultClient(),
) {

    sealed class GatewayError(message: String) : IOException(message) {
        class Unauthorised(message: String) : GatewayError(message)
        class NotPermitted(message: String) : GatewayError(message)
        class Rejected(val code: Int, message: String) : GatewayError("$code: $message")
        class Unreachable(cause: String) : GatewayError(cause)
    }

    /** Raw response text, so callers can decode their own shape. */
    fun call(method: String, target: String, body: ByteArray = ByteArray(0)): String {
        val request = buildSigned(method, target, body)
        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw GatewayError.Unreachable(e.message ?: "cannot reach the gateway")
        }
        response.use {
            val text = it.body?.string().orEmpty()
            when (it.code) {
                200, 204 -> return text
                // 401 and 403 are different answers: authentication and
                // authorization. Conflating them would tell a user whose
                // pairing is intact to re-pair, which is the wrong fix.
                401 -> throw GatewayError.Unauthorised(text.ifBlank { "not paired" })
                403 -> throw GatewayError.NotPermitted(text.ifBlank { "not permitted" })
                429 -> throw GatewayError.Rejected(429, "slow down")
                400, 404, 409, 422 -> throw GatewayError.Rejected(it.code, summarise(text))
                else -> throw GatewayError.Rejected(it.code, summarise(text))
            }
        }
    }

    fun state(): String = call("GET", "/v1/state")

    fun respond(paneId: String, text: String): String = call(
        "POST",
        "/v1/agents/${paneId.urlEncoded()}/respond",
        json("""{"text":${text.asJsonString()}}"""),
    )

    fun sendKeys(paneId: String, keys: List<String>, confirm: Boolean): String = call(
        "POST",
        "/v1/agents/${paneId.urlEncoded()}/keys",
        json("""{"keys":[${keys.joinToString(",") { it.asJsonString() }}],"confirm":$confirm}"""),
    )

    fun read(paneId: String, lines: Int? = null): String = call(
        "POST",
        "/v1/agents/${paneId.urlEncoded()}/read",
        json(lines?.let { """{"lines":$it}""" } ?: "{}"),
    )

    fun fcmToken(token: String): String = call(
        "POST",
        "/v1/me/fcm-token",
        json("""{"fcm_token":${token.asJsonString()}}"""),
    )

    fun newChat(name: String): String = call(
        "POST",
        "/v1/workspaces",
        json("""{"name":${name.asJsonString()}}"""),
    )

    /**
     * The client the stream uses.
     *
     * Separate from [defaultClient] because a long-lived stream must not time
     * out. A read timeout that fires mid-stream would look like a disconnect and
     * start a reconnect loop, so the stream's client has no read timeout and
     * relies on the gateway's 20-second keepalives plus the caller's own
     * watchdog instead.
     */
    fun httpForStream(): OkHttpClient = streamHttp

    private val streamHttp: OkHttpClient = http.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    /** Build the signed request without sending it, so a stream can reuse it. */
    fun buildSigned(method: String, target: String, body: ByteArray = ByteArray(0)): Request {
        val signed = signer.sign(method, target, body, deviceId)
        val builder = Request.Builder()
            .url(baseUrl.trimEnd('/') + target)
            .header("X-HN-Device", signed.deviceId)
            .header("X-HN-Timestamp", signed.timestamp.toString())
            .header("X-HN-Nonce", signed.nonce)
            .header("X-HN-Signature", signed.signature)
            .header("Accept", "application/json")
        // The wire method must be the one the signature covers. Choosing it from
        // the body's emptiness would send an empty-bodied POST as a GET while
        // signing POST, so a POST-only route would answer 405 before
        // authentication even ran.
        when (method.uppercase()) {
            "GET" -> builder.get()
            "POST" -> builder.post(body.toRequestBody(JSON_MEDIA))
            else -> builder.method(method.uppercase(), body.toRequestBody(JSON_MEDIA))
        }
        return builder.build()
    }

    companion object {
        val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        /**
         * Timeouts tuned for a tailnet link, not a datacentre.
         *
         * Read timeout is long because a signed request is cheap and the phone
         * may be on a phone tether; the connect timeout is short because there
         * is nothing useful to wait for if the host is not answering at all.
         */
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            // The SSE stream must not be buffered or reconnected behind the
            // app's back, so retries are left off: a reconnect has to be visible
            // as a reconnect.
            .retryOnConnectionFailure(false)
            .tailnetCleartextOnly()
            .build()
    }
}

/**
 * Percent-encode a path segment, keeping the characters that a path segment
 * legally allows.
 *
 * RFC 3986 defines `pchar` as unreserved / pct-encoded / sub-delims / ":" / "@",
 * so a colon is *legal* in a path segment and must be left alone. Escaping it
 * would be a security-neutral but fatal bug: the signature covers the target as
 * written, while the gateway verifies against `raw_path`, which is the
 * percent-encoded form of what actually went over the wire. Signing
 * `/v1/agents/w3:p1/respond` and sending `/v1/agents/w3%3Ap1/respond` makes
 * every single write fail with a bad-signature error, while looking entirely
 * correct in review.
 *
 * A slash still has to be encoded: it is not in `pchar`, and leaving it raw would
 * let a crafted pane id address a different endpoint.
 */
internal fun String.urlEncoded(): String = buildString {
    for (byte in this@urlEncoded.toByteArray(Charsets.UTF_8)) {
        val c = byte.toInt().toChar()
        if (c.isLetterOrDigit() || c in "-._~" || c == ':' || c == '@') {
            append(c)
        } else {
            append('%').append("%02X".format(byte.toInt() and 0xFF))
        }
    }
}

private fun json(text: String) = text.toByteArray(Charsets.UTF_8)

/**
 * Pull a human-readable message out of an error body.
 *
 * The gateway answers errors as `{"detail": ...}`, and `detail` is sometimes a
 * string and sometimes an object with `code` and `message`. Both are read, and
 * anything unrecognised is truncated rather than shown raw, because a raw
 * FastAPI traceback on a phone is noise the user cannot act on.
 */
internal fun summarise(body: String): String {
    if (body.isBlank()) return "no detail"
    return runCatching {
        val detail = Wire.json.parseToJsonElement(body).let { element ->
            (element as? kotlinx.serialization.json.JsonObject)?.get("detail")
        }
        when (detail) {
            is kotlinx.serialization.json.JsonPrimitive -> detail.content
            is kotlinx.serialization.json.JsonObject ->
                detail["message"]?.let { (it as kotlinx.serialization.json.JsonPrimitive).content }
                    ?: detail["code"]?.let { (it as kotlinx.serialization.json.JsonPrimitive).content }
                    ?: detail.toString()

            else -> null
        }?.takeIf { it.isNotBlank() } ?: body.take(120)
    }.getOrDefault(body.take(120))
}

/**
 * Minimal JSON string escaping.
 *
 * The bodies here are objects with one or two fields, so a full serialiser
 * would be more machinery than the job needs. What it must not do is emit a
 * body the signing string and the gateway disagree about — and it cannot,
 * because the bytes are hashed after this function returns, from the same array
 * that gets sent.
 */
internal fun String.asJsonString(): String = buildString {
    append('"')
    for (c in this@asJsonString) {
        when (c) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            '\b' -> append("\\b")
            '' -> append("\\f")
            else -> if (c < ' ') {
                append("\\u%04x".format(c.code))
            } else {
                append(c)
            }
        }
    }
    append('"')
}
