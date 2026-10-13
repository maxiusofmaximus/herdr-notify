package dev.herdrnotify.app.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The SSE subset the gateway actually emits.
 *
 * A parser bug here is not a crash: it is a stream that appears to work while
 * silently dropping the one event the user is waiting for. So the cases here are
 * the ones that would each produce a plausible-looking but wrong frame —
 * a frame spanning a read boundary, a keepalive mistaken for a message, a
 * multi-line data field split in half.
 */
class SseParserTest {

    private val parser = SseParser()

    private fun feed(vararg lines: String): List<SseParser.Frame> =
        lines.mapNotNull { parser.accept(it) }

    @Test
    fun `a simple state frame parses`() {
        val frames = feed(
            "event: state",
            """data: {"event":"state","revision":7,"state":{"revision":7}}""",
            "",
        )
        assertEquals(1, frames.size)
        assertEquals("state", frames[0].event)
        assertTrue(frames[0].data.contains("\"revision\":7"))
    }

    @Test
    fun `two frames in one read are two frames`() {
        val frames = feed(
            "event: state",
            """data: {"revision":1}""",
            "",
            "event: change",
            """data: {"revision":2}""",
            "",
        )
        assertEquals(2, frames.size)
        assertEquals(1L, Wire.revision(frames[0].data))
        assertEquals(2L, Wire.revision(frames[1].data))
    }

    @Test
    fun `a keepalive comment is ignored and does not emit a frame`() {
        val frames = feed(
            ": keepalive",
            "",
            ": keepalive",
            "",
        )
        assertEquals(0, frames.size)
    }

    @Test
    fun `a comment between fields does not break the frame`() {
        val frames = feed(
            "event: state",
            ": a comment mid-frame",
            """data: {"revision":3}""",
            "",
        )
        assertEquals(1, frames.size)
        assertEquals("state", frames[0].event)
        assertEquals(3L, Wire.revision(frames[0].data))
    }

    @Test
    fun `multi line data is rejoined with newlines`() {
        // The spec says repeated data lines join with \n. A gateway that wraps a
        // long JSON body at 80 columns would break the app if this were dropped.
        val frames = feed(
            "event: state",
            "data: {\"a\":1,",
            """data: "b":2}""",
            "",
        )
        assertEquals(1, frames.size)
        // Per the SSE spec repeated data lines are joined with \n. That newline
        // is part of the payload, which is why it is asserted rather than
        // assumed: dropping it would turn `{"a":1,` + `"b":2}` into invalid
        // JSON, and a gateway that wraps long bodies at 80 columns would then
        // break the app in a way that looks like a server bug.
        assertEquals("{\"a\":1,\n\"b\":2}", frames[0].data)
    }

    @Test
    fun `a frame with no event name defaults to change`() {
        val frames = feed(
            """data: {"revision":4}""",
            "",
        )
        assertEquals(1, frames.size)
        assertEquals(SseParser.DEFAULT_EVENT, frames[0].event)
    }

    @Test
    fun `an empty data field does not emit a frame`() {
        // A bare `data:` with no value would otherwise produce an empty frame
        // that decodes to nothing and is treated as a state refresh.
        val frames = feed(
            "event: state",
            "data:",
            "",
        )
        assertEquals(0, frames.size)
    }

    @Test
    fun `only the first space after the colon is stripped`() {
        val frames = feed(
            "event: state",
            "data:  two leading spaces",
            "",
        )
        assertEquals(" two leading spaces", frames[0].data)
    }

    @Test
    fun `CRLF line endings still frame correctly`() {
        val frames = feed(
            "event: state\r",
            "data: {\"revision\":5}\r",
            "\r",
        )
        assertEquals(1, frames.size)
        assertEquals(5L, Wire.revision(frames[0].data))
    }

    @Test
    fun `an unknown field is ignored rather than ending the frame`() {
        val frames = feed(
            "id: 42",
            "event: state",
            "retry: 3000",
            """data: {"revision":6}""",
            "",
        )
        assertEquals(1, frames.size)
        assertEquals(6L, Wire.revision(frames[0].data))
    }

    @Test
    fun `reset drops a partial frame so a reconnect cannot splice two messages`() {
        parser.accept("event: state")
        parser.accept("""data: {"revision":1}""")
        // No terminating blank line: the stream dropped mid-frame.
        parser.reset()

        val frames = feed(
            "event: state",
            """data: {"revision":2}""",
            "",
        )
        // If reset had not cleared the buffer, the first field would be
        // `{"revision":1}\n{"revision":2}` and the frame would be unusable.
        assertEquals(1, frames.size)
        assertEquals(2L, Wire.revision(frames[0].data))
    }

    @Test
    fun `revision returns null for a frame without one rather than zero`() {
        // Zero is a valid revision. Collapsing "absent" onto it would make an
        // out-of-order check discard or accept the wrong frames.
        assertNull(Wire.revision("""{"event":"ping"}"""))
        assertNull(Wire.revision("not json at all"))
        assertEquals(0L, Wire.revision("""{"revision":0}"""))
    }
}
