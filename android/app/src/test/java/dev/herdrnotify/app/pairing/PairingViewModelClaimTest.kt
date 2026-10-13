package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.PairRequest
import dev.herdrnotify.app.net.PairResponse
import dev.herdrnotify.app.net.PairingException
import dev.herdrnotify.app.security.DeviceKeyStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.runs
import io.mockk.slot
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pairing by short code (Fase 2(c)).
 *
 * The gateway assigns the device id, so the phone must adopt it rather than the
 * id the operator typed; the recovery code is shown once and stored encrypted;
 * and a blank code is the auto-approval path, not an error. Those three are the
 * behaviour that cannot be seen any other way, so they are pinned here.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelClaimTest {

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

    private class FakeRecovery : RecoveryCodeStore {
        var value: String? = null
        override fun get(): String? = value
        override fun save(code: String) {
            value = code
        }

        override fun clear() {
            value = null
        }
    }

    private fun response(recovery: String? = "7QK3-M2XP-9B7C-D4HF") =
        PairResponse("dev-1234", "p256", "hn-test", listOf("read_state"), "12345", recovery)

    private suspend fun PairingViewModel.awaitLoaded() {
        state.first { !it.isLoading }
    }

    @Test
    fun `claim sends the upper-cased code and holds the identity until commit`() = runTest {
        val store = storeMock()
        var captured: PairRequest? = null
        val vm = PairingViewModel(
            keys = keys,
            store = store,
            probe = { it.firstOrNull() },
            pair = { _, request -> captured = request; Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onCode("hjkq2zp4")
        vm.claim()
        advanceUntilIdle()

        assertEquals("HJKQ2ZP4", captured!!.code)
        assertEquals("dev-1234", vm.state.value.claimedDeviceId)
        assertEquals("7QK3-M2XP-9B7C-D4HF", vm.state.value.recoveryCode)
        assertFalse(vm.state.value.claiming)
        // Not committed yet: the recovery code has to be shown before the phone
        // leaves the screen.
        coVerify(exactly = 0) { store.save(any()) }
    }

    @Test
    fun `commit stores the assigned device id and the recovery code`() = runTest {
        val store = storeMock()
        val recovery = FakeRecovery()
        val vm = PairingViewModel(
            keys = keys,
            store = store,
            probe = { it.firstOrNull() },
            pair = { _, _ -> Result.success(response()) },
            recoveryCodes = recovery,
            injectedScope = this,
        )
        vm.awaitLoaded()
        vm.onCode("HJKQ2ZP4")
        vm.claim()
        advanceUntilIdle()

        var advanced = false
        vm.commitClaim { advanced = true }
        advanceUntilIdle()

        val saved = slot<Pairing>()
        coVerify { store.save(capture(saved)) }
        assertEquals("dev-1234", saved.captured.deviceId)
        assertTrue(saved.captured.baseUrl.isNotBlank())
        assertEquals("7QK3-M2XP-9B7C-D4HF", recovery.get())
        assertTrue(advanced)
    }

    @Test
    fun `a blank code asks for auto-approval instead of sending an empty code`() = runTest {
        var captured: PairRequest? = null
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, request -> captured = request; Result.success(response()) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onCode("   ")
        vm.claim()
        advanceUntilIdle()

        assertNull("a blank code must be absent, not empty", captured!!.code)
    }

    @Test
    fun `a 403 says the code is wrong or expired, and nothing is committed`() = runTest {
        val store = storeMock()
        val vm = PairingViewModel(
            keys = keys,
            store = store,
            probe = { it.firstOrNull() },
            pair = { _, _ -> Result.failure(PairingException(403, "pairing_rejected")) },
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.onCode("BADCODE1")
        vm.claim()
        advanceUntilIdle()

        assertTrue(vm.state.value.codeError!!, vm.state.value.codeError!!.contains("caducado"))
        assertFalse(vm.state.value.claiming)
        assertNull(vm.state.value.claimedDeviceId)
        coVerify(exactly = 0) { store.save(any()) }
    }

    @Test
    fun `re-pair uses the stored recovery code`() = runTest {
        val recovery = FakeRecovery().apply { value = "AAAA-BBBB-CCCC-DDDD" }
        var captured: PairRequest? = null
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, request -> captured = request; Result.success(response("EEEE-FFFF-0000-1111")) },
            recoveryCodes = recovery,
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.repairWithRecovery()
        advanceUntilIdle()

        assertEquals("AAAA-BBBB-CCCC-DDDD", captured!!.code)
        assertEquals("the rotated code is held for commit", "EEEE-FFFF-0000-1111", vm.state.value.recoveryCode)
    }

    @Test
    fun `re-pair without a stored code says there is none`() = runTest {
        val vm = PairingViewModel(
            keys = keys,
            store = storeMock(),
            probe = { it.firstOrNull() },
            pair = { _, _ -> Result.success(response()) },
            recoveryCodes = NoRecoveryCodeStore,
            injectedScope = this,
        )
        vm.awaitLoaded()

        vm.repairWithRecovery()

        assertTrue(
            vm.state.value.codeError!!,
            vm.state.value.codeError!!.contains("recuperación"),
        )
    }

    @Test
    fun `a rate limit tells the person to wait`() {
        assertTrue(claimFailure(PairingException(429, "slow down")).contains("Espera"))
    }
}
