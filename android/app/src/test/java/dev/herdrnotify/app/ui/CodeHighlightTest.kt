package dev.herdrnotify.app.ui

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The highlighter's contract: it colours what it recognises, leaves the rest
 * alone, and — critically — never drops or reorders a character.
 */
class CodeHighlightTest {

    @Test
    fun `kotlin keywords, numbers and comments are classified`() {
        val spans = CodeHighlighter.tokenizeLine("val x = 3 // nota", "kotlin")
        val byText = spans.associate { it.text to it.token }

        assertEquals(CodeToken.KEYWORD, byText["val"])
        assertEquals(CodeToken.NUMBER, byText["3"])
        assertEquals(CodeToken.COMMENT, byText["// nota"])
    }

    @Test
    fun `a python hash comment is a comment`() {
        val spans = CodeHighlighter.tokenizeLine("x = 1  # hola", "python")

        assertTrue(spans.any { it.token == CodeToken.COMMENT && it.text.contains("# hola") })
    }

    @Test
    fun `a string is one span and does not swallow the rest of the line`() {
        val spans = CodeHighlighter.tokenizeLine("echo \"hi there\" done", "shell")

        assertTrue("expected the quoted run: $spans", spans.any { it.token == CodeToken.STRING && it.text == "\"hi there\"" })
        assertTrue("the trailing word must survive: $spans", spans.any { it.token == CodeToken.KEYWORD && it.text == "done" })
    }

    @Test
    fun `a hash inside a string is not a comment`() {
        val spans = CodeHighlighter.tokenizeLine("x = \"# no es comentario\"", "python")

        assertTrue(spans.any { it.token == CodeToken.STRING })
        assertTrue("no comment may be detected inside a string: $spans", spans.none { it.token == CodeToken.COMMENT })
    }

    @Test
    fun `an unknown language is still tokenised, never dropped`() {
        val line = "fun main() { println(\"hola\") } // x"

        val spans = CodeHighlighter.tokenizeLine(line, null)

        assertEquals("tokenising must be lossless", line, spans.joinToString("") { it.text })
        assertTrue(spans.any { it.token == CodeToken.KEYWORD && it.text == "fun" })
    }

    @Test
    fun `a diff is never highlighted as keywords`() {
        val spans = CodeHighlighter.tokenizeLine("- val x", "diff")

        assertEquals(listOf(CodeSpan("- val x", CodeToken.PLAIN)), spans)
    }

    @Test
    fun `an unterminated quote does not swallow the line`() {
        val line = "val s = \"unterminated"

        assertEquals(line, CodeHighlighter.tokenizeLine(line, "kotlin").joinToString("") { it.text })
    }

    private val palette = CodePalette(
        keyword = Color(0xFF111111),
        string = Color(0xFF222222),
        comment = Color(0xFF333333),
        number = Color(0xFF444444),
    )

    @Test
    fun `annotating a line paints keyword, number and comment spans`() {
        val line = "val x = 3 // nota"

        val annotated = annotateLine(line, "kotlin", palette)
        val colors = annotated.spanStyles.map { it.item.color }

        assertEquals("the text must survive untouched", line, annotated.text)
        assertTrue("keyword span missing: $annotated", colors.contains(palette.keyword))
        assertTrue("number span missing: $annotated", colors.contains(palette.number))
        assertTrue("comment span missing: $annotated", colors.contains(palette.comment))
    }

    @Test
    fun `annotating paints string spans`() {
        val annotated = annotateLine("val s = \"hola\"", "kotlin", palette)
        val colors = annotated.spanStyles.map { it.item.color }

        assertTrue("string span missing: $annotated", colors.contains(palette.string))
        assertTrue("keyword span missing: $annotated", colors.contains(palette.keyword))
    }

    @Test
    fun `a plain line produces no colour spans`() {
        val annotated = annotateLine("total = suma de cosas", null, palette)

        // No keyword/string/comment/number tokens: nothing should be coloured,
        // so a highlighted block is never uniformly painted.
        assertTrue("plain prose must not be coloured: ${annotated.spanStyles}", annotated.spanStyles.isEmpty())
    }
}
