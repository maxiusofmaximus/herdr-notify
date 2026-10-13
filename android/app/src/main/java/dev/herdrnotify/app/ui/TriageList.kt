package dev.herdrnotify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.R
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * The triage list: the screen the phone opens when it buzzes.
 *
 * Built for a glance under time pressure, often one-handed, often outdoors.
 * Three decisions follow from that:
 *
 * **A blocked agent is the only thing that gets a filled, saturated treatment.**
 * Everything else is quiet, so a screen full of nine agents still has exactly
 * one thing that pulls the eye. The colour *is* the information, so the status
 * word is also in the content description for anyone who cannot use the colour.
 *
 * **Rows are one line of title, one line of task, never three.** A wrapped
 * subtitle makes the list twice as tall and pushes the blocked agent off the
 * bottom of a phone screen, which defeats the entire ranking.
 *
 * **The whole row is the target, not a small button.** A 48dp minimum target
 * that you can hit without aiming.
 */
@Composable
fun TriageList(
    state: SessionState,
    onOpen: (AgentSummary) -> Unit,
    modifier: Modifier = Modifier,
    onNewChat: (String) -> Unit = {},
) {
    if (state.isEmpty) {
        EmptyTriage(modifier = modifier, onNewChat = onNewChat)
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(
            start = Spacing.lg,
            end = Spacing.lg,
            top = Spacing.sm,
            bottom = Spacing.xxl,
        ),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        item {
            NewChatRow(onNewChat = onNewChat)
        }
        items(state.agents, key = { it.paneId }) { agent ->
            TriageRow(agent = agent, onClick = { onOpen(agent) })
        }
    }
}

@Composable
private fun NewChatRow(onNewChat: (String) -> Unit) {
    var show by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }

    if (show) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { show = false },
            title = { androidx.compose.material3.Text("Nueva conversación") },
            text = {
                androidx.compose.material3.OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { androidx.compose.material3.Text("Nombre") },
                    singleLine = true,
                )
            },
            confirmButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        val trimmed = name.trim()
                        if (trimmed.isNotEmpty()) {
                            onNewChat(trimmed)
                            name = ""
                            show = false
                        }
                    },
                ) { androidx.compose.material3.Text("Crear") }
            },
            dismissButton = {
                androidx.compose.material3.TextButton(onClick = { show = false }) {
                    androidx.compose.material3.Text("Cancelar")
                }
            },
        )
    }

    androidx.compose.material3.TextButton(onClick = { show = true }) {
        androidx.compose.material3.Text("+ Nueva conversación")
    }
}

@Composable
private fun TriageRow(agent: AgentSummary, onClick: () -> Unit) {
    val statusColors = LocalStatusColors.current
    val accent = statusColors.forStatus(agent.status)
    val blocked = agent.status == AgentStatus.BLOCKED

    Card(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            // 56dp is a comfortable thumb target, above the 48dp minimum,
            // because this is the only target on the screen for a blocked agent.
            .heightIn(min = 56.dp)
            .semantics {
                contentDescription = rowDescription(agent)
            },
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (blocked) {
                MaterialTheme.colorScheme.surfaceVariant
            } else {
                MaterialTheme.colorScheme.surface
            },
        ),
        border = if (blocked) {
            androidx.compose.foundation.BorderStroke(1.dp, accent.copy(alpha = 0.55f))
        } else {
            null
        },
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusDot(
                status = agent.status,
                accent = accent,
                // A blocked dot pulses; nothing else does. Motion here means
                // "there is a decision waiting", and using it for anything else
                // would spend the signal.
                pulsing = blocked,
            )

            Spacer(Modifier.width(Spacing.md))

            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = agent.project,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (agent.focused) {
                        Spacer(Modifier.width(Spacing.sm))
                        Text(
                            text = "· en foco",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                        )
                    }
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    // The agent name is the fallback, not an empty string. A row
                    // with a blank second line looks like a rendering fault even
                    // when the data is complete — and an agent with no task
                    // title is normal, not an error.
                    text = agent.title?.takeIf { it.isNotBlank() }
                        ?: agent.agent.takeIf { it.isNotBlank() }
                        ?: agent.project,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Spacer(Modifier.width(Spacing.sm))

            Text(
                text = statusLabel(agent.status),
                style = MaterialTheme.typography.labelSmall,
                color = accent,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun StatusDot(status: AgentStatus, accent: androidx.compose.ui.graphics.Color, pulsing: Boolean) {
    val size = if (pulsing) 12.dp else 8.dp
    Box(
        modifier = Modifier
            .size(if (pulsing) 22.dp else 18.dp)
            .clip(CircleShape)
            .background(accent.copy(alpha = if (pulsing) 0.16f else 0.10f))
            .clearAndSetSemantics { },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(size)
                .clip(CircleShape)
                .background(accent),
        )
    }
}

@Composable
private fun EmptyTriage(modifier: Modifier = Modifier, onNewChat: (String) -> Unit = {}) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(Spacing.xl),
        ) {
            Box(
                modifier = Modifier
                    .size(56.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
            )
            Spacer(Modifier.height(Spacing.lg))
            Text(
                text = stringResource(R.string.triage_empty_title),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.sm))
            Text(
                text = stringResource(R.string.triage_empty_body),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(Spacing.lg))
            NewChatRow(onNewChat = onNewChat)
        }
    }
}

@Composable
internal fun statusLabel(status: AgentStatus): String = stringResource(
    when (status) {
        AgentStatus.BLOCKED -> R.string.status_blocked
        AgentStatus.WORKING -> R.string.status_working
        AgentStatus.DONE -> R.string.status_done
        AgentStatus.IDLE -> R.string.status_idle
        AgentStatus.UNKNOWN -> R.string.status_unknown
    },
)

/** Spoken form, since the dot's colour is not available to a screen reader. */
private fun rowDescription(agent: AgentSummary): String {
    val status = when (agent.status) {
        AgentStatus.BLOCKED -> "necesita tu atención"
        AgentStatus.WORKING -> "trabajando"
        AgentStatus.DONE -> "terminó"
        AgentStatus.IDLE -> "listo"
        AgentStatus.UNKNOWN -> "sin clasificar"
    }
    val title = agent.title?.let { ", $it" }.orEmpty()
    return "${agent.project}, $status$title"
}

@Preview(showBackground = true, backgroundColor = 0xFF0E1116, widthDp = 380)
@Composable
private fun TriageRowBlockedPreview() {
    dev.herdrnotify.app.ui.theme.HerdrNotifyTheme(darkTheme = true) {
        TriageList(
            state = SessionState(
                revision = 7,
                herdrVersion = "0.9.1",
                counts = mapOf(AgentStatus.BLOCKED to 1),
                agents = listOf(
                    AgentSummary(
                        paneId = "w3:p1",
                        workspaceId = "w3",
                        project = "ArkASA-Servidor-Dedicado",
                        agent = "opencode",
                        status = AgentStatus.BLOCKED,
                        attention = 3,
                        title = "Revisión general del proyecto",
                        cwd = "C:\\dev\\arkasa",
                        focused = false,
                        canResume = true,
                    ),
                    AgentSummary(
                        paneId = "wA:p1",
                        workspaceId = "wA",
                        project = "herdr-notify",
                        agent = "opencode",
                        status = AgentStatus.WORKING,
                        attention = 1,
                        title = "Notificaciones Android y acceso seguro",
                        cwd = "C:\\dev\\herdr-notify",
                        focused = true,
                        canResume = true,
                    ),
                    AgentSummary(
                        paneId = "w8:p1",
                        workspaceId = "w8",
                        project = "assets",
                        agent = "opencode",
                        status = AgentStatus.DONE,
                        attention = 2,
                        title = "Assets de cabello 3D con Blender MCP",
                        cwd = "C:\\dev\\assets",
                        focused = false,
                        canResume = true,
                    ),
                ),
            ),
            onOpen = {},
        )
    }
}
