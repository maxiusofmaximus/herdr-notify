package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.Wire
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One device in the gateway's trust store, as `GET /v1/devices` reports it.
 *
 * Public material only: the gateway never returns a public key or a push token,
 * so nothing here is a secret.
 */
data class DeviceInfo(
    val deviceId: String,
    val curve: String,
    val label: String?,
    val ownerId: String,
    /** Epoch seconds, as the gateway reports them. */
    val createdAt: Double,
    val lastSeenAt: Double,
    val revoked: Boolean,
    val permissions: List<String>,
) {
    val isActive: Boolean get() = !revoked
}

/**
 * "Mis dispositivos": list and revoke.
 *
 * Revoking is a deliberate act against the host's trust store, so the outcome is
 * returned rather than swallowed: a 403 (no `admin`) and a 404 (unknown id) are
 * different answers the screen has to be able to state.
 */
interface DeviceDirectory {
    suspend fun list(): Result<List<DeviceInfo>>
    suspend fun revoke(deviceId: String): Result<Unit>
}

/**
 * The signed implementation.
 *
 * The client is a provider rather than an instance because the device list must
 * follow a re-pair: after `device_id` or the address changes, the next call has
 * to sign as the new identity, not the one captured when the screen opened.
 */
class SignedDeviceDirectory(
    private val client: () -> GatewayClient?,
) : DeviceDirectory {

    override suspend fun list(): Result<List<DeviceInfo>> = withContext(Dispatchers.IO) {
        val signed = client() ?: return@withContext Result.failure(
            IllegalStateException("sin conexión con el equipo"),
        )
        runCatching { parseDevices(signed.call("GET", "/v1/devices")) }
    }

    override suspend fun revoke(deviceId: String): Result<Unit> = withContext(Dispatchers.IO) {
        val signed = client() ?: return@withContext Result.failure(
            IllegalStateException("sin conexión con el equipo"),
        )
        // A device id is a `dev-<hex>` segment: the hyphen is safe unencoded, and
        // the target is signed exactly as written, so encoding it would be a
        // signature mismatch, not a safer call.
        runCatching { signed.call("POST", "/v1/devices/$deviceId/revoke") }.map { }
    }

    private fun parseDevices(body: String): List<DeviceInfo> =
        Wire.json.decodeFromString<WireDevicesResponse>(body).devices.map { it.toDomain() }
}

@Serializable
private data class WireDevicesResponse(
    val ok: Boolean = false,
    val devices: List<WireDevice> = emptyList(),
)

@Serializable
private data class WireDevice(
    @SerialName("device_id") val deviceId: String = "",
    val curve: String = "",
    val label: String? = null,
    @SerialName("owner_id") val ownerId: String = "",
    @SerialName("created_at") val createdAt: Double = 0.0,
    @SerialName("last_seen_at") val lastSeenAt: Double = 0.0,
    val revoked: Boolean = false,
    val permissions: List<String> = emptyList(),
) {
    fun toDomain(): DeviceInfo = DeviceInfo(
        deviceId = deviceId,
        curve = curve,
        label = label,
        ownerId = ownerId,
        createdAt = createdAt,
        lastSeenAt = lastSeenAt,
        revoked = revoked,
        permissions = permissions,
    )
}
