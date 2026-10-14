package dev.herdrnotify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.theme.Surface2
import dev.herdrnotify.app.ui.theme.TextMuted
import dev.herdrnotify.app.ui.theme.TextPrimary

/** Amber for numbers, the one syntax colour the status palette does not name. */
private val NumberAmber = Color(0xFFD29922)

/**
 * A code block the agent printed, rendered like one.
 *
 * It gets its own surface with a border, a language label and a copy button —
 * the three things that turn a wall of monospace into something a person can
 * read and reuse. A **Crudo / Resaltado** toggle sits beside the copy button:
 * highlighting is a guess about the language, and the moment it guesses wrong
 * the person needs the exact bytes back, which is what raw shows (and what the
 * copy button always copies, highlighted or not).
 */
@Composable
fun CodeBlock(
    code: String,
    language: String?,
    modifier: Modifier = Modifier,
) {
    var raw by remember { mutableStateOf(false) }
    val label = language?.trim()?.takeIf { it.isNotEmpty() } ?: "Código"

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Surface2)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = Spacing.lg, end = Spacing.xs, top = Spacing.xs),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = TextMuted,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { raw = !raw }) {
                Text(if (raw) "Resaltado" else "Crudo")
            }
            CopyButton(text = code, label = "Copiar código")
        }
        if (raw) {
            Text(
                text = code,
                style = codeStyle(),
                color = TextPrimary,
                softWrap = false,
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(start = Spacing.lg, end = Spacing.lg, bottom = Spacing.md),
            )
        } else {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(start = Spacing.lg, end = Spacing.lg, bottom = Spacing.md),
            ) {
                code.trimEnd('\n').split('\n').forEach { line ->
                    Text(
                        text = highlight(line, language),
                        style = codeStyle(),
                        softWrap = false,
                    )
                }
            }
        }
    }
}

/**
 * A unified diff, kept as a diff.
 *
 * The `+`/`-` structure is the information, so it is coloured per line rather
 * than poured into prose, and the whole block is copyable in one tap.
 */
@Composable
fun DiffBlock(lines: List<ChangeLine>, modifier: Modifier = Modifier) {
    val colors = LocalStatusColors.current
    val text = remember(lines) { lines.joinToString("\n") { it.text } }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Surface2)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = Spacing.lg, end = Spacing.xs, top = Spacing.xs),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Text(
                text = "Cambios",
                style = MaterialTheme.typography.labelMedium,
                color = TextMuted,
                modifier = Modifier.weight(1f),
            )
            CopyButton(text = text, label = "Copiar diff")
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(start = Spacing.lg, end = Spacing.lg, bottom = Spacing.md),
        ) {
            lines.forEach { line ->
                val color = when (line.kind) {
                    ChangeKind.ADDED -> colors.done
                    ChangeKind.REMOVED -> MaterialTheme.colorScheme.error
                    ChangeKind.META -> MaterialTheme.colorScheme.primary
                    ChangeKind.CONTEXT -> MaterialTheme.colorScheme.onSurfaceVariant
                }
                Text(
                    text = line.text,
                    style = codeStyle(),
                    color = color,
                    softWrap = false,
                )
            }
        }
    }
}

@Composable
private fun codeStyle() = MaterialTheme.typography.bodySmall.copy(
    fontFamily = FontFamily.Monospace,
    fontSize = 12.sp,
    lineHeight = 18.sp,
)

/** Colour one tokenised line, using the same meanings the status palette uses. */
@Composable
private fun highlight(line: String, language: String?): AnnotatedString {
    val keyword = MaterialTheme.colorScheme.primary
    val string = LocalStatusColors.current.done
    val comment = TextMuted
    return buildAnnotatedString {
        CodeHighlighter.tokenizeLine(line, language).forEach { span ->
            val style = when (span.token) {
                CodeToken.PLAIN -> null
                CodeToken.KEYWORD -> SpanStyle(color = keyword)
                CodeToken.STRING -> SpanStyle(color = string)
                CodeToken.COMMENT -> SpanStyle(color = comment)
                CodeToken.NUMBER -> SpanStyle(color = NumberAmber)
            }
            if (style == null) append(span.text) else withStyle(style) { append(span.text) }
        }
    }
}
