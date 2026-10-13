package dev.herdrnotify.app.net

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CleartextPolicyTest {

    @Test
    fun `loopback and the emulator alias may use cleartext`() {
        assertTrue(TailnetCleartext.isCleartextAllowed("http://127.0.0.1:8787".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://localhost:8787".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://10.0.2.2:8787".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://[::1]:8787".toHttpUrl()))
    }

    @Test
    fun `tailnet ips, ts net names and magicdns names may use cleartext`() {
        assertTrue(TailnetCleartext.isCleartextAllowed("http://100.64.0.1:8788".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://100.127.255.254:8788".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://pc.tailnet.ts.net:8788".toHttpUrl()))
        assertTrue(TailnetCleartext.isCleartextAllowed("http://mi-pc:8788".toHttpUrl()))
    }

    @Test
    fun `public and plain lan hosts may not use cleartext`() {
        assertFalse(TailnetCleartext.isCleartextAllowed("http://example.com/".toHttpUrl()))
        assertFalse(TailnetCleartext.isCleartextAllowed("http://192.168.1.10:8787".toHttpUrl()))
        assertFalse(TailnetCleartext.isCleartextAllowed("http://10.1.2.3:8787".toHttpUrl()))
        assertFalse(TailnetCleartext.isCleartextAllowed("http://100.63.0.1:8787".toHttpUrl()))
        assertFalse(TailnetCleartext.isCleartextAllowed("http://100.128.0.1:8787".toHttpUrl()))
    }

    @Test
    fun `https is always allowed`() {
        assertTrue(TailnetCleartext.isCleartextAllowed("https://example.com/".toHttpUrl()))
    }
}
