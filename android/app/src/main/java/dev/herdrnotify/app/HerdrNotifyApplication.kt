package dev.herdrnotify.app

import android.app.Application
import android.content.Context
import dev.herdrnotify.app.net.GatewayClient
import dev.herdrnotify.app.net.HttpPairingApi
import dev.herdrnotify.app.net.PairingApi
import dev.herdrnotify.app.net.RequestSigner
import dev.herdrnotify.app.pairing.DeviceDirectory
import dev.herdrnotify.app.pairing.EncryptedRecoveryCodeStore
import dev.herdrnotify.app.pairing.GatewayAddress
import dev.herdrnotify.app.pairing.GatewayTriageRepository
import dev.herdrnotify.app.pairing.PairingStore
import dev.herdrnotify.app.pairing.PeersDirectory
import dev.herdrnotify.app.pairing.RecoveryCodeStore
import dev.herdrnotify.app.pairing.SignedDeviceDirectory
import dev.herdrnotify.app.pairing.SignedPeersDirectory
import dev.herdrnotify.app.push.NotificationChannels
import dev.herdrnotify.app.push.TokenRelay
import dev.herdrnotify.app.security.DeviceKeyStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * The object graph, built once.
 *
 * Hand-rolled rather than injected. Hilt is on the classpath and would do this
 * properly, but it would also add a KSP pass and a compile-time cost to an app
 * whose entire dependency set is a keystore, an HTTP client and a store. If the
 * graph grows a second implementation of anything, this is the file that turns
 * into a module — and the seams are already here.
 *
 * The scope is a `SupervisorJob` so that one failed request cannot cancel the
 * stream that is keeping the screen alive.
 */
class AppContainer(context: Context) {
    val applicationScope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val keys: DeviceKeyStore = DeviceKeyStore()
    val pairingStore: PairingStore = PairingStore(context)

    /**
     * The pairing is read as a value, not a flow, because the repository's job is
     * to decide *now* whether a connection can be opened. Handing it the store's
     * StateFlow would work but would hide the fact that it only ever reads the
     * current value.
     *
     * The parked FCM token is read and cleared through lambdas for the same
     * reason the pairing is: the repository stays free of the storage
     * mechanism, and the push service and this container hand it the same
     * source.
     */
    val repository: GatewayTriageRepository = GatewayTriageRepository(
        keys = keys,
        pairing = { pairingStore.current() },
        scope = applicationScope,
        pendingToken = { TokenRelay.parked(context) },
        // The token is kept after a successful registration: the repository
        // reports it on every connect, so a gateway that lost it (pruned, or a
        // reset store) is told again instead of staying silent until Firebase
        // happens to rotate it.
        onTokenRegistered = {},
    )

    /** Moving an existing pairing to another gateway address. See [GatewayAddress]. */
    val gatewayAddress: GatewayAddress = GatewayAddress(
        current = { pairingStore.current() },
        save = { pairingStore.save(it) },
        reconnect = {
            repository.disconnect()
            repository.connect()
        },
    )

    /** The one unauthenticated write: `POST /v1/pair`. */
    val pairingApi: PairingApi = HttpPairingApi()

    /**
     * The recovery code, encrypted at rest: it re-keys this device without host
     * approval, so it is the one pairing value that is a secret.
     */
    val recoveryCodes: RecoveryCodeStore = EncryptedRecoveryCodeStore(context)

    /** "Mis dispositivos", over the signed client. */
    val devices: DeviceDirectory = SignedDeviceDirectory { signedClient() }

    /** The host's tailnet peer list, for the pairing screen's address picker. */
    val peers: PeersDirectory = SignedPeersDirectory { url -> signedClient(url) }

    /**
     * A signed client for the current pairing, built fresh each time so a
     * re-pair (a new `device_id`) is signed as the new identity, and null while
     * there is nothing to sign with.
     */
    private fun signedClient(baseUrl: String? = null): GatewayClient? {
        val current = pairingStore.current()
        if (!current.isComplete || !keys.hasKey()) return null
        return GatewayClient(
            baseUrl = baseUrl ?: current.baseUrl,
            deviceId = current.deviceId,
            signer = RequestSigner(keys),
        )
    }
}

class HerdrNotifyApplication : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        // Channels are created before anything can post to them, because
        // Android silently drops a notification aimed at a channel that does not
        // exist yet — which looks exactly like a push backend that stopped
        // working.
        NotificationChannels.createAll(this)
        container = AppContainer(this)
        // Ask Firebase for the current token at start, not only when it rotates:
        // a token issued before this process existed, or one the gateway no
        // longer has, would otherwise never be reported.
        runCatching {
            com.google.firebase.messaging.FirebaseMessaging.getInstance().token
                .addOnSuccessListener { token ->
                    TokenRelay.park(this, token)
                    container.repository.flushPendingToken()
                }
        }
    }
}
