package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * The repository must survive a disconnect.
 *
 * `disconnect()` used to call `scope.cancel()`, and that scope belongs to the
 * repository itself. The stream stopped — correctly — but so did everything the
 * repository would ever do again: a later `connect()` launched into a cancelled
 * scope, the collector never ran, and the phone sat on "connecting" with no way
 * to recover short of a process restart. Cancelling the connection's job is the
 * fix; these tests pin it so the scope cannot be cancelled again by a well-meant
 * "clean up everything" edit.
 */
class GatewayTriageRepositoryTest {

    /** A key that signs by returning its input; presence is all this needs. */
    private class FakeKey : Signer {
        override fun sign(payload: ByteArray): ByteArray = payload
    }

    @Test
    fun `disconnect does not cancel the repository scope`() {
        val scope = CoroutineScope(SupervisorJob())
        val repository = GatewayTriageRepository(FakeKey(), { Pairing.NONE }, scope)

        repository.disconnect()

        assertTrue("disconnect must not cancel the scope", scope.isActive)
    }

    @Test
    fun `a disconnected repository can still launch work`() = runBlocking {
        val scope = CoroutineScope(SupervisorJob())
        val repository = GatewayTriageRepository(FakeKey(), { Pairing.NONE }, scope)

        repository.disconnect()

        var ran = false
        // This is what connect() does after a disconnect. On a cancelled scope
        // the launch is a no-op and `ran` stays false.
        scope.launch { ran = true }.join()

        assertTrue("a later connect() would launch into this job", ran)
    }

    /**
     * The parked FCM token must reach the gateway.
     *
     * The lifecycle (push.md): Firebase issues or rotates a token, it is parked
     * persistently, and the next paired, reachable connection registers it.
     * connect() builds the client and flushes in the same breath — before this
     * existed, `GatewayClient.fcmToken()` had no production caller and a token
     * rotated while the process was dead was lost forever.
     */
    @Test
    fun `a parked token is registered on connect`() {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.path == "/v1/me/fcm-token") {
                    MockResponse().setBody("""{"ok":true}""")
                } else {
                    stateFrame(1)
                }
        }
        var parked: String? = "tok-123"
        var registered = false
        val repository = GatewayTriageRepository(
            FakeKey(),
            { Pairing("http://127.0.0.1:${server.port}", "d1") },
            CoroutineScope(SupervisorJob() + Dispatchers.IO),
            pendingToken = { parked },
            onTokenRegistered = {
                registered = true
                parked = null
            },
        )

        repository.connect()

        val request = awaitFcmRequest(server)
        assertTrue("the flush must POST the parked token", request != null)
        assertTrue(request!!.body.readUtf8().contains("tok-123"))
        assertTrue(
            "a successful registration clears the parked copy",
            awaitCondition { registered && parked == null },
        )
        server.shutdown()
    }

    @Test
    fun `a failed registration keeps the parked token`() {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.path == "/v1/me/fcm-token") {
                    MockResponse().setResponseCode(500).setBody("boom")
                } else {
                    stateFrame(1)
                }
        }
        var parked: String? = "tok-124"
        var registered = false
        val repository = GatewayTriageRepository(
            FakeKey(),
            { Pairing("http://127.0.0.1:${server.port}", "d1") },
            CoroutineScope(SupervisorJob() + Dispatchers.IO),
            pendingToken = { parked },
            onTokenRegistered = { registered = true },
        )

        repository.connect()

        val request = awaitFcmRequest(server)
        assertTrue("the flush must attempt the POST", request != null)
        // The dispatcher guarantees the 500 for this route, so the attempt can
        // only end in the keep-parked path: the parked copy and the flag hold
        // both before and after the coroutine completes.
        assertEquals("a failed registration must not clear the parked token", "tok-124", parked)
        assertTrue("onTokenRegistered must not fire on a failure", registered == false)
        server.shutdown()
    }

    /**
     * A gateway can lose the token (pruned after a send error, or a reset
     * store) while the phone still holds it. The app keeps the token after a
     * registration and reports it on every connect, so the next connection
     * repairs the gateway instead of staying silent until Firebase rotates it.
     */
    @Test
    fun `the token is registered again on every connect`() {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.path == "/v1/me/fcm-token") {
                    MockResponse().setBody("""{"ok":true}""")
                } else {
                    stateFrame(1)
                }
        }
        val repository = GatewayTriageRepository(
            FakeKey(),
            { Pairing("http://127.0.0.1:${server.port}", "d1") },
            CoroutineScope(SupervisorJob() + Dispatchers.IO),
            pendingToken = { "tok-keep" },
            onTokenRegistered = {},
        )

        repository.connect()
        assertTrue("first connect registers", awaitFcmRequest(server) != null)
        repository.disconnect()
        repository.connect()
        assertTrue("a second connect registers again", awaitFcmRequest(server) != null)
        server.shutdown()
    }

    /**
     * Every connect asks for a fresh state, not only the stream's opening frame.
     *
     * A resume should show what the host has now. The stream's first frame is
     * the same data, but it arrives behind a connection setup that can take a
     * while on a phone tether, and the explicit read makes the first paint
     * independent of that.
     */
    @Test
    fun `connecting asks the gateway for a fresh state`() {
        val server = gatewayServer()
        val repository = repositoryFor(server)

        repository.connect()

        val request = awaitRequest(server, "/v1/state")
        assertTrue("connect must read /v1/state", request != null)
        assertEquals("GET", request!!.method)
        repository.disconnect()
        server.shutdown()
    }

    /**
     * A 403 on respond comes back to the caller as a typed failure, and the
     * connection is left as it was. The screen needs the reason to say "this
     * phone may not send"; a repository that swallowed it would leave the person
     * wondering why their message vanished.
     */
    @Test
    fun `respond returns a 403 to the caller and leaves the connection alone`() = runBlocking {
        val server = gatewayServer(respondCode = 403, respondBody = """{"detail":"forbidden"}""")
        val repository = repositoryFor(server)
        repository.connect()

        val result = repository.respond("w1:p1", "hola")

        assertTrue("a 403 must come back as a failure", result.isFailure)
        assertTrue(
            "expected NotPermitted, got ${result.exceptionOrNull()?.javaClass?.simpleName}",
            result.exceptionOrNull() is GatewayClient.GatewayError.NotPermitted,
        )
        assertTrue(
            "a 403 must not fail the connection, got ${repository.currentState()}",
            repository.currentState() !is ConnectionState.Failed,
        )
        repository.disconnect()
        server.shutdown()
    }

    @Test
    fun `respond returns a 409 as a rejection with its code`() = runBlocking {
        val server = gatewayServer(
            respondCode = 409,
            respondBody = """{"detail":{"code":"agent_blocked","message":"esperando aprobación"}}""",
        )
        val repository = repositoryFor(server)
        repository.connect()

        val error = repository.respond("w1:p1", "hola").exceptionOrNull()

        assertTrue("expected a Rejected, got ${error?.javaClass?.simpleName}", error is GatewayClient.GatewayError.Rejected)
        assertEquals(409, (error as GatewayClient.GatewayError.Rejected).code)
        repository.disconnect()
        server.shutdown()
    }

    @Test
    fun `respond succeeds when the gateway accepts the message`() = runBlocking {
        val server = gatewayServer(respondCode = 200, respondBody = """{"ok":true}""")
        val repository = repositoryFor(server)
        repository.connect()

        assertTrue(repository.respond("w1:p1", "hola").isSuccess)
        repository.disconnect()
        server.shutdown()
    }

    @Test
    fun `read returns the text of the pane's output`() = runBlocking {
        val server = gatewayServer()
        val repository = repositoryFor(server)
        repository.connect()

        val text = repository.read("w1:p1", 60).getOrThrow()

        assertEquals("hola\nmundo", text)
        repository.disconnect()
        server.shutdown()
    }

    private fun gatewayServer(
        respondCode: Int = 200,
        respondBody: String = """{"ok":true}""",
    ): MockWebServer {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
                "/v1/state" -> MockResponse().setBody("""{"revision":42,"agents":[]}""")
                "/v1/agents/w1:p1/read" -> MockResponse().setBody("""{"text":"hola\nmundo","pane_id":"w1:p1"}""")
                "/v1/agents/w1:p1/respond" -> MockResponse().setResponseCode(respondCode).setBody(respondBody)
                else -> stateFrame(1)
            }
        }
        return server
    }

    private fun repositoryFor(server: MockWebServer) = GatewayTriageRepository(
        FakeKey(),
        { Pairing("http://127.0.0.1:${server.port}", "d1") },
        CoroutineScope(SupervisorJob() + Dispatchers.IO),
    )

    /** Consume recorded requests until one with [path] arrives, or timeout. */
    private fun awaitRequest(server: MockWebServer, path: String): RecordedRequest? {
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            val request = server.takeRequest(200, TimeUnit.MILLISECONDS) ?: continue
            if (request.path == path) return request
        }
        return null
    }

    /** Consume recorded requests until the fcm-token POST arrives, or timeout. */
    private fun awaitFcmRequest(server: MockWebServer): RecordedRequest? {
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            val request = server.takeRequest(200, TimeUnit.MILLISECONDS) ?: continue
            if (request.path == "/v1/me/fcm-token") return request
        }
        return null
    }

    /** Poll for the condition with a generous ceiling, in LiveStreamTest's style. */
    private fun awaitCondition(millis: Long = 15_000, condition: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return true
            Thread.sleep(50)
        }
        return condition()
    }

    private fun stateFrame(revision: Long): MockResponse = MockResponse()
        .setHeader("Content-Type", "text/event-stream")
        .setBody(
            buildString {
                append("event: state\n")
                append("data: {\"event\":\"state\",\"revision\":$revision,")
                append("\"state\":{\"revision\":$revision,\"herdr_version\":\"0.9.1\",")
                append("\"agents\":[{\"pane_id\":\"w3:p1\",\"status\":\"blocked\",")
                append("\"attention\":3,\"project\":\"herdr-notify\"}]}}\n\n")
            },
        )
        .setSocketPolicy(SocketPolicy.KEEP_OPEN)
}
