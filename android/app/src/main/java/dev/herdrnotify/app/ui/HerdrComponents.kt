package dev.herdrnotify.app.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.ui.theme.MonoKey
import dev.herdrnotify.app.ui.theme.Spacing
import kotlinx.coroutines.delay

/**
 * The card every screen builds from: one dark surface, one 1px border, one radius.
 *
 * Depth is declared once — a border *or* a shadow, never both — so a card can
 * never appear as an edge under a glow. The radius stays in the 12–16dp band
 * where a rectangle reads as a card rather than a pill or a slab.
 */
@Composable
fun HerdrCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surface)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(16.dp))
            .padding(Spacing.lg),
    ) {
        content()
    }
}

/** A small tracked label that names a group without competing with a heading. */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

/** A quiet caption under a field or a value. */
@Composable
fun Caption(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

/** An inline error, in the app's own language. */
@Composable
fun ErrorText(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.error,
        modifier = modifier,
    )
}

/**
 * A terminal command, quoted for copying.
 *
 * The code scrolls sideways rather than wrapping: a wrapped `add-device` line
 * reads as two commands, and the copy button is what the block exists for. The
 * button meets the 48dp target and flips to a check for a beat, which is the
 * confirmation Android's clipboard toast does not give on every version.
 */
@Composable
fun CommandBlock(
    label: String,
    command: String,
    copyLabel: String,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = Spacing.lg, end = Spacing.xs, top = Spacing.xs, bottom = Spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            CopyButton(text = command, label = copyLabel)
        }
        Text(
            text = command,
            style = MonoKey,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            softWrap = false,
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(start = Spacing.lg, end = Spacing.lg, bottom = Spacing.md)
                .semantics { contentDescription = "$label: $command" },
        )
    }
}

/** Copy-to-clipboard with a brief check mark, at a 48dp target. */
@Composable
fun CopyButton(text: String, label: String) {
    val context = LocalContext.current
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(1600)
            copied = false
        }
    }
    IconButton(
        onClick = {
            context.copyToClipboard(label, text)
            copied = true
        },
        modifier = Modifier
            .size(48.dp)
            .semantics { contentDescription = label },
    ) {
        Icon(
            imageVector = if (copied) Icons.Filled.Check else Icons.Filled.ContentCopy,
            contentDescription = null,
            tint = if (copied) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * A value that is meaningless when empty is hidden, not left as a blank box.
 *
 * An empty labelled field reads as a rendering fault even when the data is fine,
 * so a missing value says what is happening instead of showing nothing.
 */
@Composable
fun ValueRow(
    label: String,
    value: String?,
    placeholder: String,
    mono: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val present = !value.isNullOrBlank()
    Column(modifier = modifier.fillMaxWidth()) {
        SectionLabel(label)
        Spacer(Modifier.size(Spacing.xs))
        if (present) {
            Text(
                text = value!!,
                style = if (mono) MonoKey else MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        } else {
            Text(
                text = placeholder,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * The list's status marker. A hidden ring sized to its urgency, with the dot
 * inside: a blocked agent gets the larger, brighter one and nothing else does,
 * because motion and size here mean "a decision is waiting".
 */
@Composable
fun StatusDot(
    status: AgentStatus,
    accent: Color,
    pulsing: Boolean,
    modifier: Modifier = Modifier,
) {
    val dotSize = if (pulsing) 12.dp else 8.dp
    Box(
        modifier = modifier
            .size(if (pulsing) 22.dp else 18.dp)
            .clip(CircleShape)
            .background(accent.copy(alpha = if (pulsing) 0.16f else 0.10f))
            .clearAndSetSemantics { },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(dotSize)
                .clip(CircleShape)
                .background(accent),
        )
    }
}

/**
 * The shared shape of "nothing here": a reason, a hint at the cause, and the
 * action that resolves it. Loading and error reuse it so no screen invents its
 * own empty.
 */
@Composable
fun StateBlock(
    icon: @Composable () -> Unit,
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            icon()
        }
        Spacer(Modifier.size(Spacing.xs))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (action != null) {
            Spacer(Modifier.size(Spacing.sm))
            action()
        }
    }
}

/**
 * Copy with a label the user will recognise later.
 *
 * Android 13+ shows a system toast for clipboard writes, so a second in-app
 * confirmation would be noise. The label is what makes the clipboard entry
 * identifiable in the paste menu.
 */
fun Context.copyToClipboard(label: String, text: String) {
    val manager = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
    manager.setPrimaryClip(ClipData.newPlainText(label, text))
}

/**
 * Hand a message to the system share sheet.
 *
 * The chooser is launched with `NEW_TASK` because the caller may be a
 * non-Activity context; a share that throws (no app can take it) is swallowed
 * rather than crashing the chat, since sharing is a convenience and not the
 * only way to get the text out.
 */
fun Context.shareText(label: String, text: String) {
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, label)
        putExtra(Intent.EXTRA_TEXT, text)
    }
    val chooser = Intent.createChooser(send, label).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { startActivity(chooser) }
}
