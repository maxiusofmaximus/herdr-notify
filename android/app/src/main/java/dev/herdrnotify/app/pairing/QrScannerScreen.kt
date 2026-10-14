package dev.herdrnotify.app.pairing

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.view.CameraController
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.FlashlightOff
import androidx.compose.material.icons.filled.FlashlightOn
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import dev.herdrnotify.app.ui.NoticeAction
import dev.herdrnotify.app.ui.NoticeCard
import dev.herdrnotify.app.ui.theme.HerdrNotifyTheme
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.theme.TextPrimary
import dev.herdrnotify.app.ui.theme.TextSecondary
import java.io.Closeable
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Point the camera at a pairing QR.
 *
 * CameraX drives the preview and the analysis image stream; ML Kit reads the code
 * out of the frames. Only QR codes are asked for, so the detector is not doing
 * work for formats the app has no contract with.
 *
 * The permission is requested here, at the moment of scanning, with a reason —
 * not at first launch. A phone that pairs by hand should never be asked for the
 * camera, and after a permanent refusal the only honest route is system settings,
 * not a dialog Android will not show.
 *
 * The screen does not parse or pair: it hands the raw string up and shows the
 * reason when the pairing layer rejects it. Keeping the camera and the contract
 * apart is what lets the parser be tested and the scanner be reused.
 */
@Composable
fun QrScannerScreen(
    processing: Boolean,
    notice: String?,
    onBack: () -> Unit,
    onRaw: (String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var granted by remember { mutableStateOf(hasCameraPermission(context)) }
    var asked by rememberSaveable { mutableStateOf(false) }
    var torchOn by remember { mutableStateOf(false) }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        granted = it
        asked = true
    }

    val activity = context.findActivity()
    val rationale = activity?.let {
        ActivityCompat.shouldShowRequestPermissionRationale(it, Manifest.permission.CAMERA)
    } ?: false
    val step = CameraPermissionPolicy.step(granted, asked, rationale)

    val controller = remember { LifecycleCameraController(context) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val currentOnRaw by rememberUpdatedState(onRaw)
    val analyzer = remember { QrCodeAnalyzer { raw -> currentOnRaw(raw) } }

    val active = step == CameraPermissionStep.GRANTED && !processing && notice == null

    LaunchedEffect(step) {
        if (step == CameraPermissionStep.GRANTED) {
            controller.setEnabledUseCases(CameraController.IMAGE_ANALYSIS)
            runCatching { controller.bindToLifecycle(lifecycleOwner) }
        } else {
            runCatching { controller.unbind() }
        }
    }

    // One code at a time: the analyzer stops after the first hit and resumes only
    // when the pairing layer asks for another try.
    LaunchedEffect(active, step) {
        if (active) {
            analyzer.reset()
            controller.setImageAnalysisAnalyzer(executor, analyzer)
        } else {
            controller.clearImageAnalysisAnalyzer()
        }
    }

    LaunchedEffect(torchOn, step) {
        if (step == CameraPermissionStep.GRANTED) {
            runCatching { controller.cameraControl?.enableTorch(torchOn) }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            runCatching { controller.clearImageAnalysisAnalyzer() }
            runCatching { controller.unbind() }
            analyzer.close()
            executor.shutdown()
        }
    }

    QrScannerContent(
        step = step,
        scanning = active,
        processing = processing,
        torchOn = torchOn,
        notice = notice,
        onBack = onBack,
        onRequestPermission = { launcher.launch(Manifest.permission.CAMERA) },
        onOpenSettings = { context.openAppSettings() },
        onToggleTorch = { torchOn = !torchOn },
        onRetry = onRetry,
        preview = {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        scaleType = PreviewView.ScaleType.FILL_CENTER
                        this.controller = controller
                    }
                },
                modifier = Modifier.fillMaxSize(),
            )
        },
        modifier = modifier,
    )
}

/**
 * The scanner's chrome, with the camera feed injected.
 *
 * Split from [QrScannerScreen] so the permission, processing and error states can
 * be drawn — and looked at — without a camera, and so the layout has one home.
 */
@Composable
fun QrScannerContent(
    step: CameraPermissionStep,
    scanning: Boolean,
    processing: Boolean,
    torchOn: Boolean,
    notice: String?,
    onBack: () -> Unit,
    onRequestPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    onToggleTorch: () -> Unit,
    onRetry: () -> Unit,
    preview: @Composable () -> Unit,
    modifier: Modifier = Modifier,
) {
    // The scanner is a camera view: it stays dark whatever the app theme, so the
    // reticle, the copy and the error card read over the feed.
    HerdrNotifyTheme(darkTheme = true) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ScanBackground),
    ) {
        if (step == CameraPermissionStep.GRANTED) {
            preview()
        }

        // A dark veil over the feed keeps the reticle and the copy legible over
        // whatever the camera is pointing at.
        Box(
            Modifier
                .fillMaxSize()
                .background(Color(0x66000000)),
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(Spacing.sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onBack,
                modifier = Modifier.semantics { contentDescription = "Volver" },
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = null,
                    tint = TextPrimary,
                )
            }
            Spacer(Modifier.weight(1f))
            if (step == CameraPermissionStep.GRANTED) {
                IconButton(
                    onClick = onToggleTorch,
                    modifier = Modifier.semantics {
                        contentDescription = if (torchOn) "Apagar linterna" else "Encender linterna"
                    },
                ) {
                    Icon(
                        imageVector = if (torchOn) Icons.Filled.FlashlightOn else Icons.Filled.FlashlightOff,
                        contentDescription = null,
                        tint = if (torchOn) MaterialTheme.colorScheme.primary else TextPrimary,
                    )
                }
            }
        }

        when (step) {
            CameraPermissionStep.GRANTED -> GrantedBody(
                scanning = scanning,
                notice = notice,
                onRetry = onRetry,
            )

            CameraPermissionStep.ASK -> PermissionBody(
                title = "Permiso de cámara",
                body = "Para escanear el código QR necesitas dar permiso a la cámara. " +
                    "El escaneo es local: la imagen no sale del teléfono.",
                button = "Permitir cámara",
                onClick = onRequestPermission,
                onBack = onBack,
            )

            CameraPermissionStep.OPEN_SETTINGS -> PermissionBody(
                title = "Cámara bloqueada",
                body = "Has bloqueado la cámara para esta app. Actívala en los ajustes " +
                    "del sistema para poder escanear el código QR, o vincula a mano.",
                button = "Abrir ajustes",
                onClick = onOpenSettings,
                onBack = onBack,
            )
        }

        if (processing) {
            ProcessingOverlay()
        }
    }
    }
}

@Composable
private fun GrantedBody(
    scanning: Boolean,
    notice: String?,
    onRetry: () -> Unit,
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(260.dp)
                .border(2.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(24.dp)),
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars)
            .padding(Spacing.lg),
        verticalArrangement = Arrangement.SpaceBetween,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.size(48.dp))

        Text(
            text = if (scanning) {
                "Apunta al código que muestra el equipo"
            } else {
                "Escaneo en pausa"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
        )

        if (notice != null) {
            NoticeCard(
                message = notice,
                title = "Código no reconocido",
                actions = listOf(
                    NoticeAction("Reintentar", onRetry),
                ),
            )
        } else {
            Spacer(Modifier.height(Spacing.xxl))
        }
    }
}

@Composable
private fun PermissionBody(
    title: String,
    body: String,
    button: String,
    onClick: () -> Unit,
    onBack: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars)
            .padding(Spacing.xl),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            imageVector = Icons.Filled.CameraAlt,
            contentDescription = null,
            tint = TextSecondary,
            modifier = Modifier.size(40.dp),
        )
        Spacer(Modifier.size(Spacing.md))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = TextPrimary,
        )
        Spacer(Modifier.size(Spacing.sm))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
        )
        Spacer(Modifier.size(Spacing.lg))
        Button(
            onClick = onClick,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 52.dp),
        ) {
            Text(button)
        }
        Spacer(Modifier.size(Spacing.sm))
        OutlinedButton(
            onClick = onBack,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp),
        ) {
            Text("Vincular a mano")
        }
    }
}

@Composable
private fun ProcessingOverlay() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xCC000000)),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.size(Spacing.md))
            Text(
                text = "Emparejando…",
                style = MaterialTheme.typography.bodyMedium,
                color = TextPrimary,
            )
        }
    }
}

/** The near-black behind the camera feed; the feed itself covers it once bound. */
private val ScanBackground = Color(0xFF05070A)

/**
 * Reads the first QR code out of the analysis stream and hands it up once.
 *
 * Delivery is latched so a code that stays in frame does not fire the pairing
 * repeatedly; [reset] opens the latch again for a retry. The scanner is only ever
 * given QR frames, so it does not decode formats the app cannot use.
 */
internal class QrCodeAnalyzer(
    private val onCode: (String) -> Unit,
) : ImageAnalysis.Analyzer, Closeable {

    private val scanner = BarcodeScanning.getClient(
        BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build(),
    )
    private val delivered = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)

    fun reset() {
        delivered.set(false)
    }

    override fun analyze(image: ImageProxy) {
        val media = image.image
        if (media == null || closed.get() || delivered.get()) {
            image.close()
            return
        }
        val input = InputImage.fromMediaImage(media, image.imageInfo.rotationDegrees)
        scanner.process(input)
            .addOnSuccessListener { codes ->
                val value = codes.firstOrNull { !it.rawValue.isNullOrBlank() }?.rawValue
                if (value != null && delivered.compareAndSet(false, true)) {
                    onCode(value)
                }
            }
            .addOnCompleteListener { image.close() }
    }

    override fun close() {
        closed.set(true)
        runCatching { scanner.close() }
    }
}

private fun hasCameraPermission(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED

private fun Context.openAppSettings() {
    val intent = Intent(
        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        Uri.fromParts("package", packageName, null),
    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { startActivity(intent) }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
