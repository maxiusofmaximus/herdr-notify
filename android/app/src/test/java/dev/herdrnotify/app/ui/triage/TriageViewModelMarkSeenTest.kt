package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.pairing.GatewayTriageRepository
import dev.herdrnotify.app.pairing.Pairing
import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Opening a chat must not move the operator's focus in the terminal.
 *
 * herdr 0.9.1 clears an agent's "done" badge only through ``agent.focus``, which
 * also focuses that pane on the PC. So the phone marks the agent seen in the app
 * and sends nothing to the host: the badge clears locally and no focus-moving
 * request ever leaves the phone.
 */
class TriageViewModelMarkSeenTest {

    private class FakeKey : Signer {
        override fun sign(payload: ByteArray): ByteArray = payload
    }

    @Test
    fun `opening an agent marks it seen locally and does not touch the host`() = runBlocking {
        val server = MockWebServer().apply { start() }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                // The opening SSE frame carries the done agent; every other
                // path answers with the same state as plain JSON.
                if (request.path?.startsWith("/v1/events") == true) {
                    MockResponse()
                        .setHeader("Content-Type", "text/event-stream")
                        .setBody(
                            "event: state\ndata: {\"event\":\"state\",\"revision\":1," +
                                "\"state\":${stateJson(1)}}\n\n",
                        )
                } else {
                    MockResponse().setBody(stateJson(1))
                }
        }

        val repository = GatewayTriageRepository(
            FakeKey(),
            { Pairing("http://127.0.0.1:${server.port}", "d1") },
            CoroutineScope(SupervisorJob() + Dispatchers.IO),
        )
        val viewModel = TriageViewModel(repository, CoroutineScope(SupervisorJob() + Dispatchers.IO))

        repository.connect()

        val arrived = awaitCondition {
            viewModel.state.value.agentById("w3:p1")?.status == AgentStatus.DONE
        }
        assertTrue("the done agent must arrive before opening", arrived)

        viewModel.onOpenAgent("w3:p1")

        assertTrue(
            "opening must mark the done agent seen in the app",
            awaitCondition {
                viewModel.state.value.agentById("w3:p1")?.status == AgentStatus.IDLE
            },
        )
        assertFalse(
            "opening must not send a focus-moving request to the host",
            awaitHostAction(server) != null,
        )

        server.shutdown()
    }

    /** Drain recorded requests until a seen/focus request arrives, or timeout. */
    private fun awaitHostAction(server: MockWebServer, millis: Long = 1_500): RecordedRequest? {
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline) {
            val request = server.takeRequest(200, TimeUnit.MILLISECONDS) ?: continue
            val path = request.path ?: continue
            if (path.endsWith("/seen") || path.endsWith("/focus")) return request
        }
        return null
    }

    private fun awaitCondition(millis: Long = 15_000, condition: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return true
            Thread.sleep(50)
        }
        return condition()
    }

    private fun stateJson(revision: Long) = buildString {
        append("{\"revision\":$revision,\"herdr_version\":\"0.9.1\",\"agents\":[")
        append("{\"pane_id\":\"w3:p1\",\"status\":\"done\",\"attention\":2,")
        append("\"project\":\"herdr-notify\"}]}")
    }
}
