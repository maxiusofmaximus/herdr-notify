plugins {
    alias(libs.plugins.android.application) apply false
    // `org.jetbrains.kotlin.android` is intentionally absent: AGP 9 provides
    // Kotlin via built-in support, and applying both registers the `kotlin`
    // extension twice and fails configuration.
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.hilt) apply false
    alias(libs.plugins.ksp) apply false
}
