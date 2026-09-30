plugins {
    id("com.android.application")
    id("com.google.gms.google-services") apply false
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

if (file("google-services.json").isFile) {
    apply(plugin = "com.google.gms.google-services")
}

android {
    namespace = "com.mintly.mintly"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.mintly.mintly"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    val releaseKeystorePath = System.getenv("MINTLY_KEYSTORE_PATH")
    val releaseKeystorePassword = System.getenv("MINTLY_KEYSTORE_PASSWORD")
    val releaseKeyPassword = System.getenv("MINTLY_KEY_PASSWORD")
    val releaseKeyAlias = System.getenv("MINTLY_KEY_ALIAS")
    val hasReleaseKey = listOf(releaseKeystorePath, releaseKeystorePassword,
        releaseKeyPassword, releaseKeyAlias).all { !it.isNullOrBlank() }
    if (hasReleaseKey) {
        signingConfigs {
            create("mintlyRelease") {
                storeFile = file(releaseKeystorePath!!)
                storePassword = releaseKeystorePassword!!
                keyAlias = releaseKeyAlias!!
                keyPassword = releaseKeyPassword!!
            }
        }
    }

    buildTypes {
        release {
            if (hasReleaseKey) signingConfig = signingConfigs.getByName("mintlyRelease")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
