package dev.herdrnotify.app.pairing

/**
 * Changes where an already paired phone reaches its gateway.
 *
 * Only the address moves. The device id and the signing key are left alone: the
 * host's trust store knows this phone by its id and its key, so a new address
 * for the same pairing is the same device talking to a different host address.
 * Changing either of those is a re-pair, which this deliberately does not do.
 *
 * The three collaborators are functions rather than the store and the
 * repository themselves, so the rule (normalise, save, reconnect, in that order)
 * can be tested without a Context or a network stack.
 */
class GatewayAddress(
    private val current: () -> Pairing,
    private val save: suspend (Pairing) -> Unit,
    private val reconnect: () -> Unit,
) {

    /**
     * Save [raw] as the gateway address and reconnect to it.
     *
     * A blank address is refused before anything is written, so a mistyped
     * empty field cannot leave the phone pointing nowhere.
     */
    suspend fun change(raw: String): Result<Pairing> {
        val url = Pairing.normaliseUrl(raw)
        if (url.isEmpty()) {
            return Result.failure(IllegalArgumentException("La dirección del gateway está vacía."))
        }
        val next = current().copy(baseUrl = url)
        save(next)
        reconnect()
        return Result.success(next)
    }
}
