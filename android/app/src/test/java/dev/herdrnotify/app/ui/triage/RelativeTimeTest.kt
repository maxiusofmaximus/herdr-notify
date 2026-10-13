package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The "how old is this list" text, and the subtitle that carries it.
 *
 * A stale list shown without its age looks like a live one, which is the
 * failure this exists to prevent. So the units are coarse on purpose: a person
 * can act on "hace 3 min", and a count of milliseconds tells them nothing.
 */
class RelativeTimeTest {

    @Test
    fun `seconds are shown in seconds`() {
        assertEquals("hace 5 s", formatSince(5_000L))
        assertEquals("hace 59 s", formatSince(59_999L))
    }

    @Test
    fun `a minute rolls over into minutes, rounded down`() {
        assertEquals("hace 1 min", formatSince(60_000L))
        assertEquals("hace 3 min", formatSince(3 * 60_000L + 30_000L))
    }

    @Test
    fun `an hour rolls over into hours, rounded down`() {
        assertEquals("hace 1 h", formatSince(3_600_000L))
        assertEquals("hace 2 h", formatSince(2 * 3_600_000L + 900_000L))
    }

    @Test
    fun `a clock that went backwards reads as just now, not as a negative age`() {
        assertEquals("hace 0 s", formatSince(-4_000L))
    }

    @Test
    fun `an offline list says how long ago it was last updated`() {
        val offline = ConnectionState.Offline(
            lastKnown = SessionState.EMPTY,
            reason = "stream closed",
            updatedAt = 1_000L,
        )

        assertEquals(
            "Desconectado · última actualización hace 5 s",
            offline.subtitle(now = 6_000L),
        )
    }

    @Test
    fun `an offline screen that never had an update does not invent an age`() {
        val offline = ConnectionState.Offline(SessionState.EMPTY, "gone")

        assertEquals("Desconectado", offline.subtitle(now = 6_000L))
    }

    @Test
    fun `a live list still shows its agent count`() {
        val agents = listOf("w1:p1", "w2:p1").map { id ->
            AgentSummary(
                paneId = id,
                workspaceId = id.substringBefore(':'),
                project = "p",
                agent = "opencode",
                status = AgentStatus.WORKING,
                attention = 1,
                title = null,
                cwd = null,
                focused = false,
                canResume = true,
            )
        }
        val live = ConnectionState.Live(
            SessionState(revision = 1, herdrVersion = null, agents = agents, counts = emptyMap()),
            updatedAt = 1_000L,
        )

        assertEquals("2 agentes", live.subtitle(now = 6_000L))
    }
}
