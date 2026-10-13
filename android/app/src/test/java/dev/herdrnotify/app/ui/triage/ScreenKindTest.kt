package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import org.junit.Assert.assertEquals
import org.junit.Test

class ScreenKindTest {

    private val agent = AgentSummary(
        paneId = "w1:p1",
        workspaceId = "w1",
        project = "demo",
        agent = "opencode",
        status = AgentStatus.WORKING,
        attention = 2,
        title = null,
        cwd = null,
        focused = false,
        canResume = false,
    )

    private val withAgents = SessionState(1, "0.9.1", listOf(agent), mapOf(AgentStatus.WORKING to 1))

    @Test
    fun `not paired shows the pairing path, never a list`() {
        assertEquals(ScreenKind.UNPAIRED, ConnectionState.Unpaired.screenKind())
    }

    @Test
    fun `connecting shows loading`() {
        assertEquals(ScreenKind.CONNECTING, ConnectionState.Connecting.screenKind())
    }

    @Test
    fun `a failed stream is an error with retry`() {
        assertEquals(ScreenKind.FAILED, ConnectionState.Failed("boom").screenKind())
    }

    @Test
    fun `offline with nothing ever received is an error, not an empty list`() {
        val state = ConnectionState.Offline(SessionState.EMPTY, reason = null, updatedAt = 0L)
        assertEquals(ScreenKind.OFFLINE_NO_DATA, state.screenKind())
    }

    @Test
    fun `offline with an empty last known list is still an error`() {
        val state = ConnectionState.Offline(SessionState.EMPTY, reason = null, updatedAt = 1_000L)
        assertEquals(ScreenKind.OFFLINE_NO_DATA, state.screenKind())
    }

    @Test
    fun `offline with a last known list keeps showing it`() {
        val state = ConnectionState.Offline(withAgents, reason = null, updatedAt = 1_000L)
        assertEquals(ScreenKind.LIST, state.screenKind())
    }

    @Test
    fun `live and empty is the only place the empty state appears`() {
        assertEquals(ScreenKind.EMPTY, ConnectionState.Live(SessionState.EMPTY).screenKind())
    }

    @Test
    fun `live with agents is a list`() {
        assertEquals(ScreenKind.LIST, ConnectionState.Live(withAgents).screenKind())
    }
}
