package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.ConnectionState

/**
 * What the main screen shows for a connection state.
 *
 * The empty list is a claim: "the host is reachable and has no agents". It must
 * be reserved for a live connection that really reported an empty list. Any
 * state where the phone does not know the host's contents is an error with a way
 * out, never "no agents running".
 */
enum class ScreenKind {
    /** Not paired: the phone needs a host first. */
    UNPAIRED,

    /** First request in flight. */
    CONNECTING,

    /** The stream reported a failure; retry is offered. */
    FAILED,

    /** Offline and nothing was ever received from the host. */
    OFFLINE_NO_DATA,

    /** Live, the host reported zero agents. The only place "empty" is shown. */
    EMPTY,

    /** A list of agents: live, or offline with a last known list (shown with its age). */
    LIST,
}

fun ConnectionState.screenKind(): ScreenKind = when (this) {
    ConnectionState.Unpaired -> ScreenKind.UNPAIRED
    ConnectionState.Connecting -> ScreenKind.CONNECTING
    is ConnectionState.Failed -> ScreenKind.FAILED
    is ConnectionState.Offline -> when {
        lastKnown.isEmpty && updatedAt == 0L -> ScreenKind.OFFLINE_NO_DATA
        lastKnown.isEmpty -> ScreenKind.OFFLINE_NO_DATA
        else -> ScreenKind.LIST
    }
    is ConnectionState.Live -> if (state.isEmpty) ScreenKind.EMPTY else ScreenKind.LIST
}
