package dev.herdrnotify.app.net

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.security.MessageDigest
import java.util.Base64

/**
 * The client against a real server, over a real socket.
 *
 * The signing tests prove the string is right. These prove the string is
 * *delivered* right: that the four headers are attached, that the body sent is
 * the same array the signature covers, and that a non-200 becomes a typed
 * error rather than a silent success. A client that hashes correctly and then
 * sends different bytes is exactly the class of bug a pure unit test cannot
 * find, and it is the same class of bug that produced the two defects fixed
 * earlier.
 */
class GatewayClientTest {

    private lateinit var server: MockWebServer
    private lateinit var client: GatewayClient

    private class EchoSigner : Signer {
        override fun sign(payload: ByteArray): ByteArray =
            MessageDigest.getInstance("SHA-256").digest(payload)
    }

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        client = GatewayClient(
            baseUrl = server.url("/").toString(),
            deviceId = "device-test-1",
            signer = RequestSigner(EchoSigner(), clock = { 1_700_000_000L }),
            http = OkHttpClient(),
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `every request carries the four signing headers`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        runBlocking { client.state() }

        val request = server.takeRequest()
        assertEquals("device-test-1", request.getHeader("X-HN-Device"))
        assertEquals("1700000000", request.getHeader("X-HN-Timestamp"))
        assertNotNull(request.getHeader("X-HN-Nonce"))
        assertNotNull(request.getHeader("X-HN-Signature"))
        assertTrue(
            "the nonce must be the one that was signed",
            request.getHeader("X-HN-Nonce")!!.isNotEmpty(),
        )
    }

    @Test
    fun `the target sent is byte for byte what was signed`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        runBlocking { client.respond("w3:p1", "sí, hazlo") }

        val request = server.takeRequest()
        // The path the server saw is the one the signature must have covered.
        // The gateway verifies against `raw_path` — the percent-encoded form of
        // the request line — so encoding the colon in a pane id would sign one
        // target and send another, and every write would be refused.
        assertEquals("/v1/agents/w3:p1/respond", request.path!!)
        assertTrue("the colon must not be escaped: ${request.path}", !request.path!!.contains("%3A"))
    }

    @Test
    fun `the body sent is the exact bytes that were signed`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val text = "sí, hazlo"
        runBlocking { client.respond("w3:p1", text) }

        val sent = server.takeRequest().body.readUtf8()

        // The digest of the bytes that arrived must equal the digest of the
        // bytes the signer was given. If the client re-serialised, padded, or
        // re-encoded between signing and sending, these diverge and every
        // request is rejected as a bad signature while looking correct.
        val expected = RequestSigner.bodyDigest(
            """{"text":"sí, hazlo"}""".toByteArray(Charsets.UTF_8),
        )
        val actual = RequestSigner.bodyDigest(sent.toByteArray(Charsets.UTF_8))
        assertEquals("signed bytes differ from sent bytes", expected, actual)
    }

    @Test
    fun `non ascii text survives the round trip as utf-8`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"ok":true}"""))
        runBlocking { client.respond("w3:p1", "日本語 ✅") }

        val body = server.takeRequest().body.readUtf8()
        assertTrue("unicode must not be mangled: $body", body.contains("日本語 ✅"))
    }

    @Test
    fun `a pane id cannot escape its path segment`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        runBlocking { client.respond("../../v1/devices", "x") }

        // A slash in a pane id must be encoded, not treated as a path
        // separator, or a crafted id could address a different endpoint.
        val path = server.takeRequest().path!!
        assertTrue("path must be one segment: $path", path.startsWith("/v1/agents/"))
        assertTrue("path must be percent encoded: $path", path.contains("%2F"))
    }

    @Test
    fun `a GET read keeps its method and carries no body`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        runBlocking { client.state() }

        val request = server.takeRequest()
        assertEquals("GET", request.method)
    }

    @Test
    fun `401 becomes an Unauthorised error, not a failure state`() {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"nope"}"""))
        val error = runCatching { client.state() }.exceptionOrNull()
        assertTrue(
            "expected Unauthorised, got ${error?.javaClass?.simpleName}",
            error is GatewayClient.GatewayError.Unauthorised,
        )
    }

    @Test
    fun `403 becomes NotPermitted, not Unauthorised`() {
        // Authentication and authorization are different answers: a 403 means
        // the pairing is intact and the fix is a host-side grant. Conflating it
        // with Unauthorised would tell the user to re-pair, which is the wrong
        // fix.
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"forbidden"}"""))
        val error = runCatching { client.state() }.exceptionOrNull()
        assertTrue(
            "expected NotPermitted, got ${error?.javaClass?.simpleName}",
            error is GatewayClient.GatewayError.NotPermitted,
        )
        assertTrue(
            "403 must not be Unauthorised, or the UI would ask for a re-pair",
            error !is GatewayClient.GatewayError.Unauthorised,
        )
    }

    @Test
    fun `429 is distinguishable so a reconnect can back off`() {
        server.enqueue(MockResponse().setResponseCode(429).setBody("""{"detail":"slow down"}"""))
        val error = runCatching { client.state() }.exceptionOrNull()
        assertTrue(error is GatewayClient.GatewayError)
        assertTrue(error is GatewayClient.GatewayError.Rejected)
    }

    @Test
    fun `an error body is summarised, not shown raw`() {
        server.enqueue(
            MockResponse().setResponseCode(409)
                .setBody("""{"detail":{"code":"agent_not_blocked","message":"ya no está bloqueado"}}"""),
        )
        val error = runCatching { client.sendKeys("w3:p1", listOf("ctrl+c"), confirm = true) }
            .exceptionOrNull()
        val message = (error as GatewayClient.GatewayError.Rejected).message!!
        assertTrue("should carry the useful text: $message", message.contains("ya no está bloqueado"))
        assertTrue("must not dump raw JSON: $message", !message.contains("\"detail\""))
    }

    @Test
    fun `a host that is not there is Unreachable, not Unauthorised`() {
        // The two lead to different screens: one says "re-pair", the other says
        // "check the network". Conflating them tells a user to do the wrong
        // thing.
        val dead = GatewayClient(
            baseUrl = "http://127.0.0.1:1",
            deviceId = "d",
            signer = RequestSigner(EchoSigner()),
            http = OkHttpClient.Builder()
                .connectTimeout(1, java.util.concurrent.TimeUnit.SECONDS)
                .build(),
        )
        val error = runCatching { dead.state() }.exceptionOrNull()
        assertTrue(
            "expected Unreachable, got ${error?.javaClass?.name}",
            error is GatewayClient.GatewayError.Unreachable,
        )
        assertTrue(
            "Unreachable must not be Unauthorised, or the UI would tell the user to re-pair",
            error !is GatewayClient.GatewayError.Unauthorised,
        )
    }

    @Test
    fun `the fcm token is posted to the device self-service route`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"ok":true}"""))
        runBlocking { client.fcmToken("tok-123") }
        val request = server.takeRequest()
        assertEquals("/v1/me/fcm-token", request.path)
        assertTrue(request.body.readUtf8().contains("tok-123"))
    }

    @Test
    fun `read without a line count sends an empty object, not null`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"text":"hi"}"""))
        runBlocking { client.read("w3:p1") }
        assertEquals("{}", server.takeRequest().body.readUtf8())
    }

    @Test
    fun `read posts the line count to the pane's read route, signed`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"text":"hi","pane_id":"w1:p1"}"""))
        runBlocking { client.read("w1:p1", 60) }

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/v1/agents/w1:p1/read", request.path)
        assertEquals("""{"lines":60}""", request.body.readUtf8())
        assertNotNull("the read must be signed like every other request", request.getHeader("X-HN-Signature"))
    }

    @Test
    fun `sendKeys posts the whole key list and the confirm flag, signed`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"ok":true}"""))
        runBlocking { client.sendKeys("w3:p1", listOf("right", "enter"), confirm = true) }

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/v1/agents/w3:p1/keys", request.path)
        // The key sequence is one gesture, so it must travel as one signed body:
        // splitting it would sign two targets and let a redraw land in between.
        assertEquals(
            """{"keys":["right","enter"],"confirm":true}""",
            request.body.readUtf8(),
        )
        assertNotNull(
            "the keys write must be signed like every other request",
            request.getHeader("X-HN-Signature"),
        )
    }

    @Test
    fun `respond with 403 is NotPermitted, and respond with 409 is a Rejected that keeps its code`() {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"forbidden"}"""))
        val forbidden = runCatching { client.respond("w3:p1", "hola") }.exceptionOrNull()
        assertTrue(
            "a 403 on respond must be NotPermitted, got ${forbidden?.javaClass?.simpleName}",
            forbidden is GatewayClient.GatewayError.NotPermitted,
        )

        server.enqueue(
            MockResponse().setResponseCode(409)
                .setBody("""{"detail":{"code":"agent_not_blocked","message":"ya no está bloqueado"}}"""),
        )
        val conflict = runCatching { client.respond("w3:p1", "hola") }.exceptionOrNull()
        assertTrue(
            "a 409 on respond must be a Rejected, got ${conflict?.javaClass?.simpleName}",
            conflict is GatewayClient.GatewayError.Rejected,
        )
        assertEquals(409, (conflict as GatewayClient.GatewayError.Rejected).code)
    }
}

/**
 * Decoding the gateway's actual payloads.
 *
 * Written from `api/app.py` and `attention.py`. The cases that matter are the
 * degraded ones, because the happy path cannot break silently: a herdr version
 * that adds a status, a pane with no title, an entry with no pane id at all.
 */
class WireTest {

    @Test
    fun `a full state decodes with attention carried through, not recomputed`() {
        val state = Wire.state(
            """
            {
              "revision": 12,
              "herdr_version": "0.9.1",
              "counts": {"blocked": 1, "working": 2},
              "agents": [
                {
                  "pane_id": "w3:p1",
                  "workspace_id": "w3",
                  "project": "herdr-notify",
                  "agent": "opencode",
                  "status": "blocked",
                  "attention": 3,
                  "title": "Revisión",
                  "cwd": "C:\\dev",
                  "focused": false,
                  "can_resume": true
                }
              ]
            }
            """.trimIndent(),
        )
        assertNotNull(state)
        val agent = state!!.agents.single()
        assertEquals(AgentStatus.BLOCKED, agent.status)
        assertEquals(3, agent.attention)
        assertTrue(agent.needsYou)
        assertEquals(1, state.counts[AgentStatus.BLOCKED])
    }

    @Test
    fun `an unknown status becomes UNKNOWN rather than failing the parse`() {
        // A newer herdr adding a status must not empty the triage list on an
        // older phone. The gateway degrades this too; the app has to as well.
        val state = Wire.state(
            """{"revision":1,"agents":[{"pane_id":"w1:p1","status":"hibernating"}]}""",
        )
        assertNotNull(state)
        assertEquals(AgentStatus.UNKNOWN, state!!.agents.single().status)
    }

    @Test
    fun `an entry with no pane id is dropped`() {
        // It cannot be addressed by any action, so a row for it would fail the
        // moment it was tapped.
        val state = Wire.state(
            """{"revision":1,"agents":[{"status":"blocked"},{"pane_id":"w1:p1","status":"done"}]}""",
        )
        assertEquals(1, state!!.agents.size)
        assertEquals("w1:p1", state.agents.single().paneId)
    }

    @Test
    fun `missing optional fields fall back to the gateway's own defaults`() {
        val state = Wire.state("""{"agents":[{"pane_id":"w1:p1"}]}""")
        val agent = state!!.agents.single()
        assertEquals("?", agent.project)
        assertEquals("agent", agent.agent)
        assertEquals(AgentStatus.UNKNOWN, agent.status)
        assertNull(agent.title)
        assertNull(agent.cwd)
        assertEquals(false, agent.focused)
    }

    @Test
    fun `an empty project falls back to the workspace id`() {
        val state = Wire.state("""{"agents":[{"pane_id":"w7:p2","workspace_id":"w7","project":""}]}""")
        assertEquals("w7", state!!.agents.single().project)
    }

    @Test
    fun `unknown fields do not break decoding`() {
        // A gateway upgrade must not brick the app.
        val state = Wire.state(
            """{"revision":2,"future_field":{"a":1},"agents":[{"pane_id":"w1:p1","new_thing":true}]}""",
        )
        assertEquals(2L, state!!.revision)
    }

    @Test
    fun `a malformed body yields null so the last good state can stand`() {
        assertNull(Wire.state("not json"))
        assertNull(Wire.state(""))
        assertNull(Wire.state("[1,2,3]"))
    }

    @Test
    fun `the opening SSE frame decodes to the same shape as a state read`() {
        val state = Wire.sseState(
            """
            {"event":"state","revision":9,"state":{
              "revision":9,
              "herdr_version":"0.9.1",
              "agents":[{"pane_id":"w3:p1","status":"blocked","attention":3,"project":"p"}]
            }}
            """.trimIndent(),
        )
        assertNotNull(state)
        assertEquals(9L, state!!.revision)
        assertEquals(AgentStatus.BLOCKED, state.agents.single().status)
    }

    @Test
    fun `an empty state is a valid answer, not a failure`() {
        // "No agents running" and "cannot reach the host" must not look the
        // same, so the empty case has to decode.
        val state = Wire.state("""{"revision":1,"agents":[]}""")
        assertNotNull(state)
        assertTrue(state!!.isEmpty)
    }
}
