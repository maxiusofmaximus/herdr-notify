package dev.herdrnotify.app.ui.triage

import dev.herdrnotify.app.domain.AgentStatus
import dev.herdrnotify.app.domain.AgentSummary
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.net.GatewayClient
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * "Nueva conversación" and image attachments, the two flows added around the
 * chat.
 *
 * Both are about a person standing in front of a button and being told the
 * truth: a created conversation opens rather than leaving them on the form, and
 * an image that cannot go says so instead of quietly discarding the message.
 */
class NewChatAndAttachmentTest {

    private fun agent(paneId: String, status: AgentStatus) = AgentSummary(
        paneId = paneId,
        workspaceId = paneId.substringBefore(':'),
        project = "proj",
        agent = "opencode",
        status = status,
        attention = if (status == AgentStatus.BLOCKED) 3 else 1,
        title = "t",
        cwd = "C:\\dev\\proj",
        focused = false,
        canResume = true,
    )

    private fun stateWith(vararg agents: AgentSummary) = SessionState(
        revision = 1,
        herdrVersion = "0.9.1",
        agents = agents.toList(),
        counts = emptyMap(),
    )

    @Test
    fun `creating a conversation opens the pane the host returned`() = runTest {
        val repo = FakeTriageRepository()
        repo.newChatResult = Result.success("w9:p1")
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onOpenNewChat()
        assertTrue(vm.newChat.value.open)

        vm.onNewChat("arreglar el login")
        runCurrent()

        assertEquals(listOf("arreglar el login"), repo.newChats)
        assertEquals("the created pane opens", "w9:p1", vm.detail.value?.paneId)
        assertFalse("the form closes once the chat opens", vm.newChat.value.open)
    }

    @Test
    fun `a host refusal keeps the form open and says why`() = runTest {
        val repo = FakeTriageRepository()
        repo.newChatResult = Result.failure(GatewayClient.GatewayError.NotPermitted("forbidden"))
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onNewChat("x")
        runCurrent()

        assertNull("no chat is opened on failure", vm.detail.value)
        assertTrue(vm.newChat.value.open)
        assertEquals(
            "Este teléfono no tiene permiso para crear conversaciones",
            vm.newChat.value.error,
        )
    }

    @Test
    fun `a create with no pane id is reported rather than silently ignored`() = runTest {
        val repo = FakeTriageRepository()
        repo.newChatResult = Result.success(null)
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onNewChat("x")
        runCurrent()

        assertNull(vm.detail.value)
        assertEquals(
            "El equipo creó la conversación pero no devolvió el panel.",
            vm.newChat.value.error,
        )
    }

    @Test
    fun `a blank name is refused without calling the host`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)

        vm.onNewChat("   ")
        runCurrent()

        assertTrue(repo.newChats.isEmpty())
        assertNotNull(vm.newChat.value.error)
    }

    @Test
    fun `sending with an attachment sends the image then the text`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("mira esto")

        vm.onAttachImage(ByteArray(10) { 1 }, "image/png")
        assertEquals("image/png", vm.detail.value!!.attachment?.mime)

        vm.onSend()
        runCurrent()

        assertEquals(
            listOf(Triple("w1:p1", 10, "image/png")),
            repo.images,
        )
        assertEquals(listOf("w1:p1" to "mira esto"), repo.replies)
        assertNull("a sent attachment is cleared with the draft", vm.detail.value!!.attachment)
    }

    @Test
    fun `an unsupported image is refused at pick time`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")

        vm.onAttachImage(ByteArray(10), "application/zip")

        assertNull(vm.detail.value!!.attachment)
        assertEquals("Ese formato de imagen no es compatible.", vm.detail.value!!.notice)
    }

    @Test
    fun `a refused image stops the text too and keeps the draft`() = runTest {
        val repo = FakeTriageRepository()
        repo.sendImageResult = Result.failure(UnsupportedOperationException("no endpoint"))
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("texto")
        vm.onAttachImage(ByteArray(10), "image/png")

        vm.onSend()
        runCurrent()

        assertTrue("nothing goes if its image cannot", repo.replies.isEmpty())
        assertEquals(
            "Este gateway todavía no admite imágenes.",
            vm.detail.value!!.notice,
        )
        assertEquals("the text is kept so it is not lost", "texto", vm.detail.value!!.draft)
        assertNotNull("the image is kept too, so a retry can carry it", vm.detail.value!!.attachment)
    }

    @Test
    fun `sending without an attachment does not call the image path`() = runTest {
        val repo = FakeTriageRepository()
        val vm = TriageViewModel(repo, backgroundScope)
        repo.emit(ConnectionState.Live(stateWith(agent("w1:p1", AgentStatus.BLOCKED))))
        vm.onOpenAgent("w1:p1")
        vm.onDraftChange("hola")

        vm.onSend()
        runCurrent()

        assertTrue(repo.images.isEmpty())
        assertEquals(listOf("w1:p1" to "hola"), repo.replies)
    }
}
