package dev.herdrnotify.app.net

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.SessionState
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The gateway's wire format, as it actually is.
 *
 * Written against `api/app.py` and `notify/attention.py` rather than from the
 * Kotlin domain model, because the two are not the same shape and pretending
 * otherwise hides the difference that matters: the gateway ranks, the app
 * renders. `attention` is computed on the host from herdr's own status
 * vocabulary, and it arrives already decided. This file decodes it; it does not
 * re-derive it.
 *
 * Every field that can be absent is nullable with a default. A newer gateway
 * adding a field must not stop an older phone from listing its agents, and the
 * failure mode of getting this wrong is a blank screen rather than an error.
 */
@Serializable
data class WireState(
    val revision: Long = 0,
    @SerialName("herdr_version") val herdrVersion: String? = null,
    val counts: Map<String, Int> = emptyMap(),
    val agents: List<WireAgent> = emptyList(),
) {
    fun toDomain(): SessionState = SessionState(
        revision = revision,
        herdrVersion = herdrVersion,
        // An entry without a pane id is dropped: it cannot be addressed by any
        // action, so rendering it would produce a row that fails when tapped.
        agents = agents.mapNotNull { it.toDomain() },
        counts = counts.mapNotNull { (key, value) ->
            AgentStatus.fromWire(key)?.let { it to value }
        }.toMap(),
    )
}

@Serializable
data class WireAgent(
    @SerialName("pane_id") val paneId: String = "",
    @SerialName("workspace_id") val workspaceId: String = "",
    val project: String? = null,
    val agent: String? = null,
    val status: String? = null,
    val attention: Int = 0,
    val title: String? = null,
    val cwd: String? = null,
    val focused: Boolean = false,
    @SerialName("can_resume") val canResume: Boolean = false,
) {
    /**
     * `pane_id` is the key everything else is looked up by, and the gateway
     * signs URLs containing it. An empty one would produce a request to
     * `/v1/agents//seen`, so an entry without one is dropped rather than
     * rendered as a row that cannot be acted on.
     */
    fun toDomain(): AgentSummary? {
        if (paneId.isEmpty()) return null
        return AgentSummary(
            paneId = paneId,
            workspaceId = workspaceId.ifEmpty { paneId.substringBefore(':') },
            // The gateway already falls back to the workspace id, then to "?" —
            // mirroring that keeps the two renders identical.
            project = project?.takeIf { it.isNotEmpty() }
                ?: workspaceId.takeIf { it.isNotEmpty() }
                ?: "?",
            agent = agent?.takeIf { it.isNotEmpty() } ?: "agent",
            status = AgentStatus.fromWire(status),
            attention = attention,
            title = title?.takeIf { it.isNotEmpty() },
            cwd = cwd?.takeIf { it.isNotEmpty() },
            focused = focused,
            canResume = canResume,
        )
    }
}

/** The `state` payload nested inside the first SSE frame. */
@Serializable
data class WireSseState(
    val event: String = "state",
    val revision: Long = 0,
    val state: WireState = WireState(),
)

@Serializable
data class WireActionResult(
    val ok: Boolean = false,
)

@Serializable
data class WireReadResult(
    val text: String = "",
    @SerialName("pane_id") val paneId: String = "",
)

/**
 * The result of `POST /v1/workspaces`: the pane a fresh opencode conversation
 * was started in. The app opens that pane's chat immediately, so the person
 * lands in the conversation they just created instead of hunting for the new
 * row in the list.
 */
@Serializable
data class WireNewChatResult(
    val ok: Boolean = false,
    @SerialName("workspace_id") val workspaceId: String? = null,
    @SerialName("pane_id") val paneId: String? = null,
)

/**
 * Lenient decoding, deliberately.
 *
 * The gateway speaks `ensure_ascii=False` JSON and the app is the only thing
 * that has to read it, so the parser is configured to ignore what it does not
 * recognise rather than to fail on it. Being strict here would mean a
 * routine host-side version bump could brick the triage list on a phone that is
 * otherwise fine.
 */
object Wire {
    val json: Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        coerceInputValues = true
        explicitNulls = false
    }

    /**
     * Decode a `/v1/state` body, returning null rather than throwing.
     *
     * A malformed body is a reason to fall back to the last good state and show
     * it as stale, not a reason to empty the screen. A person looking at a list
     * of nine agents is better served by slightly old data than by nothing.
     */
    fun state(body: String): SessionState? = runCatching {
        json.decodeFromString<WireState>(body).toDomain()
    }.getOrNull()

    /** Decode the first frame of an SSE stream. */
    fun sseState(data: String): SessionState? = runCatching {
        json.decodeFromString<WireSseState>(data).state.toDomain()
    }.getOrNull()

    fun readText(data: String): String? = runCatching {
        json.decodeFromString<WireReadResult>(data).text
    }.getOrNull()

    /**
     * The pane id a new conversation was created in, or null.
     *
     * Null covers both a malformed body and a gateway that answered `ok` without
     * a pane — the screen says the conversation could not be opened rather than
     * silently doing nothing.
     */
    fun newChatPaneId(data: String): String? = runCatching {
        json.decodeFromString<WireNewChatResult>(data)
            .takeIf { it.ok }
            ?.paneId
            ?.takeIf { it.isNotBlank() }
    }.getOrNull()

    fun ok(data: String): Boolean = runCatching {
        json.decodeFromString<WireActionResult>(data).ok
    }.getOrDefault(false)

    /**
     * Pull the revision out of an arbitrary SSE frame.
     *
     * Used to discard an out-of-order frame: a reconnect replays the queue, so
     * an older revision can legitimately arrive after a newer one, and applying
     * it would visibly undo a state the user is reading.
     */
    fun revision(data: String): Long? = runCatching {
        val element = json.parseToJsonElement(data) as? JsonObject ?: return null
        (element["revision"] as? JsonPrimitive)?.jsonPrimitive?.longOrNullSafe()
    }.getOrNull()

    private fun kotlinx.serialization.json.JsonPrimitive.longOrNullSafe(): Long? =
        content.toLongOrNull()
}
