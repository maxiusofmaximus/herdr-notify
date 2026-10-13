# Keep the classes the platform and the SDKs reach by name. R8 cannot see these
# references, so a rename turns a working build into a runtime ClassNotFound.

# Room generates implementations that are looked up by name.
-keep class * extends androidx.room.RoomDatabase { <init>(); }
-keep @androidx.room.Entity class * { *; }
-dontwarn androidx.room.paging.**

# Hilt's generated components are instantiated reflectively.
-keep class dagger.hilt.** { *; }
-keep class * extends dagger.hilt.android.internal.managers.ViewComponentManager$FragmentContextWrapper

# OkHttp ships optional platform integrations that are absent at runtime.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# Kotlinx serialization generates a companion .serializer() per @Serializable
# class; renaming it silently breaks decoding at runtime.
-keepclassmembers class ** {
    *** Companion;
}
-keepclasseswithmembers class ** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class dev.herdrnotify.app.**$$serializer { *; }

# Line numbers make a release crash report readable, and the source file name
# is a deliberate trade: it is slightly more revealing than obfuscation alone,
# and worth it for a single-developer app.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
