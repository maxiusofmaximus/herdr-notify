package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.security.DeviceKeyStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.runs
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The pairing flow probes before it saves.
 *
 * Saving a URL that does not answer is the failure mode this guards against: the
 * phone would show itself as paired and then never connect, with nothing on
 * screen but a triage list that never populates. The probe is faked here — no
 * network, no MockWebServer — because the probing itself is AddressProber's own
 * tests; what is under test here is the decision the flow makes with the answer.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelProbeTest {

    private val keys = mockk<DeviceKeyStore> {
        every { hasKey() } returns true
        every { publicKeyBase64() } returns "BAAAAA"
        every { fingerprint() } returns "aa:bb:cc:dd"
        every { ensureKey(any()) } just runs
    }

    private fun storeMock() = mockk<PairingStore> {
        every { current() } returns Pairing.NONE
        every { state } returns MutableStateFlow(Pairing.NONE).asStateFlow()
        every { suggestDeviceId() } returns "hn-test"
        coEvery { load() } just runs
        coEvery { save(any()) } just runs
        coEvery { clear() } just runs
    }

    private suspend fun PairingViewModel.awaitLoaded() {
        state.first { !it.isLoading }
    }

    @Test
    fun `an answering address is the one saved and the flow advances`() = runTest {
        val store = storeMock()
        var probed: List<String>? = null
        val probe: suspend (List<String>) -> String? = { candidates ->
            probed = candidates
            candidates.firstOrNull()
        }
        val viewModel = PairingViewModel(
            keys = keys,
            store = store,
            probe = probe,
            injectedScope = this,
        )
        viewModel.awaitLoaded()
        // The save path refuses a loopback address, and a build with no
        // `gatewayUrl` in local.properties defaults to one. Pin a routable
        // address so the test measures the probe decision, not the machine's
        // default.
        viewModel.onBaseUrl("http://pc.tailnet.ts.net:8788")
        val typed = viewModel.state.value.baseUrl

        var advanced = false
        viewModel.save { advanced = true }
        advanceUntilIdle()

        // The typed address is the candidate, normalised, and the answer is the
        // address that gets saved rather than the one in the field.
        assertEquals(listOf(typed), probed)
        coVerify { store.save(Pairing(typed, "hn-test")) }
        assertTrue(advanced)
        assertTrue(viewModel.state.value.saved)
        assertNull(viewModel.state.value.error)
        assertEquals(typed, viewModel.state.value.baseUrl)
    }

    @Test
    fun `when no address answers the flow shows an error and does not advance`() = runTest {
        val store = storeMock()
        val probe: suspend (List<String>) -> String? = { null }
        val viewModel = PairingViewModel(
            keys = keys,
            store = store,
            probe = probe,
            injectedScope = this,
        )
        viewModel.awaitLoaded()

        var advanced = false
        viewModel.save { advanced = true }
        advanceUntilIdle()

        coVerify(exactly = 0) { store.save(any()) }
        assertFalse(advanced)
        assertFalse(viewModel.state.value.saved)
        assertNotNull(viewModel.state.value.error)
    }
}
