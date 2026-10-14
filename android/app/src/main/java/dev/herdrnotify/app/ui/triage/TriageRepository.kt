package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.ConnectionState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield

/**
 * The seam the screen reads from.
 *
 * An interface rather than a concrete client so the ViewModel can be tested
 * against a scripted gateway, and so the network implementation can be swapped
 * without the UI moving.
 *
 * The default instance reports Unpaired, which is the honest first-run state:
 * the app has no idea where a host is until a person pairs it, and pretending
 * otherwise would show an empty list that looks like "no agents running" rather
 * than "not configured".
 */
interface TriageRepository {
    val connection: Flow<ConnectionState>

    /**
     * What is true right now, before anything has been collected.
     *
     * Lets a screen start from real state instead of a hardcoded "connecting",
     * which would otherwise contradict a repository that already knows the
     * phone is unpaired or has a cached list to show.
     */
    fun currentState(): ConnectionState = ConnectionState.Connecting

    suspend fun markSeen(paneId: String)

    /**
     * Send a message to an agent. The outcome is returned, not swallowed: the
     * failure says why (not permitted, waiting for an approval), and the screen
     * has to say it.
     */
    suspend fun respond(paneId: String, text: String): Result<Unit>

    /** The agent's last [lines] lines of output. */
    suspend fun read(paneId: String, lines: Int): Result<String>

    suspend fun sendKey(paneId: String, key: String, confirmed: Boolean)

    /**
     * Send an image to an agent, to accompany the message the person is about to
     * send.
     *
     * `docs/contracts/api.md` has no image endpoint yet, so the default fails
     * with a clear, non-fatal reason and the screen reports it as a pending
     * capability. The seam exists now so the day the gateway grows the route,
     * only this override changes.
     */
    suspend fun sendImage(paneId: String, bytes: ByteArray, mime: String): Result<Unit> =
        Result.failure(UnsupportedOperationException("imágenes no soportadas por el gateway"))

    /**
     * Send several keys as one answer, e.g. an arrow to move a permission
     * highlight and `enter` to choose it.
     *
     * The outcome is returned, unlike [sendKey]: the person just tapped an answer
     * to a dialog and is waiting to see whether it took, so a refusal has to
     * reach the screen. The default loops [sendKey] so an implementer that does
     * not care about the batch still compiles; the real client overrides it to
     * send the whole list in one signed request.
     */
    suspend fun sendKeys(paneId: String, keys: List<String>, confirmed: Boolean): Result<Unit> {
        keys.forEach { sendKey(paneId, it, confirmed) }
        return Result.success(Unit)
    }

    suspend fun refresh()

    /**
     * Start a fresh conversation (one workspace, one opencode agent) and return
     * the pane it was created in.
     *
     * The outcome is returned rather than swallowed: if it fails the person is
     * standing in front of a "create" button and has to be told why nothing
     * happened. A success with a null pane means the host created the
     * conversation but did not name the pane, which the screen reports too.
     */
    suspend fun newChat(name: String): Result<String?> = Result.success(null)
}

/**
 * Placeholder implementation for the first build.
 *
 * It exists so the UI, the theme and the signing path can be proven compiling and
 * installable before the network layer is wired in. The next change replaces this
 * class body with the signed client and the event stream; the interface above is
 * what that change must fit through.
 */
class UnpairedTriageRepository : TriageRepository {

    private val _connection = MutableStateFlow<ConnectionState>(ConnectionState.Unpaired)
    override val connection: Flow<ConnectionState> = _connection.asStateFlow()

    override fun currentState(): ConnectionState = ConnectionState.Unpaired

    override suspend fun markSeen(paneId: String) = Unit

    override suspend fun respond(paneId: String, text: String): Result<Unit> =
        Result.failure(IllegalStateException("sin emparejar"))

    override suspend fun read(paneId: String, lines: Int): Result<String> =
        Result.failure(IllegalStateException("sin emparejar"))

    override suspend fun sendKey(paneId: String, key: String, confirmed: Boolean) = Unit

    override suspend fun refresh() = Unit

    override suspend fun newChat(name: String): Result<String?> =
        Result.failure(IllegalStateException("sin emparejar"))
}

/**
 * A scripted repository, for tests and previews.
 *
 * [emit] suspends so a test can let the ViewModel's collector run before
 * asserting. A `StateFlow` assignment returns immediately, and on a
 * single-threaded test dispatcher the collector would not have observed the new
 * value yet — so a test that emitted and asserted immediately would be
 * asserting on the state *before* the one it just set, and would pass or fail
 * for reasons unrelated to the behaviour under test.
 */
class FakeTriageRepository(
    private val initial: ConnectionState = ConnectionState.Unpaired,
) : TriageRepository {

    private val _connection = MutableStateFlow(initial)
    override val connection: Flow<ConnectionState> = _connection.asStateFlow()

    override fun currentState(): ConnectionState = initial

    val seen = mutableListOf<String>()
    val replies = mutableListOf<Pair<String, String>>()
    val keys = mutableListOf<Triple<String, String, Boolean>>()
    val keyBatches = mutableListOf<Triple<String, List<String>, Boolean>>()
    val reads = mutableListOf<Pair<String, Int>>()
    val newChats = mutableListOf<String>()
    val images = mutableListOf<Triple<String, Int, String>>()

    /** What the next calls return. Tests set these to script a failure. */
    var respondResult: Result<Unit> = Result.success(Unit)
    var readResult: Result<String> = Result.success("salida del agente")
    var sendKeysResult: Result<Unit> = Result.success(Unit)
    var newChatResult: Result<String?> = Result.success(null)
    var sendImageResult: Result<Unit> = Result.success(Unit)

    /** How often the list was re-read from `/v1/state`. */
    var refreshes = 0

    override suspend fun markSeen(paneId: String) {
        seen += paneId
    }

    override suspend fun respond(paneId: String, text: String): Result<Unit> {
        replies += paneId to text
        return respondResult
    }

    override suspend fun read(paneId: String, lines: Int): Result<String> {
        reads += paneId to lines
        return readResult
    }

    override suspend fun sendKey(paneId: String, key: String, confirmed: Boolean) {
        keys += Triple(paneId, key, confirmed)
    }

    override suspend fun sendImage(paneId: String, bytes: ByteArray, mime: String): Result<Unit> {
        images += Triple(paneId, bytes.size, mime)
        return sendImageResult
    }

    override suspend fun sendKeys(
        paneId: String,
        keys: List<String>,
        confirmed: Boolean,
    ): Result<Unit> {
        keyBatches += Triple(paneId, keys, confirmed)
        return sendKeysResult
    }

    override suspend fun refresh() {
        refreshes++
    }

    override suspend fun newChat(name: String): Result<String?> {
        newChats += name
        return newChatResult
    }

    /** Set the state and yield, so a downstream collector observes it. */
    suspend fun emit(state: ConnectionState) {
        _connection.value = state
        yield()
    }
}

/** Convenience for a scope-bound repository, so callers need not thread one. */
internal fun TriageRepository.launchIn(scope: CoroutineScope, block: suspend () -> Unit) {
    scope.launch { block() }
}
