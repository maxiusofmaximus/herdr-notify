package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.Wire
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable

data class TailnetPeer(
    val name: String,
    val addresses: List<String>,
    val online: Boolean,
)

class PeersUnavailable : java.io.IOException("tailnet unavailable")

interface PeersDirectory {
    suspend fun peers(baseUrl: String): Result<List<TailnetPeer>>
}

class SignedPeersDirectory(
    private val client: (String) -> GatewayClient?,
) : PeersDirectory {

    override suspend fun peers(baseUrl: String): Result<List<TailnetPeer>> =
        withContext(Dispatchers.IO) {
            val signed = client(baseUrl) ?: return@withContext Result.failure(PeersUnavailable())
            runCatching { parsePeers(signed.call("GET", "/v1/peers")) }
                .recoverCatching { error ->
                    if (error is GatewayClient.GatewayError.Rejected && error.code == 503) {
                        throw PeersUnavailable()
                    }
                    throw error
                }
        }
}

internal fun parsePeers(body: String): List<TailnetPeer> =
    runCatching {
        Wire.json.decodeFromString<WirePeersResponse>(body).peers.mapNotNull { it.toDomain() }
    }.getOrDefault(emptyList())

@Serializable
private data class WirePeersResponse(
    val peers: List<WirePeer> = emptyList(),
)

@Serializable
private data class WirePeer(
    val name: String = "",
    val addresses: List<String> = emptyList(),
    val online: Boolean = false,
) {
    fun toDomain(): TailnetPeer? {
        val host = addresses.firstOrNull()?.takeIf { it.isNotBlank() } ?: return null
        val label = name.takeIf { it.isNotBlank() } ?: host
        return TailnetPeer(name = label, addresses = addresses, online = online)
    }
}
