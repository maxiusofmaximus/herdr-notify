package dev.herdrnotify.app.pairing

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Where the recovery code is kept.
 *
 * The recovery code is a secret in a way the base URL and the device id are not:
 * it re-keys this device without any approval on the host. Treating it as
 * ordinary preferences would be the same mistake as storing the signing key in a
 * text file, so it is encrypted at rest.
 *
 * An interface because the encryption uses the Android keystore, which does not
 * exist on a plain JVM — the pairing flow has to be testable without it.
 */
interface RecoveryCodeStore {
    fun get(): String?
    fun save(code: String)
    fun clear()
}

/** The no-op store, for tests and for a process that has never kept one. */
object NoRecoveryCodeStore : RecoveryCodeStore {
    override fun get(): String? = null
    override fun save(code: String) = Unit
    override fun clear() = Unit
}

/**
 * An encrypted store backed by `EncryptedSharedPreferences`, whose master key
 * lives in the hardware-backed keystore via [MasterKey].
 */
class EncryptedRecoveryCodeStore(context: Context) : RecoveryCodeStore {

    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    override fun get(): String? = prefs.getString(KEY, null)

    override fun save(code: String) {
        prefs.edit().putString(KEY, code).apply()
    }

    override fun clear() {
        prefs.edit().remove(KEY).apply()
    }

    private companion object {
        const val FILE_NAME = "herdr_recovery"
        const val KEY = "recovery_code"
    }
}
