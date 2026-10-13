package dev.herdrnotify.app.net

import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * The one unauthenticated write, against a real server.
 *
 * The pair request has no signature to hide behind: it carries the public key
 * and the code, and the gateway answers with the device id every later request
 * is signed under. What is pinned here is that it is *unauthenticated* (no
 * `X-HN-*` headers), that a blank code asks for auto-approval rather than
 * sending an empty string, and that the errors are typed so the screen can say
 * the right thing.
 */
class PairingApiTest {

    private lateinit var server: MockWebServer
    private lateinit var api: HttpPairingApi

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        api = HttpPairingApi(OkHttpClient())
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun successBody() =
        """{"ok":true,"device_id":"dev-1234","curve":"p256","label":"Pixel",""" +
            """"permissions":["read_state"],"owner_id":"12345",""" +
            """"recovery_code":"7QK3-M2XP-9B7C-D4HF"}"""

    @Test
    fun `pair posts the key and the code, unsigned`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        api.pair(
            server.url("/").toString(),
            PairRequest(curve = "p256", publicKey = "BAAA", label = "Pixel 9", code = "HJKQ2ZP4"),
        )

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/v1/pair", request.path)
        assertNull("pairing is unauthenticated", request.getHeader("X-HN-Signature"))
        assertNull(request.getHeader("X-HN-Device"))
        val body = request.body.readUtf8()
        assertTrue(body, body.contains("\"public_key\":\"BAAA\""))
        assertTrue(body, body.contains("\"code\":\"HJKQ2ZP4\""))
        assertTrue(body, body.contains("\"curve\":\"p256\""))
    }

    @Test
    fun `the device id and the recovery code come back decoded`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        val result = api.pair(
            server.url("/").toString(),
            PairRequest("p256", "BAAA", null, "HJKQ2ZP4"),
        )

        val response = result.getOrThrow()
        assertEquals("dev-1234", response.deviceId)
        assertEquals(listOf("read_state"), response.permissions)
        assertEquals("7QK3-M2XP-9B7C-D4HF", response.recoveryCode)
    }

    @Test
    fun `a 403 is a typed rejection so the code can be named as the cause`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"pairing_rejected"}"""))

        val error = api.pair(
            server.url("/").toString(),
            PairRequest("p256", "BAAA", null, "BADCODE1"),
        ).exceptionOrNull()

        assertTrue(
            "expected a PairingException, got ${error?.javaClass?.simpleName}",
            error is PairingException,
        )
        assertEquals(403, (error as PairingException).status)
    }

    @Test
    fun `a 200 without a device id is not a pairing`() = runBlocking {
        // Storing an id the gateway never assigned would leave a phone that
        // authenticates as nothing, with no error to explain it.
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"ok":true}"""))

        val error = api.pair(
            server.url("/").toString(),
            PairRequest("p256", "BAAA", null, null),
        ).exceptionOrNull()

        assertTrue(error is PairingException)
    }

    @Test
    fun `a blank code is omitted so auto-approval is requested`() {
        val json = PairRequest("p256", "BAAA", null, "   ").toJson()
        assertFalse("a blank code must not be sent: $json", json.contains("\"code\""))
    }

    @Test
    fun `a label with a quote is escaped in the body`() {
        val json = PairRequest("p256", "BAAA", "a\"b", null).toJson()
        assertTrue(json, json.contains("a\\\"b"))
    }

    @Test
    fun `required fields are always present`() {
        val json = PairRequest("p256", "BAAA", null, null).toJson()
        assertTrue(json, json.contains("\"curve\":\"p256\""))
        assertTrue(json, json.contains("\"public_key\":\"BAAA\""))
    }
}
