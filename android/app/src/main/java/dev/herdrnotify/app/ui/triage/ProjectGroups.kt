package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentSummary

data class ProjectGroup(
    val project: String,
    val agents: List<AgentSummary>,
) {
    val count: Int get() = agents.size
    val waiting: Int get() = agents.count { it.needsYou }
    val latest: AgentSummary? get() = agents.firstOrNull()
}

fun groupByProject(agents: List<AgentSummary>): List<ProjectGroup> {
    val order = LinkedHashMap<String, MutableList<AgentSummary>>()
    agents.forEach { order.getOrPut(it.project) { mutableListOf() } += it }
    return order.map { (project, members) -> ProjectGroup(project, members.toList()) }
}

fun filterAgents(agents: List<AgentSummary>, query: String): List<AgentSummary> {
    val q = query.trim()
    if (q.isEmpty()) return agents
    return agents.filter { agent ->
        agent.project.contains(q, ignoreCase = true) ||
            agent.agent.contains(q, ignoreCase = true) ||
            (agent.title?.contains(q, ignoreCase = true) == true) ||
            (agent.cwd?.contains(q, ignoreCase = true) == true)
    }
}
