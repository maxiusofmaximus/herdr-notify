package dev.herdrnotify.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType

/**
 * Edit the gateway address of an existing pairing.
 *
 * Pre-filled with the address in use, so the common change (a host moved to a
 * new Tailscale name) is editing one part of a string rather than retyping it.
 * The draft survives rotation through [rememberSaveable].
 */
@Composable
fun GatewayDialog(
    currentUrl: String,
    error: String?,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var url by rememberSaveable(currentUrl) { mutableStateOf(currentUrl) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Gateway") },
        text = {
            Column {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("URL del gateway") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
                error?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(url) }) { Text("Guardar") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancelar") }
        },
    )
}
