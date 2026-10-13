package dev.herdrnotify.app.pairing

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * Pairing, shown when the app has no device identity yet.
 *
 * Two ways in, deliberately:
 *
 *  * **By code** — the operator runs one command on the host, which prints a
 *    short, single-use code. Typing it here calls the gateway's one
 *    unauthenticated write (`POST /v1/pair`), which registers this phone. A
 *    blank code is the auto-approval path: the host accepts the phone when the
 *    source address is its own tailnet owner.
 *  * **By hand** — the fingerprint and the `herdr-notify add-device` command, for
 *    a host reached over a link where `tailscale whois` cannot answer.
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
) {
    if (state.isLoading) {
        Column(
            modifier = modifier.fillMaxSize(),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            CircularProgressIndicator()
        }
        return
    }

    val context = LocalContext.current

    // Shown exactly once per pairing, and not dismissable: the recovery code is
    // the only path back in without the host, and a tap outside must not lose it.
    state.recoveryCode?.let { code ->
        RecoveryCodeDialog(
            code = code,
            onCopy = { context.copyToClipboard("herdr-notify recovery", code) },
            onContinue = onCommit,
        )
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacing.lg),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        if (onBack != null) {
            TextButton(onClick = onBack) { Text("Volver") }
        }
        Text(
            text = "Emparejar con el host",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = "La clave se genera aquí y no sale del teléfono. Regístrala con un " +
                "código, o pégala en el host por comando.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        // -- 0. the fast path: code, or auto-approval -------------------------
        PairingCodeCard(
            state = state,
            onCode = onCode,
            onClaim = onClaim,
            onRepairWithRecovery = onRepairWithRecovery,
        )

        // -- 1. identity -----------------------------------------------------
        SectionHeader("1 · Identidad de este teléfono")
        Text(
            text = "Huella de la clave pública",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = state.fingerprint.orEmpty(),
            style = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics {
                contentDescription = "Huella de la clave: ${state.fingerprint.orEmpty()}"
            },
        )
        Text(
            text = "Compara esta huella con la que muestre el host antes de continuar. " +
                "Es lo que confirma que registraste esta clave y no otra.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        OutlinedTextField(
            value = state.deviceId,
            onValueChange = onDeviceId,
            label = { Text("Identificador del dispositivo") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
            modifier = Modifier.fillMaxWidth(),
        )

        // -- 2. the host command --------------------------------------------
        SectionHeader("2 · En el host")
        Text(
            text = "Ejecuta esto en la máquina que corre el gateway:",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Text(
                text = state.hostCommand.orEmpty(),
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(Spacing.md),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            OutlinedButton(
                onClick = { context.copyToClipboard("herdr-notify add-device", state.hostCommand.orEmpty()) },
                modifier = Modifier.weight(1f),
            ) {
                Text("Copiar comando")
            }
            OutlinedButton(
                onClick = { context.copyToClipboard(state.deviceId, state.publicKey.orEmpty()) },
                modifier = Modifier.weight(1f),
            ) {
                Text("Copiar clave")
            }
        }

        // -- 3. address ------------------------------------------------------
        SectionHeader("3 · Dónde está el gateway")
        OutlinedTextField(
            value = state.baseUrl,
            onValueChange = onBaseUrl,
            label = { Text("URL del gateway") },
            placeholder = { Text("https://<tu-equipo>.<tailnet>.ts.net") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Done,
            ),
            supportingText = {
                Text("El nombre Tailscale del host. Sin https:// se añade automáticamente.")
            },
            modifier = Modifier.fillMaxWidth(),
        )

        state.error?.let { error ->
            Text(
                text = error,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Button(
            onClick = onSave,
            enabled = state.canSave,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
        ) {
            Text("Guardar y continuar")
        }

        Spacer(Modifier.height(Spacing.sm))

        OutlinedButton(
            onClick = onResetKey,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Generar una clave nueva")
        }
        Text(
            text = "La clave antigua seguirá registrada en el host hasta que la revoques " +
                "con `herdr-notify devices`. Esta pantalla no puede hacerlo por ti: " +
                "revocar es un acto deliberado en el host, no algo que un teléfono " +
                "pueda pedir por su cuenta.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(Spacing.xl))
    }
}

/**
 * The short-code entry, plus the recovery-code re-pair when one is held.
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(
            modifier = Modifier.padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            Text(
                text = "Código de emparejamiento",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                text = "En el host, ejecuta `herdr-notify enroll` y escribe aquí el " +
                    "código que imprima. Si el equipo es tuyo en Tailscale, déjalo " +
                    "vacío y se aprobará solo.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
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
            state.codeError?.let { error ->
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Button(
                onClick = onClaim,
                enabled = state.canClaim,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp),
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
                    style = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
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

@Composable
private fun SectionHeader(text: String) {
    Spacer(Modifier.height(Spacing.sm))
    Text(
        text = text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
    )
}

/**
 * Copy with a label the user will recognise later.
 *
 * Android 13+ shows a system toast for clipboard writes, so a second in-app
 * confirmation would be noise. The label is what makes the clipboard entry
 * identifiable in the paste menu.
 */
private fun Context.copyToClipboard(label: String, text: String) {
    val manager = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
    manager.setPrimaryClip(ClipData.newPlainText(label, text))
}
