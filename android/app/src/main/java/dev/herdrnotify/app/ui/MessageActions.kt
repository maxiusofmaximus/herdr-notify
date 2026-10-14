package dev.herdrnotify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.theme.TextMuted

/** Who wrote a message, which decides part of its action row. */
enum class MessageRole { USER, AGENT }

/** The actions a message offers. */
enum class MessageAction { COPY, SHARE, RETRY, VIEW_RAW }

/**
 * Which actions a message shows.
 *
 * Copy and share are always useful. Retry only when there is a prompt to send
 * again — an agent turn retries the prompt that produced it, and a person's own
 * turn retries itself. "See the raw output" is offered on the agent's turn,
 * where the terminal tail is a meaningful alternative, and never on the
 * person's own words.
 */
internal fun actionsFor(
    role: MessageRole,
    hasRetryText: Boolean,
    canViewRaw: Boolean,
): List<MessageAction> = buildList {
    add(MessageAction.COPY)
    add(MessageAction.SHARE)
    if (hasRetryText) add(MessageAction.RETRY)
    if (role == MessageRole.AGENT && canViewRaw) add(MessageAction.VIEW_RAW)
}

/**
 * The row of small actions under a message: copy, share, retry, raw.
 *
 * Kept to icons on a quiet row so it is available without competing with the
 * message itself — the reference apps hide nothing behind a long-press, and a
 * person who wants to get a line out of a phone should not have to discover a
 * gesture.
 */
@Composable
fun MessageActions(
    role: MessageRole,
    text: String,
    retryText: String?,
    canViewRaw: Boolean,
    onRetry: (String) -> Unit,
    onViewRaw: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val actions = actionsFor(role, hasRetryText = retryText != null, canViewRaw = canViewRaw)
    Row(
        modifier = modifier.padding(horizontal = Spacing.xs),
        horizontalArrangement = Arrangement.spacedBy(Spacing.xxs),
    ) {
        actions.forEach { action ->
            ActionIcon(action) {
                when (action) {
                    MessageAction.COPY -> context.copyToClipboard("Mensaje", text)
                    MessageAction.SHARE -> context.shareText("Mensaje", text)
                    MessageAction.RETRY -> retryText?.let(onRetry)
                    MessageAction.VIEW_RAW -> onViewRaw()
                }
            }
        }
    }
}

@Composable
private fun ActionIcon(action: MessageAction, onClick: () -> Unit) {
    val (icon, label) = when (action) {
        MessageAction.COPY -> Icons.Filled.ContentCopy to "Copiar mensaje"
        MessageAction.SHARE -> Icons.Filled.Share to "Compartir mensaje"
        MessageAction.RETRY -> Icons.Filled.Refresh to "Reintentar"
        MessageAction.VIEW_RAW -> Icons.Filled.Code to "Ver salida cruda"
    }
    IconButton(
        onClick = onClick,
        modifier = Modifier
            .size(36.dp)
            .semantics { contentDescription = label },
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = TextMuted,
            modifier = Modifier.size(18.dp),
        )
    }
}
