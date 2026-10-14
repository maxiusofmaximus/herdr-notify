package dev.herdrnotify.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.ui.AgentDetailScreen
import dev.herdrnotify.app.ui.theme.HerdrNotifyTheme
import dev.herdrnotify.app.ui.triage.AgentDetail

/**
 * Debug-only: renders the agent chat against a fixed pane tail.
 *
 * The gateway needs a live herdr agent to stream a real tail, which a UI pass
 * often does not have. This entry point draws the *real* [AgentDetailScreen]
 * with representative data so the composer, the insets and the transcript can be
 * inspected on a device. It exists in the debug build only.
 *
 * Launch: `adb shell am start -n <applicationId>/dev.herdrnotify.app.ChatPreviewActivity`
 */
class ChatPreviewActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            HerdrNotifyTheme {
                AgentDetailScreen(
                    agent = AgentSummary(
                        paneId = "wQ:pM",
                        workspaceId = "wQ",
                        project = "herdr-notify",
                        agent = "opencode",
                        status = AgentStatus.WORKING,
                        attention = 1,
                        title = "Project Lead de herdr-notify",
                        cwd = "C:\\dev\\herdr-notify",
                        focused = false,
                        canResume = true,
                    ),
                    detail = AgentDetail(paneId = "wQ:pM", output = SAMPLE_TAIL),
                    onBack = {},
                    onRefresh = {},
                    onDraftChange = {},
                    onSend = {},
                    onConfirmSend = {},
                    onDismissConfirm = {},
                    onPermissionKeys = { _, _ -> },
                    onStop = {},
                    onConfirmStop = {},
                    onDismissStop = {},
                    onAttachImage = { _, _ -> },
                    onClearAttachment = {},
                )
            }
        }
    }

    private companion object {
        /** The exact tail that exposed the noise and the covered composer. */
        val SAMPLE_TAIL = """
            Sigue activo
                ("esc interrupt", 21.9K de contexto),
            pero todavía no hay BUGFIX.md.
             - wQ:pJ (scroll-meas): reenvié la tarea
            y el pane muestra actividad ("esc
            interrupt", 32.3K de contexto). Todavía
            no he
                visto sus comandos ni resultados.

            Ninguno ha devuelto resultados. Hasta
            que lo hagan no daré nada por hecho.
            Reviso sus panes en el siguiente paso.

            ✻ Cogitated for 59s · done 11:44

            ✻ recap: Objetivo: arreglar el error "No
            se pudo leer la salida del agente" en el
            TECNO y medir el scroll de wN:p8, todo
                delegado a subagentes. Ahora bug-fixer
            (wQ:pH) y scroll-meas (wQ:pJ) están
            trabajando; lo siguiente es leer sus
            panes y
                recoger los resúmenes. (disable recaps
            in /config)

            6% until auto-compact
            ────────────────────────
            ────────────────────────
            ──────────
            ❯
            ────────────────────────
            ────────────────────────
            ──────────
              ⏵⏵ bypass permissions on (shift+tab to
            cycle) · [I] for agents
        """.trimIndent()
    }
}
