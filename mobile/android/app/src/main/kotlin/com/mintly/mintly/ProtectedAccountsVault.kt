package com.mintly.mintly

import android.app.KeyguardManager
import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject
import org.json.JSONArray

/** Authentication-bound installation storage. No password or wallet key is accepted. */
class ProtectedAccountsVault(private val context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "mintly-accounts.v2.enc"))
    private val alias = "mintly.accounts.aes.v2"
    private val aad = "com.mintly.mintly/accounts/v2".toByteArray(Charsets.UTF_8)
    private val allowed = setOf("user_id", "username", "origin", "refresh_token", "device_session_id", "remembered_expires_at", "pending_refresh_id")
    fun hasAccounts() = file.baseFile.exists()
    fun deviceSecure() = (context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isDeviceSecure

    private fun key(create: Boolean): SecretKey? {
        check(deviceSecure())
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey(alias, null) as? SecretKey
        if (existing != null || !create) return existing
        val spec = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setUserAuthenticationRequired(true).setRandomizedEncryptionRequired(true)
        if (Build.VERSION.SDK_INT >= 30) spec.setUserAuthenticationParameters(60,
            KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
        else {
            @Suppress("DEPRECATION")
            spec.setUserAuthenticationValidityDurationSeconds(60)
        }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(spec.build()) }.generateKey()
    }

    private fun load(): JSONObject {
        try { return loadVerified() }
        catch (_: javax.crypto.AEADBadTagException) { file.delete() }
        catch (_: org.json.JSONException) { file.delete() }
        catch (_: IllegalArgumentException) { file.delete() }
        catch (_: android.security.keystore.KeyPermanentlyInvalidatedException) {
            file.delete();KeyStore.getInstance("AndroidKeyStore").apply { load(null);deleteEntry(alias) }
        }
        return JSONObject().put("accounts",JSONArray())
    }

    private fun loadVerified(): JSONObject {
        if (!hasAccounts()) return JSONObject().put("accounts", JSONArray())
        require(file.baseFile.length() <= 65536)
        val record = JSONObject(String(file.readFully(), Charsets.UTF_8))
        val iv = Base64.decode(record.getString("iv"), Base64.NO_WRAP)
        require(iv.size == 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(false) ?: error("Missing device key"), GCMParameterSpec(128, iv)); updateAAD(aad)
        }
        val bytes = cipher.doFinal(Base64.decode(record.getString("ciphertext"), Base64.NO_WRAP))
        try { return JSONObject(String(bytes, Charsets.UTF_8)) } finally { bytes.fill(0) }
    }

    private fun write(data: JSONObject) {
        val plain = data.toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key(true)); updateAAD(aad) }
        val encrypted = try { cipher.doFinal(plain) } finally { plain.fill(0) }
        val bytes = JSONObject().put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .put("ciphertext", Base64.encodeToString(encrypted, Base64.NO_WRAP)).toString().toByteArray(Charsets.UTF_8)
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) } catch (error: Exception) { file.failWrite(stream); throw error }
    }

    fun accounts(origin: String): List<Map<String, Any>> {
        val data = load(); val rows = data.getJSONArray("accounts")
        return (0 until rows.length()).map { rows.getJSONObject(it) }.filter { it.getString("origin") == origin }.map {
            mapOf("user_id" to it.getString("user_id"), "username" to it.getString("username"), "origin" to origin,
                "active" to (data.optString("active") == origin + "|" + it.getString("user_id")))
        }
    }

    fun read(origin: String, account: String): Map<String, String>? {
        val rows = load().getJSONArray("accounts")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            if (row.getString("origin") == origin && row.getString("user_id") == account)
                return row.keys().asSequence().associateWith { row.getString(it) }
        }
        return null
    }

    fun save(record: Map<String, String>) {
        require(record.keys.all { it in allowed } && record.values.all { it.length <= 512 })
        require(record["origin"]?.startsWith("https://") == true && !record["user_id"].isNullOrBlank())
        require((record["refresh_token"]?.length ?: 0) in 32..256 && (record["device_session_id"]?.length ?: 0) == 36)
        val data = load(); val rows = data.getJSONArray("accounts"); val updated = JSONArray()
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            if (row.getString("origin") != record["origin"] || row.getString("user_id") != record["user_id"]) updated.put(row)
        }
        require(updated.length() < 8)
        updated.put(JSONObject(record));data.put("accounts",updated)
        data.put("active", record["origin"] + "|" + record["user_id"]);write(data)
    }

    fun remove(origin: String, account: String) {
        val data = load(); val rows = data.getJSONArray("accounts"); val updated = JSONArray()
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            if (row.getString("origin") != origin || row.getString("user_id") != account) updated.put(row)
        }
        data.put("accounts",updated)
        if (data.optString("active") == origin + "|" + account) data.remove("active")
        if (updated.length() == 0) file.delete() else write(data)
    }
}
