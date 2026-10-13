package dev.herdrnotify.app.pairing

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dev.herdrnotify.app.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import java.util.UUID

private val Context.pairingStore by preferencesDataStore(name = "pairing")

/**
 * Where the pairing lives on the device.
 *
 * Three facts, and no secrets among them:
 *
 *  * the **base URL** is where the gateway is, normally a Tailscale name
 *  * the **device id** is what the host's trust store calls this phone
 *  * the **signing key** is *not* here — it is in the hardware keystore and
 *    cannot be exported, which is the point of it
 *
 * So this file is not a credential store and needs no encryption. Losing it
 * costs one CLI command on the host, and the replacement phone is a different
 * device with a different key — which is exactly the property that makes
 * revocation work.
 */
data class Pairing(
    val baseUrl: String,
    val deviceId: String,
) {
    val isComplete: Boolean get() = baseUrl.isNotBlank() && deviceId.isNotBlank()

    companion object {
        val NONE = Pairing("", "")

        /**
         * Coerce whatever the user typed into something OkHttp accepts.
         *
         * A phone keyboard does not reliably produce `:` or `/`, and someone
         * copying a Tailscale name will often not add a scheme. Guessing here
         * saves a round trip of "it just says couldn't connect" that tells the
         * user nothing about which half they got wrong.
         */
        fun normaliseUrl(raw: String): String {
            val trimmed = raw.trim().trimEnd('/')
            if (trimmed.isEmpty()) return ""
            return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
                trimmed
            } else {
                "https://$trimmed"
            }
        }

        /**
         * Whether an address points at the device itself.
         *
         * A build with no gatewayUrl defaults to loopback, which on a phone is
         * the phone itself: pairing against it can only fail, and showing it
         * filled hides that nothing has been entered.
         */
        fun isLoopbackUrl(url: String): Boolean =
            url.contains("://127.0.0.1") || url.contains("://localhost")
    }
}

class PairingStore(private val context: Context) {

    private object Keys {
        val BASE_URL = stringPreferencesKey("base_url")
        val DEVICE_ID = stringPreferencesKey("device_id")
        val DEFAULT_URL_APPLIED = booleanPreferencesKey("default_url_applied")
    }

    private val _state = MutableStateFlow(Pairing.NONE)

    /**
     * The current pairing, readable synchronously.
     *
     * A `StateFlow` rather than a bare `Flow` because the consumer that matters
     * is not the UI — it is the repository, which has to decide whether to open
     * a connection the instant the activity starts, with no coroutine to wait on
     * and no window in which the answer is "unknown". Making it a `Flow` would
     * force a blocking read or a race.
     */
    val state: StateFlow<Pairing> = _state.asStateFlow()

    /**
     * Load from disk once.
     *
     * Idempotent and safe to call repeatedly: DataStore's own flow would
     * re-emit, but this only needs to happen at startup, and a repeated disk
     * read on every resume is work with no effect.
     */
    suspend fun load() {
        val stored = context.pairingStore.data.first()
        var baseUrl = stored[Keys.BASE_URL].orEmpty()
        val deviceId = stored[Keys.DEVICE_ID].orEmpty()
        // One-time move from the development loopback URL (adb reverse) to this
        // build's default gateway, so an already paired phone follows the build
        // without re-pairing. Applied once; the in-app dialog wins afterwards.
        val default = BuildConfig.DEFAULT_GATEWAY_URL
        if (default.isNotBlank() && stored[Keys.DEFAULT_URL_APPLIED] != true) {
            if (deviceId.isNotBlank() && (baseUrl.isBlank() || isLoopback(baseUrl))) {
                baseUrl = default
            }
            context.pairingStore.edit { prefs ->
                if (baseUrl.isNotBlank()) prefs[Keys.BASE_URL] = baseUrl
                prefs[Keys.DEFAULT_URL_APPLIED] = true
            }
        }
        _state.value = Pairing(baseUrl = baseUrl, deviceId = deviceId)
    }

    private fun isLoopback(url: String): Boolean = Pairing.isLoopbackUrl(url)

    /** The current value without suspending. */
    fun current(): Pairing = _state.value

    suspend fun save(pairing: Pairing) {
        val normalised = Pairing(
            baseUrl = Pairing.normaliseUrl(pairing.baseUrl),
            deviceId = pairing.deviceId.trim(),
        )
        // An empty value is stored as an empty string rather than removed, so a
        // half-finished pairing screen is distinguishable from a never-started
        // one — which is what the UI needs in order to show the pairing form
        // rather than an empty triage list every time.
        context.pairingStore.edit { prefs ->
            prefs[Keys.BASE_URL] = normalised.baseUrl
            prefs[Keys.DEVICE_ID] = normalised.deviceId
        }
        _state.value = normalised
    }

    suspend fun clear() {
        context.pairingStore.edit { it.clear() }
        _state.value = Pairing.NONE
    }

    /** A locally unique id, offered as the default the operator will register. */
    fun suggestDeviceId(): String = "hn-${UUID.randomUUID().toString().take(8)}"
}
