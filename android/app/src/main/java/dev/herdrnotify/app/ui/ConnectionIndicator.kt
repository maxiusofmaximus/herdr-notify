package dev.herdrnotify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LocalMinimumInteractiveComponentSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.ui.theme.LocalStatusColors
import dev.herdrnotify.app.ui.theme.Spacing

/** The connection's colour meaning, one light per state. */
enum class ConnectionLight { LIVE, CONNECTING, OFFLINE, ERROR, UNPAIRED }

/** A short word for the state and the light that carries it. */
data class ConnectionIndicator(val light: ConnectionLight, val label: String)

/** Amber: reachable-but-not-now deserves a colour between green and red. */
private val WarningAmber = Color(0xFFD29922)

/**
 * The connection as one light.
 *
 * The header is the one thing on screen whatever the app is showing, so it is
 * where a persistent connection signal belongs: a green dot while live, amber
 * while the host is away, red when the pairing itself is broken. The word is
 * carried next to it so the colour is never the only signal.
 */
internal fun connectionIndicator(state: ConnectionState): ConnectionIndicator = when (state) {
    is ConnectionState.Live -> ConnectionIndicator(ConnectionLight.LIVE, "En línea")
    is ConnectionState.Connecting -> ConnectionIndicator(ConnectionLight.CONNECTING, "Conectando…")
    is ConnectionState.Offline -> ConnectionIndicator(ConnectionLight.OFFLINE, "Desconectado")
    is ConnectionState.Failed -> ConnectionIndicator(ConnectionLight.ERROR, "Error de conexión")
    is ConnectionState.Unpaired -> ConnectionIndicator(ConnectionLight.UNPAIRED, "Sin emparejar")
}

@Composable
private fun lightColor(light: ConnectionLight): Color {
    val statuses = LocalStatusColors.current
    return when (light) {
        ConnectionLight.LIVE -> statuses.done
        ConnectionLight.CONNECTING -> statuses.working
        ConnectionLight.OFFLINE -> WarningAmber
        ConnectionLight.ERROR -> statuses.blocked
        ConnectionLight.UNPAIRED -> statuses.idle
    }
}

/** The header pill: a coloured dot and the state, tappable for the details. */
@Composable
fun ConnectionPill(
    light: ConnectionLight,
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val color = lightColor(light)
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(50),
        color = color.copy(alpha = 0.14f),
        modifier = modifier,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.sm, vertical = Spacing.xxs + 1.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(color),
            )
            Spacer(Modifier.width(Spacing.xs + 2.dp))
            Text(
                text = text,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * The connection's details and the actions that fix it, from the header pill.
 *
 * It repeats the three troubleshooting steps the "Sin conexión" screen offers —
 * retry, change the gateway, re-pair — so a person who only ever sees the
 * header still has somewhere to go from it.
 */
@Composable
fun ConnectionDialog(
    indicator: ConnectionIndicator,
    detail: String?,
    host: String?,
    onRetry: () -> Unit,
    onChangeGateway: () -> Unit,
    onRepair: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(lightColor(indicator.light)),
                )
                Spacer(Modifier.width(Spacing.sm))
                Text("Conexión")
            }
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                Text(
                    text = indicator.label,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                detail?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (!host.isNullOrBlank()) {
                    Text(
                        text = "Equipo: $host",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            // The three actions stacked tightly. The default minimum-touch
            // padding Material puts around every button is what made this short
            // list look airy; as one group, a snug stack reads better.
            CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides Dp.Unspecified) {
                Column(horizontalAlignment = Alignment.End) {
                    TextButton(onClick = onRetry) { Text("Reintentar") }
                    TextButton(onClick = onRepair) { Text("Reemparejar") }
                    TextButton(onClick = onChangeGateway) { Text("Gateway") }
                }
            }
        },
    )
}
