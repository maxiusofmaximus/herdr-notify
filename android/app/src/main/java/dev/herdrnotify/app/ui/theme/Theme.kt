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

/** The three grounds, from the page down to the raised field on top of a card. */
val Surface0 = Color(0xFF0E1116)
val Surface1 = Color(0xFF161B22)
val Surface2 = Color(0xFF1C2430)
val Surface3 = Color(0xFF232D3B)
val OutlineSoft = Color(0xFF2A3340)
val OutlineStrong = Color(0xFF3A4657)
val TextPrimary = Color(0xFFE6EDF3)
val TextSecondary = Color(0xFFA9B4C0)
val TextMuted = Color(0xFF8B949E)
val AccentBlue = Color(0xFF4C8DFF)
val AccentBlueSoft = Color(0xFF12243F)

/** Spacing scale. A 4dp grid, named so layouts do not invent their own. */
object Spacing {
    val xxs = 2.dp
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

    /**
     * The same hue, lifted where the status word is *text*.
     *
     * `idle` is the muted grey that reads as a dot but falls under 4.5:1 as a
     * label; the word carries the meaning for anyone who cannot use the colour,
     * so it gets the readable grey instead.
     */
    fun label(status: AgentStatus): Color = when (status) {
        AgentStatus.IDLE -> TextMuted
        else -> forStatus(status)
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
 *
 * Every role the app actually names is defined here. Leaving one out is how a
 * heading silently falls back to a Material default at the wrong size.
 */
private val HerdrTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.SemiBold,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        letterSpacing = (-0.3).sp,
    ),
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
    titleSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 19.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 23.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 17.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.2.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
        letterSpacing = 0.4.sp,
    ),
)

/** Monospace for keys, fingerprints, commands and raw terminal text. */
val MonoKey = TextStyle(
    fontFamily = FontFamily.Monospace,
    fontWeight = FontWeight.Normal,
    fontSize = 13.sp,
    lineHeight = 20.sp,
)

private val DarkColors = darkColorScheme(
    primary = AccentBlue,
    onPrimary = Color.White,
    primaryContainer = AccentBlueSoft,
    onPrimaryContainer = Color(0xFFC9DEFF),
    background = Surface0,
    onBackground = TextPrimary,
    surface = Surface1,
    onSurface = TextPrimary,
    surfaceVariant = Surface2,
    onSurfaceVariant = TextSecondary,
    surfaceContainerLowest = Surface0,
    surfaceContainerLow = Surface1,
    surfaceContainer = Surface1,
    surfaceContainerHigh = Surface2,
    surfaceContainerHighest = Surface3,
    surfaceTint = Color.Transparent,
    outline = OutlineSoft,
    outlineVariant = OutlineStrong,
    error = StatusBlocked,
    onError = Color(0xFF3A0A0A),
    errorContainer = Color(0xFF3A1116),
    onErrorContainer = Color(0xFFFFD9D9),
    inverseSurface = TextPrimary,
    inverseOnSurface = Surface0,
    scrim = Color(0xCC000000),
)

/**
 * Light is kept only so the token set is total; the product is dark-first.
 *
 * The phone reads beside a dark terminal, often outdoors at night, and the status
 * colours were chosen against a dark ground. [HerdrNotifyTheme] ignores the system
 * setting by default, so a phone in light mode no longer paints light Material
 * surfaces over the dark window background — which is what split the app's cards
 * from its own frame.
 */
private val LightColors = lightColorScheme(
    primary = Color(0xFF1F6FEB),
    background = Color(0xFFF7F9FC),
    surface = Color.White,
    surfaceVariant = Color(0xFFEAEEF3),
    onSurface = Color(0xFF0E1116),
    onSurfaceVariant = Color(0xFF57606A),
    outline = Color(0xFFD5DBE3),
    outlineVariant = Color(0xFFC6CDD6),
    error = Color(0xFFCF222E),
)

/** Truncation that keeps the tail, which is where a task title's verb is. */
val EllipsisMiddle = TextOverflow.Ellipsis

@Composable
fun HerdrNotifyTheme(
    darkTheme: Boolean = true,
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

/** Explicitly the system preference, for the one caller that wants it. */
@Composable
fun systemDarkTheme(): Boolean = isSystemInDarkTheme()
