package dev.herdrnotify.app.recovery

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dev.herdrnotify.app.domain.ConnectionState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * The result of the last "Reintentar".
 *
 * [Found] carries the address that answered the unauthenticated health probe, so
 * the screen can say which one worked instead of a bare "reconnected". [None]
 * means no address answered within the probe's bound, which is the concrete
 * signal that the fault is the link (Tailscale), not the app.
 */
sealed interface ProbeOutcome {
    data class Found(val url: String) : ProbeOutcome
    data object None : ProbeOutcome
}

/**
 * What the guided "Sin conexión" screen shows.
 *
 * [connection] mirrors the repository's own flow rather than being owned here:
 * the recovery screen is another view of the same connection, not a second
 * source of truth about it.
 */
data class RecoveryUiState(
    val connection: ConnectionState = ConnectionState.Connecting,
    val host: String = "",
    val probing: Boolean = false,
    val outcome: ProbeOutcome? = null,
)

/**
 * Drives the guided reconnect screen.
 *
 * The old screen was a dead end: a message and one "Reintentar". This one has
 * the three steps that actually fix an unreachable host, in the order a person
 * would take them, and it names the reason it failed instead of restating that
 * it did.
 *
 * The work is not in this class — it is in the three collaborators it is handed,
 * which is what lets the whole flow be tested on a plain JVM without a Context,
 * a keystore or a socket.
 */
class RecoveryViewModel(
    connection: Flow<ConnectionState>,
    private val host: () -> String,
    // Every address that names the same gateway, in priority order. The prober
    // decides by priority which one answers, so the result does not change with
    // network timing.
    private val candidates: () -> List<String>,
    private val probe: suspend (List<String>) -> String?,
    // Point the app at an address that answered: save it and reconnect. A
    // separate call from [reconnect] because a found address is a *change*,
    // while no answer is only an attempt.
    private val onAddressFound: suspend (String) -> Unit,
    private val reconnect: () -> Unit,
    // Nullable rather than defaulted to `viewModelScope`, because that is an
    // extension property and a default argument has no `this` to resolve it
    // against — the same reason PairingViewModel takes one.
    injectedScope: CoroutineScope? = null,
) : ViewModel() {

    private val scope: CoroutineScope = injectedScope ?: viewModelScope

    private val _state = MutableStateFlow(RecoveryUiState())
    val state: StateFlow<RecoveryUiState> = _state.asStateFlow()

    init {
        scope.launch {
            connection.collect { next ->
                _state.update { it.copy(connection = next, host = host()) }
            }
        }
    }

    /**
     * Re-probe every address and reconnect.
     *
     * A second tap while a probe is in flight is ignored: the coroutine is
     * already going to answer, and launching another would race two answers onto
     * one screen.
     */
    fun retry() {
        if (_state.value.probing) return
        _state.update { it.copy(probing = true, outcome = null) }
        scope.launch {
            val found = probe(candidates())
            if (found != null) {
                onAddressFound(found)
                _state.update { it.copy(probing = false, outcome = ProbeOutcome.Found(found)) }
            } else {
                _state.update { it.copy(probing = false, outcome = ProbeOutcome.None) }
                // Nothing answered, but the stream may still recover on its own
                // (the address could answer the signed call even if the health
                // probe timed out), so the reconnect is attempted regardless.
                reconnect()
            }
        }
    }
}

/**
 * The concrete reason, in plain Spanish, for the state the screen is in.
 *
 * A probe result, once there is one, is more specific than the connection's own
 * reason and supersedes it: "no address answers" says Tailscale, while a
 * generic offline message would not.
 */
internal fun recoveryReason(state: RecoveryUiState): String = when (val outcome = state.outcome) {
    is ProbeOutcome.Found ->
        "El equipo responde en ${outcome.url}. Reconectando…"

    ProbeOutcome.None ->
        "Ninguna dirección del equipo responde (${state.host.ifBlank { "sin dirección" }}). " +
            "Comprueba que Tailscale está activo en el teléfono y en el PC, y que el " +
            "gateway está en marcha."

    null -> when (val connection = state.connection) {
        is ConnectionState.Failed ->
            if (connection.recoverable) {
                connection.message
            } else {
                "${connection.message} Necesitas volver a emparejar este teléfono."
            }

        is ConnectionState.Offline ->
            connection.reason?.takeIf { it.isNotBlank() }
                ?.let { "No se pudo conectar con el equipo: $it" }
                ?: "No se pudo conectar con el equipo."

        ConnectionState.Unpaired ->
            "Este teléfono no está emparejado con ningún equipo."

        ConnectionState.Connecting ->
            "Conectando con el equipo…"

        is ConnectionState.Live ->
            "La conexión se ha restablecido."
    }
}

/**
 * Whether re-pairing is the fix the screen should lead with.
 *
 * A 401 (the gateway no longer trusts this device) and the unpaired state are
 * the two cases a retry cannot fix; everything else is worth a retry first.
 */
internal fun recoveryNeedsRepair(state: RecoveryUiState): Boolean =
    state.connection is ConnectionState.Unpaired ||
        (state.connection as? ConnectionState.Failed)?.recoverable == false
