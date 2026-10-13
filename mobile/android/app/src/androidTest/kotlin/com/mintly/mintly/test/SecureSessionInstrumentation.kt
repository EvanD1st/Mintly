package com.mintly.mintly.test

import android.app.Instrumentation
import android.os.Bundle
import com.mintly.mintly.SecureSessionVault
import java.io.File
import android.content.Intent
import com.mintly.mintly.ProtectedAccountsVault
import com.mintly.mintly.UnlockTestActivity
import android.security.keystore.KeyInfo
import java.security.KeyStore
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import java.util.concurrent.TimeUnit

class SecureSessionInstrumentation : Instrumentation() {
    private var phase = "verify"
    override fun onCreate(arguments: Bundle?) { phase = arguments?.getString("phase") ?: "verify"; super.onCreate(arguments); start() }
    override fun onStart() {
        try {
            if (phase.startsWith("protected-")) { protectedTest();return }
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

    private fun shell(command: String) { uiAutomation.executeShellCommand(command).use { descriptor ->
        java.io.FileInputStream(descriptor.fileDescriptor).use { it.readBytes() }
    } }

    private fun protectedTest() {
        val vault=ProtectedAccountsVault(targetContext)
        check(vault.deviceSecure())
        val activity=startActivitySync(Intent(targetContext,UnlockTestActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as UnlockTestActivity
        check(!activity.unlock.authorized())
        if (phase == "protected-verify") {
            runOnMainSync { activity.authenticate() }
            Thread.sleep(1500);shell("input keyevent 4");Thread.sleep(500);shell("input keyevent 4")
            check(activity.completed.await(10,TimeUnit.SECONDS) && !activity.accepted && !activity.unlock.authorized())
        }
        runOnMainSync { activity.authenticate() }
        Thread.sleep(2000);shell("input text 739182");shell("input keyevent 66")
        check(activity.completed.await(15,TimeUnit.SECONDS) && activity.accepted && activity.unlock.authorized())
        val origin="https://mintly.example/api"
        val token="disposable-protected-refresh-credential-1234567890"
        val marker=File(targetContext.noBackupFilesDir,"mintly-protected-test-process")
        fun record(account:String)=mapOf("user_id" to account,"username" to account,"origin" to origin,
            "refresh_token" to token+account,"device_session_id" to "11111111-1111-4111-8111-111111111111",
            "remembered_expires_at" to "2099-10-13T00:00:00Z")
        if (phase == "protected-save") {
            vault.save(record("alice"));vault.save(record("bob"))
            marker.writeText(android.os.Process.myPid().toString())
            check(vault.accounts(origin).size==2 && vault.read(origin,"alice")?.get("refresh_token")==token+"alice")
            check(vault.read("https://other.example/api","alice")==null && vault.read(origin,"missing")==null)
            check(vault.accounts(origin).all { !it.containsKey("refresh_token") })
            val disk=File(targetContext.noBackupFilesDir,"mintly-accounts.v2.enc").readText()
            check(!disk.contains(token) && !disk.contains("alice") && !disk.contains(origin))
            val key=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.getKey("mintly.accounts.aes.v2",null) as SecretKey
            val info=SecretKeyFactory.getInstance(key.algorithm,"AndroidKeyStore").getKeySpec(key,KeyInfo::class.java) as KeyInfo
            check(info.isUserAuthenticationRequired && info.userAuthenticationValidityDurationSeconds==60)
            runOnMainSync { activity.finish() }
            finish(0,Bundle().apply { putString("stream","Protected accounts saved for process restart; Keystore authentication and origin binding verified.") });return
        }
        check(marker.readText()!=android.os.Process.myPid().toString());marker.delete()
        check(vault.read(origin,"bob")?.get("refresh_token")==token+"bob")
        vault.remove(origin,"alice");check(vault.accounts(origin).size==1)
        check(vault.read(origin,"alice")==null && vault.read(origin,"bob")!=null)
        File(targetContext.noBackupFilesDir,"mintly-accounts.v2.enc").writeText("{\"iv\":\"bad\",\"ciphertext\":\"bad\"}")
        check(vault.accounts(origin).isEmpty())
        vault.save(record("alice"));vault.remove(origin,"alice");check(!vault.hasAccounts())
        runOnMainSync { activity.finish() }
        finish(0,Bundle().apply { putString("stream","Protected accounts: PIN unlock, cancelled unlock, encrypted storage, origin binding, process restart, remove and tamper recovery passed.") })
    }
}
