package com.mintly.mintly

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import java.util.concurrent.Executor

/** System-owned authentication UI; Mintly never receives a phone PIN. */
class DeviceUnlock(private val activity: Activity) {
    private var callback: ((Boolean) -> Unit)? = null
    private var signal: CancellationSignal? = null
    private var unlockedAt = 0L
    private val requestCode = 8371
    fun authorized() = unlockedAt > 0 && android.os.SystemClock.elapsedRealtime() - unlockedAt < 60000
    private fun finish(ok: Boolean) {
        unlockedAt = if (ok) android.os.SystemClock.elapsedRealtime() else 0L
        val done = callback;callback = null;signal = null;done?.invoke(ok)
    }
    fun request(done: (Boolean) -> Unit) {
        if (callback != null) { done(false); return }
        callback = done;unlockedAt = 0
        val guard = activity.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (!guard.isDeviceSecure) { finish(false); return }
        if (Build.VERSION.SDK_INT >= 30) {
            val executor = Executor { activity.runOnUiThread(it) }
            signal = CancellationSignal()
            BiometricPrompt.Builder(activity).setTitle("Unlock Mintly accounts")
                .setSubtitle("Use fingerprint or your phone PIN")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
                .build().authenticate(signal!!, executor, object: BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) { finish(true) }
                    override fun onAuthenticationError(code: Int, message: CharSequence) { finish(false) }
                })
        } else {
            @Suppress("DEPRECATION")
            val intent = guard.createConfirmDeviceCredentialIntent("Unlock Mintly accounts", "Use your phone PIN, pattern or password")
            if (intent == null) finish(false) else {
                @Suppress("DEPRECATION")
                activity.startActivityForResult(intent, requestCode)
            }
        }
    }
    fun activityResult(code: Int, result: Int): Boolean {
        if (code != requestCode) return false
        finish(result == Activity.RESULT_OK);return true
    }
    fun close() { signal?.cancel();finish(false) }
}
