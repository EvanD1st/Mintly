package com.mintly.mintly

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val sessionWorker = Executors.newSingleThreadExecutor()
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val vault = SecureSessionVault(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "mintly/secure-session").setMethodCallHandler { call, result ->
            if (call.method !in setOf("read", "save", "clear")) { result.notImplemented(); return@setMethodCallHandler }
            sessionWorker.execute {
                try {
                    val value = when (call.method) {
                        "read" -> vault.read()
                        "save" -> { vault.save(call.argument<String>("token") ?: "", call.argument<String>("expires_at") ?: "", call.argument<String>("origin") ?: ""); true }
                        else -> { vault.clear(); true }
                    }
                    runOnUiThread { result.success(value) }
                } catch (_: Exception) {
                    runOnUiThread { result.error("secure_session_unavailable", "Secure session storage is unavailable.", null) }
                }
            }
        }
    }
    override fun onDestroy() { sessionWorker.shutdown(); super.onDestroy() }
}
