package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
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
import java.util.concurrent.TimeUnit

/**
 * Moving a paired phone to a new gateway address.
 *
 * The pairing (device id and key) must survive the move untouched, and the move
 * must actually reach the new host: a change that saved the address but left the
 * connection on the old one would look correct on disk and fail on the screen.
 */
class GatewayAddressTest {

    private class FakeKey : Signer {
        override fun sign(payload: ByteArray): ByteArray = payload
    }

    private lateinit var oldHost: MockWebServer
    private lateinit var newHost: MockWebServer

    @Before
    fun setUp() {
        oldHost = gatewayServer()
        newHost = gatewayServer()
    }

    @After
    fun tearDown() {
        oldHost.shutdown()
        newHost.shutdown()
    }

    @Test
    fun `changing the address keeps the device id and stores the normalised URL`() = runBlocking {
        var saved: Pairing? = null
        val address = GatewayAddress(
            current = { Pairing("http://127.0.0.1:8787", "phone-1") },
            save = { saved = it },
            reconnect = {},
        )

        val result = address.change("  http://100.64.0.1:8787/  ")

        assertTrue(result.isSuccess)
        assertEquals(Pairing("http://100.64.0.1:8787", "phone-1"), saved)
    }

    @Test
    fun `a blank address is refused before anything is written or reconnected`() = runBlocking {
        var saves = 0
        var reconnects = 0
        val address = GatewayAddress(
            current = { Pairing("http://127.0.0.1:8787", "phone-1") },
            save = { saves++ },
            reconnect = { reconnects++ },
        )

        val result = address.change("   ")

        assertTrue("a blank address must fail", result.isFailure)
        assertEquals("nothing may be saved", 0, saves)
        assertEquals("nothing may reconnect", 0, reconnects)
    }

    /**
     * The contract that matters: after the change, the phone talks to the new
     * gateway. The repository is real and the pairing is read from the same
     * place the app reads it, so this fails if the reconnect ever stops
     * following the saved address.
     */
    @Test
    fun `saving a new address reconnects against the new gateway`() = runBlocking {
        var pairing = Pairing("http://127.0.0.1:${oldHost.port}", "phone-1")
        val repository = GatewayTriageRepository(
            FakeKey(),
            { pairing },
            CoroutineScope(SupervisorJob() + Dispatchers.IO),
        )
        val address = GatewayAddress(
            current = { pairing },
            save = { pairing = it },
            reconnect = {
                repository.disconnect()
                repository.connect()
            },
        )
        repository.connect()
        assertTrue("the first connection goes to the old host", awaitRequest(oldHost, "/v1/state") != null)

        val newUrl = "http://127.0.0.1:${newHost.port}"
        val result = address.change(newUrl)

        assertTrue(result.isSuccess)
        assertEquals("the saved pairing names the new host", newUrl, pairing.baseUrl)
        assertEquals("the device id is kept", "phone-1", pairing.deviceId)
        assertTrue(
            "after the change the phone must reconnect to the new host",
            awaitRequest(newHost, "/v1/state") != null,
        )
        repository.disconnect()
    }

    private fun gatewayServer(): MockWebServer {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
                "/v1/state" -> MockResponse().setBody("""{"revision":1,"agents":[]}""")
                else -> MockResponse()
                    .setHeader("Content-Type", "text/event-stream")
                    .setBody("event: state\ndata: {\"event\":\"state\",\"revision\":1,\"state\":{\"revision\":1,\"agents\":[]}}\n\n")
                    .setSocketPolicy(SocketPolicy.KEEP_OPEN)
            }
        }
        return server
    }

    /** Consume recorded requests until one with [path] arrives, or timeout. */
    private fun awaitRequest(server: MockWebServer, path: String): RecordedRequest? {
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            val request = server.takeRequest(200, TimeUnit.MILLISECONDS) ?: continue
            if (request.path == path) return request
        }
        return null
    }
}
