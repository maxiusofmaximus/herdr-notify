package dev.herdrnotify.app.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import dev.herdrnotify.app.ui.theme.AccentBlue
import dev.herdrnotify.app.ui.theme.StatusBlocked
import dev.herdrnotify.app.ui.theme.StatusDone
import dev.herdrnotify.app.ui.theme.Surface2
import dev.herdrnotify.app.ui.theme.TextPrimary
import dev.herdrnotify.app.ui.theme.TextSecondary

/**
 * A tiny, line-at-a-time syntax highlighter.
 *
 * The pane tail carries code as plain text, and dropping it into a monospaced
 * bubble loses the one thing that makes a snippet scannable: what is a comment,
 * what is a string, what is a keyword. This tokenizer recovers just enough of
 * that to colour a line, and nothing more — it is deliberately not a parser, and
 * a language it has never heard of is rendered plainly rather than wrongly.
 *
 * It is pure and line-based so it can be unit-tested without Compose: the
 * composable maps the tokens to colours, and the classification lives here.
 */
enum class CodeToken { PLAIN, KEYWORD, STRING, COMMENT, NUMBER }

/** A run of a line and how it should be drawn. */
data class CodeSpan(val text: String, val token: CodeToken)

/**
 * The four colours a code line is painted with.
 *
 * A plain value type rather than reading the theme directly, so the annotation
 * is a pure function that can be tested for the spans it actually produces —
 * the point of the whole exercise being that the colours reach the text.
 */
data class CodePalette(
    val keyword: Color,
    val string: Color,
    val comment: Color,
    val number: Color,
)

/**
 * The colours code is drawn with, fixed to the dark ground the code surface
 * always uses.
 *
 * A code block is a dark slab in *every* theme, so its palette must be the
 * light-on-dark one — the theme's own `primary`/`error` are tuned for a light
 * background and, over a dark slab, are the low-contrast pair that made `fun`
 * and the diff routes hard to read in the light theme. Kept here as plain values
 * so a test can check each one against the surface; they are deliberately *not*
 * read from [androidx.compose.material3.MaterialTheme].
 */
object CodeColors {
    /** The code surface itself, the ground every colour below is checked against. */
    val surface: Color = Surface2
    val plain: Color = TextPrimary
    val keyword: Color = AccentBlue
    val string: Color = StatusDone
    val comment: Color = TextSecondary
    val number: Color = Color(0xFFD29922)

    // Diff line colours, on the same ground.
    val added: Color = StatusDone
    val removed: Color = StatusBlocked
    val meta: Color = AccentBlue
    val context: Color = TextSecondary
}

/**
 * Colour one line: the tokenizer's spans mapped onto [palette].
 *
 * Kept out of the composable on purpose. "The block rendered white even though
 * it said Resaltado" is a claim about spans, so the thing that builds the spans
 * is a plain function a unit test can inspect, not something reachable only
 * through a Composable.
 */
fun annotateLine(line: String, language: String?, palette: CodePalette): AnnotatedString =
    buildAnnotatedString {
        CodeHighlighter.tokenizeLine(line, language).forEach { span ->
            val style = when (span.token) {
                CodeToken.PLAIN -> null
                CodeToken.KEYWORD -> SpanStyle(color = palette.keyword)
                CodeToken.STRING -> SpanStyle(color = palette.string)
                CodeToken.COMMENT -> SpanStyle(color = palette.comment)
                CodeToken.NUMBER -> SpanStyle(color = palette.number)
            }
            if (style == null) append(span.text) else withStyle(style) { append(span.text) }
        }
    }

object CodeHighlighter {

    /**
     * Words coloured as keywords, pooled across the languages a coding agent is
     * likely to print.
     *
     * One union rather than a table per language: a false positive inside a code
     * block costs nothing (an identifier tinted as a keyword still reads), while
     * a per-language table that is missing a language would leave a whole
     * snippet flat. The union is the honest trade for a highlighter this size.
     */
    private val KEYWORDS: Set<String> = setOf(
        // Kotlin / Java / C-like
        "fun", "val", "var", "when", "if", "else", "for", "while", "return", "class",
        "object", "interface", "data", "sealed", "enum", "import", "package", "private",
        "public", "protected", "internal", "override", "suspend", "in", "is", "as",
        "null", "true", "false", "this", "super", "try", "catch", "finally", "throw",
        "new", "do", "static", "void", "int", "long", "double", "float", "char", "bool",
        "boolean", "string", "final", "const", "struct", "switch", "case", "default",
        "break", "continue", "extends", "implements", "instanceof", "typeof", "interface",
        // Python / Ruby
        "def", "elif", "lambda", "None", "True", "False", "self", "from", "with", "yield",
        "async", "await", "match", "pass", "raise", "global", "nonlocal", "assert", "del",
        "except", "not", "and", "or", "end", "then", "do", "nil",
        // JavaScript / TypeScript
        "function", "let", "export", "type", "interface",
        // Rust / Go / shell / SQL
        "fn", "pub", "use", "mod", "mut", "ref", "impl", "trait", "loop", "where",
        "unsafe", "dyn", "move", "echo", "fi", "done", "esac", "select", "insert",
        "update", "delete", "join", "into", "values", "create", "table", "where",
    )

    /** Languages where `#` opens a comment. */
    private val HASH_COMMENT = setOf(
        "python", "py", "sh", "bash", "shell", "zsh", "fish", "yaml", "yml", "toml",
        "r", "ruby", "rb", "perl", "pl", "makefile", "dockerfile", "conf",
    )

    /** Languages where `--` opens a comment. */
    private val DASH_COMMENT = setOf("sql", "lua", "haskell", "hs", "ada")

    /** Languages that are data or diffs, where colouring words as keywords lies. */
    private val NO_KEYWORDS = setOf("diff", "patch", "text", "txt", "plain", "log", "csv")

    /** Tokenise one line. An unknown language degrades to a plain run. */
    fun tokenizeLine(line: String, language: String?): List<CodeSpan> {
        val lang = language?.trim()?.lowercase().orEmpty()
        if (lang in NO_KEYWORDS) return listOf(CodeSpan(line, CodeToken.PLAIN))

        val spans = mutableListOf<CodeSpan>()
        val plain = StringBuilder()
        var i = 0

        fun flush() {
            if (plain.isNotEmpty()) {
                spans += CodeSpan(plain.toString(), CodeToken.PLAIN)
                plain.clear()
            }
        }

        while (i < line.length) {
            val c = line[i]

            // Comments run to the end of the line, so they are the last thing a
            // line can contain and cut the scan short.
            val commentAt = commentIndex(line, i, lang, lineStartsHere = i == 0)
            if (commentAt == i) {
                flush()
                spans += CodeSpan(line.substring(i), CodeToken.COMMENT)
                return spans
            }

            if (c == '"' || c == '\'' || (c == '`' && lang in setOf("js", "javascript", "ts", "typescript"))) {
                val end = stringEnd(line, i, c)
                // An unterminated quote is almost always wrapped code; treat it
                // as plain so the rest of the line is not swallowed as a string.
                if (end > i) {
                    flush()
                    spans += CodeSpan(line.substring(i, end), CodeToken.STRING)
                    i = end
                    continue
                }
            }

            if (c.isDigit() && (plain.isEmpty() || !plain.last().isLetterOrDigit() && plain.last() != '_')) {
                var j = i
                while (j < line.length && (line[j].isLetterOrDigit() || line[j] == '.' || line[j] == '_')) j++
                flush()
                spans += CodeSpan(line.substring(i, j), CodeToken.NUMBER)
                i = j
                continue
            }

            if (c.isLetter() || c == '_') {
                var j = i
                while (j < line.length && (line[j].isLetterOrDigit() || line[j] == '_')) j++
                val word = line.substring(i, j)
                if (word in KEYWORDS) {
                    flush()
                    spans += CodeSpan(word, CodeToken.KEYWORD)
                } else {
                    plain.append(word)
                }
                i = j
                continue
            }

            plain.append(c)
            i++
        }
        flush()
        return spans
    }

    /** The index where a comment opens at or after [from], or [line.length]. */
    private fun commentIndex(line: String, from: Int, language: String, lineStartsHere: Boolean): Int {
        val hash = if (language in HASH_COMMENT) {
            line.indexOf('#', from)
        } else if (language.isEmpty() && lineStartsHere && line.startsWith("#")) {
            0
        } else {
            -1
        }
        val slashes = if (language !in NO_KEYWORDS) line.indexOf("//", from) else -1
        val dashes = if (language in DASH_COMMENT) line.indexOf("--", from) else -1
        return listOf(hash, slashes, dashes).filter { it >= 0 }.minOrNull() ?: line.length
    }

    /** The index just past the string opened at [start], or [start] if unclosed. */
    private fun stringEnd(line: String, start: Int, quote: Char): Int {
        var i = start + 1
        while (i < line.length) {
            val c = line[i]
            if (c == '\\' && quote != '`') {
                i += 2
                continue
            }
            if (c == quote) return i + 1
            i++
        }
        return start
    }
}
