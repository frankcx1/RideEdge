import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
// A server address is configuration, never a credential. API keys stay on the server.
val rideEdgeOrigin = providers.gradleProperty("rideedgeOrigin")
    .orElse("https://rideedge.example.com").get().trimEnd('/')
val parsedOrigin = URI(rideEdgeOrigin)
require(parsedOrigin.scheme == "https" && parsedOrigin.host != null &&
    parsedOrigin.rawUserInfo == null && parsedOrigin.rawQuery == null &&
    parsedOrigin.rawFragment == null && parsedOrigin.rawPath.isNullOrEmpty()) {
    "rideedgeOrigin must be a single HTTPS origin, without credentials or a path"
}
android {
    namespace = "com.rideedge.app"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.rideedge.app"
        minSdk = 35
        targetSdk = 36
        versionCode = 11
        versionName = "2.5.2"
        buildConfigField("String", "RIDEEDGE_ORIGIN", "\"$rideEdgeOrigin\"")
    }
    buildFeatures { compose = true; buildConfig = true }
    buildTypes {
        create("preview") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".preview"
            versionNameSuffix = "-fixture"
            matchingFallbacks += listOf("debug")
            resValue("string", "app_name", "RideEdge Preview")
        }
    }
    sourceSets.getByName("test").resources.srcDir("../../fixtures/contracts")
    sourceSets.getByName("preview").assets.srcDir("../../fixtures/contracts")
    testOptions.unitTests.isIncludeAndroidResources = true
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { jvmToolchain(17) }
dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.0")
    implementation("androidx.car.app:app:1.7.0")
    implementation("androidx.car.app:app-projected:1.7.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20231013")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    testImplementation("androidx.car.app:app-testing:1.7.0")
    testImplementation("org.robolectric:robolectric:4.16.1")
}
