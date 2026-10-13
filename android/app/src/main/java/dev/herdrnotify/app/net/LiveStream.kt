package dev.herdrnotify.app.net

import android.util.Log
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.ui.triage.TriageRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import java.io.IOException
import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/**
 * Keeps one signed SSE stream open and publishes what it says.
 *
 * The shape of this class is dictated by three facts about the gateway:
 *
 *  * **The stream is authenticated once, at connect.** `GET /v1/events` is a
 *    normal signed request; the connection it opens is then long-lived. So the
 *    signature has a timestamp in it, and a stream held open for longer than the
 *    gateway's skew window would be... fine, because verification happens at
 *    connect only. This matters for reconnect: a reconnect is a fresh signed
 *    request, not a resumption, and must carry a fresh nonce.
 *
 *  * **The gateway caps streams per device** and answers 429 beyond it. A
 *    reconnect loop that did not wait would be refused forever, so backoff is
 *    not optional.
 *
 *  * **The gateway sends a full state frame first.** A client that connects
 *    while events are queued still converges without a second round trip, which
 *    is why the stream alone is enough and no polling sits beside it.
 */
class LiveStream(
    private val client: GatewayClient,
    private val scope: CoroutineScope,
    private val random: Random = Random(SecureRandom().nextInt()),

) {
    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Connecting)

    /**
     * A [StateFlow], not a bare `Flow`, so a caller that misses an emission can
     * still read the current value synchronously. A `Flow` would force every
     * reader into a coroutine to learn what is on screen right now.
     */
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private var job: Job? = null
    private var lastGood: SessionState = SessionState.EMPTY
    private var lastGoodAt: Long = 0L

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch { loop() }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    /**
     * Read the full state now, rather than waiting for the stream's next frame.
     *
     * Called on connect, so a resume shows what the host has right now and not
     * whatever the last frame said. It is a separate request, not a stream frame,
     * so a failure here is not a stream failure: the stream reports its own.
     */
    fun refreshNow() {
        scope.launch {
            try {
                refresh()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Unauthorised lands here too. The stream sees the same answer on
                // its own request and reports it there, so nothing is lost.
                Log.w(TAG, "state refresh failed", e)
            }
        }
    }

    private suspend fun loop() {
        var attempt = 0
        while (scope.isActive) {
            try {
                // Only publish Connecting on the first attempt. On a reconnect
                // the previous Live value stays on screen, because replacing a
                // list someone is reading with a spinner is a worse experience
                // than a list that is a few seconds stale.
                if (attempt == 0) _state.value = ConnectionState.Connecting
                consume()
                // A clean end of stream is still a disconnect, so it goes
                // through the same backoff as a failure.
                _state.value = ConnectionState.Offline(lastGood, "stream closed", lastGoodAt)
                attempt = 0
            } catch (e: CancellationException) {
                throw e
            } catch (e: GatewayClient.GatewayError.Unauthorised) {
                // Retrying cannot fix this, and retrying forever would drain a
                // phone's battery telling the user nothing. Re-pairing is the
                // only way out, so the state says exactly that.
                Log.w(TAG, "device is not in the trust store; stopping", e)
                _state.value = ConnectionState.Failed("Este teléfono ya no está emparejado.")
                return
            } catch (e: GatewayClient.GatewayError.NotPermitted) {
                // Trusted but not allowed: the pairing is intact, so the state
                // must not say "re-pair". The fix is a host-side grant, and
                // retrying a stream that can never succeed would drain the
                // battery the same way, so this stops like Unauthorised.
                Log.w(TAG, "device is not permitted; stopping", e)
                _state.value = ConnectionState.Failed("El gateway denegó el acceso de este teléfono.")
                return
            } catch (e: Exception) {
                Log.w(TAG, "stream failed", e)
                _state.value = when (e) {

                    is GatewayClient.GatewayError -> ConnectionState.Failed(
                        e.message ?: "the gateway refused the request",
                    )

                    is IOException -> ConnectionState.Offline(lastGood, e.message, lastGoodAt)
                    else -> ConnectionState.Failed(e.message ?: "unexpected error")
                }
            }

            attempt++
            val wait = backoffMillis(attempt)
            Log.i(TAG, "stream down (attempt $attempt), reconnecting in ${wait}ms")
            delay(wait)
        }
    }

    /**
     * Read the stream to completion, publishing each frame.
     *
     * Suspends for the life of the connection, so `loop` stays parked here and
     * only resumes when the stream breaks — which is what keeps exactly one
     * connection open per device.
     */
    private suspend fun consume() = withContext(Dispatchers.IO) {
        val request = client.buildSigned("GET", "/v1/events").newBuilder()
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-store")
            .build()

        client.httpForStream().newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                // 401 has to surface as Unauthorised, not a generic rejection:
                // it is the one code that means "stop, this device is not in the
                // trust store", and the loop treats the two differently.
                // 403 is a different answer again — trusted but not allowed:
                // the pairing is intact, the grant is missing, and the fix is
                // host-side, so it surfaces as NotPermitted for the same
                // reason.
                when (response.code) {
                    401 -> throw GatewayClient.GatewayError.Unauthorised("not paired")
                    403 -> throw GatewayClient.GatewayError.NotPermitted("not permitted")
                    else -> throw GatewayClient.GatewayError.Rejected(
                        response.code,
                        "stream refused: ${response.code}",
                    )
                }
            }
            val body = response.body ?: throw IOException("empty stream body")
            val source = body.source()
            val parser = SseParser()

            // Read line by line straight off the source rather than buffering
            // fixed-size chunks. A chunked read waits until it has filled its
            // buffer, which an SSE stream never does — a 20-second keepalive
            // frame is 14 bytes, so a stream would sit silent until the socket
            // died. Reading lines yields each frame the moment it arrives.
            while (true) {
                val line = source.readUtf8Line() ?: break
                // onFrame re-reads the state on a change, so it suspends. That
                // serialises the refresh behind the stream reader, which is
                // deliberate: a burst of changes coalesces into one read rather
                // than a read per frame.
                parser.accept(line)?.let { onFrame(it) }
            }
        }
    }

    private suspend fun onFrame(frame: SseParser.Frame) {
        when (frame.event) {
            "state" -> {
                // The opening frame carries the full read model. This is the
                // only place the app learns its revision baseline.
                Wire.sseState(frame.data)?.let {
                    lastGood = it
                    lastGoodAt = System.currentTimeMillis()
                    _state.value = ConnectionState.Live(it, lastGoodAt)
                }
            }

            else -> {
                // A change frame. The gateway publishes the change, not the
                // whole state, so the correct response is to re-read rather
                // than to patch locally: a client that guessed at the merge
                // would drift from the host's own view of a session.
                val revision = Wire.revision(frame.data)
                if (revision != null && revision <= lastGood.revision && lastGood.revision != 0L) {
                    // Out of order. Applying it would visibly undo newer state.
                    return
                }
                refresh()
            }
        }
    }

    /** Re-read the full state after a change notification. */
    private suspend fun refresh() {
        val body = withContext(Dispatchers.IO) {
            try {
                client.state()
            } catch (e: GatewayClient.GatewayError.Unauthorised) {
                throw e
            } catch (e: Exception) {
                null
            }
        } ?: return
        Wire.state(body)?.let {
            // A read that races a newer change frame must not roll the screen
            // back. Equal revisions are allowed: a re-read of the same state is
            // harmless, and the timestamp still moves forward.
            if (it.revision < lastGood.revision) return
            lastGood = it
            lastGoodAt = System.currentTimeMillis()
            _state.value = ConnectionState.Live(it, lastGoodAt)
        }
    }

    /**
     * Exponential backoff, capped, with jitter.
     *
     * The jitter is not decoration. A gateway and the phones on its tailnet
     * usually go down and come back together — the laptop sleeps, the network
     * drops, the router reboots. Deterministic backoff means every device
     * computes the same interval and reconnects in the same instant, so the
     * gateway takes the whole fleet at once, immediately after it is ready. It
     * has a per-device stream cap, so the reconnect storm is exactly what turns
     * a routine wake-up into a burst of 429s.
     *
     * A full jitter would make the backoff untestable, so the spread is bounded
     * to 20%: enough to break synchronisation between devices, tight enough
     * that a test can assert a range. `internal` rather than private so that
     * range is checkable rather than assumed.
     */
    internal fun backoffMillis(attempt: Int): Long {
        val base = (BASE_BACKOFF_MS * (1L shl (attempt - 1).coerceAtMost(5)))
            .coerceAtMost(MAX_BACKOFF_MS)
        val spread = base / 5
        return (base - spread + random.nextLong(spread * 2 + 1))
            .coerceIn(BASE_BACKOFF_MS, MAX_BACKOFF_MS)
    }

    companion object {
        private const val TAG = "HerdrStream"
        private const val BASE_BACKOFF_MS = 1_000L
        private const val MAX_BACKOFF_MS = 30_000L
    }
}
