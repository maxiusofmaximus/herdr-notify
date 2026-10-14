package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.Wire
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The screen's contract, and the one place the states are checked as a set.
 *
 * The individual cases were already pinned against a real stream; what is added
 * here is the ordering guarantee, which cannot be tested from any single test:
 * that a reconnect never regresses the screen from Live to Connecting, because a
 * person reading a list of nine agents is worse served by a spinner than by a
 * list that is two seconds stale.
 */
class TriageViewModelTest {

    private fun agent(
        paneId: String,
        status: AgentStatus,
        project: String = "proj",
        title: String? = "task",
        focused: Boolean = false,
    ) = AgentSummary(
        paneId = paneId,
        workspaceId = paneId.substringBefore(':'),
        project = project,
        agent = "opencode",
        status = status,
        attention = if (status == AgentStatus.BLOCKED) 3 else 1,
        title = title,
        cwd = "C:\\dev\\$project",
        focused = focused,
        canResume = true,
    )

    private fun stateWith(vararg agents: AgentSummary) = SessionState(
        revision = 1,
        herdrVersion = "0.9.1",
        agents = agents.toList(),
        counts = emptyMap(),
    )

    @Test
    fun `a live repository is shown`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))

        val state = vm.state.value
        assertTrue(state is ConnectionState.Live)
        assertEquals(1, (state as ConnectionState.Live).state.agents.size)
    }

    @Test
    fun `an unpaired phone says so rather than showing an empty list`() = runTest {
        val repo = FakeTriageRepository(ConnectionState.Unpaired)
        val vm = TriageViewModel(repo, backgroundScope)
        // The initial value is Unpaired, and the collector has to run before the
        // flow's value is guaranteed to have been observed.
        yield()
        assertTrue(vm.state.value is ConnectionState.Unpaired)
    }

    @Test
    fun `offline keeps the last known state on screen`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        val last = stateWith(agent("w1:p1", AgentStatus.BLOCKED), agent("w2:p1", AgentStatus.WORKING))
        repo.emit(ConnectionState.Live(last))
        repo.emit(ConnectionState.Offline(last, "host went away"))

        val offline = vm.state.value as ConnectionState.Offline
        assertEquals(2, offline.lastKnown.agents.size)
        assertTrue("a stale list beats a spinner", offline.lastKnown.needsYou.isNotEmpty())
    }

    @Test
    fun `a reconnect does not blank a live list`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        repo.emit(ConnectionState.Connecting)

        // If Connecting replaced Live, the screen would flash a spinner every
        // time the stream reconnected, which is the single most common thing a
        // person sees on a flaky tailnet link.
        val current = vm.state.value
        assertTrue("reconnect must not regress to Connecting", current is ConnectionState.Live)
    }

    @Test
    fun `an unconfigured repository starts as Connecting`() = runTest {
        // The regression guard on reconnect must not stop the first state from
        // ever being Connecting, or the screen would have nothing to show at
        // launch. `currentState()` defaults to Connecting for exactly this.
        val vm = TriageViewModel(NeverConfigured(), backgroundScope)
        assertTrue(
            "expected Connecting, got ${vm.state.value}",
            vm.state.value is ConnectionState.Connecting,
        )
    }

    /** A repository that reports nothing and never emits, to pin the default. */
    private class NeverConfigured : TriageRepository {
        override val connection = kotlinx.coroutines.flow.flow<ConnectionState> {}
        override suspend fun markSeen(paneId: String) = Unit
        override suspend fun respond(paneId: String, text: String): Result<Unit> = Result.success(Unit)
        override suspend fun read(paneId: String, lines: Int): Result<String> = Result.success("")
        override suspend fun sendKey(paneId: String, key: String, confirmed: Boolean) = Unit
        override suspend fun refresh() = Unit
    }

    @Test
    fun `an error can be dismissed back to connecting`() = runTest {
        val repo = FakeTriageRepository()
        // The scope is supplied so the test controls the dispatcher rather than
        // depending on Main, which does not exist in a JVM unit test.
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Failed("boom"))
        assertTrue("expected Failed, got ${vm.state.value}", vm.state.value is ConnectionState.Failed)
        vm.onDismissError()
        assertTrue(
            "expected Connecting after dismissal, got ${vm.state.value}",
            vm.state.value is ConnectionState.Connecting,
        )
    }

    @Test
    fun `dismissing an error does not touch a live list`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onDismissError()
        assertTrue("there is no error to dismiss", vm.state.value is ConnectionState.Live)
    }

    @Test
    fun `opening an agent marks it seen`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        vm.onOpenAgent("w1:p1")
        // The write is launched, so the assertion has to give the dispatcher a
        // turn. Without this it would pass on an empty list or fail on
        // scheduling, and neither outcome would mean anything.
        yield()
        assertEquals(listOf("w1:p1"), repo.seen)
    }

    @Test
    fun `the subtitle counts what is waiting, not everything`() = runTest {
        val vm = TriageViewModel(FakeTriageRepository(), backgroundScope)
        val live = ConnectionState.Live(
            stateWith(
                agent("w1:p1", AgentStatus.BLOCKED),
                agent("w2:p1", AgentStatus.WORKING),
                agent("w3:p1", AgentStatus.WORKING),
            ),
        )
        // One agent needs a decision, so one is what the subtitle says. Counting
        // all three would make a working session look as urgent as a blocked one,
        // which is the whole distinction the triage list exists to make.
        assertEquals("1 te esperan", live.subtitle())
    }

    @Test
    fun `the subtitle for no agents is not alarming`() = runTest {
        val empty = ConnectionState.Live(SessionState.EMPTY)
        assertEquals("Nada en marcha", empty.subtitle())
    }

    @Test
    fun `the subtitle for offline says so, and how old the list is`() = runTest {
        // Was "Sin conexión". The offline subtitle now carries the age of the
        // list, which is the point of the change: a stale list must say it is stale.
        val offline = ConnectionState.Offline(SessionState.EMPTY, "gone", updatedAt = 1L)
        assertEquals("Desconectado · última actualización hace 0 s", offline.subtitle(now = 1L))
    }

    @Test
    fun `a payload is rendered in the order the gateway ranked it`() = runTest {
        // The gateway sorts by (-attention, focused, project, pane_id) before it
        // serialises, and this test pins the contract that the app does not
        // re-sort. If a sort were added on the phone, the two sides could
        // disagree about which agent is first — and the blocked one would not be
        // the one at the top.
        val body = """
            {"revision":3,"herdr_version":"0.9.1",
             "agents":[
               {"pane_id":"w1:p1","project":"a","agent":"opencode","status":"blocked",
                "attention":3,"title":"t1","focused":false,"can_resume":true},
               {"pane_id":"w2:p1","project":"b","agent":"opencode","status":"working",
                "attention":1,"title":"t2","focused":true,"can_resume":true}]}
        """.trimIndent()
        val state = Wire.state(body)!!
        assertEquals(
            "the gateway's order must survive decoding",
            listOf("w1:p1", "w2:p1"),
            state.agents.map { it.paneId },
        )
        assertEquals(AgentStatus.BLOCKED, state.agents.first().status)
        assertEquals(1, state.needsYou.size)
    }

    @Test
    fun `a row always has something on its second line`() = runTest {
        // An agent with no task title is normal, not an error, and a blank
        // subtitle renders as a fault even when the data is complete.
        val state = Wire.state("""{"agents":[{"pane_id":"w1:p1","agent":"opencode","project":"p"}]}""")!!
        val row = state.agents.single()
        assertEquals("opencode", row.agent)
        val secondLine = row.title?.takeIf { it.isNotBlank() }
            ?: row.agent.takeIf { it.isNotBlank() }
            ?: row.project
        assertTrue("the row must never render an empty second line", secondLine.isNotBlank())
    }

    @Test
    fun `the output is read every three seconds, and reading stops when the detail closes`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onOpenAgent("w1:p1")
        runCurrent()
        assertEquals("the first read happens at once", 1, repo.reads.size)
        assertEquals("salida del agente", vm.detail.value?.output)

        advanceTimeBy(TriageViewModel.POLL_MILLIS)
        runCurrent()
        assertEquals("one tick later, one more read", 2, repo.reads.size)

        vm.onCloseAgent()
        advanceTimeBy(TriageViewModel.POLL_MILLIS * 5)
        runCurrent()
        assertEquals("a closed detail must not keep reading", 2, repo.reads.size)
        assertEquals("the tail is what is asked for", 60, repo.reads.first().second)
        assertEquals(null, vm.detail.value)
    }

    @Test
    fun `the poll interval is 15 seconds, because every read moves the PC session viewport`() {
        // Each agent.read the phone makes is repeated by herdr on the PC, and each
        // one moves the Claude session's viewport: at 3 s the terminal was dragged
        // out from under the person every few seconds while they were reading.
        // 15 s still reads at once on open and after a send — only the background
        // poll slows down, which is the part nobody is waiting on.
        assertEquals(15_000L, TriageViewModel.POLL_MILLIS)
    }

    @Test
    fun `thirty seconds of polling produce one read per interval, plus the immediate one`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onOpenAgent("w1:p1")
        runCurrent()
        assertEquals("the first read happens at once", 1, repo.reads.size)

        advanceTimeBy(30_000)
        runCurrent()

        // advanceTimeBy runs the task scheduled exactly on the boundary too, so
        // 30 s hold the immediate read plus one read per elapsed interval.
        val expected = 1 + (30_000 / TriageViewModel.POLL_MILLIS).toInt()
        assertEquals("one immediate read plus one per poll interval in 30 s", expected, repo.reads.size)
    }

    @Test
    fun `sending to an agent that is not waiting asks for confirmation first`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("sí, hazlo")

        vm.onSend()
        runCurrent()

        assertTrue("nothing may be sent before the person confirms", repo.replies.isEmpty())
        assertTrue(vm.detail.value!!.confirmRequired)
    }

    @Test
    fun `confirming sends the text, clears the box and reads the output at once`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        runCurrent()
        val readsBeforeSend = repo.reads.size
        vm.onDraftChange("  sí, hazlo  ")

        vm.onSend()
        vm.onConfirmSend()
        runCurrent()

        assertEquals(listOf("w1:p1" to "sí, hazlo"), repo.replies)
        assertEquals("", vm.detail.value!!.draft)
        assertFalse(vm.detail.value!!.confirmRequired)
        assertEquals("a send forces a read", readsBeforeSend + 1, repo.reads.size)
    }

    @Test
    fun `sending to a blocked agent does not ask, because that is what it is waiting for`() = runTest {
        val repo = FakeTriageRepository()
        // The view model is built before the state is emitted: its collector has
        // to be running to see the emission, or the blocked check reads the
        // stale initial state and the test passes or fails for the wrong reason.
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("sí")

        vm.onSend()
        runCurrent()

        assertEquals(listOf("w1:p1" to "sí"), repo.replies)
        assertFalse(vm.detail.value!!.confirmRequired)
    }

    @Test
    fun `a blank message is not sent`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("   ")

        vm.onSend()
        runCurrent()

        assertTrue(repo.replies.isEmpty())
    }

    @Test
    fun `retrying a message sends that text directly, without the confirmation`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        // The agent is working: the composer would ask before sending, but a
        // Retry on a message is already an explicit decision to send again.
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onRetryPrompt("  arregla el scroll  ")
        runCurrent()

        assertEquals(listOf("w1:p1" to "arregla el scroll"), repo.replies)
        assertFalse(vm.detail.value!!.confirmRequired)
    }

    @Test
    fun `retrying a blank message sends nothing`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onRetryPrompt("   ")
        runCurrent()

        assertTrue(repo.replies.isEmpty())
    }

    @Test
    fun `a 403 on send says the phone may not send, and the connection stays as it was`() = runTest {
        val repo = FakeTriageRepository()
        repo.respondResult = Result.failure(GatewayClient.GatewayError.NotPermitted("forbidden"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("sí")

        vm.onSend()
        runCurrent()

        assertEquals(
            "Este teléfono no tiene permiso para enviar mensajes",
            vm.detail.value!!.notice,
        )
        assertEquals("the text is kept so it is not lost", "sí", vm.detail.value!!.draft)
        assertTrue(
            "a 403 must not change the connection, got ${vm.state.value}",
            vm.state.value is ConnectionState.Live,
        )
    }

    @Test
    fun `a 409 on send says the agent is waiting for an approval`() = runTest {
        val repo = FakeTriageRepository()
        repo.respondResult = Result.failure(GatewayClient.GatewayError.Rejected(409, "blocked"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("sí")

        vm.onSend()
        runCurrent()

        assertEquals(
            "El agente está esperando una aprobación; usa los botones",
            vm.detail.value!!.notice,
        )
    }

    @Test
    fun `a 409 on read says the agent is working, not that reading failed`() {
        // herdr refuses a full history read while the pane is on its alternate
        // screen, and the gateway may still answer 409 if the visible fallback
        // is refused too. That is a transient state the poll retries, so the
        // screen must not show the generic, permanent-looking failure.
        assertEquals(
            "El agente está trabajando; se leerá la salida en un momento",
            readFailure(GatewayClient.GatewayError.Rejected(409, "working")),
        )
    }

    @Test
    fun `a non-403, non-409 read failure gets the generic message`() {
        assertEquals(
            "No se pudo leer la salida del agente",
            readFailure(IllegalStateException("boom")),
        )
    }

    @Test
    fun `a read error says whether retrying can help`() {
        // The card only offers Retry when a retry can succeed: a closed pane and
        // a permission refusal are final, a transient conflict is not.
        val gone = readError(GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found"))
        assertFalse("a closed pane must not offer Retry", gone.retryable)
        assertFalse("a closed pane is not a transient notice", gone.transient)

        val forbidden = readError(GatewayClient.GatewayError.NotPermitted("forbidden"))
        assertFalse("a 403 is final for this action", forbidden.retryable)

        val working = readError(GatewayClient.GatewayError.Rejected(409, "working"))
        assertTrue("a transient conflict is worth retrying", working.retryable)
        assertTrue("the 409 working case is a notice, not an error", working.transient)

        val generic = readError(IllegalStateException("boom"))
        assertTrue("an unknown read failure is worth retrying", generic.retryable)
        assertFalse("an unknown failure is a real error", generic.transient)
    }

    @Test
    fun `a transient read failure retries on the short cadence`() = runTest {
        val repo = FakeTriageRepository()
        repo.readResult = Result.failure(GatewayClient.GatewayError.Rejected(409, "working"))
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onOpenAgent("w1:p1")
        runCurrent()
        assertEquals("the first read happens at once", 1, repo.reads.size)
        assertTrue("the working case is transient", vm.detail.value!!.outputError!!.transient)

        advanceTimeBy(TriageViewModel.RETRY_MILLIS)
        runCurrent()
        assertEquals("a transient failure is re-read on the short cadence", 2, repo.reads.size)
    }

    @Test
    fun `a real read error waits the normal poll interval`() = runTest {
        val repo = FakeTriageRepository()
        repo.readResult = Result.failure(IllegalStateException("boom"))
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onOpenAgent("w1:p1")
        runCurrent()
        assertEquals(1, repo.reads.size)

        advanceTimeBy(TriageViewModel.RETRY_MILLIS)
        runCurrent()
        assertEquals("a real error must not spin on the short cadence", 1, repo.reads.size)

        advanceTimeBy(TriageViewModel.POLL_MILLIS)
        runCurrent()
        assertEquals("it still retries on the normal cadence", 2, repo.reads.size)
    }

    @Test
    fun `a 404 on read says the agent is gone, not that reading failed`() {
        // The symptom this pins: a chat left open for a pane the operator
        // closed showed the red generic read failure and polled forever.
        assertEquals(
            "Este agente ya no existe",
            readFailure(GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found")),
        )
    }

    @Test
    fun `a 404 on send and on a permission answer say the agent is gone`() {
        val gone = GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found")
        assertEquals("Este agente ya no existe", sendFailure(gone))
        assertEquals("Este agente ya no existe", keyFailure(gone))
    }

    @Test
    fun `a 409 is still the working or awaiting answer, never the gone one`() {
        val conflict = GatewayClient.GatewayError.Rejected(409, "cannot read while working")
        assertFalse(conflict.isAgentGone())
        assertEquals(
            "El agente está trabajando; se leerá la salida en un momento",
            readFailure(conflict),
        )
    }

    @Test
    fun `a gone agent stops the poll and asks for a fresh state`() = runTest {
        val repo = FakeTriageRepository()
        repo.readResult = Result.failure(
            GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found"),
        )
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("wQ:pG", AgentStatus.WORKING))))
        vm.onOpenAgent("wQ:pG")
        runCurrent()

        assertEquals("Este agente ya no existe", vm.detail.value?.outputError?.message)
        assertEquals("one read is all a gone pane gets", 1, repo.reads.size)

        advanceTimeBy(TriageViewModel.POLL_MILLIS * 5)
        runCurrent()
        assertEquals("a gone pane must not be polled", 1, repo.reads.size)
        assertEquals("the list is re-read so the row can go", 1, repo.refreshes)
    }

    @Test
    fun `a 404 on send says the agent is gone and stops the poll too`() = runTest {
        val repo = FakeTriageRepository()
        repo.respondResult = Result.failure(
            GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found"),
        )
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("wQ:pG", AgentStatus.BLOCKED))))
        vm.onOpenAgent("wQ:pG")
        runCurrent()
        val readsBeforeSend = repo.reads.size

        vm.onDraftChange("hola")
        vm.onSend()
        runCurrent()

        assertEquals("Este agente ya no existe", vm.detail.value!!.notice)
        assertEquals("the list is re-read so the row can go", 1, repo.refreshes)

        advanceTimeBy(TriageViewModel.POLL_MILLIS * 5)
        runCurrent()
        assertEquals("a gone pane must not be polled", readsBeforeSend, repo.reads.size)
    }

    @Test
    fun `the refreshed state drops the agent that is gone`() = runTest {
        val repo = FakeTriageRepository()
        repo.readResult = Result.failure(
            GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found"),
        )
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(
            ConnectionState.Live(
                stateWith(
                    agent("wQ:pG", AgentStatus.WORKING),
                    agent("w1:p1", AgentStatus.BLOCKED),
                ),
            ),
        )
        vm.onOpenAgent("wQ:pG")
        runCurrent()
        assertTrue(vm.state.value is ConnectionState.Live)

        // The refresh the 404 asked for: /v1/state no longer carries the pane
        // the operator closed, and the list renders exactly what it is given.
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        val agents = (vm.state.value as ConnectionState.Live).state.agents
        assertEquals(listOf("w1:p1"), agents.map { it.paneId })
        assertFalse(agents.any { it.paneId == "wQ:pG" })
    }

    @Test
    fun `any other failure on send gets the generic message`() = runTest {
        val repo = FakeTriageRepository()
        repo.respondResult = Result.failure(IllegalStateException("boom"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("sí")

        vm.onSend()
        runCurrent()

        assertEquals("No se pudo enviar el mensaje. Inténtalo de nuevo.", vm.detail.value!!.notice)
    }

    @Test
    fun `a permission answer is sent as the parsed keys, and forces a read`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        runCurrent()
        val readsBefore = repo.reads.size

        vm.onPermissionKeys(listOf("right", "enter"), confirmed = true)
        runCurrent()

        assertEquals(
            "the card's keys must reach the gateway in one batch",
            listOf(Triple("w1:p1", listOf("right", "enter"), true)),
            repo.keyBatches,
        )
        assertFalse(vm.detail.value!!.sending)
        assertEquals("an answer forces a read of the result", readsBefore + 1, repo.reads.size)
    }

    @Test
    fun `a plain approve answer is sent with confirm false`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onPermissionKeys(listOf("enter"), confirmed = false)
        runCurrent()

        assertEquals(
            listOf(Triple("w1:p1", listOf("enter"), false)),
            repo.keyBatches,
        )
    }

    @Test
    fun `a message longer than any client limit is still sent`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        val long = "x".repeat(20_000)
        vm.onDraftChange(long)
        vm.onSend()
        runCurrent()

        assertEquals(listOf("w1:p1" to long), repo.replies)
    }

    @Test
    fun `a refused permission answer is shown, not swallowed`() = runTest {
        val repo = FakeTriageRepository()
        repo.sendKeysResult = Result.failure(GatewayClient.GatewayError.NotPermitted("forbidden"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onPermissionKeys(listOf("enter"), confirmed = false)
        runCurrent()

        assertEquals(
            "Este teléfono no tiene permiso para responder al agente",
            vm.detail.value!!.notice,
        )
        assertFalse(vm.detail.value!!.sending)
    }

    @Test
    fun `stopping a working agent asks first, then sends ctrl+c with confirm`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onStopAgent()
        assertTrue("stopping must be confirmed before anything is sent", vm.detail.value!!.stopRequired)
        assertTrue("no key may be sent before the confirmation", repo.keyBatches.isEmpty())

        vm.onConfirmStop()
        runCurrent()

        assertEquals(
            "the interrupt key must be sent as a guarded key",
            listOf(Triple("w1:p1", listOf("ctrl+c"), true)),
            repo.keyBatches,
        )
        assertFalse(vm.detail.value!!.stopRequired)
        assertFalse(vm.detail.value!!.sending)
    }

    @Test
    fun `dismissing the stop confirmation sends nothing`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onStopAgent()
        vm.onDismissStop()
        runCurrent()

        assertTrue(repo.keyBatches.isEmpty())
        assertFalse(vm.detail.value!!.stopRequired)
    }

    @Test
    fun `a 403 on stop says the phone may not stop the agent`() = runTest {
        val repo = FakeTriageRepository()
        repo.sendKeysResult = Result.failure(GatewayClient.GatewayError.NotPermitted("forbidden"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.WORKING))))
        vm.onOpenAgent("w1:p1")
        runCurrent()

        vm.onStopAgent()
        vm.onConfirmStop()
        runCurrent()

        assertEquals(
            "Este teléfono no tiene permiso para detener al agente",
            vm.detail.value!!.notice,
        )
        assertFalse(vm.detail.value!!.sending)
    }

    @Test
    fun `a stop that finds the agent no longer working says so`() {
        assertEquals(
            "El agente ya no está trabajando",
            stopFailure(GatewayClient.GatewayError.Rejected(409, "working")),
        )
        assertEquals(
            "Este agente ya no existe",
            stopFailure(GatewayClient.GatewayError.Rejected(404, "agent target wQ:pG not found")),
        )
    }
}
