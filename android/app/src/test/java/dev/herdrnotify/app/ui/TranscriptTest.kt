package dev.herdrnotify.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TranscriptTest {

    @Test
    fun `a blank or null tail has no turns`() {
        assertTrue(TranscriptParser.parse(null).isEmpty())
        assertTrue(TranscriptParser.parse("").isEmpty())
        assertTrue(TranscriptParser.parse("   \n  \n").isEmpty())
    }

    @Test
    fun `rules and a bare input line are chrome, not turns`() {
        val tail = """
            ────────────────────────
            ──────────
            ❯
            ──────────
        """.trimIndent()

        assertTrue(TranscriptParser.parse(tail).isEmpty())
    }

    @Test
    fun `a prompt becomes the person's turn`() {
        val entries = TranscriptParser.parse("❯ arregla el scroll de wN:p8")

        assertEquals(listOf(TranscriptEntry.User("arregla el scroll de wN:p8")), entries)
    }

    @Test
    fun `terminal wraps are rejoined but a bullet keeps its own line`() {
        val tail = """
            Sigue activo
            y el pane muestra actividad.
             - wQ:pJ: reenvié la tarea
            y aún no hay resultado.
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(1, entries.size)
        assertEquals(
            "Sigue activo y el pane muestra actividad.\n- wQ:pJ: reenvié la tarea y aún no hay resultado.",
            entries.single().text,
        )
    }

    @Test
    fun `a blank line separates two agent turns`() {
        val tail = """
            Primero.

            Segundo.
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(2, entries.size)
        assertEquals(TranscriptEntry.Agent("Primero."), entries[0])
        assertEquals(TranscriptEntry.Agent("Segundo."), entries[1])
    }

    @Test
    fun `cogitated progress becomes a quiet status row`() {
        val entries = TranscriptParser.parse("✻ Cogitated for 59s · done 11:44")

        assertEquals(
            listOf(TranscriptEntry.Status("Cogitated for 59s · done 11:44", StatusKind.PROGRESS)),
            entries,
        )
    }

    @Test
    fun `recap keeps its text without the prefix`() {
        val entries = TranscriptParser.parse("✻ recap: Objetivo: arreglar el error del TECNO")

        assertEquals(
            listOf(TranscriptEntry.Status("Objetivo: arreglar el error del TECNO", StatusKind.RECAP)),
            entries,
        )
    }

    @Test
    fun `a wrapped permission bar is stitched into one chrome row`() {
        val tail = """
            ⏵⏵ bypass permissions on (shift+tab to
            cycle) · [I] for agents
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(
            listOf(
                TranscriptEntry.Status(
                    "bypass permissions on (shift+tab to cycle) · [I] for agents",
                    StatusKind.CHROME,
                ),
            ),
            entries,
        )
    }

    @Test
    fun `body text that merely mentions interrupt is not chrome`() {
        val entries = TranscriptParser.parse("(\"esc interrupt\", 21.9K de contexto),")

        assertEquals(listOf(TranscriptEntry.Agent("(\"esc interrupt\", 21.9K de contexto),")), entries)
    }

    @Test
    fun `the screenshot tail parses to the expected turns`() {
        val tail = """
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
                delegado a subagentes.

            6% until auto-compact
            ────────────────────────
            ──────────
            ❯
            ──────────
              ⏵⏵ bypass permissions on (shift+tab to
            cycle) · [I] for agents
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(6, entries.size)
        assertEquals(
            "Sigue activo (\"esc interrupt\", 21.9K de contexto), pero todavía no hay BUGFIX.md.\n" +
                "- wQ:pJ (scroll-meas): reenvié la tarea y el pane muestra actividad " +
                "(\"esc interrupt\", 32.3K de contexto). Todavía no he visto sus comandos ni resultados.",
            entries[0].text,
        )
        assertEquals(
            "Ninguno ha devuelto resultados. Hasta que lo hagan no daré nada por hecho. " +
                "Reviso sus panes en el siguiente paso.",
            entries[1].text,
        )
        assertEquals(TranscriptEntry.Status("Cogitated for 59s · done 11:44", StatusKind.PROGRESS), entries[2])
        assertEquals(
            TranscriptEntry.Status(
                "Objetivo: arreglar el error \"No se pudo leer la salida del agente\" en el TECNO " +
                    "y medir el scroll de wN:p8, todo delegado a subagentes.",
                StatusKind.RECAP,
            ),
            entries[3],
        )
        assertEquals(TranscriptEntry.Status("6% until auto-compact", StatusKind.PROGRESS), entries[4])
        assertEquals(
            TranscriptEntry.Status(
                "bypass permissions on (shift+tab to cycle) · [I] for agents",
                StatusKind.CHROME,
            ),
            entries[5],
        )
    }

    @Test
    fun `the opencode sidebar and footer are dropped, the agent's words survive`() {
        // The exact shape of the tail that exposed the noise: opencode paints an
        // MCP/LSP sidebar and a Build/context footer beside and under the
        // conversation, so the rendered pane interleaves them with the agent's
        // own sentences.
        val tail = """
            • github Disabled
                Tests: pytest 271 passed / 3
            deselected; ruff All checks passed;
            android
            • huggingface Disabled
                markSeen tests BUILD SUCCESSFUL.
            • playwright Disabled

            • sentry Disabled
                Deploy: gateway reiniciado sobre el
            código actual (8787, devices:9), APK
            • smart-terminal Disabled
                debug reinstalado en el TECNO. Trust
            store limpiado (dispositivos de
                prueba revocados/eliminados). Sin
            commits/push; release hn-cccccccc
            LSP
                intacto; no se escribió a wN:p8.
            • pyright gateway

                ⬒ Build · DeepSeek V4.1 Flash · 9m
            32s

                │
                │
                │
            D:\Documentos\Projects\herdr-notify:
                │
                Build · DeepSeek V4.1 Flash OpenCode
            Go
            chore/publishable-tree

            ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁
            ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁
            ▁▁▁▁▁▁▁▁▁

                D:\Documentos\Projects\herdr-notify
            251.5K (25%) · $0.18  ctrl+p commands
            • OpenCode 1.19.0
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)
        val everything = entries.joinToString("\n") { it.text }

        // None of the sidebar/footer chrome may reach the conversation.
        listOf(
            "Disabled", "Connected", "· Build", "ctrl+p commands",
            "OpenCode 1.19.0", "LSP", "MCP", "Context",
        ).forEach { noise ->
            assertTrue("chrome leaked into the chat: $noise", !everything.contains(noise))
        }
        // The agent's own sentences are still there, de-wrapped and in order.
        assertTrue(everything.contains("pytest 271 passed"))
        assertTrue(everything.contains("BUILD SUCCESSFUL"))
        assertTrue(everything.contains("Deploy: gateway reiniciado"))
        assertTrue(everything.contains("no se escribió a wN:p8"))
    }

    @Test
    fun `a tail of pure opencode sidebar is not a conversation`() {
        val tail = """
            MCP
            • github Disabled
            • huggingface Disabled
            LSP
            • pyright gateway
            ⬒ Build · DeepSeek V4.1 Flash · 9m 32s
            │
            ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁
            D:\Documentos\Projects\herdr-notify
            251.5K (25%) · $0.18  ctrl+p commands
            • OpenCode 1.19.0
        """.trimIndent()

        assertTrue(TranscriptParser.parse(tail).isEmpty())
    }

    @Test
    fun `the opencode permission dialog becomes an answerable card`() {
        val tail = """
            ⚠ Permission required
             ↳ Access external directory C:\Users\example\.herdr-leads\herdr-notify

             Patterns

             - C:\Users\example\.herdr-leads\herdr-notify\*

             Allow once    Allow always    Reject    ctrl+f fullscreen
            ⇥ select  enter confirm
        """.trimIndent()

        val entry = TranscriptParser.parse(tail).single()
        assertTrue("expected a permission card, got $entry", entry is TranscriptEntry.Permission)
        val prompt = (entry as TranscriptEntry.Permission).prompt

        assertEquals(PermissionKind.OPENCODE, prompt.kind)
        assertTrue("the card must say what is being granted", prompt.detail!!.contains("Access external directory"))
        assertEquals(
            listOf("Permitir una vez", "Permitir siempre", "Rechazar"),
            prompt.options.map { it.label },
        )
        // left/right move the highlight, enter chooses; the second answer widens
        // access for good and so is the one that asks again.
        assertEquals(listOf("enter"), prompt.options[0].keys)
        assertEquals(listOf("right", "enter"), prompt.options[1].keys)
        assertEquals(listOf("right", "right", "enter"), prompt.options[2].keys)
        assertTrue("Permitir siempre must be confirmed", prompt.options[1].confirm)
        assertTrue(!prompt.options[0].confirm && !prompt.options[2].confirm)
    }

    @Test
    fun `the Claude Code permission dialog becomes a card answered by number`() {
        val tail = """
            Do you want to proceed?

            ❯ 1. Yes
              2. Yes, and don't ask again for bash commands in D:\dev
              3. No, and tell Claude what to do differently (esc)
        """.trimIndent()

        val entry = TranscriptParser.parse(tail).single()
        assertTrue("expected a permission card, got $entry", entry is TranscriptEntry.Permission)
        val prompt = (entry as TranscriptEntry.Permission).prompt

        assertEquals(PermissionKind.CLAUDE_CODE, prompt.kind)
        assertTrue(prompt.detail!!.contains("Do you want to proceed"))
        assertEquals(listOf("1"), prompt.options[0].keys)
        assertEquals(listOf("2"), prompt.options[1].keys)
        assertEquals(listOf("3"), prompt.options[2].keys)
        assertTrue("don't ask again must be confirmed", prompt.options[1].confirm)
    }

    @Test
    fun `a permission card keeps the agent turn that preceded it`() {
        val tail = """
            Voy a leer el directorio.

            ⚠ Permission required
             ↳ Access external directory C:\Users\example\.herdr-leads\herdr-notify

             Allow once    Allow always    Reject

            (esperando…)
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)
        assertEquals(3, entries.size)
        assertEquals(TranscriptEntry.Agent("Voy a leer el directorio."), entries[0])
        assertTrue(entries[1] is TranscriptEntry.Permission)
        assertEquals(TranscriptEntry.Agent("(esperando…)"), entries[2])
    }

    @Test
    fun `a unified diff becomes a changes block, not prose`() {
        val tail = """
            Voy a aplicar el cambio.

            --- a/src/foo.kt
            +++ b/src/foo.kt
            @@ -1,3 +1,3 @@
             fun main() {
            -    old()
            +    new()
             }
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(2, entries.size)
        assertEquals(TranscriptEntry.Agent("Voy a aplicar el cambio."), entries[0])
        val changes = entries[1] as TranscriptEntry.Changes
        assertTrue(
            "an added diff line must be marked as added: ${changes.lines}",
            changes.lines.any { it.kind == ChangeKind.ADDED && it.text == "+    new()" },
        )
        assertTrue(
            "a removed diff line must be marked as removed: ${changes.lines}",
            changes.lines.any { it.kind == ChangeKind.REMOVED && it.text == "-    old()" },
        )
        assertTrue(
            "the hunk header is metadata, not a change: ${changes.lines}",
            changes.lines.any { it.kind == ChangeKind.META && it.text.startsWith("@@") },
        )
    }

    @Test
    fun `a prose bullet is not mistaken for a diff`() {
        val entries = TranscriptParser.parse(" - wQ:pJ: reenvié la tarea\n - wN:p8: sin resultado")

        assertEquals(1, entries.size)
        assertTrue(entries.single() is TranscriptEntry.Agent)
    }

    @Test
    fun `a fenced block becomes a code entry, not prose`() {
        val tail = """
            Aquí va el ejemplo:

            ```kotlin
            val x = 1
            // nota
            ```

            Fin.
        """.trimIndent()

        val entries = TranscriptParser.parse(tail)

        assertEquals(3, entries.size)
        assertEquals(TranscriptEntry.Agent("Aquí va el ejemplo:"), entries[0])
        assertEquals(TranscriptEntry.Code("kotlin", "val x = 1\n// nota"), entries[1])
        assertEquals(TranscriptEntry.Agent("Fin."), entries[2])
    }

    @Test
    fun `a fence with no language keeps its body verbatim`() {
        val tail = "```\nline that the pane would have wrapped here\n```"

        assertEquals(
            TranscriptEntry.Code(null, "line that the pane would have wrapped here"),
            TranscriptParser.parse(tail).single(),
        )
    }

    @Test
    fun `an unterminated fence degrades to text rather than swallowing the tail`() {
        val entries = TranscriptParser.parse("antes\n```kotlin\nval x = 1")

        assertTrue("an unterminated fence must not become a code card", entries.none { it is TranscriptEntry.Code })
    }
}
