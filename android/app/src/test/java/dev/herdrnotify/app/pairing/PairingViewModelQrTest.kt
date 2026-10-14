package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.PairRequest
import dev.herdrnotify.app.net.PairResponse
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The QR path is the manual path with the two fields filled for you.
 *
 * The behaviour worth pinning is that a valid QR runs the *same* claim (so there
 * is no second pairing path), and that an invalid QR changes nothing but the
 * reason it shows.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelQrTest {

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

    private fun response() =
        PairResponse("dev-1234", "p256", "hn-test", listOf("read_state"), "12345", "7QK3-M2XP")

    private suspend fun PairingViewModel.awaitLoaded() {
        state.first { !it.isLoading }
    }

    @Test
    fun `a valid QR fills both fields and runs the same claim`() = runTest {
        val captured = mutableListOf<PairRequest>()
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, request -> captured += request; Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onQrScanned(
            "herdr-notify://pair?u=http%3A%2F%2Fpc.tailnet.ts.net%3A8788&c=abcd1234&v=1",
        )
        advanceUntilIdle()

        assertEquals("http://pc.tailnet.ts.net:8788", vm.state.value.baseUrl)
        // The claim upper-cases the code, exactly like a typed one.
        assertEquals("ABCD1234", captured.single().code)
        assertEquals("dev-1234", vm.state.value.claimedDeviceId)
        assertNull(vm.state.value.qrError)
    }

    @Test
    fun `an invalid QR sets a reason and changes nothing else`() = runTest {
        var paired = false
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, _ -> paired = true; Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()
        val before = vm.state.value.baseUrl

        vm.onQrScanned("https://example.test/not-a-pairing-code")
        advanceUntilIdle()

        assertFalse(paired)
        assertNotNull(vm.state.value.qrError)
        assertEquals(before, vm.state.value.baseUrl)
        assertNull(vm.state.value.claimedDeviceId)
    }

    @Test
    fun `a loopback QR is refused like the manual flow refuses it`() = runTest {
        var paired = false
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, _ -> paired = true; Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onQrScanned("herdr-notify://pair?u=http%3A%2F%2F127.0.0.1%3A8788&c=C&v=1")
        advanceUntilIdle()

        assertFalse(paired)
        assertTrue(vm.state.value.qrError!!.contains("este mismo teléfono"))
    }

    @Test
    fun `the reason can be dismissed for another try`() = runTest {
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, _ -> Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onQrScanned("nonsense")
        assertNotNull(vm.state.value.qrError)

        vm.dismissQrError()
        assertNull(vm.state.value.qrError)
    }
}
