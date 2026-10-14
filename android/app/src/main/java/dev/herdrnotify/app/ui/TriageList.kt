package dev.herdrnotify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.toMutableStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.R
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.theme.Surface2
import dev.herdrnotify.app.ui.theme.TextPrimary
import dev.herdrnotify.app.ui.theme.TextSecondary
import dev.herdrnotify.app.ui.triage.ProjectGroup
import dev.herdrnotify.app.ui.triage.filterAgents
import dev.herdrnotify.app.ui.triage.groupByProject

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
    onNewChat: () -> Unit = {},
) {
    if (state.isEmpty) {
        EmptyTriage(modifier = modifier, onNewChat = onNewChat)
        return
    }

    var query by rememberSaveable { mutableStateOf("") }
    val collapsed = rememberSaveable(
        saver = listSaver(
            save = { it.toList() },
            restore = { it.toMutableStateList() },
        ),
    ) { mutableStateListOf<String>() }
    val filtered = remember(state.agents, query) { filterAgents(state.agents, query) }
    val groups = remember(filtered) { groupByProject(filtered) }

    Column(modifier = modifier.fillMaxSize()) {
        SearchRow(
            query = query,
            onQuery = { query = it },
            modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(
                start = Spacing.lg,
                end = Spacing.lg,
                bottom = Spacing.xxl,
            ),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            item {
                NewChatRow(onNewChat = onNewChat)
            }
            if (groups.isEmpty()) {
                item {
                    NoMatches(query = query)
                }
            } else {
                groups.forEach { group ->
                    val open = group.project !in collapsed
                    item(key = "header:${group.project}") {
                        ProjectHeader(
                            group = group,
                            open = open,
                            onToggle = {
                                if (open) collapsed.add(group.project) else collapsed.remove(group.project)
                            },
                        )
                    }
                    if (open) {
                        items(group.agents, key = { it.paneId }) { agent ->
                            TriageRow(agent = agent, onClick = { onOpen(agent) })
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NewChatRow(onNewChat: () -> Unit) {
    androidx.compose.material3.TextButton(
        onClick = onNewChat,
        modifier = Modifier.fillMaxWidth(),
    ) {
        androidx.compose.material3.Text("+ Nueva conversación")
    }
}

@Composable
private fun SearchRow(query: String, onQuery: (String) -> Unit, modifier: Modifier = Modifier) {
    OutlinedTextField(
        value = query,
        onValueChange = onQuery,
        modifier = modifier.fillMaxWidth(),
        singleLine = true,
        placeholder = { Text("Buscar conversaciones…") },
        leadingIcon = {
            Icon(
                imageVector = Icons.Filled.Search,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        trailingIcon = {
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQuery("") }) {
                    Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = "Borrar la búsqueda",
                    )
                }
            }
        },
    )
}

@Composable
private fun ProjectHeader(group: ProjectGroup, open: Boolean, onToggle: () -> Unit) {
    val statusColors = LocalStatusColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 52.dp)
            .clickable(onClick = onToggle)
            .padding(vertical = Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.ExpandMore,
            contentDescription = if (open) "Contraer ${group.project}" else "Expandir ${group.project}",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier
                .size(20.dp)
                .rotate(if (open) 0f else -90f),
        )
        Spacer(Modifier.width(Spacing.xs))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = group.project,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            group.latest?.let { latest ->
                Text(
                    text = listOfNotNull(
                        statusLabel(latest.status),
                        latest.title?.takeIf { it.isNotBlank() } ?: latest.agent.takeIf { it.isNotBlank() },
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = statusColors.label(latest.status),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Spacer(Modifier.width(Spacing.sm))
        Text(
            text = if (group.waiting > 0) "${group.waiting}/${group.count}" else group.count.toString(),
            style = MaterialTheme.typography.labelMedium,
            color = if (group.waiting > 0) {
                statusColors.label(AgentStatus.BLOCKED)
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

@Composable
private fun NoMatches(query: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(Spacing.xl),
        contentAlignment = Alignment.Center,
    ) {
        StateBlock(
            icon = {
                Icon(
                    imageVector = Icons.Filled.Search,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            title = "Sin coincidencias",
            body = "Ninguna conversación coincide con «$query».",
        )
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
                color = statusColors.label(agent.status),
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun EmptyTriage(modifier: Modifier = Modifier, onNewChat: () -> Unit = {}) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacing.xl),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(Surface2),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Filled.Bolt,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = stringResource(R.string.triage_empty_title),
                style = MaterialTheme.typography.titleMedium,
                color = TextPrimary,
            )
            // What an agent *is*, for the person who opened the app to an empty
            // list and has not used it before. A blank screen with "nothing here"
            // teaches nothing; this says what would appear and how to make it.
            Text(
                text = stringResource(R.string.triage_empty_body),
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary,
                textAlign = TextAlign.Center,
            )
            HerdrCard {
                Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    SectionLabel(stringResource(R.string.triage_empty_steps_title))
                    EmptyStep("1", stringResource(R.string.triage_empty_step_1))
                    EmptyStep("2", stringResource(R.string.triage_empty_step_2))
                    EmptyStep("3", stringResource(R.string.triage_empty_step_3))
                }
            }
            Button(
                onClick = onNewChat,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 52.dp),
            ) {
                Text(stringResource(R.string.action_new_chat))
            }
        }
    }
}

@Composable
private fun EmptyStep(number: String, text: String) {
    Row(verticalAlignment = Alignment.Top) {
        Text(
            text = number,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.width(Spacing.sm))
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
        )
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
