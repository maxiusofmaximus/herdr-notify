package dev.herdrnotify.app.ui

import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.domain.SessionState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The header light's contract: each connection state maps to its own light, so
 * the header never shows green for a host that is away.
 */
class ConnectionIndicatorTest {

    @Test
    fun `live is the live light`() {
        val indicator = connectionIndicator(ConnectionState.Live(SessionState.EMPTY))

        assertEquals(ConnectionLight.LIVE, indicator.light)
        assertEquals("En línea", indicator.label)
    }

    @Test
    fun `offline keeps its own light, distinct from an error`() {
        val offline = connectionIndicator(ConnectionState.Offline(SessionState.EMPTY, "gone"))
        val failed = connectionIndicator(ConnectionState.Failed("boom", recoverable = false))

        assertEquals(ConnectionLight.OFFLINE, offline.light)
        assertEquals(ConnectionLight.ERROR, failed.light)
    }

    @Test
    fun `connecting and unpaired are their own lights`() {
        assertEquals(ConnectionLight.CONNECTING, connectionIndicator(ConnectionState.Connecting).light)
        assertEquals(ConnectionLight.UNPAIRED, connectionIndicator(ConnectionState.Unpaired).light)
    }
}
