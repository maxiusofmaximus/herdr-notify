package dev.herdrnotify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.pairing.DeviceInfo
import dev.herdrnotify.app.pairing.DevicesUiState
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.triage.formatSince

/**
 * "Mis dispositivos".
 *
 * A list of what the host trusts, with one action. Revoking is destructive and
 * remote, so it is behind a confirmation that names the device — and warns
 * loudly when the device being revoked is the phone in the person's hand.
 *
 * A device without `admin` cannot see this list at all; the error says so.
 */
@Composable
fun DevicesScreen(
    state: DevicesUiState,
    onBack: () -> Unit,
    onRevoke: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var pendingRevoke by remember { mutableStateOf<DeviceInfo?>(null) }
    val now = remember { System.currentTimeMillis() }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(Spacing.lg),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("Volver") }
            Spacer(Modifier.width(Spacing.sm))
            Text(
                text = "Mis dispositivos",
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }

        if (state.loading) {
            CircularProgressIndicator()
            return@Column
        }

        state.error?.let { error ->
            Text(
                text = error,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }

        if (state.isEmpty) {
            Text(
                text = "El equipo no tiene ningún dispositivo registrado.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@Column
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            state.devices.forEach { device ->
                DeviceCard(
                    device = device,
                    isSelf = device.deviceId == state.selfId,
                    revoking = state.revokingId == device.deviceId,
                    now = now,
                    onRevoke = { pendingRevoke = device },
                )
            }
        }
    }

    pendingRevoke?.let { device ->
        RevokeDialog(
            device = device,
            isSelf = device.deviceId == state.selfId,
            onConfirm = {
                pendingRevoke = null
                onRevoke(device.deviceId)
            },
            onDismiss = { pendingRevoke = null },
        )
    }
}

@Composable
private fun DeviceCard(
    device: DeviceInfo,
    isSelf: Boolean,
    revoking: Boolean,
    now: Long,
    onRevoke: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(
            modifier = Modifier.padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.xs),
        ) {
            Text(
                text = buildString {
                    append(device.label?.takeIf { it.isNotBlank() } ?: device.deviceId)
                    if (isSelf) append(" · este teléfono")
                    if (device.revoked) append(" · revocado")
                },
                style = MaterialTheme.typography.titleSmall,
                color = if (device.revoked) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
            Text(
                text = device.deviceId,
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = "Permisos: " + device.permissions.ifEmpty { listOf("ninguno") }.joinToString(", "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = lastSeen(device, now),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (device.isActive) {
                OutlinedButton(
                    onClick = onRevoke,
                    enabled = !revoking,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .semantics {
                            contentDescription = "Revocar ${device.label ?: device.deviceId}"
                        },
                ) {
                    Text(if (revoking) "Revocando…" else "Revocar")
                }
            }
        }
    }
}

@Composable
private fun RevokeDialog(
    device: DeviceInfo,
    isSelf: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val name = device.label?.takeIf { it.isNotBlank() } ?: device.deviceId
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (isSelf) "¿Revocar este teléfono?" else "¿Revocar $name?") },
        text = {
            Text(
                text = if (isSelf) {
                    "Se cerrará la sesión de este teléfono al instante y tendrás que " +
                        "volver a emparejarlo para seguir usándolo."
                } else {
                    "El dispositivo dejará de poder hablar con el equipo de inmediato. " +
                        "Tendrá que volver a emparejarse para reconectarse."
                },
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text("Revocar") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancelar") }
        },
    )
}

/** Last seen, in the short relative form, or that it never has. */
private fun lastSeen(device: DeviceInfo, now: Long): String = when {
    device.lastSeenAt <= 0.0 -> "Sin actividad registrada"
    else -> "Última vez ${formatSince(now - (device.lastSeenAt * 1_000.0).toLong())}"
}
