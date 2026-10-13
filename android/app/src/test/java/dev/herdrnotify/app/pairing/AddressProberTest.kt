package dev.herdrnotify.app.pairing

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class AddressProberTest {

    private lateinit var first: MockWebServer
    private lateinit var second: MockWebServer
    private val prober = AddressProber(timeoutMs = 1_500)

    @Before
    fun setUp() {
        first = MockWebServer().apply { start() }
        second = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        first.shutdown()
        second.shutdown()
    }

    private fun MockWebServer.healthy() = enqueue(MockResponse().setBody("""{"ok":true}"""))

    private fun MockWebServer.url2() = "http://127.0.0.1:$port"

    @Test
    fun `earlier candidate wins even when a later one answers first`() = runBlocking {
        first.enqueue(MockResponse().setBody("""{"ok":true}""").setBodyDelay(300, TimeUnit.MILLISECONDS))
        second.healthy()

        val picked = prober.firstHealthy(listOf(first.url2(), second.url2()))

        assertEquals(first.url2(), picked)
    }

    @Test
    fun `a refused address is skipped for the next healthy one`() = runBlocking {
        second.healthy()

        val picked = prober.firstHealthy(listOf("http://127.0.0.1:1", second.url2()))

        assertEquals(second.url2(), picked)
    }

    @Test
    fun `a host that answers ok false does not count`() = runBlocking {
        first.enqueue(MockResponse().setBody("""{"ok":false}"""))

        assertNull(prober.firstHealthy(listOf(first.url2())))
    }

    @Test
    fun `a hanging address is cut off and the healthy one still wins`() = runBlocking {
        // Twice the 1500ms probe bound, short enough that MockWebServer.shutdown() in tearDown can drain it.
        first.enqueue(MockResponse().setBody("""{"ok":true}""").setBodyDelay(3, TimeUnit.SECONDS))
        second.healthy()

        val started = System.nanoTime()
        val picked = prober.firstHealthy(listOf(first.url2(), second.url2()))
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)

        // The hanging one is first in priority, so it must be given up on, not waited for.
        assertEquals(second.url2(), picked)
        assertTrue("took ${elapsedMs}ms, expected under the 1500ms probe bound", elapsedMs < 2_500)
    }

    @Test
    fun `nothing answering returns null within the bound`() = runBlocking {
        val started = System.nanoTime()
        val picked = prober.firstHealthy(listOf("http://127.0.0.1:1", "http://127.0.0.1:2"))
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)

        assertNull(picked)
        assertTrue("took ${elapsedMs}ms", elapsedMs < 2_500)
    }

    @Test
    fun `no candidates means no probe and no answer`() = runBlocking {
        assertNull(prober.firstHealthy(emptyList()))
        assertNull(prober.firstHealthy(listOf("", "   ")))
        assertEquals(0, first.requestCount)
    }

    @Test
    fun `duplicate candidates are probed once`() = runBlocking {
        first.healthy()

        val picked = prober.firstHealthy(listOf(first.url2(), first.url2() + "/"))

        assertEquals(first.url2(), picked)
        assertEquals(1, first.requestCount)
    }
}
