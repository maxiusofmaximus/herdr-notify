package dev.herdrnotify.app.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.herdrnotify.app.R
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.triage.AgentDetail
import dev.herdrnotify.app.ui.triage.PendingImage

/**
 * One agent: what it is doing, its recent turns, and a box to answer it.
 *
 * The pane comes back as a rendered terminal screen, so the view is split in
 * two. **Conversación** is the cleaned reading: the person's prompts and the
 * agent's replies as separate bubbles, with Claude Code's chrome folded into
 * quiet status rows (see [TranscriptParser]). **Salida cruda** is the untouched
 * tail, one tap away, so nothing the parser misreads is ever really lost.
 *
 * The box is always there, because the common reason to open an agent is to
 * answer it: the input and Send button ride above the keyboard and the
 * navigation bar through the bottom inset, and the system back gesture returns
 * to the list.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentDetailScreen(
    agent: AgentSummary?,
    detail: AgentDetail,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onConfirmSend: () -> Unit,
    onDismissConfirm: () -> Unit,
    onPermissionKeys: (List<String>, Boolean) -> Unit,
    onRetry: (String) -> Unit,
    onStop: () -> Unit,
    onConfirmStop: () -> Unit,
    onDismissStop: () -> Unit,
    onDismissNotice: () -> Unit,
    onAttachImage: (ByteArray, String) -> Unit,
    onClearAttachment: () -> Unit,
) {
    // The system back gesture closes the detail, rather than leaving the app.
    BackHandler(onBack = onBack)

    if (detail.confirmRequired) {
        AlertDialog(
            onDismissRequest = onDismissConfirm,
            text = {
                Text("Este agente no está esperando una respuesta. ¿Enviar de todos modos?")
            },
            confirmButton = {
                TextButton(onClick = onConfirmSend) { Text("Enviar") }
            },
            dismissButton = {
                TextButton(onClick = onDismissConfirm) { Text("Cancelar") }
            },
        )
    }

    // Interrupting is not reversible, so the stop button is a question first.
    if (detail.stopRequired) {
        AlertDialog(
            onDismissRequest = onDismissStop,
            title = { Text(stringResource(R.string.action_stop_confirm_title)) },
            text = { Text(stringResource(R.string.action_stop_confirm_body)) },
            confirmButton = {
                TextButton(onClick = onConfirmStop) {
                    Text(stringResource(R.string.action_stop_agent))
                }
            },
            dismissButton = {
                TextButton(onClick = onDismissStop) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }

    // "Permitir siempre" widens access for good, so it is asked twice: the button
    // is the first tap, this dialog is the second. The option is held here rather
    // than in the card so a re-read of the tail cannot move the question the
    // person is about to answer.
    var pendingAlways by remember { mutableStateOf<PermissionOption?>(null) }
    pendingAlways?.let { option ->
        AlertDialog(
            onDismissRequest = { pendingAlways = null },
            title = { Text("¿Permitir siempre?") },
            text = {
                Text(
                    "Se concederá el permiso sin volver a preguntar en esta sesión. " +
                        "Podrás revocarlo en el host, pero no desde aquí.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        pendingAlways = null
                        onPermissionKeys(option.keys, true)
                    },
                ) { Text("Permitir siempre") }
            },
            dismissButton = {
                TextButton(onClick = { pendingAlways = null }) { Text("Cancelar") }
            },
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { ChatHeaderTitle(agent = agent, paneId = detail.paneId) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Volver a la lista",
                        )
                    }
                },
                actions = {
                    IconButton(onClick = onRefresh) {
                        Icon(
                            imageVector = Icons.Filled.Refresh,
                            contentDescription = "Leer de nuevo",
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        bottomBar = {
            Composer(
                detail = detail,
                // The agent's own status decides whether the composer offers a
                // Stop: the reference apps make the composer the place generation
                // is cancelled, and this mirrors the signal the list already shows.
                working = agent?.status == AgentStatus.WORKING,
                onDraftChange = onDraftChange,
                onSend = onSend,
                onStop = onStop,
                onDismissNotice = onDismissNotice,
                onAttachImage = onAttachImage,
                onClearAttachment = onClearAttachment,
            )
        },
    ) { insets ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(insets)
                .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
        ) {
            var rawMode by rememberSaveable { mutableStateOf(false) }

            detail.outputError?.let { problem ->
                // "The agent is working; the output will load in a moment" is a
                // normal state, not a failure: shown as a neutral notice with no
                // Retry button (the read retries itself), so red is reserved for
                // things that are actually broken.
                NoticeCard(
                    message = problem.message,
                    title = if (problem.transient) "Leyendo el agente" else "No se pudo leer el agente",
                    kind = if (problem.transient) NoticeKind.WARNING else NoticeKind.ERROR,
                    actions = buildList {
                        if (problem.retryable && !problem.transient) {
                            add(NoticeAction("Reintentar", onRefresh))
                        }
                        if (!detail.output.isNullOrBlank()) {
                            add(NoticeAction("Ver salida cruda") { rawMode = true })
                        }
                    },
                )
                Spacer(Modifier.height(Spacing.sm))
            }

            ModeToggle(
                raw = rawMode,
                onChange = { rawMode = it },
                enabled = !detail.output.isNullOrBlank(),
            )
            Spacer(Modifier.height(Spacing.sm))

            val output = detail.output
            when {
                output == null -> Placeholder("Cargando la salida…")
                output.isBlank() -> Placeholder("Sin salida reciente")
                rawMode -> RawOutput(output = output, modifier = Modifier.weight(1f))
                else -> Transcript(
                    entries = remember(output) { TranscriptParser.parse(output) },
                    onPermissionOption = { option ->
                        if (option.confirm) {
                            pendingAlways = option
                        } else {
                            onPermissionKeys(option.keys, false)
                        }
                    },
                    onRetry = onRetry,
                    onViewRaw = { rawMode = true },
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

/**
 * Project on top, the agent's state and task underneath, carried by a coloured
 * dot whose colour is herdr's own status meaning — the same signal the list and
 * the terminal use, so the two never disagree about what "blocked" looks like.
 */
@Composable
private fun ChatHeaderTitle(agent: AgentSummary?, paneId: String) {
    Column {
        Text(
            text = agent?.project ?: paneId,
            style = MaterialTheme.typography.titleLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (agent != null) {
            val statusColors = LocalStatusColors.current
            val accent = statusColors.forStatus(agent.status)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(accent),
                )
                Spacer(Modifier.width(Spacing.xs + 2.dp))
                Text(
                    text = statusLabel(agent.status),
                    style = MaterialTheme.typography.bodySmall,
                    color = statusColors.label(agent.status),
                    maxLines = 1,
                )
                val title = agent.title?.takeIf { it.isNotBlank() }
                if (title != null) {
                    Text(
                        text = " · $title",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

/**
 * The reading is the default; the raw tail is one tap away. A segmented pair
 * rather than a hidden gesture, because "the phone rewrote this" is exactly the
 * moment a developer wants to check the source, and it should be obvious.
 */
@Composable
private fun ModeToggle(raw: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Segment(
            label = "Conversación",
            selected = !raw,
            enabled = enabled,
            onClick = { onChange(false) },
        )
        Spacer(Modifier.width(Spacing.sm))
        Segment(
            label = "Salida cruda",
            selected = raw,
            enabled = enabled,
            onClick = { onChange(true) },
        )
    }
}

@Composable
private fun Segment(label: String, selected: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val container = when {
        selected -> MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
        else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
    }
    val content = when {
        selected -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(50),
        color = container,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = if (enabled) content else content.copy(alpha = 0.4f),
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.xs + 2.dp),
        )
    }
}

@Composable
private fun Placeholder(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * The cleaned conversation: the person's turns on the right, the agent's on the
 * left, status rows in the middle. It follows the newest turn the way a chat
 * does, because the question brought to this screen is almost always "what did
 * it just say"; scrolling up to read history still works until the next read.
 */
@Composable
private fun Transcript(
    entries: List<TranscriptEntry>,
    onPermissionOption: (PermissionOption) -> Unit,
    onRetry: (String) -> Unit,
    onViewRaw: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scroll = rememberScrollState()
    AutoScrollToBottom(scroll)

    Column(
        modifier = modifier
            .fillMaxWidth()
            .verticalScroll(scroll),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        // The prompt that produced the agent's current turn, so an agent message
        // can retry it. Reset by the next person's turn.
        var lastUser: String? = null
        entries.forEach { entry ->
            when (entry) {
                is TranscriptEntry.User -> {
                    Column(Modifier.fillMaxWidth()) {
                        Bubble(text = entry.text, fromUser = true)
                        MessageActions(
                            role = MessageRole.USER,
                            text = entry.text,
                            retryText = entry.text,
                            canViewRaw = false,
                            onRetry = onRetry,
                            onViewRaw = onViewRaw,
                            modifier = Modifier.align(Alignment.End),
                        )
                    }
                    lastUser = entry.text
                }

                is TranscriptEntry.Agent -> Column(Modifier.fillMaxWidth()) {
                    Bubble(text = entry.text, fromUser = false)
                    MessageActions(
                        role = MessageRole.AGENT,
                        text = entry.text,
                        retryText = lastUser,
                        canViewRaw = true,
                        onRetry = onRetry,
                        onViewRaw = onViewRaw,
                        modifier = Modifier.align(Alignment.Start),
                    )
                }

                is TranscriptEntry.Status -> StatusRow(entry)
                is TranscriptEntry.Permission -> PermissionCard(entry.prompt, onPermissionOption)
                is TranscriptEntry.Changes -> DiffBlock(entry.lines)
                is TranscriptEntry.Code -> CodeBlock(code = entry.code, language = entry.language)
            }
        }
    }
}

/**
 * A blocking permission dialog, drawn as its own card of buttons.
 *
 * This is the one piece of the pane the phone exists to answer: the agent is
 * stopped until a choice is made, and the person is away from the PC. The
 * buttons carry the parsed keystrokes, so tapping one is the same as reaching
 * over and pressing the key. "Permitir siempre" is routed back through the
 * screen's confirmation dialog rather than sent from here.
 */
@Composable
private fun PermissionCard(prompt: PermissionPrompt, onOption: (PermissionOption) -> Unit) {
    val accent = LocalStatusColors.current.blocked
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(Spacing.md)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(accent),
                )
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = prompt.title,
                    style = MaterialTheme.typography.labelLarge,
                    color = accent,
                )
            }
            prompt.detail?.let { detail ->
                Spacer(Modifier.height(Spacing.xs))
                Text(
                    text = detail,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            Spacer(Modifier.height(Spacing.sm))
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                prompt.options.forEachIndexed { index, option ->
                    if (index == 0) {
                        Button(
                            onClick = { onOption(option) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(option.label) }
                    } else {
                        OutlinedButton(
                            onClick = { onOption(option) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(option.label) }
                    }
                }
            }
        }
    }
}

@Composable
private fun Bubble(text: String, fromUser: Boolean) {
    val bubbleColor = if (fromUser) {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    // The agent's turn is terminal output and stays monospaced so column-shaped
    // text survives; the person's own words are prose and read better in the
    // normal face, which is also what makes "mine vs. its" legible at a glance.
    val textStyle = if (fromUser) {
        MaterialTheme.typography.bodyMedium
    } else {
        MaterialTheme.typography.bodySmall.copy(
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (fromUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            color = bubbleColor,
            shape = if (fromUser) {
                RoundedCornerShape(18.dp, 18.dp, 18.dp, 6.dp)
            } else {
                RoundedCornerShape(18.dp, 18.dp, 6.dp, 18.dp)
            },
            modifier = Modifier.widthIn(max = 330.dp),
        ) {
            Text(
                text = text,
                style = textStyle,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.sm + 2.dp),
            )
        }
    }
}

@Composable
private fun StatusRow(status: TranscriptEntry.Status) {
    when (status.kind) {
        StatusKind.RECAP -> RecapBlock(text = status.text)
        else -> {
            val colors = LocalStatusColors.current
            val accent = if (status.kind == StatusKind.PROGRESS) colors.working else colors.idle
            CenteredStatus(text = status.text, accent = accent)
        }
    }
}

/** Progress and chrome: a small centred chip, quiet enough to skim past. */
@Composable
private fun CenteredStatus(text: String, accent: Color) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
    ) {
        Surface(
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
            shape = RoundedCornerShape(50),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.xs),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .background(accent),
                )
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = text,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 300.dp),
                )
            }
        }
    }
}

/**
 * A `recap:` block is a real summary, so it gets a labelled, left-anchored card
 * instead of a chip: it is the one piece of chrome worth reading, and a summary
 * dressed as noise would be skipped.
 */
@Composable
private fun RecapBlock(text: String) {
    val accent = LocalStatusColors.current.done
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .height(IntrinsicSize.Min)
                .padding(Spacing.md),
        ) {
            Box(
                Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(accent),
            )
            Spacer(Modifier.width(Spacing.md))
            Column {
                Text(
                    text = "Resumen",
                    style = MaterialTheme.typography.labelSmall,
                    color = accent,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = text,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * The pane exactly as the terminal drew it, for the moments the cleaned view is
 * not trusted. Monospaced, follows the tail, and never reformatted.
 */
@Composable
private fun RawOutput(output: String, modifier: Modifier = Modifier) {
    val scroll = rememberScrollState()
    AutoScrollToBottom(scroll)

    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(Spacing.md)
            .verticalScroll(scroll),
    ) {
        Text(
            text = output,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * The answer box. Disabled while a send is in flight, so a double tap cannot
 * send the same text twice.
 *
 * The edge-to-edge window draws behind the navigation bar, so the box must
 * leave room for it: `imePadding` alone lifts the box only for the keyboard and
 * lets the navigation bar cover it when the keyboard is down. The bottom inset
 * is the union — the larger of the keyboard and the navigation bar — not their
 * sum, because with the keyboard up the navigation bar sits under it and adding
 * both would leave a stray gap above the keyboard.
 */
@Composable
private fun Composer(
    detail: AgentDetail,
    working: Boolean,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onDismissNotice: () -> Unit,
    onAttachImage: (ByteArray, String) -> Unit,
    onClearAttachment: () -> Unit,
) {
    val context = LocalContext.current
    val pickImage = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        // Reading on the callback thread is fine for the few-megabyte ceiling
        // the validator enforces; a failure is reported as an unreadable image.
        readImage(context, uri)?.let { (bytes, mime) -> onAttachImage(bytes, mime) }
            ?: onAttachImage(ByteArray(0), "")
    }

    Column(
        Modifier
            .fillMaxWidth()
            .windowInsetsPadding(
                WindowInsets.ime.union(WindowInsets.navigationBars).only(WindowInsetsSides.Bottom),
            )
            .background(MaterialTheme.colorScheme.background)
            .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
    ) {
        detail.notice?.let { message ->
            NoticeCard(
                message = message,
                title = "No se pudo completar la acción",
                actions = buildList {
                    // A preserved draft is what makes Retry meaningful: the text
                    // is still here, so sending it again is one tap.
                    if (detail.draft.isNotBlank() && !detail.sending) {
                        add(NoticeAction("Reintentar", onSend))
                    }
                    add(NoticeAction("Descartar", onDismissNotice))
                },
            )
            Spacer(Modifier.height(Spacing.xs))
        }
        detail.attachment?.let { image ->
            AttachmentChip(image = image, enabled = !detail.sending, onRemove = onClearAttachment)
            Spacer(Modifier.height(Spacing.xs))
        }
        if (working) {
            StreamingIndicator()
            Spacer(Modifier.height(Spacing.sm))
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Bottom,
        ) {
            IconButton(
                onClick = {
                    pickImage.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                    )
                },
                enabled = !detail.sending,
            ) {
                Icon(
                    imageVector = Icons.Filled.AttachFile,
                    contentDescription = "Adjuntar imagen",
                )
            }
            OutlinedTextField(
                value = detail.draft,
                onValueChange = onDraftChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Escribe una respuesta…") },
                maxLines = 6,
                enabled = !detail.sending,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
            )
            Spacer(Modifier.width(Spacing.sm))
            // One slot, two meanings: while the agent is working and there is
            // nothing typed, it is a filled Stop; the moment there is a draft it
            // is Enviar again, so a person can always send what they typed.
            val showStop = working && detail.draft.isBlank()
            if (showStop) {
                FilledIconButton(
                    onClick = onStop,
                    enabled = !detail.sending,
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                        contentColor = MaterialTheme.colorScheme.onError,
                    ),
                ) {
                    Icon(
                        imageVector = Icons.Filled.Stop,
                        contentDescription = stringResource(R.string.action_stop_agent),
                    )
                }
            } else {
                FilledIconButton(
                    onClick = onSend,
                    enabled = detail.draft.isNotBlank() && !detail.sending,
                ) {
                    Icon(
                        imageVector = Icons.Filled.Send,
                        contentDescription = "Enviar",
                    )
                }
            }
        }
    }
}

/**
 * A quiet "the agent is working" line for the composer: three dots that pulse in
 * sequence beside the words.
 *
 * The status is already in the header, but the composer is where the person's
 * thumb is while they wait, so the same signal is repeated where the decision to
 * wait or to stop is made. The dots use the working colour so the motion is the
 * same "in progress" the list shows.
 */
@Composable
private fun StreamingIndicator() {
    val accent = LocalStatusColors.current.working
    val transition = rememberInfiniteTransition(label = "streaming")
    Row(verticalAlignment = Alignment.CenterVertically) {
        repeat(3) { index ->
            val alpha by transition.animateFloat(
                initialValue = 0.25f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(
                        durationMillis = 600,
                        delayMillis = index * 160,
                        easing = LinearEasing,
                    ),
                    repeatMode = RepeatMode.Reverse,
                ),
                label = "streaming-dot-$index",
            )
            Box(
                Modifier
                    .size(7.dp)
                    .clip(CircleShape)
                    .background(accent.copy(alpha = alpha)),
            )
            if (index < 2) Spacer(Modifier.width(4.dp))
        }
        Spacer(Modifier.width(Spacing.sm))
        Text(
            text = "El agente está trabajando…",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * The picked image, before it is sent. It shows only what the person needs to
 * confirm the choice — that it is an image, and how big — with a one-tap way to
 * drop it. The picture itself is not decoded here: the transport is still
 * pending on the host, and a thumbnail would be work spent on a payload that
 * cannot leave the phone yet.
 */
@Composable
private fun AttachmentChip(image: PendingImage, enabled: Boolean, onRemove: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(start = Spacing.md, end = Spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Filled.Image,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = "Imagen · ${image.bytes.size / 1024} KB",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onRemove, enabled = enabled) {
                Icon(
                    imageVector = Icons.Filled.Close,
                    contentDescription = "Quitar imagen",
                )
            }
        }
    }
}
