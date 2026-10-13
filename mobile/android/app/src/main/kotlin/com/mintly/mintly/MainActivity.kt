package com.mintly.mintly

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private var authenticatedWindow = false
    private val sessionWorker = Executors.newSingleThreadExecutor()
    private val deviceUnlock by lazy { DeviceUnlock(this) }
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val vault = SecureSessionVault(applicationContext)
        val accounts = ProtectedAccountsVault(applicationContext)
        // UI preference only. All account identifiers and credentials stay in the
        // authenticated vault; this flag cannot bypass device authentication.
        val chooser = AccountChooserPreference(applicationContext)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "mintly/protected-accounts").setMethodCallHandler { call, result ->
            if (call.method == "capabilities") {
                result.success(mapOf("version" to 2, "device_secure" to accounts.deviceSecure(), "has_accounts" to accounts.hasAccounts(),
                    "has_legacy_session" to vault.hasSession(), "chooser_on_reopen" to
                    chooser.show(call.argument<String>("origin") ?: "")));return@setMethodCallHandler
            }
            if (call.method == "account_chooser") {
                val origin = call.argument<String>("origin") ?: ""
                if (!origin.startsWith("https://")) { result.error("invalid_origin", "Secure server required.", null);return@setMethodCallHandler }
                if (chooser.set(origin, call.argument<Boolean>("show") == true)) result.success(true)
                else result.error("storage_unavailable", "Could not save account selection.", null)
                return@setMethodCallHandler
            }
            if (call.method == "unlock") { deviceUnlock.request {
                if (it) { authenticatedWindow = true;window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE) }
                result.success(it)
            };return@setMethodCallHandler }
            if (call.method == "foreground_authenticated") {
                authenticatedWindow = true;window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);result.success(true);return@setMethodCallHandler
            }
            if (call.method !in setOf("accounts", "read", "save", "remove")) { result.notImplemented();return@setMethodCallHandler }
            if (!deviceUnlock.authorized()) { result.error("unlock_required", "Unlock your phone to access saved accounts.", null);return@setMethodCallHandler }
            sessionWorker.execute {
                try {
                    val origin = call.argument<String>("origin") ?: ""
                    val account = call.argument<String>("user_id") ?: ""
                    val value = when (call.method) {
                        "accounts" -> accounts.accounts(origin)
                        "read" -> accounts.read(origin, account)
                        "remove" -> { accounts.remove(origin, account);true }
                        else -> {
                            @Suppress("UNCHECKED_CAST")
                            accounts.save(call.arguments as Map<String, String>);true
                        }
                    }
                    runOnUiThread { result.success(value) }
                } catch (_: Exception) { runOnUiThread { result.error("protected_accounts_unavailable", "Unlock again or sign in with your password.", null) } }
            }
        }
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
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        if (!deviceUnlock.activityResult(requestCode, resultCode)) super.onActivityResult(requestCode, resultCode, data)
    }
    override fun onPause() { window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);super.onPause() }
    override fun onResume() {
        super.onResume()
        if (authenticatedWindow || !(getSystemService(android.content.Context.KEYGUARD_SERVICE) as android.app.KeyguardManager).isDeviceSecure)
            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
    }
    override fun onDestroy() { deviceUnlock.close();sessionWorker.shutdown(); super.onDestroy() }
}
