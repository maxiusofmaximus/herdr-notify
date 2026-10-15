package dev.herdrnotify.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import dev.herdrnotify.app.push.HerdrMessagingService
import dev.herdrnotify.app.push.NotificationPermissionPolicy
import dev.herdrnotify.app.push.NotificationPermissionStep
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.herdrnotify.app.domain.ConnectionState
import dev.herdrnotify.app.pairing.AddressProber
import dev.herdrnotify.app.pairing.PairingScreen
import dev.herdrnotify.app.pairing.PairingViewModel
import dev.herdrnotify.app.pairing.DevicesViewModel
import dev.herdrnotify.app.recovery.NoConnectionScreen
import dev.herdrnotify.app.recovery.RecoveryViewModel
import dev.herdrnotify.app.recovery.openTailscale
import dev.herdrnotify.app.ui.AgentDetailScreen
import dev.herdrnotify.app.ui.ConnectionDialog
import dev.herdrnotify.app.ui.ConnectionPill
import dev.herdrnotify.app.ui.DevicesScreen
import dev.herdrnotify.app.ui.GatewayDialog
import dev.herdrnotify.app.ui.NewConversationScreen
import dev.herdrnotify.app.ui.StateBlock
import dev.herdrnotify.app.ui.TriageList
import dev.herdrnotify.app.ui.connectionIndicator
import dev.herdrnotify.app.ui.theme.HerdrNotifyTheme
import dev.herdrnotify.app.ui.theme.Spacing
import dev.herdrnotify.app.ui.triage.TriageViewModel
import dev.herdrnotify.app.ui.triage.agentById
import dev.herdrnotify.app.ui.triage.rememberNowMillis
import dev.herdrnotify.app.ui.triage.subtitle

/**
 * One activity, two screens.
 *
 * Not navigation: a phone that is not paired has nothing to navigate to, and the
 * only way out of pairing is to finish pairing. A nav graph would add a back
 * stack whose every entry is invalid.
 */
class MainActivity : ComponentActivity() {

    private val container: AppContainer
        get() = (application as HerdrNotifyApplication).container

    override fun onCreate(savedInstanceState: Bundle?) {
        // The app is dark on every system setting, so the system bars get the
        // light icons explicitly. The no-argument enableEdgeToEdge() reads the
        // *system* night mode, which on a light-mode phone draws a pale
        // navigation bar with dark icons and hides the bar against our dark UI.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        setContent {
            HerdrNotifyTheme {
                App(container)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        container.repository.connect()
        openAgentFromIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openAgentFromIntent(intent)
    }

    /**
     * A tapped notification carries the pane that raised it. The extra comes
     * from a push payload, so it is validated against the pane id shape before
     * it is used, and consumed so a recreation does not repeat the action. FCM
     * puts every data field in the extras itself when it displays the
     * notification for a backgrounded app, so the same key serves both paths.
     */
    private fun openAgentFromIntent(intent: Intent?) {
        val paneId = intent?.getStringExtra(EXTRA_PANE_ID) ?: return
        intent.removeExtra(EXTRA_PANE_ID)
        if (!HerdrMessagingService.PANE_ID.matches(paneId)) return
        DebugLog.d("opening agent from notification: $paneId")
        container.applicationScope.launch { container.repository.markSeen(paneId) }
    }

    companion object {
        const val EXTRA_PANE_ID = "pane_id"
    }

    override fun onStop() {
        super.onStop()
        // Closed on every stop, not only on destroy: a foreground connection
        // held while the app is invisible is a battery cost with no benefit, and
        // FCM covers the case where the app is not running at all.
        container.repository.disconnect()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(container: AppContainer) {
    // The store's StateFlow, not a one-shot read.
    //
    // Reading the pairing once with `produceState` looks right — a suspend disk
    // read with a "not known yet" value — but it only ever answers the question
    // at startup. Saving a pairing would not re-trigger it, so the app would sit
    // on the pairing screen forever with the values stored and nothing
    // connecting. Collecting the flow is what makes "finish pairing" actually
    // lead anywhere.
    val pairing by container.pairingStore.state.collectAsStateWithLifecycle()

    // Disk read once. `load` is idempotent, so a configuration change re-running
    // it costs a redundant read and nothing else.
    LaunchedEffect(Unit) { container.pairingStore.load() }

    NotificationPermissionPrompt()

    // Re-pairing is reachable from the guided "Sin conexión" screen even while
    // the phone is still paired: it is the pairing that is broken, not the
    // address, so clearing the pairing would be the wrong move.
    var showPairing by rememberSaveable { mutableStateOf(false) }

    // One explicit ground for the whole app. Without it a screen that does not
    // paint its own background falls through to the window colour, which is how
    // light Material surfaces ended up sitting on a dark frame.
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        if (pairing.isComplete && !showPairing) {
            TriageApp(container, onRepair = { showPairing = true })
        } else {
            PairingRoute(
                container,
                // Only offer a way back when there is a paired state to return to.
                onBack = if (pairing.isComplete) ({ showPairing = false }) else null,
                onPaired = { showPairing = false },
            )
        }
    }
}

@Composable
private fun PairingRoute(
    container: AppContainer,
    onBack: (() -> Unit)? = null,
    onPaired: (() -> Unit)? = null,
) {
    val factory = remember {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                PairingViewModel(
                    keys = container.keys,
                    store = container.pairingStore,
                    probe = { AddressProber().firstHealthy(it) },
                    // The one unauthenticated write: POST /v1/pair.
                    pair = { url, request -> container.pairingApi.pair(url, request) },
                    recoveryCodes = container.recoveryCodes,
                    peers = { url -> container.peers.peers(url) },
                ) as T
        }
    }
    val viewModel: PairingViewModel = viewModel(factory = factory)
    val state by viewModel.state.collectAsStateWithLifecycle()

    PairingScreen(
        state = state,
        onBaseUrl = viewModel::onBaseUrl,
        onDeviceId = viewModel::onDeviceId,
        onSave = { viewModel.save { } },
        onResetKey = viewModel::resetKey,
        onBack = onBack,
        onCode = viewModel::onCode,
        onClaim = viewModel::claim,
        onRepairWithRecovery = viewModel::repairWithRecovery,
        onCommit = { viewModel.commitClaim { onPaired?.invoke() } },
        onDismissRecovery = viewModel::dismissRecovery,
        onPickPeer = viewModel::onPickPeer,
        onRefreshPeers = viewModel::onRefreshPeers,
        onQrScanned = viewModel::onQrScanned,
        onDismissQrError = viewModel::dismissQrError,
        onDismissCodeError = viewModel::dismissCodeError,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TriageApp(container: AppContainer, onRepair: () -> Unit) {
    val repository = container.repository
    val factory = remember {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                TriageViewModel(repository) as T
        }
    }
    val viewModel: TriageViewModel = viewModel(factory = factory)
    val state by viewModel.state.collectAsStateWithLifecycle()
    val detail by viewModel.detail.collectAsStateWithLifecycle()
    val newChat by viewModel.newChat.collectAsStateWithLifecycle()

    // The guided reconnect screen's own state. Its dependencies are handed to it
    // rather than looked up inside, so it stays a plain JVM-testable object: the
    // prober and the two ways to reconnect are the only things that touch the
    // network or the disk.
    val recoveryFactory = remember {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                RecoveryViewModel(
                    connection = repository.connection,
                    host = { repository.host() },
                    candidates = {
                        listOf(
                            container.pairingStore.current().baseUrl,
                            BuildConfig.DEFAULT_GATEWAY_URL,
                        )
                    },
                    probe = { AddressProber().firstHealthy(it) },
                    onAddressFound = { url -> container.gatewayAddress.change(url) },
                    reconnect = { repository.retry() },
                ) as T
        }
    }
    val recoveryViewModel: RecoveryViewModel = viewModel(factory = recoveryFactory)
    val recoveryState by recoveryViewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Reconnect whenever the app comes to the foreground. `onStart` does this
    // too, but a configuration change keeps the ViewModel and therefore keeps
    // the repository, so the stream has to be re-established explicitly.
    LaunchedEffect(Unit) { repository.connect() }

    // The agent detail replaces the list rather than stacking on it. There is
    // no navigation graph for two screens: the back gesture is handled inside
    // the detail, and closing it returns to the list the ViewModel still holds.
    detail?.let { open ->
        AgentDetailScreen(
            agent = state.agentById(open.paneId),
            detail = open,
            onBack = viewModel::onCloseAgent,
            onRefresh = viewModel::onRefreshOutput,
            onDraftChange = viewModel::onDraftChange,
            onSend = viewModel::onSend,
            onConfirmSend = viewModel::onConfirmSend,
            onDismissConfirm = viewModel::onDismissConfirm,
            onPermissionKeys = viewModel::onPermissionKeys,
            onRetry = viewModel::onRetryPrompt,
            onStop = viewModel::onStopAgent,
            onConfirmStop = viewModel::onConfirmStop,
            onDismissStop = viewModel::onDismissStop,
            onDismissNotice = viewModel::onDismissNotice,
            onAttachImage = viewModel::onAttachImage,
            onClearAttachment = viewModel::onClearAttachment,
        )
        return
    }

    // "Nueva conversación" is its own screen, like the detail and the device
    // list: a create in flight and a host refusal need room to be read. It is
    // closed by the ViewModel the moment a conversation opens, so closing that
    // chat returns to the list rather than the form.
    if (newChat.open) {
        NewConversationScreen(
            state = newChat,
            onCreate = viewModel::onNewChat,
            onBack = viewModel::onCloseNewChat,
            onDismissError = viewModel::onDismissNewChatError,
        )
        return
    }

    var showGateway by rememberSaveable { mutableStateOf(false) }
    var gatewayError by rememberSaveable { mutableStateOf<String?>(null) }
    var showDevices by rememberSaveable { mutableStateOf(false) }
    var showConnection by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    // The device list replaces the triage list while open, like the agent detail:
    // there is no nav graph, and closing returns to the list the ViewModel holds.
    if (showDevices) {
        val devicesFactory = remember {
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                    DevicesViewModel(
                        directory = container.devices,
                        selfId = { container.pairingStore.current().deviceId },
                    ) as T
            }
        }
        val devicesViewModel: DevicesViewModel = viewModel(factory = devicesFactory)
        val devicesState by devicesViewModel.state.collectAsStateWithLifecycle()
        DevicesScreen(
            state = devicesState,
            onBack = { showDevices = false },
            onRevoke = devicesViewModel::revoke,
            onReload = devicesViewModel::load,
        )
        return
    }

    if (showGateway) {
        GatewayDialog(
            currentUrl = container.pairingStore.current().baseUrl,
            error = gatewayError,
            onSave = { url ->
                scope.launch {
                    container.gatewayAddress.change(url)
                        .onSuccess {
                            gatewayError = null
                            showGateway = false
                        }
                        .onFailure { gatewayError = "Escribe la dirección del gateway." }
                }
            },
            onDismiss = {
                gatewayError = null
                showGateway = false
            },
        )
    }

    if (showConnection) {
        ConnectionDialog(
            indicator = connectionIndicator(state),
            detail = state.subtitle(),
            host = repository.host(),
            onRetry = {
                showConnection = false
                recoveryViewModel.retry()
            },
            onChangeGateway = {
                showConnection = false
                showGateway = true
            },
            onRepair = {
                showConnection = false
                onRepair()
            },
            onDismiss = { showConnection = false },
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    // The clock is read here, inside the title, and not at the
                    // screen's top level: a value read at the top would make the
                    // whole one recompose on every tick — the triage list
                    // included — for a subtitle that changes once a minute.
                    val now = rememberNowMillis()
                    val indicator = connectionIndicator(state)
                    Column {
                        Text(
                            text = stringResource(R.string.triage_title),
                            style = MaterialTheme.typography.titleLarge,
                        )
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            // The connection is always visible here, whatever the
                            // body shows, and tapping it opens the fixes.
                            ConnectionPill(
                                light = indicator.light,
                                text = indicator.label,
                                onClick = { showConnection = true },
                            )
                            state.subtitle(now)?.let { subtitle ->
                                Spacer(Modifier.width(Spacing.sm))
                                Text(
                                    text = subtitle,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    }
                },
                actions = {
                    TextButton(onClick = { showDevices = true }) { Text("Dispositivos") }
                    TextButton(onClick = { showGateway = true }) { Text("Gateway") }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
    ) { insets ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(insets),
        ) {
            when (val current = state) {
                is ConnectionState.Unpaired -> Message(
                    R.string.state_unauthorized_title,
                    R.string.state_unauthorized_body,
                )

                is ConnectionState.Connecting -> Message(
                    R.string.state_connecting,
                    R.string.state_connecting,
                    loading = true,
                )

                is ConnectionState.Failed -> NoConnectionScreen(
                    state = recoveryState,
                    onActivateTailscale = { openTailscale(context) },
                    onRetry = recoveryViewModel::retry,
                    onRepair = onRepair,
                )

                is ConnectionState.Offline -> if (current.lastKnown.isEmpty) {
                    NoConnectionScreen(
                        state = recoveryState,
                        onActivateTailscale = { openTailscale(context) },
                        onRetry = recoveryViewModel::retry,
                        onRepair = onRepair,
                    )
                } else {
                    TriageList(
                        state = current.lastKnown,
                        onOpen = { viewModel.onOpenAgent(it.paneId) },
                        onNewChat = viewModel::onOpenNewChat,
                    )
                }

                is ConnectionState.Live -> TriageList(
                    state = current.state,
                    onOpen = { viewModel.onOpenAgent(it.paneId) },
                    onNewChat = viewModel::onOpenNewChat,
                )
            }
        }
    }
}

@Composable
private fun Message(
    titleRes: Int,
    bodyRes: Int,
    loading: Boolean = false,
    onChangeGateway: (() -> Unit)? = null,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(Spacing.xl),
        contentAlignment = Alignment.Center,
    ) {
        StateBlock(
            icon = {
                if (loading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(28.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                } else {
                    Icon(
                        imageVector = Icons.Filled.CloudOff,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            title = stringResource(titleRes),
            body = stringResource(bodyRes),
            // A failed connection is often the address, not the host: a Tailscale
            // name that moved. Offering the change here is the fix for that case.
            action = if (onChangeGateway != null) {
                { TextButton(onClick = onChangeGateway) { Text("Cambiar gateway") } }
            } else {
                null
            },
        )
    }
}

/**
 * Android 13+ shows nothing until the user grants POST_NOTIFICATIONS, and a push
 * that is silently dropped looks exactly like a broken backend. Ask once — with
 * a short reason first — and, when the system will no longer show the dialog,
 * send the person to the settings page instead of asking into the void.
 *
 * Postponing ("Ahora no", outside tap) must actually close the dialog: the old
 * code only flipped a flag that was already true, so no recomposition came and
 * the dialog could not be dismissed. It is now a persisted timestamp that
 * suppresses the prompt until the cooldown expires or an explicit attempt at
 * the permission retires it.
 */
@Composable
private fun NotificationPermissionPrompt() {
    val context = LocalContext.current
    val granted = ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.POST_NOTIFICATIONS,
    ) == PackageManager.PERMISSION_GRANTED
    // How many times the system dialog has returned a result — not a boolean.
    // "Already asked" plus a second refusal flips rationale to false without
    // changing the boolean, and a state that does not change does not
    // recompose: the dialog would keep the stale rationale on screen forever.
    // Bumping a counter on every result forces the fresh read; 0 = never asked.
    var systemResults by rememberSaveable { mutableStateOf(0) }
    val prefs = remember { context.getSharedPreferences(PROMPT_PREFS, Context.MODE_PRIVATE) }
    var dismissedAtMs by remember {
        mutableStateOf(prefs.getLong(KEY_DISMISSED_AT, 0L).takeIf { it > 0L })
    }
    val launcher = rememberLauncherForNotificationPermission { systemResults++ }
    val rationale = (context as? Activity)?.let {
        ActivityCompat.shouldShowRequestPermissionRationale(it, Manifest.permission.POST_NOTIFICATIONS)
    } ?: false

    val dismiss = {
        val now = System.currentTimeMillis()
        dismissedAtMs = now
        prefs.edit().putLong(KEY_DISMISSED_AT, now).apply()
    }
    val forgetDismissal = {
        dismissedAtMs = null
        prefs.edit().remove(KEY_DISMISSED_AT).apply()
    }

    when (
        NotificationPermissionPolicy.step(
            Build.VERSION.SDK_INT,
            granted,
            systemResults > 0,
            rationale,
            dismissedAtMs,
            System.currentTimeMillis(),
        )
    ) {
        // Suppressed is the same visible outcome as "nothing to do": no dialog.
        NotificationPermissionStep.NOT_NEEDED,
        NotificationPermissionStep.SUPPRESSED,
        -> return

        NotificationPermissionStep.ASK -> AlertDialog(
            onDismissRequest = dismiss,
            title = { Text(stringResource(R.string.notification_title)) },
            text = { Text(stringResource(R.string.notification_permission_rationale)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        forgetDismissal()
                        launcher()
                    },
                ) {
                    Text(stringResource(R.string.notification_permission_allow))
                }
            },
            dismissButton = {
                TextButton(onClick = dismiss) { Text("Ahora no") }
            },
        )

        NotificationPermissionStep.OPEN_SETTINGS -> AlertDialog(
            onDismissRequest = dismiss,
            title = { Text(stringResource(R.string.notification_blocked_title)) },
            text = { Text(stringResource(R.string.notification_blocked_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        openNotificationSettings(context)
                        forgetDismissal()
                    },
                ) { Text(stringResource(R.string.notification_open_settings)) }
            },
            dismissButton = {
                TextButton(onClick = dismiss) { Text("Ahora no") }
            },
        )
    }
}

private const val PROMPT_PREFS = "notification_prompt"
private const val KEY_DISMISSED_AT = "dismissed_at"

/** The app's own notification page. There is no more specific deep link. */
private fun openNotificationSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}


@Composable
private fun rememberLauncherForNotificationPermission(onResult: () -> Unit): () -> Unit {
    val launcher = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { onResult() }
    return { launcher.launch(Manifest.permission.POST_NOTIFICATIONS) }
}
