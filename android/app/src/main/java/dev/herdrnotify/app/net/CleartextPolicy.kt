package dev.herdrnotify.app.net

import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import java.io.IOException

object TailnetCleartext {

    fun isAllowedHost(host: String): Boolean {
        val h = host.trim().trimEnd('.').removePrefix("[").removeSuffix("]").lowercase()
        if (h.isEmpty()) return false
        if (h == "localhost" || h == "10.0.2.2") return true
        if (isLoopbackIp(h)) return true
        if (h.endsWith(".ts.net")) return true
        if (isTailnetIp(h)) return true
        if (!h.contains('.')) return true
        return false
    }

    fun isCleartextAllowed(url: HttpUrl): Boolean =
        url.scheme != "http" || isAllowedHost(url.host)

    private fun isLoopbackIp(host: String): Boolean =
        host == "::1" || host.startsWith("127.")

    private fun isTailnetIp(host: String): Boolean {
        val parts = host.split('.')
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() }
        if (octets.any { it == null || it !in 0..255 }) return false
        val first = octets[0]!!
        val second = octets[1]!!
        return first == 100 && second in 64..127
    }
}

class TailnetCleartextInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val url = chain.request().url
        if (!TailnetCleartext.isCleartextAllowed(url)) {
            throw IOException("cleartext HTTP is not allowed for ${url.host}")
        }
        return chain.proceed(chain.request())
    }
}

fun OkHttpClient.Builder.tailnetCleartextOnly(): OkHttpClient.Builder =
    addInterceptor(TailnetCleartextInterceptor())
