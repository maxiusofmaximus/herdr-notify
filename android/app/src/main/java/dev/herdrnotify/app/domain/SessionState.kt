package dev.herdrnotify.app.domain

/**
 * One coding agent, as the gateway reports it.
 *
 * `attention` is the gateway's ranking carried through, not recomputed here. The
 * gateway owns the ordering because it owns the full session, and a second
 * implementation in the app would be a second place for the two to disagree —
 * with the phone showing a working agent above a blocked one.
 */
data class AgentSummary(
    val paneId: String,
    val workspaceId: String,
    val project: String,
    val agent: String,
    val status: AgentStatus,
    val attention: Int,
    val title: String?,
    val cwd: String?,
    val focused: Boolean,
    val canResume: Boolean,
) {
    val needsYou: Boolean get() = status == AgentStatus.BLOCKED
    val isFinished: Boolean get() = status == AgentStatus.DONE
}

enum class AgentStatus(val wire: String) {
    BLOCKED("blocked"),
    WORKING("working"),
    DONE("done"),
    IDLE("idle"),
    UNKNOWN("unknown"),
    ;

    companion object {
        /**
         * Map from the wire, degrading rather than throwing.
         *
         * The gateway forwards herdr's own status vocabulary, and a newer herdr
         * can add a value this build has never heard of. Crashing on it would
         * turn a server upgrade into a phone that cannot open.
         */
        fun fromWire(value: String?): AgentStatus =
            entries.firstOrNull { it.wire == value } ?: UNKNOWN
    }
}

data class SessionState(
    val revision: Long,
    val herdrVersion: String?,
    val agents: List<AgentSummary>,
    val counts: Map<AgentStatus, Int>,
) {
    val needsYou: List<AgentSummary> get() = agents.filter { it.needsYou }
    val isEmpty: Boolean get() = agents.isEmpty()

    companion object {
        val EMPTY = SessionState(0, null, emptyList(), emptyMap())
    }
}

/** The states the app itself can be in. Every one is designed, not defaulted. */
sealed interface ConnectionState {
    /** Never paired, or the gateway forgot this device. */
    data object Unpaired : ConnectionState

    /** Paired, first request in flight. */
    data object Connecting : ConnectionState

    /** [updatedAt] is the epoch millis of the last frame that changed [state]. */
    data class Live(val state: SessionState, val updatedAt: Long = 0L) : ConnectionState

    /**
     * Paired, was live, lost the host. Keeps showing the last known state, and
     * says how old it is: [updatedAt] is when [lastKnown] was received, or 0 if
     * it never was.
     */
    data class Offline(
        val lastKnown: SessionState,
        val reason: String?,
        val updatedAt: Long = 0L,
    ) : ConnectionState

    /** Paired, reachable, but something is wrong. Says what. */
    data class Failed(val message: String, val recoverable: Boolean = true) : ConnectionState
}
