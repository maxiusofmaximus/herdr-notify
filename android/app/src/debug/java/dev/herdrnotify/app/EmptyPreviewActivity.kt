package dev.herdrnotify.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import dev.herdrnotify.app.domain.SessionState
import dev.herdrnotify.app.ui.TriageList
import dev.herdrnotify.app.ui.theme.HerdrNotifyTheme

/**
 * Debug-only: renders the triage list with no agents.
 *
 * The real empty state needs a host with nothing running, which a UI pass rarely
 * has. This draws the *real* [TriageList] with [SessionState.EMPTY] so the
 * enriched empty state can be inspected on a device.
 *
 * Launch: `adb shell am start -n <applicationId>/dev.herdrnotify.app.EmptyPreviewActivity`
 */
class EmptyPreviewActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            HerdrNotifyTheme {
                Surface(
                    modifier = Modifier
                        .fillMaxSize()
                        .windowInsetsPadding(WindowInsets.systemBars),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    TriageList(state = SessionState.EMPTY, onOpen = {}, onNewChat = {})
                }
            }
        }
    }
}
