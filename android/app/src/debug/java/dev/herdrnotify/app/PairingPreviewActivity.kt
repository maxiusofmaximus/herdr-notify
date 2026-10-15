package dev.herdrnotify.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import dev.herdrnotify.app.pairing.CameraPermissionStep
import dev.herdrnotify.app.pairing.PairingScreen
import dev.herdrnotify.app.pairing.PairingUiState
import dev.herdrnotify.app.pairing.QrScannerContent
import dev.herdrnotify.app.pairing.QrScannerScreen
import dev.herdrnotify.app.ui.theme.HerdrNotifyTheme
import dev.herdrnotify.app.ui.theme.TextSecondary

/**
 * Debug-only: every QR pairing screen, with data, without a gateway.
 *
 * The real pairing screen needs an unpaired phone and the scanner needs a camera
 * pointed at a code, neither of which a UI pass usually has. This draws the real
 * composables with representative data so the states can be inspected on a
 * device — and captured in light and dark, since the product itself is
 * dark-first and does not follow the system setting.
 *
 * Launch:
 * `adb shell am start -n <applicationId>/dev.herdrnotify.app.PairingPreviewActivity \
 *   --es screen scanner-error --ez dark true`
 *
 * [screen] is one of `pairing`, `scanner-live`, `scanner-ask`, `scanner-blocked`,
 * `scanner-error`, `scanner-processing`. Re-issuing the intent re-renders in
 * place, so one launch can be walked through every state.
 */
class PairingPreviewActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        render(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        render(intent)
    }

    private fun render(intent: Intent?) {
        val screen = intent?.getStringExtra(EXTRA_SCREEN) ?: "pairing"
        val dark = intent?.getBooleanExtra(EXTRA_DARK, true) ?: true
        setContent {
            HerdrNotifyTheme(darkTheme = dark) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    when (screen) {
                        "scanner-live" -> QrScannerScreen(
                            processing = false,
                            notice = null,
                            onBack = {},
                            onRaw = {},
                            onRetry = {},
                        )

                        "scanner-ask" -> QrScannerContent(
                            step = CameraPermissionStep.ASK,
                            scanning = false,
                            processing = false,
                            torchOn = false,
                            notice = null,
                            onBack = {},
                            onRequestPermission = {},
                            onOpenSettings = {},
                            onToggleTorch = {},
                            onRetry = {},
                            preview = { CameraPlaceholder() },
                        )

                        "scanner-blocked" -> QrScannerContent(
                            step = CameraPermissionStep.OPEN_SETTINGS,
                            scanning = false,
                            processing = false,
                            torchOn = false,
                            notice = null,
                            onBack = {},
                            onRequestPermission = {},
                            onOpenSettings = {},
                            onToggleTorch = {},
                            onRetry = {},
                            preview = { CameraPlaceholder() },
                        )

                        "scanner-error" -> QrScannerContent(
                            step = CameraPermissionStep.GRANTED,
                            scanning = false,
                            processing = false,
                            torchOn = false,
                            notice = "El código QR apunta a este mismo teléfono, no al equipo.",
                            onBack = {},
                            onRequestPermission = {},
                            onOpenSettings = {},
                            onToggleTorch = {},
                            onRetry = {},
                            preview = { CameraPlaceholder() },
                        )

                        "scanner-processing" -> QrScannerContent(
                            step = CameraPermissionStep.GRANTED,
                            scanning = true,
                            processing = true,
                            torchOn = false,
                            notice = null,
                            onBack = {},
                            onRequestPermission = {},
                            onOpenSettings = {},
                            onToggleTorch = {},
                            onRetry = {},
                            preview = { CameraPlaceholder() },
                        )

                        else -> PairingScreen(
                            state = SAMPLE_STATE,
                            onBaseUrl = {},
                            onDeviceId = {},
                            onSave = {},
                            onResetKey = {},
                        )
                    }
                }
            }
        }
    }

    private companion object {
        const val EXTRA_SCREEN = "screen"
        const val EXTRA_DARK = "dark"

        val SAMPLE_STATE = PairingUiState(
            baseUrl = "http://pc.tailnet.ts.net:8788",
            deviceId = "hn-demo1234",
            publicKey = "BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            fingerprint = "4f:9a:1c:2e:7b:03:aa:55:de:66:10:42:8c:9f:b1:23",
            isLoading = false,
            code = "",
            hasStoredRecoveryCode = true,
        )
    }
}

/** A stand-in for the camera feed, so the chrome can be drawn without one. */
@Composable
private fun CameraPlaceholder() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0B1017)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "Vista previa de la cámara",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
        )
    }
}
