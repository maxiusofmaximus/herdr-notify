package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.RequestSigner
import dev.herdrnotify.app.security.Signer
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.security.MessageDigest

/**
 * "Mis dispositivos": the wire shape and the one destructive route, against a
 * real server.
 *
 * The signed call is exercised through the same [GatewayClient] the rest of the
 * app uses, so what is pinned is the path, the method, and that the response
 * decodes into the public-only shape the contract promises.
 */
class DeviceDirectoryTest {

    private lateinit var server: MockWebServer
    private lateinit var directory: SignedDeviceDirectory

    private class EchoSigner : Signer {
        override fun sign(payload: ByteArray): ByteArray =
            MessageDigest.getInstance("SHA-256").digest(payload)
    }

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val client = GatewayClient(
            baseUrl = server.url("/").toString(),
            deviceId = "dev-self",
            signer = RequestSigner(EchoSigner(), clock = { 1_700_000_000L }),
            http = OkHttpClient(),
        )
        directory = SignedDeviceDirectory { client }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `the device list decodes, with no secret fields to read`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {"ok":true,"devices":[
                  {"device_id":"dev-self","curve":"p256","label":"TECNO","owner_id":"12345",
                   "created_at":1730000000.0,"last_seen_at":1730000100.0,"revoked":false,
                   "permissions":["read_state"]},
                  {"device_id":"dev-old","curve":"p256","label":null,"owner_id":"12345",
                   "created_at":1720000000.0,"last_seen_at":0.0,"revoked":true,"permissions":[]}
                ]}
                """.trimIndent(),
            ),
        )

        val devices = directory.list().getOrThrow()

        assertEquals(2, devices.size)
        assertEquals("dev-self", devices[0].deviceId)
        assertTrue(devices[0].isActive)
        assertFalse(devices[1].isActive)
        assertNull(devices[1].label)

        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/v1/devices", request.path)
        assertNotNull("the list is a signed call", request.getHeader("X-HN-Signature"))
    }

    @Test
    fun `revoke posts to the device's revoke route`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"ok":true,"device_id":"dev-old","revoked":true}"""),
        )

        directory.revoke("dev-old").getOrThrow()

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/v1/devices/dev-old/revoke", request.path)
        assertNotNull("revoke is signed", request.getHeader("X-HN-Signature"))
    }

    @Test
    fun `a 403 stays a typed NotPermitted for the screen to explain`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"forbidden"}"""))

        val error = directory.list().exceptionOrNull()

        assertTrue(
            "expected NotPermitted, got ${error?.javaClass?.simpleName}",
            error is GatewayClient.GatewayError.NotPermitted,
        )
    }

    @Test
    fun `no client means no call and a failure`() = runBlocking {
        val offline = SignedDeviceDirectory { null }
        assertTrue(offline.list().isFailure)
        assertEquals(0, server.requestCount)
    }
}
