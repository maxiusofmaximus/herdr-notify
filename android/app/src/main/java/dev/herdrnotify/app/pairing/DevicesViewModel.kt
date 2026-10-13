package dev.herdrnotify.app.pairing

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dev.herdrnotify.app.net.GatewayClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * "Mis dispositivos": the devices the host trusts, and the one action that
 * matters — revoke.
 *
 * [selfId] is what the phone signs as, so the list can mark "este teléfono" and
 * warn before a person revokes the device they are holding.
 */
data class DevicesUiState(
    val devices: List<DeviceInfo> = emptyList(),
    val loading: Boolean = true,
    val error: String? = null,
    val revokingId: String? = null,
    val selfId: String = "",
) {
    val isEmpty: Boolean get() = !loading && error == null && devices.isEmpty()
}

/**
 * Drives the device list.
 *
 * The directory is an interface so the screen is testable against a scripted
 * 403/404 without a signed client or a socket.
 */
class DevicesViewModel(
    private val directory: DeviceDirectory,
    private val selfId: () -> String,
    injectedScope: CoroutineScope? = null,
) : ViewModel() {

    private val scope: CoroutineScope = injectedScope ?: viewModelScope

    private val _state = MutableStateFlow(DevicesUiState(selfId = selfId()))
    val state: StateFlow<DevicesUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(loading = true, error = null, revokingId = null, selfId = selfId()) }
        scope.launch {
            directory.list()
                .onSuccess { list ->
                    _state.update { it.copy(devices = list, loading = false, error = null) }
                }
                .onFailure { error ->
                    _state.update { it.copy(loading = false, error = devicesFailure(error)) }
                }
        }
    }

    /**
     * Revoke one device, then reload so the revoked marker reflects the host
     * rather than an optimistic guess.
     */
    fun revoke(deviceId: String) {
        if (_state.value.revokingId != null) return
        _state.update { it.copy(revokingId = deviceId, error = null) }
        scope.launch {
            directory.revoke(deviceId)
                .onSuccess { load() }
                .onFailure { error ->
                    _state.update { it.copy(revokingId = null, error = devicesFailure(error)) }
                }
        }
    }
}

/**
 * What a failed device call says to the person.
 *
 * A 403 here is not a fault: it is the reservation working. A freshly paired
 * device gets `read_state` and nothing else, so `admin` is a host-side grant and
 * the message has to say so rather than imply the phone is broken.
 */
internal fun devicesFailure(error: Throwable): String = when {
    error is GatewayClient.GatewayError.NotPermitted ->
        "Este teléfono no administra el equipo: falta el permiso admin. Pídelo en el host."

    error is GatewayClient.GatewayError.Unauthorised ->
        "Este teléfono ya no está emparejado. Vuelve a emparejarlo."

    error is GatewayClient.GatewayError.Rejected && error.code == 404 ->
        "Ese dispositivo ya no existe en el equipo."

    error is IllegalStateException ->
        "Sin conexión con el equipo."

    else ->
        error.message ?: "No se pudieron cargar los dispositivos."
}
