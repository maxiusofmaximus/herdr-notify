package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.DebugLog
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.LiveStream
import dev.herdrnotify.app.net.RequestSigner
import dev.herdrnotify.app.net.Wire
import dev.herdrnotify.app.security.Signer
import dev.herdrnotify.app.ui.triage.TriageRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The real repository: a signed client, a live stream, and the actions the
 * triage screen can fire.
 *
 * Deliberately thin. It owns no policy — the gateway ranks, this renders — and
 * it owns the retry loop, because a phone's network is unreliable in ways a
 * server's is not.
 *
 * The stream is the source of truth and every action is fire-and-forget. An
 * action is a nudge to herdr; the change that results arrives on the stream. If
 * the app also applied its own optimistic update, the phone and the terminal
 * could disagree about an agent's state, and the user would be looking at a
 * lie while waiting for the truth to come back.
 */
class GatewayTriageRepository(
    private val keys: Signer,
    private val pairing: () -> Pairing,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
    private val pendingToken: () -> String? = { null },
    private val onTokenRegistered: () -> Unit = {},
) : TriageRepository {

    private val _connection = MutableStateFlow<ConnectionState>(ConnectionState.Unpaired)
    override val connection: Flow<ConnectionState> = _connection.asStateFlow()

    override fun currentState(): ConnectionState = _connection.value

    private var stream: LiveStream? = null
    private var client: GatewayClient? = null

    /**
     * Panes the operator has opened in this app run.
     *
     * herdr 0.9.1 clears an agent's "done" badge only through ``agent.focus``,
     * which also moves the terminal's focus to that pane. Opening a chat on the
     * phone must not move focus on the PC, so "seen" lives here: a ``done``
     * agent the operator has opened renders as ``idle`` in the app, and the host
     * is never told to focus anything. Concurrent because the stream collector
     * and the UI both touch it.
     */
    private val seenPanes: MutableSet<String> =
        java.util.concurrent.ConcurrentHashMap.newKeySet()

    /**
     * The collector that mirrors [LiveStream.state] into this repository.
     *
     * Kept as its own job so [disconnect] can cancel the connection without
     * cancelling [scope]. Cancelling the scope would kill the repository, not
     * the connection: a later [connect] would launch into a dead scope, the
     * stream would never open, and the only symptom would be a phone that stays
     * on "connecting" forever after the first disconnect.
     */
    private var connectionJob: Job? = null

    /**
     * Open the stream, or do nothing if it is already open for this pairing.
     *
     * Called on every resume and after every save. Idempotency matters because
     * an activity recreation is not a reason to drop a working connection and
     * make the user watch the list reload.
     */
    fun connect() {
        val current = pairing()
        if (!current.isComplete || !keys.hasKey()) {
            _connection.value = ConnectionState.Unpaired
            return
        }
        if (stream != null) return

        val gateway = GatewayClient(
            baseUrl = current.baseUrl,
            deviceId = current.deviceId,
            signer = RequestSigner(keys),
        )
        client = gateway
        // A paired, reachable connection is the moment a parked FCM token gets
        // reported — including one parked by a process that has since died.
        flushPendingToken()
        _connection.value = ConnectionState.Connecting

        stream = LiveStream(gateway, scope).also { live ->
            connectionJob = scope.launch {
                live.state.collect { state ->
                    // The stream is the authority on connection state; this
                    // repository just mirrors it so the ViewModel has one source.
                    _connection.value = applySeen(state)
                }
            }
            live.start()
            // Every connect asks for a fresh state too, so a resume shows the
            // host's current view at once rather than waiting on the first frame.
            live.refreshNow()
        }
    }

    /**
     * Register a parked FCM token with the gateway, if there is somewhere to
     * send it.
     *
     * The contract's lifecycle (push.md): the token is parked persistently when
     * Firebase issues or rotates it, and the next paired, reachable connection
     * reports it. [connect] calls this every time it builds a client, and the
     * push service calls it the moment a token rotates mid-connection, so a
     * parked token reaches the gateway on the first connection that can carry
     * it. A failed attempt keeps the parked copy and retries on the next
     * connect; a failed registration is not a connection event, so the
     * connection state never changes here.
     */
    fun flushPendingToken() {
        val token = pendingToken() ?: return
        val gateway = client ?: return
        scope.launch {
            try {
                withContext(Dispatchers.IO) { gateway.fcmToken(token) }
                onTokenRegistered()
            } catch (e: GatewayClient.GatewayError.Unauthorised) {
                // Not in the trust store: the token stays parked. The next
                // pairing's connect reports it.
            } catch (e: GatewayClient.GatewayError) {
                // Refused, rejected or unreachable: the token stays parked and
                // the next connect retries. A 403 on self-service should not
                // happen (the device's own record needs no grant), but keeping
                // the token parked loses nothing either way.
            } catch (e: Exception) {
                // The token stays parked; the next connect retries.
            }
        }
    }

    /** The host this phone talks to, for an error screen to name. */
    fun host(): String = pairing().baseUrl

    /** Drop the connection and open it again: the retry on an error screen. */
    fun retry() {
        disconnect()
        connect()
    }

    fun disconnect() {
        // Cancel the connection, never the scope. See [connectionJob].
        connectionJob?.cancel()
        connectionJob = null
        stream?.stop()
        stream = null
        client = null
    }

    override suspend fun markSeen(paneId: String) {
        // Local only. herdr has no seen-without-focus call, and focusing would
        // move the operator's terminal — exactly what opening a chat must not do.
        seenPanes += paneId
        _connection.value = applySeen(_connection.value)
    }

    /**
     * Apply the local "seen" set to a connection's state.
     *
     * A pane that has moved off ``done`` (working again, or gone) is forgotten,
     * so its next completion raises the badge afresh rather than staying
     * suppressed forever.
     */
    private fun applySeen(connection: ConnectionState): ConnectionState = when (connection) {
        is ConnectionState.Live -> connection.copy(state = applySeen(connection.state))
        is ConnectionState.Offline -> connection.copy(lastKnown = applySeen(connection.lastKnown))
        else -> connection
    }

    private fun applySeen(state: SessionState): SessionState {
        if (seenPanes.isEmpty()) return state
        val byPane = state.agents.associateBy { it.paneId }
        // Re-arm any pane that is no longer done: a later done is a new
        // completion and deserves the badge again.
        seenPanes.removeAll { pane ->
            val agent = byPane[pane]
            agent != null && agent.status != AgentStatus.DONE
        }
        if (seenPanes.isEmpty()) return state
        return state.copy(
            agents = state.agents.map { agent ->
                if (agent.status == AgentStatus.DONE && agent.paneId in seenPanes) {
                    agent.copy(status = AgentStatus.IDLE, attention = 0)
                } else {
                    agent
                }
            },
        )
    }

    /**
     * Unlike [markSeen], the outcome is returned. Sending a message is something
     * the person is waiting on, so "it did not go" has to reach the screen as a
     * typed error (403 is not permitted, 409 is waiting for an approval), not be
     * swallowed as an answer.
     */
    override suspend fun respond(paneId: String, text: String): Result<Unit> =
        request { it.respond(paneId, text) }.map { }

    /** The agent's last lines of output, as the gateway's `text` field. */
    override suspend fun read(paneId: String, lines: Int): Result<String> =
        request { it.read(paneId, lines) }.mapCatching { body ->
            Wire.readText(body) ?: throw java.io.IOException("respuesta de lectura no válida")
        }

    override suspend fun sendKey(paneId: String, key: String, confirmed: Boolean) {
        call { it.sendKeys(paneId, listOf(key), confirmed) }
    }

    /**
     * An answer to a permission dialog: the whole sequence in one signed request.
     *
     * The gateway takes up to eight keys in one `agent.send_keys` call, so sending
     * `right, enter` together keeps the highlight and the choice atomic from the
     * dialog's point of view — two requests could land either side of a redraw.
     */
    override suspend fun sendKeys(
        paneId: String,
        keys: List<String>,
        confirmed: Boolean,
    ): Result<Unit> = request { it.sendKeys(paneId, keys, confirmed) }.map { }

    /**
     * Re-read `/v1/state` and publish what it says.
     *
     * This is what removes an agent the host no longer has: a chat answered
     * with `404 agent_not_found` asks for one refresh, and the body that comes
     * back no longer carries the closed pane, so the row disappears. A body
     * older than what is on screen is dropped, so a slow answer cannot roll
     * the list back to a state it has already left.
     */
    override suspend fun refresh() {
        request { it.state() }.onSuccess { body ->
            val fresh = Wire.state(body) ?: return
            val shown = when (val current = _connection.value) {
                is ConnectionState.Live -> current.state.revision
                is ConnectionState.Offline -> current.lastKnown.revision
                else -> 0L
            }
            if (fresh.revision < shown) return
            _connection.value = applySeen(
                ConnectionState.Live(fresh, System.currentTimeMillis()),
            )
        }
    }

    override suspend fun newChat(name: String): Result<String?> =
        request { it.newChat(name) }.mapCatching { Wire.newChatPaneId(it) }

    /**
     * Run one action and discard its outcome, for the actions that are answers
     * rather than results: marking an agent seen, sending a key, a refresh.
     */
    private suspend fun call(block: (GatewayClient) -> Unit) {
        request(block)
    }

    /**
     * Run one signed request, mapping its outcome onto connection state, and
     * return the outcome to the caller.
     *
     * A 401 here is the authoritative signal that the device is no longer in the
     * trust store — the host may have revoked it, or re-paired under a new id.
     * The stream cannot act on that alone because it may never get the chance to
     * emit again, so every action is also a chance to notice.
     *
     * A 403 is a different answer: the device is trusted but not allowed to do
     * this. The pairing is intact and the stream is intact, so the connection
     * state does not change — the fix is a host-side grant, never a re-pair and
     * never a retry.
     *
     * Cancellation is rethrown, not recorded. A poll cancelled mid-request is
     * the screen closing, not the host going away, and must not flip the
     * connection to Offline.
     */
    private suspend fun <T> request(block: (GatewayClient) -> T): Result<T> {
        val gateway = client ?: run {
            DebugLog.d("request: no client, skipping action")
            return Result.failure(IllegalStateException("sin conexión con el gateway"))
        }
        return try {
            Result.success(withContext(Dispatchers.IO) { block(gateway) })
        } catch (e: CancellationException) {
            throw e
        } catch (e: GatewayClient.GatewayError.Unauthorised) {
            _connection.value = ConnectionState.Failed(
                "Este teléfono ya no está emparejado. Vuelve a registrarlo en el host.",
                recoverable = false,
            )
            Result.failure(e)
        } catch (e: GatewayClient.GatewayError.NotPermitted) {
            // Terminal for this action, but not a re-pair situation and not a
            // network fault: the pairing and the stream stay exactly as they are.
            DebugLog.d("request: NotPermitted (403) — action refused, connection unchanged")
            Result.failure(e)
        } catch (e: GatewayClient.GatewayError) {
            // A rejected action is an answer, not a fault. herdr declining a
            // prompt is a legitimate outcome, and the stream will say so.
            Result.failure(e)
        } catch (e: Exception) {
            val current = _connection.value
            _connection.value = ConnectionState.Offline(
                lastKnown = lastKnown(),
                reason = e.message,
                updatedAt = (current as? ConnectionState.Live)?.updatedAt
                    ?: (current as? ConnectionState.Offline)?.updatedAt
                    ?: 0L,
            )
            Result.failure(e)
        }
    }

    /** Read the last known state without opening a stream. Used by previews. */
    fun lastKnown(): dev.herdrnotify.app.domain.SessionState =
        (_connection.value as? ConnectionState.Live)?.state
            ?: (_connection.value as? ConnectionState.Offline)?.lastKnown
            ?: dev.herdrnotify.app.domain.SessionState.EMPTY

    /** Parse a state body, exposed so tests and the debug screen agree. */
    fun parseState(body: String) = Wire.state(body)
}
