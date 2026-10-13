package dev.herdrnotify.app.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PeersTest {

    private val body = """
        {
          "backend_state": "Running",
          "self": {"name": "host", "addresses": ["100.64.0.1"], "online": true},
          "peers": [
            {"name": "pc", "addresses": ["100.64.0.2"], "online": true, "os": "windows", "owner_id": "u1"},
            {"name": "phone", "addresses": ["100.64.0.3"], "online": false, "os": "android", "owner_id": "u1"},
            {"name": "tagged", "addresses": [], "online": true}
          ]
        }
    """.trimIndent()

    @Test
    fun `peers decode to name, address and online state`() {
        val peers = parsePeers(body)

        assertEquals(listOf("pc", "phone"), peers.map { it.name })
        assertEquals(listOf("100.64.0.2"), peers[0].addresses)
        assertTrue(peers[0].online)
        assertTrue(!peers[1].online)
    }

    @Test
    fun `a peer with no address is dropped, since it cannot be reached`() {
        assertTrue(parsePeers(body).none { it.name == "tagged" })
    }

    @Test
    fun `a malformed body yields no peers rather than throwing`() {
        assertTrue(parsePeers("not json").isEmpty())
    }
}
