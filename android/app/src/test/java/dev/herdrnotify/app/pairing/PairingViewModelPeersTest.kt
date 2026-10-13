package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.security.DeviceKeyStore
import io.mockk.coEvery
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
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelPeersTest {

    private val keys = mockk<DeviceKeyStore> {
        every { hasKey() } returns true
        every { publicKeyBase64() } returns "BAAAAA"
        every { fingerprint() } returns "aa:bb:cc:dd"
        every { ensureKey(any()) } just runs
    }

    private fun pairedStore() = mockk<PairingStore> {
        every { current() } returns Pairing("http://100.64.0.5:8788", "dev-1")
        every { state } returns MutableStateFlow(Pairing("http://100.64.0.5:8788", "dev-1")).asStateFlow()
        every { suggestDeviceId() } returns "hn-test"
        coEvery { load() } just runs
        coEvery { save(any()) } just runs
        coEvery { clear() } just runs
    }

    private suspend fun PairingViewModel.awaitLoaded() {
        state.first { !it.isLoading }
    }

    @Test
    fun `reachable peers are offered once the screen loads`() = runTest {
        val viewModel = PairingViewModel(
            keys = keys,
            store = pairedStore(),
            peers = { Result.success(listOf(TailnetPeer("pc", listOf("100.64.0.2"), online = true))) },
            injectedScope = this,
        )
        viewModel.awaitLoaded()
        advanceUntilIdle()

        assertEquals(listOf("pc"), viewModel.state.value.peers.map { it.name })
        assertFalse(viewModel.state.value.peersUnavailable)
    }

    @Test
    fun `a 503 falls back to the manual field`() = runTest {
        val viewModel = PairingViewModel(
            keys = keys,
            store = pairedStore(),
            peers = { Result.failure(PeersUnavailable()) },
            injectedScope = this,
        )
        viewModel.awaitLoaded()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.peers.isEmpty())
        assertTrue(viewModel.state.value.peersUnavailable)
    }

    @Test
    fun `picking a peer fills the address field with its tailnet ip`() = runTest {
        val viewModel = PairingViewModel(
            keys = keys,
            store = pairedStore(),
            peers = { Result.success(emptyList()) },
            injectedScope = this,
        )
        viewModel.awaitLoaded()
        advanceUntilIdle()

        viewModel.onPickPeer(TailnetPeer("pc", listOf("100.64.0.2"), online = true))

        assertEquals("http://100.64.0.2:8788", viewModel.state.value.baseUrl)
    }
}
