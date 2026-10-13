package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.tailnetCleartextOnly
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume

/**
 * Finds which of several addresses for the same gateway answers right now.
 *
 * A paired phone can reach its host by more than one address (the saved one,
 * a tailnet name, a tailnet IP). This probes all of them at once against the
 * unauthenticated `/v1/health` and returns the first in priority order that
 * says `ok: true`. Priority order, not arrival order, decides the winner, so the
 * answer does not change with network timing.
 *
 * Every probe is bounded by [timeoutMs] in total, so a dead address costs the
 * user at most that wait, never a hang. Returns null when none answers.
 */
class AddressProber(
    private val http: OkHttpClient = defaultClient(),
    private val timeoutMs: Long = DEFAULT_TIMEOUT_MS,
) {

    /** The first of [candidates] that answers healthy, or null. */
    suspend fun firstHealthy(candidates: List<String>): String? {
        val urls = candidates.map { Pairing.normaliseUrl(it) }.filter { it.isNotEmpty() }.distinct()
        if (urls.isEmpty()) return null
        return coroutineScope {
            val probes = urls.map { url -> async { url to isHealthy(url) } }
            // Await in priority order: the earliest candidate that is healthy wins.
            probes.map { it.await() }.firstOrNull { it.second }?.first
        }
    }

    /**
     * True only if [baseUrl] answers `/v1/health` with `ok: true` within [timeoutMs].
     * The call is cancelled on timeout, so a hanging address does not hold up the others.
     */
    private suspend fun isHealthy(baseUrl: String): Boolean {
        val request = Request.Builder().url(baseUrl.trimEnd('/') + "/v1/health").get().build()
        val call = http.newCall(request)
        return withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                cont.invokeOnCancellation { call.cancel() }
                call.enqueue(object : Callback {
                    // Refused, unreachable or cancelled: this address does not count.
                    override fun onFailure(call: Call, e: IOException) {
                        cont.resume(false)
                    }

                    override fun onResponse(call: Call, response: Response) {
                        val healthy = response.use {
                            try {
                                it.isSuccessful &&
                                    Json.parseToJsonElement(it.body?.string().orEmpty())
                                        .jsonObject["ok"]?.jsonPrimitive?.booleanOrNull == true
                            } catch (e: Exception) {
                                // Not JSON: this address does not count.
                                false
                            }
                        }
                        cont.resume(healthy)
                    }
                })
            }
        } ?: false
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS = 3_000L

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(DEFAULT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            .readTimeout(DEFAULT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            .callTimeout(DEFAULT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            .tailnetCleartextOnly()
            .build()
    }
}
