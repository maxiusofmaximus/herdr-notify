package dev.herdrnotify.app.ui

/**
 * Turns the agent's terminal tail into something a phone can read as a chat.
 *
 * The gateway hands back the last few dozen lines of the pane exactly as the
 * terminal drew them: hard-wrapped to the PC's column count and interleaved with
 * Claude Code's own chrome — the `❯` input line, `────` rules, `✻ Cogitated for
 * …` spinners, the `⏵⏵ bypass permissions…` status bar, `6% until auto-compact`,
 * and `recap:` summaries. Poured straight into a bubble that is a screenful of
 * noise, not a conversation, and the noise buries the one line that matters.
 *
 * opencode is worse still: its tail also carries the sidebar and footer it draws
 * beside the conversation — the `MCP`/`LSP`/`Context` sections, their `• … Disabled`
 * entries, the `⬒ Build · …` status line, the `▁▁▁` context meter and the
 * `OpenCode x.y.z` version — all mixed into the agent's own words.
 *
 * This parser is deliberately heuristic, and says so: the pane is a *rendered
 * screen*, not a message log, so there is no authoritative speaker marker to
 * read. It groups visible text into turns, folds the chrome into small status
 * rows (or drops it), and de-wraps the terminal's line breaks. It never throws
 * and never drops the person's own words; the untouched tail stays available
 * under "Salida cruda", so a misread costs a tap and not information.
 */
sealed interface TranscriptEntry {
    /** The readable text of the turn, already de-wrapped and trimmed. */
    val text: String

    /** Something the person typed, drawn as their own bubble. */
    data class User(override val text: String) : TranscriptEntry

    /** What the agent printed, drawn as the agent's bubble. */
    data class Agent(override val text: String) : TranscriptEntry

    /** Terminal chrome or a progress line, drawn as a quiet centred row. */
    data class Status(override val text: String, val kind: StatusKind) : TranscriptEntry

    /**
     * A blocking permission dialog the agent is waiting on, drawn as a card of
     * buttons. It is not a turn and not chrome: it is a question with answers,
     * and the whole point of the phone is to be able to answer it.
     */
    data class Permission(val prompt: PermissionPrompt) : TranscriptEntry {
        override val text: String get() = prompt.detail ?: prompt.title
    }

    /**
     * A file-change diff the agent printed, drawn as its own block rather than
     * poured into a bubble: the `+`/`-` structure is the information, and
     * de-wrapping it into prose destroys it.
     */
    data class Changes(val lines: List<ChangeLine>) : TranscriptEntry {
        override val text: String get() = lines.joinToString("\n") { it.text }
    }

    /**
     * A fenced code block the agent printed, drawn as a card with a copy button.
     *
     * [language] is whatever the opening fence named (`kotlin`, `python`, …), or
     * null when it named nothing; the body is kept exactly as the terminal drew
     * it, because a code block is the one thing de-wrapping would corrupt.
     */
    data class Code(val language: String?, val code: String) : TranscriptEntry {
        override val text: String get() = code
    }
}

enum class ChangeKind { ADDED, REMOVED, CONTEXT, META }

data class ChangeLine(val kind: ChangeKind, val text: String)

enum class StatusKind {
    /** `Cogitated for 59s · done 11:44`, `6% until auto-compact`. */
    PROGRESS,

    /** A `recap:` block, kept because it is a summary, not noise. */
    RECAP,

    /** The input hint and permission bar: `bypass permissions on…`. */
    CHROME,
}

/** Which agent's permission dialog was recognised, so the right keys are sent. */
enum class PermissionKind { OPENCODE, CLAUDE_CODE }

/**
 * One answer to a permission dialog: the label a person sees and the keystrokes
 * that choose it. [confirm] marks the answers that widen access "from now on",
 * which the screen asks about again before sending — a yes that cannot be taken
 * back deserves one more question.
 */
data class PermissionOption(
    val label: String,
    val keys: List<String>,
    val confirm: Boolean = false,
)

/**
 * A permission dialog found in the tail.
 *
 * [options] is fixed per [kind], because both TUIs present a known three-way
 * choice and the keystrokes are a property of the TUI, not of the text captured
 * off the screen. [detail] is whatever the screen said about *what* is being
 * granted, so the person is not approving blind.
 */
data class PermissionPrompt(
    val kind: PermissionKind,
    val detail: String?,
    val options: List<PermissionOption>,
) {
    val title: String get() = when (kind) {
        PermissionKind.OPENCODE -> "Permiso de opencode"
        PermissionKind.CLAUDE_CODE -> "Permiso de Claude Code"
    }

    companion object {
        /**
         * opencode draws `Allow once  Allow always  Reject` on one line, with the
         * first selected; `left`/`right` move the highlight and `enter` chooses.
         */
        val OPENCODE = listOf(
            PermissionOption("Permitir una vez", listOf("enter")),
            PermissionOption("Permitir siempre", listOf("right", "enter"), confirm = true),
            PermissionOption("Rechazar", listOf("right", "right", "enter")),
        )

        /**
         * Claude Code draws a numbered list; the number key answers it directly.
         * The wording differs by tool, so the option is labelled by its number.
         */
        val CLAUDE_CODE = listOf(
            PermissionOption("Sí", listOf("1")),
            PermissionOption("Sí, no volver a preguntar", listOf("2"), confirm = true),
            PermissionOption("No", listOf("3")),
        )
    }
}

object TranscriptParser {

    // A line that is nothing but a horizontal rule or a run of dashes.
    private val rule = Regex("^[\\s\\u2500\\u2501\\u2550\\u2551\\-=_]{3,}$")

    // Any line drawn entirely from box-drawing, block or bar glyphs: the `│`
    // column separators and the `▁▁▁` context meter that opencode paints beside
    // and under the conversation. Such a line has no text, only a shape.
    private val blockBar = Regex("^\\s*[\\u2500-\\u259F\\u25A0-\\u25FF|]+\\s*$")

    // The Claude Code input line: a chevron (or a shell `>`), then the text.
    private val prompt = Regex("^\\s*(?:\\u276F|>)\\s?(.*)$")

    // Spinner / bullet glyphs that decorate a line but are not its content.
    private val markerLead =
        Regex("^\\s*[\\u273B\\u2733\\u2736\\u2739\\u273D\\u2722\\u23FA\\u23F5\\u23F4\\u2022\\u2023\\u25CF\\u25CB\\u25AA\\u25AB\\u2502\\u2570\\u23BF]+\\s?")

    private val cogitated = Regex("\\b(?:Cogitated|Baked|Worked|Thought) for .+", RegexOption.IGNORE_CASE)
    private val done = Regex("\\bdone \\d{1,2}:\\d{2}\\b")
    private val autoCompact = Regex("^\\s*\\d{1,3}% until auto-compact", RegexOption.IGNORE_CASE)
    private val recap = Regex("^\\s*recap:\\s*(.*)$", RegexOption.IGNORE_CASE)

    // Literal fragments of Claude Code's chrome bar. Kept narrow on purpose: a
    // message that merely *talks about* interrupting (`"esc interrupt"`) is body
    // text, not the hint, so only the exact hint is matched. The bar wraps, so
    // its tail is recognised by its own ending rather than the whole phrase.
    private val chromeFragments = listOf(
        "esc to interrupt",
        "shift+tab to cycle",
        "bypass permissions",
        "accept edits on",
        "plan mode on",
    )
    private val chromeEndings = listOf("for agents")

    // opencode's sidebar and footer. Each is a rendering artefact with a stable
    // shape, so it is matched by shape rather than by position: the tail has no
    // reliable ordering between the sidebar column and the conversation column.
    private val opencodeSection = Regex("^\\s*(?:MCP|LSP|Context)\\s*$", RegexOption.IGNORE_CASE)
    private val opencodeEntry = Regex(
        "^\\s*[\\u2022\\u00b7]\\s*\\S+\\s+(?:disabled|enabled|connected|connecting|error|failed|gateway)\\s*$",
        RegexOption.IGNORE_CASE,
    )
    private val opencodeBuild = Regex("\\bBuild\\s+\\u00b7")
    private val opencodeVersion = Regex(
        "^\\s*[\\u2022\\u00b7]?\\s*OpenCode\\s+\\d+(?:\\.\\d+)+\\s*$",
        RegexOption.IGNORE_CASE,
    )
    private val opencodeMeter = Regex("\\bctrl\\+p\\b", RegexOption.IGNORE_CASE)
    private val opencodeHint = Regex("(?:ctrl\\+f|fullscreen|\\u21E5)", RegexOption.IGNORE_CASE)

    // The dialog's own key-hint row (`⇥ select  enter confirm`), which wraps onto
    // its own line. Only used to bound the permission block, so its words need not
    // be safe to match anywhere in the tail.
    private val permissionKeyHint =
        Regex("(?:ctrl\\+f|fullscreen|\\bselect\\b|\\bconfirm\\b|\\u21E5)", RegexOption.IGNORE_CASE)

    // A wrapped tail of the `Build · … · 9m 32s` line, left dangling when the
    // line it belongs to is dropped.
    private val durationFragment = Regex("^\\s*\\d+(?:\\.\\d+)?[smh]\\s*$")

    // A bare Windows path: the cwd the sidebar prints. Anchored tightly so an
    // agent sentence that merely contains a path is untouched.
    private val windowsPath = Regex("^\\s*[A-Za-z]:\\\\\\S*:?\\s*$")

    // -- permission dialogs ----------------------------------------------------
    private val permissionHeader = Regex("\\bpermission required\\b", RegexOption.IGNORE_CASE)
    private val allowOnce = Regex("\\ballow once\\b", RegexOption.IGNORE_CASE)

    private val claudeQuestion = Regex("\\bdo you want to proceed\\b", RegexOption.IGNORE_CASE)
    private val claudeYes = Regex("^\\s*[^A-Za-z0-9]*1[.)]\\s*Yes\\b", RegexOption.IGNORE_CASE)
    private val claudeAlways = Regex("^\\s*[^A-Za-z0-9]*2[.)]\\s*Yes\\b", RegexOption.IGNORE_CASE)
    private val claudeNo = Regex("^\\s*[^A-Za-z0-9]*3[.)]\\s*No\\b", RegexOption.IGNORE_CASE)

    private val listItem = Regex("^(?:[-*\\u2022\\u2023]|\\d+[.)])\\s")
    private val heading = Regex("^#{1,6}\\s")

    // A fenced code block: an opening run of backticks (optionally naming a
    // language) and a closing run. The tail is a rendered screen, not a message
    // log, so an unclosed fence is treated as ordinary text rather than guessed.
    private val fenceOpen = Regex("^\\s*```(.*)$")
    private val fenceClose = Regex("^\\s*```\\s*$")

    private sealed interface Token {
        data object Boundary : Token
        data class User(val text: String) : Token
        data class Agent(val text: String) : Token
        data class Status(val text: String, val kind: StatusKind) : Token
        data class Changes(val lines: List<ChangeLine>) : Token
        data class Code(val language: String?, val code: String) : Token
    }

    /** A permission block: the half-open line range it occupies, and its prompt. */
    private data class Detected(val start: Int, val end: Int, val prompt: PermissionPrompt)

    /** Parse a pane tail. A null or blank tail yields no entries. */
    fun parse(raw: String?): List<TranscriptEntry> {
        if (raw.isNullOrBlank()) return emptyList()
        val lines = raw.replace("\r\n", "\n").replace('\r', '\n').split('\n')

        // A permission dialog is lifted out before the line-by-line pass, so its
        // own chrome (the question, the option row, the key hints) never leaks
        // into the conversation *and* the dialog is not split across two turns.
        val detected = detectPermission(lines) ?: return assemble(parseTokens(lines))
        return assemble(parseTokens(lines.subList(0, detected.start))) +
            TranscriptEntry.Permission(detected.prompt) +
            assemble(parseTokens(lines.subList(detected.end, lines.size)))
    }

    /**
     * Find a permission dialog, opencode's first.
     *
     * opencode announces itself with a `Permission required` line and draws its
     * answers (`Allow once … Reject`) a few rows below; Claude Code asks with
     * `Do you want to proceed?` and its numbered answers, or (in some styles)
     * only the numbered answers. Either signature returns the block to excise and
     * the fixed keystrokes that answer it.
     */
    private fun detectPermission(lines: List<String>): Detected? =
        detectOpencodePermission(lines) ?: detectClaudePermission(lines)

    private fun detectOpencodePermission(lines: List<String>): Detected? {
        val header = lines.indexOfFirst { permissionHeader.containsMatchIn(it) }
        if (header < 0) return null
        val options = (header until minOf(lines.size, header + 14))
            .firstOrNull { allowOnce.containsMatchIn(lines[it]) }
        // The key hints (`ctrl+f fullscreen … enter confirm`) wrap onto their own
        // row after the option row; they belong to the dialog, so they go too.
        var end = if (options != null) options + 1 else header + 1
        while (end < lines.size && permissionKeyHint.containsMatchIn(lines[end])) end++
        val detail = lines.subList(header + 1, if (options != null) options else end)
            .map { clean(it).removePrefix("\u21B3").trim() }
            .filter { it.isNotEmpty() && !it.equals("Patterns", ignoreCase = true) }
            .joinToString(" · ")
            .ifBlank { null }
        return Detected(header, end, PermissionPrompt(PermissionKind.OPENCODE, detail, PermissionPrompt.OPENCODE))
    }

    private fun detectClaudePermission(lines: List<String>): Detected? {
        val question = lines.indexOfFirst { claudeQuestion.containsMatchIn(it) }
        val yes = lines.indexOfFirst { claudeYes.containsMatchIn(it) }
        val always = lines.indexOfFirst { claudeAlways.containsMatchIn(it) }
        val no = lines.indexOfFirst { claudeNo.containsMatchIn(it) }
        // The three answers must be present, in order. That ordering is what
        // separates the dialog from an agent that merely lists numbered steps.
        if (yes < 0 || always <= yes || no <= always) return null
        val start = if (question in 0 until yes && yes - question <= 8) question else yes
        val detail = lines.getOrNull(question)?.let { clean(it) }?.ifBlank { null }
        return Detected(start, no + 1, PermissionPrompt(PermissionKind.CLAUDE_CODE, detail, PermissionPrompt.CLAUDE_CODE))
    }

    private fun parseTokens(lines: List<String>): List<Token> {
        val tokens = mutableListOf<Token>()

        // A `recap:` block is one paragraph that the terminal wrapped, so its
        // first line opens a buffer and the rest of the paragraph joins it,
        // until a blank line or a rule ends the block.
        var recap: MutableList<String>? = null
        var i = 0
        while (i < lines.size) {
            val line = lines[i].trimEnd()
            if (recap != null) {
                if (line.isBlank() || rule.matches(line)) {
                    tokens += Token.Status(dewrap(recap), StatusKind.RECAP)
                    recap = null
                    tokens += Token.Boundary
                } else {
                    recap.add(stripMarkers(line))
                }
                i++
                continue
            }

            // A fenced code block is lifted out whole, so its body is never
            // de-wrapped or mistaken for prose. An unterminated fence falls
            // through to normal classification instead of swallowing the tail.
            fenceOpen.matchEntire(line)?.let { open ->
                val body = mutableListOf<String>()
                var j = i + 1
                var closed = false
                while (j < lines.size) {
                    if (fenceClose.matches(lines[j])) {
                        closed = true
                        j++
                        break
                    }
                    body += lines[j]
                    j++
                }
                if (closed) {
                    val language = open.groupValues[1].trim().takeIf { it.isNotEmpty() }
                    tokens += Token.Code(language, body.joinToString("\n"))
                    i = j
                    continue
                }
            }

            if (changeAnchor(line)) {
                val block = mutableListOf<ChangeLine>()
                var j = i
                while (j < lines.size && isChangeLine(lines[j])) {
                    block += changeLine(lines[j])
                    j++
                }
                if (block.any { it.kind == ChangeKind.ADDED } && block.any { it.kind == ChangeKind.REMOVED }) {
                    tokens += Token.Changes(block)
                    i = j
                    continue
                }
            }

            val token = classify(line)
            if (token is Token.Status && token.kind == StatusKind.RECAP) {
                recap = mutableListOf(token.text)
            } else {
                tokens += token
            }
            i++
        }
        recap?.let { tokens += Token.Status(dewrap(it), StatusKind.RECAP) }
        return tokens
    }

    private fun changeAnchor(line: String): Boolean =
        line.startsWith("@@") ||
            line.startsWith("+++ ") ||
            line.startsWith("--- ") ||
            line.startsWith("diff --git")

    private fun isChangeLine(line: String): Boolean =
        line.startsWith("@@") ||
            line.startsWith("+") ||
            line.startsWith("-") ||
            line.startsWith(" ")

    private fun changeLine(line: String): ChangeLine = ChangeLine(
        kind = when {
            line.startsWith("+++") || line.startsWith("---") ||
                line.startsWith("@@") || line.startsWith("diff ") -> ChangeKind.META

            line.startsWith("+") -> ChangeKind.ADDED
            line.startsWith("-") -> ChangeKind.REMOVED
            else -> ChangeKind.CONTEXT
        },
        text = line,
    )

    private fun classify(line: String): Token {
        if (line.isBlank() || rule.matches(line)) return Token.Boundary

        // opencode's own sidebar and footer are not turns: dropping them keeps
        // the conversation the person is actually having with the agent.
        if (isOpencodeChrome(line)) return Token.Boundary

        prompt.matchEntire(line)?.let {
            val rest = it.groupValues[1].trim()
            // A bare chevron is just the empty input box, not a turn.
            return if (rest.isEmpty()) Token.Boundary else Token.User(rest)
        }

        // The chrome glyphs (`✻`, `⏵⏵`) decorate a line rather than lead it, so
        // classification runs on the marker-stripped text.
        val stripped = stripMarkers(line)
        if (stripped.isEmpty()) return Token.Boundary

        recap.matchEntire(stripped)?.let {
            val body = it.groupValues[1].trim()
            return if (body.isEmpty()) Token.Boundary else Token.Status(body, StatusKind.RECAP)
        }

        val trimmed = stripped.trim()
        if (chromeFragments.any { line.contains(it, ignoreCase = true) } ||
            chromeEndings.any { trimmed.endsWith(it, ignoreCase = true) }
        ) {
            return Token.Status(clean(line), StatusKind.CHROME)
        }
        if (autoCompact.containsMatchIn(line)) {
            return Token.Status(clean(line), StatusKind.PROGRESS)
        }
        if (cogitated.containsMatchIn(line) || done.containsMatchIn(line)) {
            return Token.Status(clean(line), StatusKind.PROGRESS)
        }

        return Token.Agent(stripped)
    }

    /** True for the sidebar, footer and bar blocks opencode draws beside a turn. */
    private fun isOpencodeChrome(line: String): Boolean =
        blockBar.matches(line) ||
        opencodeSection.matches(line) ||
        opencodeEntry.matches(line) ||
        opencodeBuild.containsMatchIn(line) ||
        opencodeVersion.matches(line) ||
        opencodeMeter.containsMatchIn(line) ||
        opencodeHint.containsMatchIn(line) ||
        durationFragment.matches(line) ||
        windowsPath.matches(line)

    private fun assemble(tokens: List<Token>): List<TranscriptEntry> {
        val out = mutableListOf<TranscriptEntry>()
        val buffer = mutableListOf<String>()
        // A status line wrapped by the terminal arrives as two adjacent chrome
        // rows; they read as one, so they are stitched back together. A blank
        // line or a turn in between is a real break and stops the merge.
        var mergeStatus = false

        fun flushAgent() {
            if (buffer.isNotEmpty()) {
                out += TranscriptEntry.Agent(dewrap(buffer))
                buffer.clear()
                mergeStatus = false
            }
        }

        for (token in tokens) {
            when (token) {
                is Token.Boundary -> {
                    flushAgent()
                    mergeStatus = false
                }

                is Token.User -> {
                    flushAgent()
                    out += TranscriptEntry.User(dewrap(listOf(token.text)))
                    mergeStatus = false
                }

                is Token.Agent -> buffer += token.text

                is Token.Status -> {
                    flushAgent()
                    val previous = out.lastOrNull()
                    if (mergeStatus && previous is TranscriptEntry.Status &&
                        previous.kind == token.kind
                    ) {
                        out[out.lastIndex] = previous.copy(
                            text = "${previous.text.trim()} ${token.text.trim()}",
                        )
                    } else {
                        out += TranscriptEntry.Status(token.text, token.kind)
                    }
                    mergeStatus = true
                }

                is Token.Changes -> {
                    flushAgent()
                    out += TranscriptEntry.Changes(token.lines)
                    mergeStatus = false
                }

                is Token.Code -> {
                    flushAgent()
                    out += TranscriptEntry.Code(token.language, token.code)
                    mergeStatus = false
                }
            }
        }
        flushAgent()
        return out
    }

    private fun stripMarkers(line: String): String =
        markerLead.replace(line, "").trim()

    private fun clean(line: String): String =
        stripMarkers(line).replace(Regex("\\s{2,}"), " ").trim()

    /**
     * Rebuild paragraphs from the terminal's hard wraps.
     *
     * A pane wraps at the PC's column count, so a sentence arrives split across
     * lines; on a phone that reads as a poem. Blank lines still separate
     * paragraphs, and a bullet or a heading starts its own line, but everything
     * else is joined back into a flowing sentence.
     */
    private fun dewrap(lines: List<String>): String {
        val paragraphs = mutableListOf<MutableList<String>>()
        var current = mutableListOf<String>()
        for (line in lines) {
            val text = line.trim()
            if (text.isEmpty()) {
                if (current.isNotEmpty()) {
                    paragraphs += current
                    current = mutableListOf()
                }
            } else {
                current += text
            }
        }
        if (current.isNotEmpty()) paragraphs += current

        return paragraphs.joinToString("\n\n") { paragraph ->
            paragraph.fold(StringBuilder()) { acc, text ->
                when {
                    acc.isEmpty() -> acc.append(text)
                    listItem.containsMatchIn(text) || heading.containsMatchIn(text) ->
                        acc.append('\n').append(text)
                    else -> acc.append(' ').append(text)
                }
            }.toString()
        }
    }
}
