package dev.herdrnotify.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import dev.herdrnotify.app.ui.triage.NewChatState
import dev.herdrnotify.app.ui.theme.Spacing

/**
 * Start a fresh conversation: one workspace, one opencode agent on the host.
 *
 * This is the "master" entry point — the place a person goes when the phone has
 * nothing to triage and they want to *begin* work rather than answer it. It is a
 * screen, not a one-line dialog, because it needs to explain what it will do on
 * the computer, show a create in flight, and report a host refusal without the
 * message being dismissed by an accidental tap outside.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewConversationScreen(
    state: NewChatState,
    onCreate: (String) -> Unit,
    onBack: () -> Unit,
    onDismissError: () -> Unit,
) {
    BackHandler(onBack = onBack)
    var name by rememberSaveable { mutableStateOf("") }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Nueva conversación") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Volver a la lista",
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
    ) { insets ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(insets)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacing.lg, vertical = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            Text(
                text = "Se creará un espacio de trabajo nuevo en el equipo y " +
                    "arrancará un agente de opencode en él. Después podrás " +
                    "hablarle desde aquí.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            OutlinedTextField(
                value = name,
                onValueChange = { name = it.take(64) },
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.creating,
                label = { Text("Nombre") },
                placeholder = { Text("p. ej. arreglar el login") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            )

            state.error?.let { message ->
                NoticeCard(
                    message = message,
                    title = "No se pudo crear la conversación",
                    actions = buildList {
                        if (name.isNotBlank() && !state.creating) {
                            add(NoticeAction("Reintentar") { onCreate(name) })
                        }
                        add(NoticeAction("Descartar", onDismissError))
                    },
                )
            }

            Button(
                onClick = { onCreate(name) },
                modifier = Modifier.fillMaxWidth(),
                enabled = name.isNotBlank() && !state.creating,
            ) {
                Text(if (state.creating) "Creando…" else "Crear conversación")
            }

            Spacer(Modifier.height(Spacing.xs))
        }
    }
}
