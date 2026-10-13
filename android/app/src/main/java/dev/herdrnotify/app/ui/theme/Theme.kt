package dev.herdrnotify.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.herdrnotify.app.domain.AgentStatus

/**
 * The status colours are herdr's, not a fresh palette.
 *
 * The terminal and the phone must read as one system: a developer glancing at the
 * phone and then at the terminal should not have to re-learn what red means. So
 * these are the same meanings herdr uses in its own sidebar, carried over rather
 * than redesigned.
 *
 * Dynamic colour is deliberately off. A wallpaper-derived scheme would let the
 * status colours shift into something that no longer means "needs you", and the
 * colour *is* the information here.
 */
val StatusBlocked = Color(0xFFFF6B6B)
val StatusWorking = Color(0xFF4C8DFF)
val StatusDone = Color(0xFF3FB950)
val StatusIdle = Color(0xFF6E7681)
val StatusUnknown = Color(0xFF8B949E)

val Surface0 = Color(0xFF0E1116)
val Surface1 = Color(0xFF161B22)
val Surface2 = Color(0xFF1C2430)
val OutlineSoft = Color(0xFF2A3340)
val TextPrimary = Color(0xFFE6EDF3)
val TextSecondary = Color(0xFF9AA5B1)
val AccentBlue = Color(0xFF4C8DFF)

/** Spacing scale. A 4dp grid, named so layouts do not invent their own. */
object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
}

data class StatusColors(
    val blocked: Color,
    val working: Color,
    val done: Color,
    val idle: Color,
    val unknown: Color,
) {
    fun forStatus(status: AgentStatus): Color = when (status) {
        AgentStatus.BLOCKED -> blocked
        AgentStatus.WORKING -> working
        AgentStatus.DONE -> done
        AgentStatus.IDLE -> idle
        AgentStatus.UNKNOWN -> unknown
    }
}

val LocalStatusColors = staticCompositionLocalOf {
    StatusColors(StatusBlocked, StatusWorking, StatusDone, StatusIdle, StatusUnknown)
}

/**
 * Type scale tuned for a glance.
 *
 * Project names are the primary scanning target, so they get the weight and the
 * tight line height. Task titles truncate rather than wrap: a two-line card
 * doubles the height of the list for text most people will not read on a phone.
 */
private val HerdrTypography = Typography(
    titleLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.SemiBold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        letterSpacing = (-0.2).sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 21.sp,
        letterSpacing = (-0.1).sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 19.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 18.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
        letterSpacing = 0.4.sp,
    ),
)

private val DarkColors = darkColorScheme(
    primary = AccentBlue,
    onPrimary = Color.White,
    background = Surface0,
    onBackground = TextPrimary,
    surface = Surface1,
    onSurface = TextPrimary,
    surfaceVariant = Surface2,
    onSurfaceVariant = TextSecondary,
    outline = OutlineSoft,
    error = StatusBlocked,
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF1F6FEB),
    background = Color(0xFFF7F9FC),
    surface = Color.White,
    onSurface = Color(0xFF0E1116),
    onSurfaceVariant = Color(0xFF57606A),
    outline = Color(0xFFD5DBE3),
    error = Color(0xFFCF222E),
)

/** Truncation that keeps the tail, which is where a task title's verb is. */
val EllipsisMiddle = TextOverflow.Ellipsis

@Composable
fun HerdrNotifyTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    CompositionLocalProvider(
        LocalStatusColors provides StatusColors(
            blocked = StatusBlocked,
            working = StatusWorking,
            done = StatusDone,
            idle = StatusIdle,
            unknown = StatusUnknown,
        ),
    ) {
        MaterialTheme(
            colorScheme = if (darkTheme) DarkColors else LightColors,
            typography = HerdrTypography,
            content = content,
        )
    }
}
