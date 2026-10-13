package dev.herdrnotify.app.ui.triage

import androidx.lifecycle.ViewModel
import dev.herdrnotify.app.DebugLog
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.net.GatewayClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Drives the triage screen and the agent detail behind it.
 *
 * Deliberately thin. The gateway owns the ranking, so this owns no policy: it
 * holds the connection state and forwards intents. A second place deciding what
 * "needs you" means is a second place for the phone and the terminal to disagree
 * about whether an agent is waiting.
 */
class TriageViewModel(
    private val repository: TriageRepository = UnpairedTriageRepository(),
    private val scope: CoroutineScope = MainScope(),
) : ViewModel() {

    /**
     * Seeded from the repository rather than hardcoded to `Connecting`.
     *
     * A hardcoded initial value lies when the repository already knows better:
     * an unpaired phone or a restored cached state would show "connecting" until
     * the first emission arrives, and a screen that contradicts known state is
     * worse than a slow one.
     */
    private val _state = MutableStateFlow<ConnectionState>(repository.currentState())
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private val _detail = MutableStateFlow<AgentDetail?>(null)

    /** The open agent's detail, or null while the list is showing. */
    val detail: StateFlow<AgentDetail?> = _detail.asStateFlow()

    /** The output poll for the open agent. Cancelled when the detail closes. */
    private var pollJob: Job? = null

    init {
        observe()
    }

    private fun observe() {
        scope.launch {
            repository.connection.collect { next ->
                // Never regress from a live view to a loading one: a reconnect
                // must not blank a list the user is reading.
                val current = _state.value
                _state.value = if (next is ConnectionState.Connecting &&
                    current is ConnectionState.Live
                ) {
                    current
                } else {
                    next
                }
            }
        }
    }

    /**
     * Open an agent's detail: mark it seen, and start reading its output.
     *
     * Opening is the only thing that marks an agent seen, and that stays true
     * now that the detail exists: the person has looked at it.
     */
    fun onOpenAgent(paneId: String) {
        DebugLog.d("onOpenAgent: paneId=$paneId")
        scope.launch { repository.markSeen(paneId) }
        _detail.value = AgentDetail(paneId = paneId)
        startPolling(paneId)
    }

    /** Back to the list. Stops the output poll, so nothing reads in the background. */
    fun onCloseAgent() {
        pollJob?.cancel()
        pollJob = null
        _detail.value = null
    }

    /** Read the output now, outside the poll's schedule. */
    fun onRefreshOutput() {
        val paneId = _detail.value?.paneId ?: return
        startPolling(paneId)
    }

    fun onDraftChange(text: String) {
        _detail.update { it?.copy(draft = text, notice = null) }
    }

    /**
     * Send the draft. An agent that is not waiting for an answer gets a question
     * first: a message sent to a working agent lands in the middle of its work,
     * which is rarely what the person meant, so the confirmation is the default
     * and the blocked agent is the exception.
     */
    fun onSend() {
        val current = _detail.value ?: return
        val text = current.draft.trim()
        if (current.sending) return
        if (text.isEmpty()) return
        if (text.length > MAX_MESSAGE_CHARS) {
            _detail.update { it?.copy(notice = "El mensaje no puede pasar de $MAX_MESSAGE_CHARS caracteres.") }
            return
        }
        if (state.value.agentById(current.paneId)?.needsYou != true) {
            _detail.update { it?.copy(confirmRequired = true) }
            return
        }
        send(current.paneId, text)
    }

    /** The person said yes to the confirmation for an agent that is not waiting. */
    fun onConfirmSend() {
        val current = _detail.value ?: return
        _detail.update { it?.copy(confirmRequired = false) }
        send(current.paneId, current.draft.trim())
    }

    fun onDismissConfirm() {
        _detail.update { it?.copy(confirmRequired = false) }
    }

    /**
     * Answer a permission dialog with the keys that choose an option.
     *
     * The keys are decided by the parsed prompt
     * ([dev.herdrnotify.app.ui.PermissionPrompt]) and passed in whole, so the
     * screen never composes a keystroke and the mapping from button to terminal
     * lives in one place. A refusal (403) or a dialog that has already gone (409)
     * is shown as a notice and the poll re-reads: either the dialog is still
     * there, or the agent moved on.
     */
    fun onPermissionKeys(keys: List<String>, confirmed: Boolean) {
        val current = _detail.value ?: return
        if (current.sending) return
        val paneId = current.paneId
        _detail.update { if (it?.paneId == paneId) it.copy(sending = true, notice = null) else it }
        scope.launch {
            repository.sendKeys(paneId, keys, confirmed)
                .onSuccess {
                    _detail.update { if (it?.paneId == paneId) it.copy(sending = false) else it }
                    startPolling(paneId)
                }
                .onFailure { error ->
                    _detail.update {
                        if (it?.paneId == paneId) {
                            it.copy(sending = false, notice = keyFailure(error))
                        } else {
                            it
                        }
                    }
                }
        }
    }

    private fun send(paneId: String, text: String) {
        _detail.update { if (it?.paneId == paneId) it.copy(sending = true, notice = null) else it }
        scope.launch {
            repository.respond(paneId, text)
                .onSuccess {
                    _detail.update {
                        if (it?.paneId == paneId) it.copy(draft = "", sending = false) else it
                    }
                    // Read straight away, so the reply to what was just sent
                    // appears without waiting for the next poll tick.
                    startPolling(paneId)
                }
                .onFailure { error ->
                    _detail.update {
                        if (it?.paneId == paneId) {
                            it.copy(sending = false, notice = sendFailure(error))
                        } else {
                            it
                        }
                    }
                }
        }
    }

    /**
     * Read the output now and then every [POLL_MILLIS] until closed.
     *
     * Restarting cancels the previous loop first, so a send that forces a read
     * does not leave two loops running side by side for the same agent.
     */
    private fun startPolling(paneId: String) {
        pollJob?.cancel()
        pollJob = scope.launch {
            while (isActive) {
                readOutput(paneId)
                delay(POLL_MILLIS)
            }
        }
    }

    private suspend fun readOutput(paneId: String) {
        repository.read(paneId, OUTPUT_LINES)
            .onSuccess { text ->
                _detail.update {
                    if (it?.paneId == paneId) it.copy(output = text, outputError = null) else it
                }
            }
            .onFailure { error ->
                _detail.update {
                    if (it?.paneId == paneId) it.copy(outputError = readFailure(error)) else it
                }
            }
    }

    fun onNewChat(name: String) {
        scope.launch { repository.newChat(name) }
    }

    fun onDismissError() {
        // Synchronous, and deliberately so. Dismissing an error is a response to
        // something the user just tapped; deferring it to a coroutine means the
        // button appears to do nothing on a frame the collector has not been
        // scheduled for yet.
        _state.update { if (it is ConnectionState.Failed) ConnectionState.Connecting else it }
    }

    companion object {
        /**
         * How often the open agent's output is re-read.
         *
         * Every agent.read the phone makes is repeated by herdr on the PC, and
         * each one moves the Claude session's viewport: at 3 s the terminal was
         * dragged out from under the person every few seconds while they were
         * reading. 15 s leaves the immediate read on open and after a send
         * untouched — only the background poll, which nobody is waiting on,
         * slows down.
         */
        const val POLL_MILLIS = 15_000L

        /** The tail of the pane that the detail shows. */
        const val OUTPUT_LINES = 60

        /** The gateway's limit on a message, from the respond route. */
        const val MAX_MESSAGE_CHARS = 4_000
    }
}

/**
 * The open agent's detail screen.
 *
 * [output] is null until the first read lands, so the screen can tell "still
 * loading" from "loaded and empty". [confirmRequired] is the question asked
 * before sending to an agent that is not waiting for an answer.
 */
data class AgentDetail(
    val paneId: String,
    val output: String? = null,
    val outputError: String? = null,
    val draft: String = "",
    val sending: Boolean = false,
    val notice: String? = null,
    val confirmRequired: Boolean = false,
)

/** What a failed send means to the person, from the typed error. */
internal fun sendFailure(error: Throwable): String = when {
    error is GatewayClient.GatewayError.NotPermitted ->
        "Este teléfono no tiene permiso para enviar mensajes"

    error is GatewayClient.GatewayError.Rejected && error.code == 409 ->
        "El agente está esperando una aprobación; usa los botones"

    else -> "No se pudo enviar el mensaje. Inténtalo de nuevo."
}

/** What a failed read means to the person. */
internal fun readFailure(error: Throwable): String = when {
    error is GatewayClient.GatewayError.NotPermitted ->
        "Este teléfono no tiene permiso para leer este agente"

    // herdr refuses a full history read while the agent's pane is on its
    // alternate screen (working). The gateway falls back to the visible screen,
    // but if that also lands as a 409 it is a transient state, not a fault: the
    // poll retries, and the message says so instead of the generic one.
    error is GatewayClient.GatewayError.Rejected && error.code == 409 ->
        "El agente está trabajando; se leerá la salida en un momento"

    else -> "No se pudo leer la salida del agente"
}

/** What a failed answer to a permission dialog means to the person. */
internal fun keyFailure(error: Throwable): String = when {
    error is GatewayClient.GatewayError.NotPermitted ->
        "Este teléfono no tiene permiso para responder al agente"

    // The dialog is gone (answered on the PC, or the agent moved on). The next
    // poll shows the truth; there is nothing for the person to fix.
    error is GatewayClient.GatewayError.Rejected && error.code == 409 ->
        "El agente ya no espera esa aprobación"

    else -> "No se pudo enviar la respuesta. Inténtalo de nuevo."
}

/** The agent with this pane id in whatever list the connection last showed. */
internal fun ConnectionState.agentById(paneId: String): AgentSummary? {
    val agents = when (this) {
        is ConnectionState.Live -> state.agents
        is ConnectionState.Offline -> lastKnown.agents
        else -> emptyList()
    }
    return agents.firstOrNull { it.paneId == paneId }
}

/**
 * Subtitle under the title: what the screen is currently saying about itself.
 *
 * [now] is a parameter so the "how old is this" part is testable. An offline
 * screen says how old its list is, because a stale list shown without its age
 * looks like a live one.
 */
internal fun ConnectionState.subtitle(now: Long = System.currentTimeMillis()): String? = when (this) {
    is ConnectionState.Live -> {
        val blocked = state.needsYou.size
        when {
            blocked > 0 -> "$blocked te esperan"
            state.isEmpty -> "Nada en marcha"
            else -> "${state.agents.size} agentes"
        }
    }

    is ConnectionState.Offline -> if (updatedAt > 0L) {
        "Desconectado · última actualización ${formatSince(now - updatedAt)}"
    } else {
        "Desconectado"
    }

    else -> null
}
