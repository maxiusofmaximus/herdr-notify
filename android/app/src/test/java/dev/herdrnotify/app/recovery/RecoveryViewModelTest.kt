package dev.herdrnotify.app.recovery

import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.domain.ConnectionState
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The guided reconnect screen's logic, on a plain JVM.
 *
 * The three collaborators are fakes, so what is under test is the decision the
 * screen makes — whether an answer becomes the saved address, whether no answer
 * still reconnects, and what it tells the person about why — not the network.
 *
 * The scope injected is the test's own, and the connection is a finite flow, so
 * `runTest` waits for every launched coroutine: an assertion that ran while the
 * probe coroutine was still queued would pass or fail for reasons unrelated to
 * the behaviour.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RecoveryViewModelTest {

    private fun stateWith(connection: ConnectionState, outcome: ProbeOutcome? = null) =
        RecoveryUiState(connection = connection, host = "hn-host:8788", outcome = outcome)

    @Test
    fun `the current connection and host are shown`() = runTest {
        val offline = ConnectionState.Offline(SessionState.EMPTY, "timeout")
        val vm = RecoveryViewModel(
            connection = flowOf(offline),
            host = { "hn-host:8788" },
            candidates = { emptyList() },
            probe = { null },
            onAddressFound = {},
            reconnect = {},
            injectedScope = this,
        )
        advanceUntilIdle()

        assertEquals("hn-host:8788", vm.state.value.host)
        assertTrue(vm.state.value.connection is ConnectionState.Offline)
    }

    @Test
    fun `retry probes every candidate and saves the one that answers`() = runTest {
        var probed: List<String>? = null
        var applied: String? = null
        var reconnects = 0
        val vm = RecoveryViewModel(
            connection = flowOf(ConnectionState.Offline(SessionState.EMPTY, "gone")),
            host = { "h" },
            candidates = { listOf("https://a", "https://b") },
            probe = { candidates -> probed = candidates; "https://b" },
            onAddressFound = { applied = it },
            reconnect = { reconnects++ },
            injectedScope = this,
        )

        vm.retry()
        advanceUntilIdle()

        assertEquals(listOf("https://a", "https://b"), probed)
        assertEquals("https://b", applied)
        assertEquals("a found address is applied, not merely retried", 0, reconnects)
        assertFalse(vm.state.value.probing)
        assertEquals(ProbeOutcome.Found("https://b"), vm.state.value.outcome)
    }

    @Test
    fun `retry with no answer records none and still reconnects`() = runTest {
        var applied: String? = null
        var reconnects = 0
        val vm = RecoveryViewModel(
            connection = flowOf(ConnectionState.Connecting),
            host = { "h" },
            candidates = { listOf("https://a") },
            probe = { null },
            onAddressFound = { applied = it },
            reconnect = { reconnects++ },
            injectedScope = this,
        )

        vm.retry()
        advanceUntilIdle()

        assertEquals(null, applied)
        assertEquals("the stream is still given a chance", 1, reconnects)
        assertEquals(ProbeOutcome.None, vm.state.value.outcome)
        assertFalse(vm.state.value.probing)
    }

    @Test
    fun `a second retry while one is in flight is ignored`() = runTest {
        val gate = CompletableDeferred<String?>()
        var probeCalls = 0
        val vm = RecoveryViewModel(
            connection = flowOf(ConnectionState.Connecting),
            host = { "h" },
            candidates = { listOf("https://a") },
            probe = { probeCalls++; gate.await() },
            onAddressFound = {},
            reconnect = {},
            injectedScope = this,
        )

        vm.retry()
        runCurrent()
        assertTrue(vm.state.value.probing)
        vm.retry()
        runCurrent()
        assertEquals("a second tap must not race a second probe", 1, probeCalls)

        gate.complete(null)
        advanceUntilIdle()
        assertFalse(vm.state.value.probing)
    }

    @Test
    fun `an unrecoverable failure tells the person to re-pair`() {
        val reason = recoveryReason(
            stateWith(ConnectionState.Failed("Este teléfono ya no está emparejado.", recoverable = false)),
        )
        assertTrue(reason, reason.contains("volver a emparejar"))
    }

    @Test
    fun `a recoverable failure is stated as it is`() {
        val reason = recoveryReason(stateWith(ConnectionState.Failed("Algo ha fallado")))
        assertEquals("Algo ha fallado", reason)
    }

    @Test
    fun `no answer names Tailscale and the host`() {
        val reason = recoveryReason(stateWith(ConnectionState.Connecting, ProbeOutcome.None))
        assertTrue(reason, reason.contains("Tailscale"))
        assertTrue(reason, reason.contains("hn-host:8788"))
    }

    @Test
    fun `a found address is named in the reason`() {
        val reason = recoveryReason(
            stateWith(ConnectionState.Connecting, ProbeOutcome.Found("https://b")),
        )
        assertTrue(reason, reason.contains("https://b"))
    }

    @Test
    fun `re-pair is led with only for unpaired or an unrecoverable failure`() {
        assertTrue(recoveryNeedsRepair(stateWith(ConnectionState.Unpaired)))
        assertTrue(
            recoveryNeedsRepair(
                stateWith(ConnectionState.Failed("no", recoverable = false)),
            ),
        )
        assertFalse(recoveryNeedsRepair(stateWith(ConnectionState.Failed("boom"))))
        assertFalse(
            recoveryNeedsRepair(
                stateWith(ConnectionState.Offline(SessionState.EMPTY, "x")),
            ),
        )
    }
}
