package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProjectGroupsTest {

    private fun agent(
        paneId: String,
        project: String,
        status: AgentStatus = AgentStatus.IDLE,
        agent: String = "opencode",
        title: String? = null,
        cwd: String? = null,
    ) = AgentSummary(
        paneId = paneId,
        workspaceId = paneId.substringBefore(':'),
        project = project,
        agent = agent,
        status = status,
        attention = if (status == AgentStatus.BLOCKED) 3 else 1,
        title = title,
        cwd = cwd,
        focused = false,
        canResume = true,
    )

    @Test
    fun `agents are grouped by project, in first-seen order`() {
        val groups = groupByProject(
            listOf(
                agent("w2:p1", "beta"),
                agent("w1:p1", "alpha"),
                agent("w2:p2", "beta"),
                agent("w3:p1", "gamma"),
            ),
        )

        assertEquals(listOf("beta", "alpha", "gamma"), groups.map { it.project })
        assertEquals(2, groups[0].count)
        assertEquals(listOf("w2:p1", "w2:p2"), groups[0].agents.map { it.paneId })
    }

    @Test
    fun `the header counts how many in the group are waiting`() {
        val group = groupByProject(
            listOf(
                agent("w1:p1", "alpha", status = AgentStatus.BLOCKED),
                agent("w1:p2", "alpha", status = AgentStatus.WORKING),
                agent("w1:p3", "alpha", status = AgentStatus.BLOCKED),
            ),
        ).single()

        assertEquals(3, group.count)
        assertEquals(2, group.waiting)
        assertEquals("w1:p1", group.latest?.paneId)
    }

    @Test
    fun `filter matches project, agent, title and cwd`() {
        val agents = listOf(
            agent("w1:p1", "herdr-notify", title = "pairing screen", cwd = "C:\\dev\\herdr"),
            agent("w2:p1", "atlas-os", agent = "claude", title = "release"),
        )

        assertEquals(listOf("w2:p1"), filterAgents(agents, "atlas").map { it.paneId })
        assertEquals(listOf("w1:p1"), filterAgents(agents, "pairing").map { it.paneId })
        assertEquals(listOf("w2:p1"), filterAgents(agents, "claude").map { it.paneId })
        assertEquals(listOf("w1:p1"), filterAgents(agents, "dev\\herdr").map { it.paneId })
    }

    @Test
    fun `a blank query keeps the gateway ordering untouched`() {
        val agents = listOf(agent("w1:p1", "alpha"), agent("w2:p1", "beta"))
        assertEquals(agents, filterAgents(agents, "   "))
    }

    @Test
    fun `a query that matches nothing yields no groups`() {
        val groups = groupByProject(filterAgents(listOf(agent("w1:p1", "alpha")), "zzz"))
        assertTrue(groups.isEmpty())
    }
}
