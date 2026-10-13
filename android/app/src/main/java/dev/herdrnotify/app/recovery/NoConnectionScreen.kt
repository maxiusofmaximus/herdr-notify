package dev.herdrnotify.app.recovery

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.herdrnotify.app.ui.HerdrCard
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * The guided "Sin conexión" screen.
 *
 * It replaces a message and a single retry with the three steps that actually
 * fix an unreachable host, in the order a person would take them, and it says
 * *why* the last attempt failed rather than only that it did.
 *
 * The steps are numbered because order matters: Tailscale has to be up before a
 * retry can succeed, and re-pairing is the last resort rather than the first
 * thing to try.
 */
@Composable
fun NoConnectionScreen(
    state: RecoveryUiState,
    onActivateTailscale: () -> Unit,
    onRetry: () -> Unit,
    onRepair: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val needsRepair = recoveryNeedsRepair(state)

    Column(
        modifier = modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars)
            .verticalScroll(rememberScrollState())
            .padding(Spacing.lg),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        Text(
            text = "Sin conexión con el equipo",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = recoveryReason(state),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.semantics { contentDescription = recoveryReason(state) },
        )
        if (state.host.isNotBlank()) {
            Text(
                text = "Equipo: ${state.host}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(Spacing.sm))

        // -- 1. Tailscale -----------------------------------------------------
        RecoveryStep(
            number = "1",
            title = "Activar Tailscale",
            body = "Ábrela y comprueba que está conectada en este teléfono y en el PC. " +
                "Sin la red Tailscale el equipo no es alcanzable por su nombre.",
        ) {
            OutlinedButton(
                onClick = onActivateTailscale,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp),
            ) {
                Text("Activar Tailscale")
            }
        }

        // -- 2. Retry the addresses ------------------------------------------
        RecoveryStep(
            number = "2",
            title = "Reintentar",
            body = "Vuelve a probar las direcciones conocidas del equipo y reconecta. " +
                "Hazlo después de activar Tailscale.",
        ) {
            Button(
                onClick = onRetry,
                enabled = !state.probing,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp),
            ) {
                if (state.probing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.width(Spacing.sm))
                    Text("Comprobando…")
                } else {
                    Text("Reintentar")
                }
            }
        }

        // -- 3. Re-pair -------------------------------------------------------
        RecoveryStep(
            number = "3",
            title = "Re-emparejar",
            body = "Vuelve a registrar este teléfono en el equipo. Es lo necesario " +
                "cuando el equipo ha olvidado la clave de este dispositivo.",
        ) {
            if (needsRepair) {
                Button(
                    onClick = onRepair,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp),
                ) {
                    Text("Re-emparejar")
                }
            } else {
                OutlinedButton(
                    onClick = onRepair,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp),
                ) {
                    Text("Re-emparejar")
                }
            }
        }

        Spacer(Modifier.height(Spacing.xl))
    }
}

@Composable
private fun RecoveryStep(
    number: String,
    title: String,
    body: String,
    action: @Composable () -> Unit,
) {
    HerdrCard {
        Column(
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = number,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.width(Spacing.sm))
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            Text(
                text = body,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            action()
        }
    }
}

/** The Tailscale Android package. */
const val TAILSCALE_PACKAGE: String = "com.tailscale.ipn"

/**
 * Open the Tailscale app.
 *
 * Falls back to the Play Store listing when the app is not installed, so the
 * step is never a button that does nothing. Returns false only if neither the
 * app nor a store can be opened, which the call site may ignore: the step is
 * advisory, and the retry below it is the part that connects.
 */
fun openTailscale(context: Context): Boolean {
    val launch = context.packageManager.getLaunchIntentForPackage(TAILSCALE_PACKAGE)
    if (launch != null) {
        return runCatching { context.startActivity(launch); true }.getOrDefault(false)
    }
    val store = Intent(
        Intent.ACTION_VIEW,
        Uri.parse("market://details?id=$TAILSCALE_PACKAGE"),
    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    return runCatching { context.startActivity(store); true }.getOrDefault(false)
}
