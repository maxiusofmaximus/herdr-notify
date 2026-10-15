package dev.herdrnotify.app.pairing

import dev.herdrnotify.app.BuildConfig
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dev.herdrnotify.app.net.PairRequest
import dev.herdrnotify.app.net.PairResponse
import dev.herdrnotify.app.net.PairingException
import dev.herdrnotify.app.security.DeviceKeyStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * What the pairing screen shows.
 *
 * [publicKey] is deliberately *not* a secret — it is the thing the operator pastes
 * on the host — but it is still not put in logs, screenshots or analytics, because
 * a public key on its own is a durable identifier for this device. Knowing which
 * phone is which is not something the operator usually wants broadcast.
 */
data class PairingUiState(
    val baseUrl: String = "",
    val deviceId: String = "",
    val publicKey: String? = null,
    val fingerprint: String? = null,
    val isLoading: Boolean = true,
    val saved: Boolean = false,
    val error: String? = null,
    // -- short-code / auto-approval pairing (Fase 2(c)) --------------------
    /** The code the operator typed: a pairing code, or a recovery code. */
    val code: String = "",
    val claiming: Boolean = false,
    val codeError: String? = null,
    /** Why a scanned QR was refused, shown on the scanner as a card. */
    val qrError: String? = null,
    /** The recovery code from a successful claim. Shown exactly once. */
    val recoveryCode: String? = null,
    /** Whether one is already held, so a re-pair can offer it as a path. */
    val hasStoredRecoveryCode: Boolean = false,
    /** The id the gateway assigned to a claim that is not committed yet. */
    val claimedDeviceId: String? = null,
    val claimedBaseUrl: String = "",
    val permissions: List<String> = emptyList(),
    // -- tailnet peer picker (A6) ------------------------------------------
    val peers: List<TailnetPeer> = emptyList(),
    val peersLoading: Boolean = false,
    val peersUnavailable: Boolean = false,
) {
    /**
     * The host command, ready to copy.
     *
     * Assembled as one line because it is meant to be copied. Splitting it across
     * a code block with a continuation prompt invites a paste that carries the
     * prompt along, and a trust store entry with a stray character is a device
     * that never authenticates with no obvious cause.
     */
    val hostCommand: String?
        get() = publicKey?.let {
            "herdr-notify add-device --curve p256 --public-key $it --label ${deviceId.ifBlank { "phone" }}"
        }

    val canSave: Boolean get() = publicKey != null && hasRoutableAddress && deviceId.isNotBlank()

    val visibleBaseUrl: String get() = if (hasRoutableAddress) baseUrl else ""

    val hasRoutableAddress: Boolean
        get() = baseUrl.isNotBlank() && !Pairing.isLoopbackUrl(baseUrl)

    /**
     * Whether "Emparejar" can be pressed.
     *
     * A blank code is allowed on purpose: it is the auto-approval path, where the
     * gateway accepts the device because the source IP is the host's own tailnet
     * owner. Requiring a code here would hide the easiest path behind the hardest
     * one.
     */
    val canClaim: Boolean get() = publicKey != null && hasRoutableAddress && !claiming
}

/**
 * Drives pairing.
 *
 * The flow is deliberately not a form that posts somewhere. The gateway has no
 * HTTP enrollment endpoint, and that absence is a security decision rather than a
 * gap: enrollment is an act performed by a person at the machine that runs the
 * gateway, so the only unauthenticated write in the API does not exist. That
 * makes the app's job show the right two values and stay out of the way.
 *
 * What it does do before saving is ask [AddressProber] which address answers:
 * a URL that does not answer must not become the address the app keeps, or the
 * phone looks paired and then never connects.
 */
class PairingViewModel(
    private val keys: DeviceKeyStore,
    private val store: PairingStore,
    // Which address of the gateway answers, asked before anything is saved.
    // Injected so tests can answer without a network; production wires
    // AddressProber here. Priority and timeout stay in the prober.
    private val probe: suspend (List<String>) -> String? = { AddressProber().firstHealthy(it) },
    // The one unauthenticated write: POST /v1/pair. A default that fails keeps
    // the manual (host-command) path working in a build that has no HTTP pairing.
    private val pair: suspend (String, PairRequest) -> Result<PairResponse> = { _, _ ->
        Result.failure(IllegalStateException("emparejamiento no configurado"))
    },
    // A6: the host's tailnet peers, offered as addresses. Fails closed when the
    // list cannot be read, so the screen falls back to the manual field.
    private val peers: suspend (String) -> Result<List<TailnetPeer>> = {
        Result.failure(PeersUnavailable())
    },
    // The recovery code, held encrypted. A no-op store by default so the flow is
    // still complete without the Android keystore.
    private val recoveryCodes: RecoveryCodeStore = NoRecoveryCodeStore,
    // Nullable rather than defaulted to `viewModelScope`, because that is an
    // extension property on ViewModel and a default argument has no `this` to
    // resolve it against. It has to be defaulted to null and resolved inside the
    // class body, where `this` exists.
    injectedScope: CoroutineScope? = null,
) : ViewModel() {

    private val scope: CoroutineScope = injectedScope ?: viewModelScope

    private val _state = MutableStateFlow(PairingUiState())
    val state: StateFlow<PairingUiState> = _state.asStateFlow()

    init {
        load()
    }

    private fun load() {
        scope.launch {
            store.load()
            val existing = store.current()
            // The key is generated here rather than at first launch so that a
            // phone which is never paired never holds one. A key nobody asked
            // for is a liability with no benefit.
            val material = withContext(Dispatchers.Default) {
                if (!keys.hasKey()) {
                    keys.ensureKey(existing.deviceId.ifBlank { DEFAULT_PAIRING_LABEL })
                }
                keys.publicKeyBase64() to keys.fingerprint()
            }
            // Read off the main thread: creating the encrypted store touches the
            // keystore, which is not free.
            val storedRecovery = withContext(Dispatchers.Default) {
                recoveryCodes.get()?.takeIf { it.isNotBlank() }
            }
            _state.update {
                it.copy(
                    // A new install starts on this build's gateway instead of an empty field.
                    baseUrl = existing.baseUrl.ifBlank { BuildConfig.DEFAULT_GATEWAY_URL },
                    deviceId = existing.deviceId.ifBlank { store.suggestDeviceId() },
                    publicKey = material.first,
                    fingerprint = material.second,
                    isLoading = false,
                    hasStoredRecoveryCode = storedRecovery != null,
                )
            }
            loadPeers()
        }
    }

    fun onBaseUrl(value: String) {
        _state.update { it.copy(baseUrl = value, saved = false) }
    }

    fun onRefreshPeers() {
        loadPeers()
    }

    fun loadPeers() {
        val current = _state.value
        if (!current.hasRoutableAddress || current.peersLoading) return
        _state.update { it.copy(peersLoading = true) }
        scope.launch {
            peers(Pairing.normaliseUrl(current.baseUrl))
                .onSuccess { list ->
                    _state.update {
                        it.copy(peersLoading = false, peers = list, peersUnavailable = list.isEmpty())
                    }
                }
                .onFailure {
                    _state.update { it.copy(peersLoading = false, peersUnavailable = true) }
                }
        }
    }

    fun onPickPeer(peer: TailnetPeer) {
        val address = peer.addresses.firstOrNull()?.takeIf { it.isNotBlank() } ?: return
        _state.update {
            it.copy(baseUrl = "http://$address:${gatewayPort(it.baseUrl)}", saved = false)
        }
    }

    private fun gatewayPort(url: String): String {
        val afterScheme = url.substringAfter("://", url)
        val port = afterScheme.substringAfter(':', "").takeWhile { it.isDigit() }
        return port.ifBlank { DEFAULT_GATEWAY_PORT }
    }

    fun onDeviceId(value: String) {
        _state.update { it.copy(deviceId = value, saved = false) }
    }

    fun save(onSaved: () -> Unit) {
        val current = _state.value
        if (!current.canSave) {
            _state.update { it.copy(error = "Falta la URL o el identificador del dispositivo") }
            return
        }
        scope.launch {
            // The address the operator sees first, then the one already saved:
            // both name the same gateway, and the prober decides by priority
            // which of them answers. A URL that does not answer is not stored.
            val candidates = listOf(current.baseUrl, store.current().baseUrl)
                .map { Pairing.normaliseUrl(it) }
                .filter { it.isNotEmpty() }
                .distinct()
            val reachable = probe(candidates)
            if (reachable == null) {
                _state.update {
                    it.copy(error = "No responde el gateway. Comprueba la URL y que el host esté encendido.")
                }
                return@launch
            }
            store.save(Pairing(reachable, current.deviceId))
            _state.update { it.copy(baseUrl = reachable, saved = true, error = null) }
            onSaved()
        }
    }

    fun onCode(value: String) {
        _state.update { it.copy(code = value, codeError = null) }
    }

    /**
     * A string read off a pairing QR.
     *
     * The QR is just another way to fill the two fields the manual flow already
     * has, so a valid one sets the address and the code and then runs the exact
     * same [claim] the "Emparejar" button runs — no second pairing path to keep
     * in step. An invalid one does not touch the fields at all: it records why,
     * and the scanner shows that as a card with a retry, leaving the manual form
     * untouched behind it.
     */
    fun onQrScanned(raw: String) {
        when (val result = PairingQrPayload.parse(raw)) {
            is PairingQrResult.Valid -> {
                _state.update {
                    it.copy(
                        baseUrl = result.payload.baseUrl,
                        code = result.payload.code,
                        codeError = null,
                        qrError = null,
                    )
                }
                claim()
            }

            is PairingQrResult.Invalid ->
                _state.update { it.copy(qrError = result.reason) }
        }
    }

    fun dismissQrError() {
        _state.update { it.copy(qrError = null) }
    }

    /**
     * Pair with the code the host printed, or with no code for auto-approval.
     *
     * The address is probed first, for the same reason [save] probes: the one
     * request that must succeed cannot be sent to a URL that does not answer. A
     * success is deliberately *not* committed here — the recovery code has to be
     * shown once before the phone leaves this screen, so [commitClaim] is what
     * stores the identity.
     */
    fun claim() {
        val current = _state.value
        val publicKey = current.publicKey
        if (publicKey == null) {
            _state.update { it.copy(codeError = "Todavía no hay clave en este teléfono.") }
            return
        }
        if (current.claiming) return
        _state.update { it.copy(claiming = true, codeError = null) }
        scope.launch {
            val candidates = listOf(current.baseUrl, store.current().baseUrl)
                .map { Pairing.normaliseUrl(it) }
                .filter { it.isNotEmpty() }
                .distinct()
            val reachable = probe(candidates)
            if (reachable == null) {
                _state.update {
                    it.copy(
                        claiming = false,
                        codeError = "No responde el equipo. Activa Tailscale y comprueba la dirección.",
                    )
                }
                return@launch
            }
            // A lower-case paste is the common case on a phone; the gateway's
            // alphabet is upper-case, so normalise before it is ever sent.
            val code = current.code.trim().uppercase().takeIf { it.isNotEmpty() }
            val request = PairRequest(
                curve = CURVE,
                publicKey = publicKey,
                label = current.deviceId.ifBlank { null },
                code = code,
            )
            pair(reachable, request)
                .onSuccess { response ->
                    _state.update {
                        it.copy(
                            claiming = false,
                            codeError = null,
                            claimedDeviceId = response.deviceId,
                            claimedBaseUrl = reachable,
                            recoveryCode = response.recoveryCode,
                            permissions = response.permissions,
                        )
                    }
                }
                .onFailure { error ->
                    _state.update { it.copy(claiming = false, codeError = claimFailure(error)) }
                }
        }
    }

    /**
     * Commit a successful claim.
     *
     * The identity, the address and the recovery code are written together, so a
     * phone can never be left paired with a code it did not keep.
     */
    fun commitClaim(onPaired: () -> Unit) {
        val current = _state.value
        val deviceId = current.claimedDeviceId ?: return
        scope.launch {
            current.recoveryCode?.takeIf { it.isNotBlank() }?.let { recoveryCodes.save(it) }
            store.save(Pairing(current.claimedBaseUrl, deviceId))
            _state.update {
                it.copy(saved = true, hasStoredRecoveryCode = current.recoveryCode != null)
            }
            onPaired()
        }
    }

    /**
     * Re-pair with the recovery code already held.
     *
     * The recovery path re-keys the *same* device id; the gateway rotates the
     * recovery code, and the new one is what [commitClaim] stores.
     */
    fun repairWithRecovery() {
        val stored = recoveryCodes.get()
        if (stored.isNullOrBlank()) {
            _state.update {
                it.copy(codeError = "No hay código de recuperación guardado en este teléfono.")
            }
            return
        }
        _state.update { it.copy(code = stored, codeError = null) }
        claim()
    }

    fun dismissCodeError() {
        _state.update { it.copy(codeError = null) }
    }

    fun dismissRecovery() {
        _state.update { it.copy(recoveryCode = null) }
    }

    /**
     * Replace the signing key.
     *
     * The old key stays in the host's trust store, so after this the phone
     * authenticates as a *new* device and the operator has to run
     * `herdr-notify devices` and revoke the old one. That is the intended
     * sequence: nothing should be able to swap the key on a phone that is lost,
     * and a key change is visible in the host's device list rather than silent.
     */
    fun resetKey() {
        scope.launch {
            val label = _state.value.deviceId.ifBlank { DEFAULT_PAIRING_LABEL }
            withContext(Dispatchers.Default) { keys.reset(label) }
            _state.update {
                it.copy(
                    publicKey = keys.publicKeyBase64(),
                    fingerprint = keys.fingerprint(),
                    saved = false,
                )
            }
        }
    }

    fun dismissError() {
        _state.update { it.copy(error = null) }
    }

    private companion object {
        /**
         * The attestation challenge for a key generated before a device id is
         * known. It is a nonce, not a secret: it exists so the keystore binds the
         * key to this pairing ceremony.
         */
        const val DEFAULT_PAIRING_LABEL = "herdr-notify-pairing"

        /** The curve this app generates: P-256, the keystore's well-supported one. */
        const val CURVE = "p256"

        const val DEFAULT_GATEWAY_PORT = "8788"
    }
}

/**
 * What a failed `POST /v1/pair` says to the person.
 *
 * The gateway's `403 pairing_rejected` is uniform on purpose — the client is
 * never told which code or which check failed — so the app must not invent a
 * distinction the host refuses to make. It states the two things the person can
 * act on (the code, or the rate limit) and nothing more.
 */
internal fun claimFailure(error: Throwable): String = when {
    error is PairingException && error.status == 403 ->
        "El código no es válido, ya se usó o ha caducado."

    error is PairingException && error.status == 429 ->
        "Demasiados intentos seguidos. Espera un momento y vuelve a probar."

    error is PairingException && error.status == 413 ->
        "La petición de emparejamiento es demasiado grande."

    error is PairingException && error.status == 0 ->
        "No se pudo contactar con el equipo. Comprueba que está encendido y con Tailscale."

    error is PairingException ->
        "No se pudo emparejar: ${error.detail}"

    else ->
        "No se pudo emparejar. Inténtalo de nuevo."
}
