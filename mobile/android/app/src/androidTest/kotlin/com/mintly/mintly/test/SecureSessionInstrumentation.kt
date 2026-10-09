package com.mintly.mintly.test

import android.app.Instrumentation
import android.os.Bundle
import com.mintly.mintly.SecureSessionVault
import java.io.File

class SecureSessionInstrumentation : Instrumentation() {
    private var phase = "verify"
    override fun onCreate(arguments: Bundle?) { phase = arguments?.getString("phase") ?: "verify"; super.onCreate(arguments); start() }
    override fun onStart() {
        try {
            val vault = SecureSessionVault(targetContext)
            val token = "disposable-session-credential-1234567890"
            val expiry = "2099-10-09T00:00:00Z"
            val origin = "https://mintly.example/api"
            val processMarker = File(targetContext.noBackupFilesDir, "mintly-session-test-process")
            if (phase == "save") {
                vault.clear(); check(vault.read() == null)
                vault.save(token, expiry, origin)
                processMarker.writeText(android.os.Process.myPid().toString())
                finish(0, Bundle().apply { putString("stream", "Session saved for restart test.") })
                return
            }
            check(processMarker.readText() != android.os.Process.myPid().toString())
            processMarker.delete()
            check(vault.read()?.get("token") == token)
            val stored = File(targetContext.noBackupFilesDir, "mintly-session.enc")
            check(!stored.readText().contains(token))
            check(SecureSessionVault(targetContext).read()?.get("origin") == origin)
            stored.writeText("{\"iv\":\"bad\",\"ciphertext\":\"bad\"}")
            check(vault.read() == null && !stored.exists())
            vault.save(token, expiry, origin); vault.clear()
            check(SecureSessionVault(targetContext).read() == null)
            finish(0, Bundle().apply { putString("stream", "Secure session: round-trip, encrypted disk, restart, tamper, clear passed.") })
        } catch (_: Exception) {
            finish(1, Bundle().apply { putString("stream", "Secure session instrumentation failed.") })
        }
    }
}
