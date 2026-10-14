package dev.herdrnotify.app.ui

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * Every colour drawn on the code surface must be readable there.
 *
 * The code surface is a fixed dark slab in every theme, so its palette is fixed
 * too; the bug this pins is a token colour tuned for a light background ending
 * up on that slab. The check is the WCAG contrast ratio against the surface —
 * the same 4.5:1 a body of text is held to.
 */
class CodeContrastTest {

    @Test
    fun `every code colour clears 4_5 to 1 on the code surface`() {
        val surface = CodeColors.surface
        val colours = listOf(
            "plain" to CodeColors.plain,
            "keyword" to CodeColors.keyword,
            "string" to CodeColors.string,
            "comment" to CodeColors.comment,
            "number" to CodeColors.number,
            "diff added" to CodeColors.added,
            "diff removed" to CodeColors.removed,
            "diff meta" to CodeColors.meta,
            "diff context" to CodeColors.context,
        )

        colours.forEach { (name, colour) ->
            val ratio = contrastRatio(colour, surface)
            assertTrue(
                "$name has contrast $ratio against the surface, needs >= 4.5",
                ratio >= 4.5,
            )
        }
    }

    @Test
    fun `the known dark theme values pass`() {
        // A direct guard on the values that were hard to read when taken from the
        // light theme: the light `primary` is darker than the dark one.
        assertTrue(contrastRatio(Color(0xFF4C8DFF), CodeColors.surface) >= 4.5)
    }

    /** WCAG 2.x relative luminance. */
    private fun luminance(color: Color): Double {
        fun channel(value: Float): Double {
            val c = value.toDouble()
            return if (c <= 0.03928) c / 12.92 else ((c + 0.055) / 1.055).pow(2.4)
        }
        return 0.2126 * channel(color.red) +
            0.7152 * channel(color.green) +
            0.0722 * channel(color.blue)
    }

    private fun contrastRatio(a: Color, b: Color): Double {
        val la = luminance(a)
        val lb = luminance(b)
        val lighter = max(la, lb)
        val darker = min(la, lb)
        return (lighter + 0.05) / (darker + 0.05)
    }
}
