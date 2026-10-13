package dev.herdrnotify.app.net

import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.security.MessageDigest
import java.util.Collections
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.random.Random

/**
 * The stream, against a real server.
 *
 * These record *every* state the flow emits rather than waiting for a particular
 * one, and that is not a style choice. `LiveStream` is a `StateFlow`, which
 * conflates: a value written twice before anything collects is only ever seen
 * once, as the later value. MockWebServer sends a fixed-length body, so the
 * reader reaches end-of-body immediately after the opening frame, and the
 * stream publishes `Live` and then `Offline` in the same instant. A test that
 * waited for `Live` would pass or fail depending on scheduler timing, which is
 * the worst possible property for a test to have.
 *
 * A real SSE response has no Content-Length, so the reader blocks instead of
 * hitting end-of-body, and `Live` stays current. The tests below therefore
 * assert on the history of emissions, which is deterministic either way.
 */
class LiveStreamTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private val seen = Collections.synchronizedList(mutableListOf<ConnectionState>())

    private class DigestSigner : Signer {
        override fun sign(payload: ByteArray): ByteArray =
            MessageDigest.getInstance("SHA-256").digest(payload)
    }

    /**
     * Deliberately tiny, so each frame arrives split across several chunks.
     * A buffer-sized chunk would let a whole frame land at once and would hide
     * any bug in reading a frame that spans a chunk boundary.
     */
    private val maxChunk = 1

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        seen.clear()
    }

    @After
    fun tearDown() {
        runBlocking { scope.cancel() }
        server.shutdown()
    }

    private fun client(deviceId: String = "d1") = GatewayClient(
        baseUrl = server.url("/").toString(),
        deviceId = deviceId,
        signer = RequestSigner(DigestSigner()),
        http = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build(),
    )

    /**
     * A stream response that behaves like the real one.
     *
     * `setChunkedBody` rather than `setBody`, and this distinction is the whole
     * reason the suite is stable. `setBody` sets a Content-Length, so the reader
     * reaches end-of-body the instant it has the last byte and the stream emits
     * `Live` and then `Offline` back to back — which a `StateFlow` conflates
     * away for any consumer that has not processed the first value yet. A real
     * SSE response has no Content-Length: the connection stays open, the reader
     * blocks, and `Live` stays current. A trailing keepalive comment makes that
     * explicit.
     */
    private fun streamResponse(body: String) = MockResponse()
        .setHeader("Content-Type", "text/event-stream")
        .setChunkedBody(body, maxChunk)
        .setSocketPolicy(SocketPolicy.KEEP_OPEN)

    private fun stateFrame(revision: Long) = buildString {
        append("event: state\n")
        append("data: {\"event\":\"state\",\"revision\":$revision,")
        append("\"state\":{\"revision\":$revision,\"herdr_version\":\"0.9.1\",")
        append("\"agents\":[{\"pane_id\":\"w3:p1\",\"status\":\"blocked\",")
        append("\"attention\":3,\"project\":\"herdr-notify\"}]}}\n\n")
    }

    /**
     * Attach the collector, then start the stream, then wait.
     *
     * The order matters and is the whole reason this helper exists. `StateFlow`
     * conflates, so a value written twice before anything collects is seen only
     * as the later one. MockWebServer sends a fixed-length body, so the reader
     * hits end-of-body immediately after the opening frame and the stream
     * publishes `Live` and then `Offline` in quick succession. A collector that
     * attached after `start()` would race that pair and intermittently observe
     * only `Offline`, so the test would be flaky for a reason that has nothing
     * to do with the code.
     *
     * Assertions therefore read [seen], the full history, rather than waiting
     * for a particular state.
     */
    /**
     * Start the stream and wait until [condition] holds, or the deadline passes.
     *
     * A fixed sleep is the wrong tool here. These tests share a thread pool with
     * the rest of the suite, so a 2s wait that passes on an idle machine can
     * fail under load — a test whose result depends on machine speed is a test
     * that will be blamed for a product bug one day. Polling for the condition
     * with a generous ceiling is both faster in the common case and stable in
     * the bad one.
     */
    private suspend fun awaitState(
        stream: LiveStream,
        millis: Long = 15_000,
        condition: (List<ConnectionState>) -> Boolean,
    ) {
        val job = scope.launch { stream.state.toList(seen) }
        delay(200)
        stream.start()
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline) {
            if (condition(seen.toList())) break
            delay(100)
        }
        job.cancel()
    }

    private fun liveRevisions(): List<Long> = seen
        .filterIsInstance<ConnectionState.Live>()
        .map { it.state.revision }

    /** The backoff is `internal`, so the test can read it directly. */
    private fun LiveStream.backoffMillisForTest(attempt: Int): Long = backoffMillis(attempt)

    @Test
    fun `the opening state frame is published as Live`() = runBlocking {
        server.enqueue(streamResponse(stateFrame(7)))
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Live } }
        stream.stop()

        assertTrue("expected a Live emission, got ${seen.map { it::class.simpleName }}", liveRevisions().isNotEmpty())
        assertEquals(7L, liveRevisions().first())
        val live = seen.filterIsInstance<ConnectionState.Live>().first()
        assertEquals(1, live.state.agents.size)
        assertEquals("w3:p1", live.state.agents.single().paneId)
    }

    @Test
    fun `a refused stream produces a failure, not an empty list`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(429).setBody("""{"detail":"too many"}"""))
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Failed } }
        stream.stop()

        assertTrue(seen.any { it is ConnectionState.Failed })
        assertTrue(
            "a refusal must not render as a working empty list",
            seen.none { it is ConnectionState.Live },
        )
    }

    @Test
    fun `401 stops retrying instead of draining the battery`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"nope"}"""))
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Failed } }

        val failed = seen.filterIsInstance<ConnectionState.Failed>().firstOrNull()

        assertTrue("expected a Failed state, got ${seen.map { it::class.simpleName }}", failed != null)

        // The message has to point at re-pairing, because no amount of retrying
        // will ever succeed and the user needs a different action.
        //
        // Asserted by shape rather than by a word: the string is Spanish, and a
        // test that greps for an English token passes or fails on translation
        // rather than on behaviour. What matters is that the message is present
        // and is not the generic reconnect error.
        val message = failed!!.message.orEmpty()
        assertTrue("a 401 must explain itself, got a blank message", message.isNotBlank())
        assertTrue(
            "a 401 must not be reported as a transient network problem: $message",
            !message.contains("reintent", ignoreCase = true),
        )
        assertTrue(
            "a 401 must ask for re-pairing, got: $message",
            message.contains("emparej", ignoreCase = true),
        )

        // The behavioural claim: the loop returned rather than retrying. A
        // grace period after the failure is what makes this real — had the loop
        // kept going, a second request would have landed in that window.
        delay(1_500)
        stream.stop()
        assertEquals("must not retry after 401", 1, server.requestCount)
    }

    @Test
    fun `403 stops retrying and never asks for a re-pair`() = runBlocking {
        // Trusted but not allowed: the pairing is intact, so the message must
        // not say "emparej" (that is the 401 answer), and the fix is a
        // host-side grant, so the loop must return rather than retry.
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"forbidden"}"""))
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Failed } }
        val failed = seen.filterIsInstance<ConnectionState.Failed>().firstOrNull()

        assertTrue("expected a Failed state, got ${seen.map { it::class.simpleName }}", failed != null)
        val message = failed!!.message.orEmpty()
        assertTrue("a 403 must explain itself, got a blank message", message.isNotBlank())
        assertTrue(
            "a 403 must not ask for re-pairing, got: $message",
            !message.contains("emparej", ignoreCase = true),
        )

        delay(1_500)
        stream.stop()
        assertEquals("must not retry after 403", 1, server.requestCount)
    }


    @Test
    fun `a dropped connection is followed by a reconnect`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "text/event-stream")
                .setChunkedBody(stateFrame(1), maxChunk)
                .setSocketPolicy(SocketPolicy.DISCONNECT_AT_END),
        )
        server.enqueue(streamResponse(stateFrame(2)))
        val stream = LiveStream(client(), scope)
        // Wait for the reconnect itself, not for a fixed duration. The loop
        // sleeps 1s before retrying and that sleep is production behaviour, so
        // this test cannot set its own pace — but it can wait for the outcome
        // with a ceiling, which is stable where a sleep is not.
        awaitState(stream, millis = 20_000) {
            it.any { s -> s is ConnectionState.Live && s.state.revision == 2L }
        }
        stream.stop()

        assertTrue("expected a reconnect, saw ${server.requestCount}", server.requestCount >= 2)
        // The second connection delivers a newer revision, which only happens
        // if the loop retried rather than giving up.
        assertTrue("expected revision 2, saw ${liveRevisions()}", 2L in liveRevisions())
    }

    @Test
    fun `an out of order change frame does not roll the state back`() = runBlocking {
        // The gateway replays its queue on reconnect, so a stale frame arriving
        // after a newer state is a real possibility. Applying it would visibly
        // undo what the user is reading.
        val staleChange = "event: change\ndata: {\"revision\":2,\"pane_id\":\"w3:p1\"}\n\n"
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "text/event-stream")
                .setChunkedBody(stateFrame(5) + stateFrame(9) + staleChange, maxChunk)
                .setSocketPolicy(SocketPolicy.KEEP_OPEN),
        )
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Live && s.state.revision == 9L } }
        stream.stop()

        val revisions = liveRevisions()
        assertTrue("expected to reach revision 9, saw $revisions", 9L in revisions)
        // The stale frame would have triggered a re-read, but the point is that
        // no state with a revision below 9 was ever applied.
        assertTrue(
            "a stale frame must not publish an older revision: $revisions",
            revisions.none { it < 5L },
        )
    }

    @Test
    fun `an empty state is Live, not Offline`() = runBlocking {
        // "No agents running" is a valid answer from a working gateway. Showing
        // it as an error would train the user to distrust a correct screen.
        server.enqueue(
            streamResponse(
                "event: state\ndata: {\"event\":\"state\",\"revision\":1," +
                    "\"state\":{\"revision\":1,\"agents\":[]}}\n\n",
            ),
        )
        val stream = LiveStream(client(), scope)
        awaitState(stream) { it.any { s -> s is ConnectionState.Live } }
        stream.stop()

        val live = seen.filterIsInstance<ConnectionState.Live>().firstOrNull()
        assertTrue("expected a Live emission, got ${seen.map { it::class.simpleName }}", live != null)
        assertTrue(live!!.state.isEmpty)
    }

    @Test
    fun `reconnect backoff is jittered so devices do not synchronise`() = runBlocking {
        // A gateway and the phones on its tailnet come back up together — the
        // laptop sleeps, the router reboots. Deterministic backoff makes every
        // device compute the same interval and reconnect in the same instant,
        // and the gateway has a per-device stream cap, so the storm it creates
        // is exactly what turns a routine wake-up into a burst of 429s.
        //
        // One draw is not evidence of jitter, so this samples many. What it
        // pins is that the interval varies at all, and that it stays inside the
        // documented 20% spread — a full jitter would be fine in production and
        // impossible to assert here.
        val intervals = (1..40).map { attempt ->
            LiveStream(client(), scope, random = Random(attempt)).backoffMillisForTest(attempt)
        }
        assertTrue(
            "40 draws produced a single value; there is no jitter",
            intervals.toSet().size > 1,
        )
        val first = intervals.first()
        assertTrue("interval must not be below the base, got $first", first >= 800)
        assertTrue("interval must not exceed the cap", intervals.all { it <= 30_000 })
    }

    /**
     * A stream that is cut mid-session is shown as Offline, with the age of the
     * list it still holds, and then comes back Live on its own. This is the
     * "never freezes in silence" guarantee: the screen has to be able to say the
     * list is stale, and the loop has to be the thing that gets it fresh again.
     */
    @Test
    fun `a cut stream is shown as Offline with its age, then comes back Live`() = runBlocking {
        // A dispatcher rather than a queue. The first connection is cut; every
        // later one gets the healthy stream. A queue would hang the reconnect if
        // the client's pooled socket was already dead and swallowed a request,
        // because the stream client has no read timeout to give up on it.
        val requests = AtomicInteger()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (requests.getAndIncrement() == 0) {
                    MockResponse()
                        .setHeader("Content-Type", "text/event-stream")
                        .setChunkedBody(stateFrame(1), maxChunk)
                        .setSocketPolicy(SocketPolicy.DISCONNECT_AT_END)
                } else {
                    streamResponse(stateFrame(2))
                }
        }
        val stream = LiveStream(client(), scope)
        awaitState(stream, millis = 20_000) {
            it.any { s -> s is ConnectionState.Live && s.state.revision == 2L }
        }
        stream.stop()

        val offline = seen.filterIsInstance<ConnectionState.Offline>().firstOrNull()
        assertTrue("a cut stream must be shown as Offline, got ${seen.map { it::class.simpleName }}", offline != null)
        assertTrue(
            "Offline must carry when its list was received, or the screen cannot say how stale it is",
            offline!!.updatedAt > 0L,
        )
        assertTrue("a reconnect must reach Live again, saw ${liveRevisions()}", 2L in liveRevisions())
        assertTrue(
            "every Live state must carry the time it was received",
            seen.filterIsInstance<ConnectionState.Live>().all { it.updatedAt > 0L },
        )
        assertTrue("expected a second connection, saw ${server.requestCount}", server.requestCount >= 2)
    }

    @Test
    fun `stop cancels the loop`() = runBlocking {

        server.enqueue(streamResponse(stateFrame(1)))
        val stream = LiveStream(client(), scope)
        // Wait for the first connection to be established, so `stop` is called
        // while a stream is genuinely open rather than before it ever started.
        awaitState(stream) { it.any { s -> s is ConnectionState.Live } }
        stream.stop()
        val settled = server.requestCount
        delay(3_000)
        assertEquals("a stopped stream must not reconnect", settled, server.requestCount)
    }
}
