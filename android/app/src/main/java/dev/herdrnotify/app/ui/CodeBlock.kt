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
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * A code block the agent printed, rendered like one.
 *
 * It gets its own surface with a border, a language label and a copy button —
 * the three things that turn a wall of monospace into something a person can
 * read and reuse. A raw/rendered toggle sits beside the copy button, labelled
 * with the *action* it performs ("Ver crudo" while highlighted, "Ver resaltado"
 * while raw): labelling the current state made a highlighted block that looked
 * plain read as a bug, when it was only the raw view.
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
            .background(CodeColors.surface)
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
                color = CodeColors.comment,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { raw = !raw }) {
                Text(if (raw) "Ver resaltado" else "Ver crudo")
            }
            CopyButton(text = code, label = "Copiar código")
        }
        if (raw) {
            Text(
                text = code,
                style = codeStyle(),
                color = CodeColors.plain,
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
                        // The code surface is the same dark ground in both themes,
                        // so plain code is always the light text colour; without
                        // this it inherits the light theme's dark content colour
                        // and only the coloured tokens would be readable.
                        color = CodeColors.plain,
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
    val text = remember(lines) { lines.joinToString("\n") { it.text } }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(CodeColors.surface)
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
                color = CodeColors.comment,
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
                Text(
                    text = line.text,
                    style = codeStyle(),
                    // Diff colours are the light-on-dark set too, for the same
                    // reason: the diff is drawn on the same dark slab.
                    color = when (line.kind) {
                        ChangeKind.ADDED -> CodeColors.added
                        ChangeKind.REMOVED -> CodeColors.removed
                        ChangeKind.META -> CodeColors.meta
                        ChangeKind.CONTEXT -> CodeColors.context
                    },
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

/** Colour one tokenised line from the fixed dark-surface palette. */
@Composable
private fun highlight(line: String, language: String?): AnnotatedString {
    val palette = CodePalette(
        keyword = CodeColors.keyword,
        string = CodeColors.string,
        comment = CodeColors.comment,
        number = CodeColors.number,
    )
    return annotateLine(line, language, palette)
}
