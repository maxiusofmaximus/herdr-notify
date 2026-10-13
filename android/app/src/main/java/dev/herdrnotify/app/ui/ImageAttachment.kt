package dev.herdrnotify.app.ui

import android.content.Context
import android.net.Uri
import dev.herdrnotify.app.net.GatewayClient

/**
 * The client's half of image attachments.
 *
 * The gateway contract in `docs/contracts/api.md` has no image endpoint yet, so
 * the transport is a pending seam on [dev.herdrnotify.app.ui.triage.TriageRepository]:
 * the app can pick an image, validate it and carry it to the send, and the
 * moment the host grows the endpoint the same path works. Until then the send
 * says plainly that the gateway does not take images, rather than failing
 * silently or pretending the picture went.
 *
 * Everything here that is a decision (what is acceptable, what a failure means)
 * is pure and unit-tested; only [readImage] touches the platform.
 */
internal object ImageAttachment {
    /** Comfortably below what a tailnet link should carry per message. */
    const val MAX_BYTES = 5 * 1024 * 1024

    val SUPPORTED_MIME = setOf(
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/heic",
    )

    enum class Problem { EMPTY, TOO_LARGE, UNSUPPORTED_TYPE }

    /**
     * Why this image cannot be attached, or null when it can.
     *
     * Type is checked before size so a `.zip` renamed to `.png` is reported as
     * the wrong kind rather than as too large — the person fixes the first by
     * picking another file, and the second only by shrinking it.
     */
    fun problem(mime: String?, size: Int): Problem? = when {
        mime.isNullOrBlank() || mime.lowercase() !in SUPPORTED_MIME -> Problem.UNSUPPORTED_TYPE
        size <= 0 -> Problem.EMPTY
        size > MAX_BYTES -> Problem.TOO_LARGE
        else -> null
    }
}

/** Read the bytes and MIME type behind a picked image, or null if unreadable. */
internal fun readImage(context: Context, uri: Uri): Pair<ByteArray, String>? = runCatching {
    val mime = context.contentResolver.getType(uri).orEmpty()
    val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
    if (bytes == null) null else bytes to mime
}.getOrNull()

/** What an unacceptable image says to the person. */
internal fun imageProblemMessage(problem: ImageAttachment.Problem): String = when (problem) {
    ImageAttachment.Problem.EMPTY -> "No se pudo leer la imagen."
    ImageAttachment.Problem.TOO_LARGE -> "La imagen es demasiado grande (máximo 5 MB)."
    ImageAttachment.Problem.UNSUPPORTED_TYPE -> "Ese formato de imagen no es compatible."
}

/** What a failed image send says. The gateway has no image endpoint yet. */
internal fun imageFailureMessage(error: Throwable?): String = when (error) {
    is GatewayClient.GatewayError.NotPermitted ->
        "Este teléfono no tiene permiso para enviar imágenes"

    else -> "Este gateway todavía no admite imágenes."
}
