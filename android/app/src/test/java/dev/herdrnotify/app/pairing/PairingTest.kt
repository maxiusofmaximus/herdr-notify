package dev.herdrnotify.app.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The URL the operator types is the one place the app guesses.
 *
 * A phone keyboard does not reliably produce `:` or `/`, and someone copying a
 * Tailscale name will usually not add a scheme. Guessing here saves a round trip
 * of "it just says it couldn't connect", which tells the user nothing about
 * which of the two halves they got wrong. The risk of guessing is picking the
 * wrong scheme, so the cases that must NOT be rewritten are pinned below.
 */
class PairingNormalisationTest {

    @Test
    fun `a bare tailnet name gets https`() {
        assertEquals(
            "https://mi-pc.tailnet-ejemplo.ts.net",
            Pairing.normaliseUrl("mi-pc.tailnet-ejemplo.ts.net"),
        )
    }

    @Test
    fun `a name with a port keeps the port`() {
        assertEquals(
            "https://mi-pc.tailnet-ejemplo.ts.net:8443",
            Pairing.normaliseUrl("mi-pc.tailnet-ejemplo.ts.net:8443"),
        )
    }

    @Test
    fun `an existing scheme is not doubled`() {
        assertEquals("http://127.0.0.1:8787", Pairing.normaliseUrl("http://127.0.0.1:8787"))
        assertEquals("https://example.test", Pairing.normaliseUrl("https://example.test"))
    }

    @Test
    fun `a trailing slash is removed so paths do not double up`() {
        // OkHttp plus "/v1/state" on a base ending in "/" would produce "//v1/state",
        // which is a different path — and the signature is computed over the
        // target, so it would fail as a bad signature rather than a 404.
        assertEquals("https://host.test", Pairing.normaliseUrl("https://host.test/"))
        assertEquals("https://host.test", Pairing.normaliseUrl("  https://host.test///  "))
    }

    @Test
    fun `whitespace from a paste is removed`() {
        assertEquals("https://host.test", Pairing.normaliseUrl("  host.test  "))
    }

    @Test
    fun `empty stays empty rather than becoming a bare scheme`() {
        // "https://" is a syntactically valid prefix and a useless address; a
        // blank field must stay blank so canSave can reject it.
        assertEquals("", Pairing.normaliseUrl(""))
        assertEquals("", Pairing.normaliseUrl("   "))
    }
}

class PairingUiStateTest {

    private fun stateWith(
        baseUrl: String = "",
        deviceId: String = "",
        publicKey: String? = "BAAAAA",
    ) = PairingUiState(
        baseUrl = baseUrl,
        deviceId = deviceId,
        publicKey = publicKey,
        isLoading = false,
    )

    @Test
    fun `saving needs all three things`() {
        assertFalse(stateWith().canSave)
        assertFalse(stateWith(baseUrl = "https://h").canSave)
        assertFalse(stateWith(deviceId = "d").canSave)
        assertFalse(stateWith(baseUrl = "https://h", deviceId = "d", publicKey = null).canSave)
        assertTrue(stateWith(baseUrl = "https://h", deviceId = "d").canSave)
    }

    @Test
    fun `the host command carries the public key and the device id`() {
        val command = stateWith(deviceId = "hn-1234", publicKey = "BAAA").hostCommand!!
        // These are the two values the operator has to transfer by hand. If either
        // is missing or wrong, the phone authenticates as nothing and the
        // operator sees a device that never appears in `herdr-notify devices`.
        assertTrue(command.contains("--public-key BAAA"))
        assertTrue(command.contains("--curve p256"))
        assertTrue(command.contains("--label hn-1234"))
    }

    @Test
    fun `the host command is a single line`() {
        // Split across lines it invites a paste that carries a continuation
        // prompt, and a trust store entry with a stray character is a device
        // that never authenticates with no obvious cause.
        val command = stateWith(deviceId = "hn-1", publicKey = "BAAA").hostCommand!!
        assertFalse(command.contains("\n"))
    }

    @Test
    fun `the command still names something when the device id is blank`() {
        // An unnamed device is still registerable; a blank label would produce
        // `--label ` followed by nothing, which the CLI rejects.
        val command = stateWith(publicKey = "BAAA").hostCommand!!
        assertTrue(command.contains("--label "))
        assertFalse(command.trimEnd().endsWith("--label"))
    }

    @Test
    fun `there is no command before the key exists`() {
        // Nothing to register yet, so offering a command would be a way to
        // paste an empty key and get a confusing rejection from the host.
        assertEquals(null, stateWith(publicKey = null).hostCommand)
    }

    @Test
    fun `a loopback or blank address is hidden and cannot pair`() {
        // A build with no gatewayUrl defaults to loopback, which on a phone is
        // the phone itself: it must not look like a filled, working address.
        val loopback = stateWith(baseUrl = "http://127.0.0.1:8788", deviceId = "d")
        assertEquals("", loopback.visibleBaseUrl)
        assertFalse(loopback.canClaim)
        assertFalse(loopback.canSave)

        val localhost = stateWith(baseUrl = "http://localhost:8788", deviceId = "d")
        assertEquals("", localhost.visibleBaseUrl)
        assertFalse(localhost.canClaim)

        val blank = stateWith(deviceId = "d")
        assertEquals("", blank.visibleBaseUrl)
        assertFalse(blank.canClaim)
    }

    @Test
    fun `a routable address is shown and enables pairing`() {
        val state = stateWith(baseUrl = "http://100.64.0.1:8788", deviceId = "d")
        assertEquals("http://100.64.0.1:8788", state.visibleBaseUrl)
        assertTrue(state.hasRoutableAddress)
        assertTrue(state.canClaim)
    }
}
