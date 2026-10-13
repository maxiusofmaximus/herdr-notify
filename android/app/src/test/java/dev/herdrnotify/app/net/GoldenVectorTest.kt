package dev.herdrnotify.app.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * Runs the *same* committed vectors as the Python suite.
 *
 * `gateway/tests/vectors/signing_vectors.json` is the contract. The Python test
 * (`gateway/tests/test_golden_vectors.py`) already reads it, and this one reads
 * it too rather than keeping a private Kotlin copy — a second copy is a second
 * contract, and the two would drift the first time someone edits one.
 *
 * This closes the gap the other Android tests leave. `RequestSignerTest` proves
 * Kotlin is internally consistent; this proves Kotlin and Python produce
 * identical bytes. Only this catches a divergence like a different body digest
 * encoding, a different newline convention, or a timestamp formatted as a float
 * — all of which leave each side's own tests green.
 */
class GoldenVectorTest {

    @Serializable
    private data class Vector(
        val name: String,
        val method: String,
        val target: String,
        val body: String,
        val timestamp: Long,
        val nonce: String,
        val expected: String,
    )

    @Serializable
    private data class VectorFile(val vectors: List<Vector>)

    private val json = Json {
        // The file carries a `_comment` and `encoding` key that are not part of
        // the contract, and it is documentation written for humans, so an
        // unknown key must not be an error.
        ignoreUnknownKeys = true
    }

    private fun vectorsFile(): File {
        // Walk up from the Gradle working directory to the repository root, so
        // the test works whether it is run from the repo root or from `android/`.
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            val candidate = File(dir, "gateway/tests/vectors/signing_vectors.json")
            if (candidate.isFile) return candidate
            dir = dir.parentFile
        }
        error(
            "signing_vectors.json not found from ${System.getProperty("user.dir")}; " +
                "the two language suites must share one file",
        )
    }

    private fun load(): VectorFile = json.decodeFromString(vectorsFile().readText())

    @Test
    fun `kotlin produces the bytes python expects`() {
        val vectors = load().vectors
        assertEquals("every committed vector must run here too", 6, vectors.size)

        vectors.forEach { vector ->
            val actual = String(
                RequestSigner.signingString(
                    method = vector.method,
                    target = vector.target,
                    body = vector.body.toByteArray(Charsets.UTF_8),
                    timestamp = vector.timestamp,
                    nonce = vector.nonce,
                ),
                Charsets.UTF_8,
            )
            assertEquals("vector '${vector.name}' does not match", vector.expected, actual)
        }
    }

    @Test
    fun `every vector name is covered so a new one cannot be skipped`() {
        // The Python suite asserts its own count. Asserting the names here as
        // well means adding a vector to the JSON and forgetting one side is a
        // visible failure rather than a vector that quietly runs in only one
        // language.
        val names = load().vectors.map { it.name }
        assertEquals(
            listOf(
                "read-state",
                "respond-unicode",
                "keys-confirm",
                "read-pane",
                "mark-seen",
                "empty-body-write",
            ).sorted(),
            names.sorted(),
        )
    }

    @Test
    fun `the empty body digest is the one both sides agree on`() {
        // The single most load-bearing constant in the format: it is what every
        // GET request signs, and it is the value a divergence is least likely
        // to be noticed in.
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            RequestSigner.bodyDigest(ByteArray(0)),
        )
        val readState = load().vectors.first { it.name == "read-state" }
        assertEquals("", readState.body)
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            RequestSigner.bodyDigest(readState.body.toByteArray(Charsets.UTF_8)),
        )
    }
}
