package dev.herdrnotify.app.pairing

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.ui.Caption
import dev.herdrnotify.app.ui.CommandBlock
import dev.herdrnotify.app.ui.CopyButton
import dev.herdrnotify.app.ui.ErrorText
import dev.herdrnotify.app.ui.HerdrCard
import dev.herdrnotify.app.ui.SectionLabel
import dev.herdrnotify.app.ui.ValueRow
import dev.herdrnotify.app.ui.copyToClipboard
import dev.herdrnotify.app.ui.theme.MonoKey
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * Pairing, shown when the app has no device identity yet.
 *
 * One flow, not three. The card at the top is the whole fast path: the operator
 * runs `herdr-notify enroll`, types the short code, and the gateway registers the
 * phone — or leaves the code blank and the host approves it because the source
 * address is its own tailnet owner. The fingerprint, the `add-device` command,
 * the device id and the gateway URL are still here, but folded under "Avanzado":
 * they are for the host reached over a link where `tailscale whois` cannot answer,
 * and putting them on the surface made a one-tap job look like a checklist.
 *
 * The recovery code a successful pairing returns is shown once, in a dialog that
 * will not close until it is acknowledged: it is the only way back in without
 * the host, so losing it silently would be a pairing that cannot be repaired.
 */
@Composable
fun PairingScreen(
    state: PairingUiState,
    onBaseUrl: (String) -> Unit,
    onDeviceId: (String) -> Unit,
    onSave: () -> Unit,
    onResetKey: () -> Unit,
    modifier: Modifier = Modifier,
    // Present when the phone is already paired and this screen was reached to
    // re-pair: the person has somewhere to go back to, and pairing must not be a
    // one-way door out of a working app.
    onBack: (() -> Unit)? = null,
    onCode: (String) -> Unit = {},
    onClaim: () -> Unit = {},
    onRepairWithRecovery: () -> Unit = {},
    onCommit: () -> Unit = {},
    onDismissRecovery: () -> Unit = {},
    onPickPeer: (TailnetPeer) -> Unit = {},
    onRefreshPeers: () -> Unit = {},
    onQrScanned: (String) -> Unit = {},
    onDismissQrError: () -> Unit = {},
    onDismissCodeError: () -> Unit = {},
) {
    val context = LocalContext.current
    var scanning by rememberSaveable { mutableStateOf(false) }

    if (state.isLoading) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars),
            contentAlignment = Alignment.Center,
        ) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
        }
        return
    }

    // Shown exactly once per pairing, and not dismissable: the recovery code is
    // the only path back in without the host, and a tap outside must not lose it.
    state.recoveryCode?.let { code ->
        RecoveryCodeDialog(
            code = code,
            onCopy = { context.copyToClipboard("herdr-notify recovery", code) },
            onContinue = onCommit,
        )
    }

    // A successful claim stops the camera: the recovery dialog is what matters
    // now, and a live preview behind it is battery spent on nothing.
    LaunchedEffect(state.claimedDeviceId) {
        if (state.claimedDeviceId != null) scanning = false
    }

    if (scanning) {
        QrScannerScreen(
            processing = state.claiming,
            notice = state.qrError ?: state.codeError,
            onBack = { scanning = false },
            onRaw = onQrScanned,
            onRetry = {
                onDismissQrError()
                onDismissCodeError()
            },
        )
        return
    }

    var advanced by rememberSaveable { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars.union(WindowInsets.ime))
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Spacing.lg, vertical = Spacing.md),
        verticalArrangement = Arrangement.spacedBy(Spacing.lg),
    ) {
        if (onBack != null) {
            TextButton(
                onClick = onBack,
                modifier = Modifier.heightIn(min = 48.dp),
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(Spacing.sm))
                Text("Volver")
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Text(
                text = "Emparejar este teléfono",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "La clave se genera aquí y no sale del teléfono. Regístrala con un " +
                    "código, o déjalo vacío para aprobarla desde el host.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // The QR is the fast path: one scan fills both fields and runs the same
        // claim the manual button runs. It is offered first, and the manual form
        // stays right below it for a phone with no camera or a code that will not
        // scan.
        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Button(
                onClick = { scanning = true },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            ) {
                Icon(
                    imageVector = Icons.Filled.QrCodeScanner,
                    contentDescription = null,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(Spacing.sm))
                Text("Escanear QR")
            }
            Caption("Apunta la cámara al código que muestra el equipo al emparejar.")
        }

        SectionLabel("Vincular manualmente")

        PcAddressCard(state = state, onBaseUrl = onBaseUrl)

        PeerPickerCard(state = state, onPickPeer = onPickPeer, onRefresh = onRefreshPeers)

        PairingCodeCard(
            state = state,
            onCode = onCode,
            onClaim = onClaim,
            onRepairWithRecovery = onRepairWithRecovery,
        )

        AdvancedToggle(expanded = advanced, onToggle = { advanced = !advanced })

        if (advanced) {
            AdvancedSection(
                state = state,
                onDeviceId = onDeviceId,
                onSave = onSave,
                onResetKey = onResetKey,
            )
        }

        Spacer(Modifier.height(Spacing.xl))
    }
}

@Composable
private fun PcAddressCard(
    state: PairingUiState,
    onBaseUrl: (String) -> Unit,
) {
    HerdrCard {
        OutlinedTextField(
            value = state.visibleBaseUrl,
            onValueChange = onBaseUrl,
            label = { Text("Dirección de tu PC") },
            placeholder = { Text("http://<IP-tailscale-del-PC>:8788") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Next,
            ),
            supportingText = {
                Text("La IP de Tailscale de tu PC y el puerto del gateway")
            },
            modifier = Modifier
                .fillMaxWidth()
                .semantics { contentDescription = "Dirección de tu PC" },
        )
    }
}

@Composable
private fun PeerPickerCard(
    state: PairingUiState,
    onPickPeer: (TailnetPeer) -> Unit,
    onRefresh: () -> Unit,
) {
    HerdrCard {
        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "Equipos en tu tailnet",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                if (state.peersLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                } else {
                    TextButton(onClick = onRefresh) { Text("Buscar") }
                }
            }
            when {
                state.peers.isNotEmpty() -> {
                    Caption("Toca un equipo para usar su dirección.")
                    state.peers.forEach { peer ->
                        PeerRow(peer = peer, onClick = { onPickPeer(peer) })
                    }
                }

                state.peersUnavailable ->
                    Caption("No se pudo leer la lista de equipos. Escribe la dirección a mano.")

                else ->
                    Caption("Escribe la dirección del equipo, o búscalo si ya está emparejado.")
            }
        }
    }
}

@Composable
private fun PeerRow(peer: TailnetPeer, onClick: () -> Unit) {
    val dot = if (peer.online) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(dot),
            )
            Spacer(Modifier.width(Spacing.sm))
            Column(Modifier.weight(1f)) {
                Text(
                    text = peer.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = peer.addresses.firstOrNull().orEmpty() +
                        if (peer.online) " · en línea" else " · desconectado",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/**
 * The fast path: a short code, or a blank one for the tailnet auto-approval.
 *
 * The hint about the blank code is not decoration: auto-approval is the fastest
 * way in and the least obvious, so it is stated where the field is.
 */
@Composable
private fun PairingCodeCard(
    state: PairingUiState,
    onCode: (String) -> Unit,
    onClaim: () -> Unit,
    onRepairWithRecovery: () -> Unit,
) {
    HerdrCard {
        Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
                Text(
                    text = "Código de emparejamiento",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Caption(
                    "En el host, ejecuta herdr-notify enroll y escribe aquí el código que " +
                        "imprima. Si el equipo es tuyo en Tailscale, déjalo vacío y se aprobará solo.",
                )
            }
            OutlinedTextField(
                value = state.code,
                onValueChange = onCode,
                label = { Text("Código") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Ascii,
                    imeAction = ImeAction.Done,
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Código de emparejamiento" },
            )
            state.codeError?.let { ErrorText(it) }
            Button(
                onClick = onClaim,
                enabled = state.canClaim,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            ) {
                if (state.claiming) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.width(Spacing.sm))
                    Text("Emparejando…")
                } else {
                    Text("Emparejar")
                }
            }
            if (state.hasStoredRecoveryCode) {
                OutlinedButton(
                    onClick = onRepairWithRecovery,
                    enabled = state.canClaim,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp),
                ) {
                    Text("Re-emparejar con código de recuperación")
                }
            }
        }
    }
}

/** A plain row that reveals the manual path. Kept off the surface by default. */
@Composable
private fun AdvancedToggle(expanded: Boolean, onToggle: () -> Unit) {
    val rotation by animateFloatAsState(if (expanded) 180f else 0f, label = "advanced")
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .clickable(onClick = onToggle)
            .semantics {
                contentDescription = if (expanded) "Ocultar opciones avanzadas" else "Mostrar opciones avanzadas"
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "Avanzado: emparejar a mano",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        Icon(
            imageVector = Icons.Filled.ExpandMore,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.rotate(rotation),
        )
    }
}

/**
 * The manual path, unchanged in behaviour from the original screen.
 *
 * The fingerprint and the device id are shown for real or said to be pending —
 * never left as an empty labelled box, which reads as a fault. The command and
 * the key scroll sideways and copy in one tap.
 */
@Composable
private fun AdvancedSection(
    state: PairingUiState,
    onDeviceId: (String) -> Unit,
    onSave: () -> Unit,
    onResetKey: () -> Unit,
) {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(Spacing.lg)) {
        HerdrCard {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "Identidad de este teléfono",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                    if (!state.publicKey.isNullOrBlank()) {
                        CopyButton(text = state.publicKey, label = "Copiar clave pública")
                    }
                }
                ValueRow(
                    label = "Huella de la clave pública",
                    value = state.fingerprint,
                    placeholder = "Generando la clave…",
                    mono = true,
                )
                Caption(
                    "Compara esta huella con la que muestre el host antes de continuar. Es lo " +
                        "que confirma que registraste esta clave y no otra.",
                )
                OutlinedTextField(
                    value = state.deviceId,
                    onValueChange = onDeviceId,
                    label = { Text("Identificador del dispositivo") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Caption("Ejecuta esto en la máquina que corre el gateway:")
            CommandBlock(
                label = "herdr-notify add-device",
                command = state.hostCommand.orEmpty(),
                copyLabel = "Copiar comando",
            )
        }

        state.error?.let { ErrorText(it) }

        Button(
            onClick = onSave,
            enabled = state.canSave,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
        ) {
            Text("Guardar y continuar")
        }
        OutlinedButton(
            onClick = onResetKey,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp),
        ) {
            Text("Generar una clave nueva")
        }
        Caption(
            "La clave antigua seguirá registrada en el host hasta que la revoques con " +
                "herdr-notify devices. Esta pantalla no puede hacerlo por ti: revocar es un " +
                "acto deliberado en el host.",
        )
    }
}

/**
 * Show the recovery code once.
 *
 * Not dismissable by tapping outside: the code is not stored anywhere the person
 * can read it back, so losing it here means losing the ability to re-pair without
 * the host.
 */
@Composable
private fun RecoveryCodeDialog(
    code: String,
    onCopy: () -> Unit,
    onContinue: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = { /* acknowledge explicitly */ },
        title = { Text("Guarda tu código de recuperación") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                Text(
                    text = "Se muestra una sola vez. Sirve para volver a emparejar este " +
                        "teléfono sin ayuda del equipo.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = code,
                    style = MonoKey,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.semantics {
                        contentDescription = "Código de recuperación: $code"
                    },
                )
                OutlinedButton(
                    onClick = onCopy,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp),
                ) {
                    Text("Copiar código")
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onContinue) { Text("Continuar") }
        },
    )
}
