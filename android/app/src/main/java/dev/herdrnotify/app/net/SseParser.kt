package dev.herdrnotify.app.net

/**
 * Server-sent events, parsed.
 *
 * Written by hand rather than pulled in as a library, because the format the
 * gateway emits is a narrow subset and every extra line of parsing is another
 * place for a stream to hang. The subset is:
 *
 *  * `event:` and `data:` lines, one field each
 *  * `: keepalive` comments, ignored
 *  * a blank line terminates a frame
 *  * a frame with no `data` is a keepalive, not a message
 *
 * The parser is fed lines and returns complete frames, so it has no timeout of
 * its own and never blocks waiting for one. A stream that goes quiet is handled
 * by the caller's watchdog, not by a parser that has decided to wait.
 */
class SseParser {

    private val data = StringBuilder()
    private var event: String? = null

    /** Feed one line. Returns a frame when the line completes one, else null. */
    fun accept(line: String): Frame? {
        // The gateway sends LF only, but tolerating a trailing CR means a proxy
        // that rewrites line endings does not silently break framing.
        val clean = line.removeSuffix("\r")

        when {
            clean.isEmpty() -> {
                if (data.isEmpty()) {
                    // Two blank lines in a row, or a leading one. Nothing was
                    // collected, so there is no frame to emit.
                    event = null
                    return null
                }
                val frame = Frame(
                    event = event ?: DEFAULT_EVENT,
                    data = data.toString(),
                )
                data.setLength(0)
                event = null
                return frame
            }

            clean.startsWith(":") -> {
                // A comment. The gateway's keepalive arrives as `: keepalive`,
                // and it exists purely to stop intermediaries timing the
                // connection out. It carries no state.
                return null
            }

            else -> {
                val colon = clean.indexOf(':')
                if (colon < 0) {
                    // A field name with no value. Per the spec that is a field
                    // with an empty value, which for `data` would append a
                    // newline and corrupt the frame — so it is dropped.
                    return null
                }
                val name = clean.substring(0, colon)
                // A single leading space after the colon is part of the framing
                // and is stripped; any further spaces are content.
                val value = clean.substring(colon + 1).removePrefix(" ")
                when (name) {
                    "event" -> event = value
                    "data" -> {
                        if (data.isNotEmpty()) data.append('\n')
                        data.append(value)
                    }

                    else -> Unit // id, retry, and anything unknown
                }
                return null
            }
        }
    }

    /** Drop any partial frame, so a reconnect does not splice two messages. */
    fun reset() {
        data.setLength(0)
        event = null
    }

    data class Frame(val event: String, val data: String)

    companion object {
        /** What the gateway sends when a message omits the event name. */
        const val DEFAULT_EVENT = "change"
    }
}
