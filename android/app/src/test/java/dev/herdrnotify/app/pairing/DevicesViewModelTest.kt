package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.GatewayClient
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DevicesViewModelTest {

    private class FakeDirectory : DeviceDirectory {
        var listResult: Result<List<DeviceInfo>> = Result.success(emptyList())
        var revokeResult: Result<Unit> = Result.success(Unit)
        var listCalls = 0
        val revoked = mutableListOf<String>()

        override suspend fun list(): Result<List<DeviceInfo>> {
            listCalls++
            return listResult
        }

        override suspend fun revoke(deviceId: String): Result<Unit> {
            revoked += deviceId
            return revokeResult
        }
    }

    private fun device(id: String, revoked: Boolean = false) = DeviceInfo(
        deviceId = id,
        curve = "p256",
        label = "TECNO",
        ownerId = "12345",
        createdAt = 1_730_000_000.0,
        lastSeenAt = 1_730_000_100.0,
        revoked = revoked,
        permissions = listOf("read_state"),
    )

    @Test
    fun `the list is loaded on open`() = runTest {
        val directory = FakeDirectory().apply {
            listResult = Result.success(listOf(device("dev-self"), device("dev-old", revoked = true)))
        }
        val vm = DevicesViewModel(directory, selfId = { "dev-self" }, injectedScope = this)
        advanceUntilIdle()

        assertEquals(2, vm.state.value.devices.size)
        assertFalse(vm.state.value.loading)
        assertEquals("dev-self", vm.state.value.selfId)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `a 403 says the phone does not administer the host`() = runTest {
        val directory = FakeDirectory().apply {
            listResult = Result.failure(GatewayClient.GatewayError.NotPermitted("forbidden"))
        }
        val vm = DevicesViewModel(directory, selfId = { "dev-self" }, injectedScope = this)
        advanceUntilIdle()

        assertTrue(vm.state.value.error!!, vm.state.value.error!!.contains("admin"))
        assertFalse(vm.state.value.loading)
    }

    @Test
    fun `revoking reloads the list so the marker comes from the host`() = runTest {
        val directory = FakeDirectory()
        val vm = DevicesViewModel(directory, selfId = { "dev-self" }, injectedScope = this)
        advanceUntilIdle()
        assertEquals("one load on open", 1, directory.listCalls)

        vm.revoke("dev-old")
        advanceUntilIdle()

        assertEquals(listOf("dev-old"), directory.revoked)
        assertEquals("the list is fetched again after a revoke", 2, directory.listCalls)
    }

    @Test
    fun `a 404 on revoke says the device is already gone`() = runTest {
        val directory = FakeDirectory().apply {
            revokeResult = Result.failure(GatewayClient.GatewayError.Rejected(404, "no such device"))
        }
        val vm = DevicesViewModel(directory, selfId = { "dev-self" }, injectedScope = this)
        advanceUntilIdle()

        vm.revoke("dev-old")
        advanceUntilIdle()

        assertTrue(vm.state.value.error!!, vm.state.value.error!!.contains("ya no existe"))
        assertNull("a failed revoke must not leave a spinner on the row", vm.state.value.revokingId)
    }
}
