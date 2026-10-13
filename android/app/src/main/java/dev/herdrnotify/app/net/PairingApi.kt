package dev.herdrnotify.app.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/**
 * One `POST /v1/pair` request.
 *
 * [code] is either a host-printed pairing code or a recovery code — the two
 * formats never collide, and the gateway tries a pairing code first. A null or
 * blank [code] asks for auto-approval: the gateway checks `tailscale whois` of
 * the source IP against the host's own tailnet owner, and pairs the device only
 * when they match.
 */
data class PairRequest(
    val curve: String,
    val publicKey: String,
    val label: String?,
    val code: String?,
) {
    /**
     * Built by hand rather than with a serialiser so the escape rule is the same
     * one [RequestSigner] uses over the body: the bytes that go out are the
     * bytes the gateway parses. The fields are short and known, and the body cap
     * is 8 KiB.
     */
    fun toJson(): String = buildString {
        append("{\"curve\":").append(curve.asJsonString())
        append(",\"public_key\":").append(publicKey.asJsonString())
        label?.takeIf { it.isNotBlank() }
            ?.let { append(",\"label\":").append(it.asJsonString()) }
        code?.takeIf { it.isNotBlank() }
            ?.let { append(",\"code\":").append(it.asJsonString()) }
        append('}')
    }
}

/** The gateway's answer to a successful pairing. */
data class PairResponse(
    val deviceId: String,
    val curve: String,
    val label: String?,
    val permissions: List<String>,
    val ownerId: String,
    /** Shown once, and only in this response. Null when the gateway did not mint
     * one (it always does on success, so a null here is treated as "none to
     * show", not as a fault). */
    val recoveryCode: String?,
)

/** A refused pairing, with the status that makes the reason distinguishable. */
class PairingException(val status: Int, val detail: String) : IOException("$status: $detail")

/**
 * The one unauthenticated write in the API.
 *
 * It carries the public key of the phone and is answered with the device id the
 * gateway assigned — signed like every other request afterwards. The call is
 * unauthenticated by design, so it does not go through [GatewayClient]: it has
 * nothing to sign with until it has succeeded.
 */
interface PairingApi {
    suspend fun pair(baseUrl: String, request: PairRequest): Result<PairResponse>
}

class HttpPairingApi(
    private val http: OkHttpClient = OkHttpClient.Builder().tailnetCleartextOnly().build(),
) : PairingApi {

    override suspend fun pair(baseUrl: String, request: PairRequest): Result<PairResponse> =
        withContext(Dispatchers.IO) {
            val body = request.toJson().toByteArray(Charsets.UTF_8)
            val httpRequest = Request.Builder()
                .url(baseUrl.trimEnd('/') + "/v1/pair")
                .header("Accept", "application/json")
                .post(body.toRequestBody(GatewayClient.JSON_MEDIA))
                .build()
            val response = try {
                http.newCall(httpRequest).execute()
            } catch (e: IOException) {
                return@withContext Result.failure(
                    PairingException(0, e.message ?: "no se pudo contactar con el equipo"),
                )
            }
            response.use {
                val text = it.body?.string().orEmpty()
                if (it.code == 200) {
                    val parsed = runCatching {
                        Wire.json.decodeFromString<WirePairResponse>(text)
                    }.getOrNull()
                    if (parsed == null || !parsed.ok || parsed.deviceId.isEmpty()) {
                        // A 200 without a device id is not a pairing; treating it
                        // as one would store an id that authenticates as nothing.
                        return@withContext Result.failure(PairingException(200, "respuesta no válida"))
                    }
                    Result.success(parsed.toDomain())
                } else {
                    Result.failure(PairingException(it.code, summarise(text)))
                }
            }
        }
}

@Serializable
private data class WirePairResponse(
    val ok: Boolean = false,
    @SerialName("device_id") val deviceId: String = "",
    val curve: String = "",
    val label: String? = null,
    val permissions: List<String> = emptyList(),
    @SerialName("owner_id") val ownerId: String = "",
    @SerialName("recovery_code") val recoveryCode: String? = null,
) {
    fun toDomain(): PairResponse = PairResponse(
        deviceId = deviceId,
        curve = curve,
        label = label,
        permissions = permissions,
        ownerId = ownerId,
        recoveryCode = recoveryCode,
    )
}
