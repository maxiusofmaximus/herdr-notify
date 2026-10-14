package dev.herdrnotify.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing

/** One thing a person can do about a notice. */
data class NoticeAction(val label: String, val onClick: () -> Unit)

enum class NoticeKind { ERROR, WARNING }

/**
 * A problem with something to do about it.
 *
 * A bare red line tells the person that something failed; it does not tell them
 * what to do next, which is the only question they have. So an error is drawn as
 * a card with a title, the reason, and the buttons that resolve it — Retry,
 * see the raw output, re-pair. A card with no buttons still beats a red line,
 * because it at least has a shape and a severity.
 */
@Composable
fun NoticeCard(
    message: String,
    modifier: Modifier = Modifier,
    title: String? = null,
    kind: NoticeKind = NoticeKind.ERROR,
    actions: List<NoticeAction> = emptyList(),
) {
    val accent = when (kind) {
        NoticeKind.ERROR -> MaterialTheme.colorScheme.error
        NoticeKind.WARNING -> LocalStatusColors.current.working
    }
    // The triangle is reserved for errors; a neutral, informational notice — the
    // "the agent is working, the output will load" case — gets an info glyph so
    // the shape does not claim something is wrong.
    val icon = when (kind) {
        NoticeKind.ERROR -> Icons.Filled.Warning
        NoticeKind.WARNING -> Icons.Filled.Info
    }
    Surface(
        color = accent.copy(alpha = 0.10f),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, accent.copy(alpha = 0.45f)),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            Row(verticalAlignment = Alignment.Top) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = accent,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(Spacing.sm))
                Column {
                    if (title != null) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.labelLarge,
                            color = accent,
                        )
                    }
                    Text(
                        text = message,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
            if (actions.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    actions.forEach { action ->
                        TextButton(onClick = action.onClick) { Text(action.label) }
                    }
                }
            }
        }
    }
}
