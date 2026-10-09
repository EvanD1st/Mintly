package com.mintly.mintly

import android.content.Context
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

/** Installation-bound session credentials only; no wallet secrets or passwords. */
class SecureSessionVault(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "mintly-session.enc"))
    private val alias = "mintly.session.aes.v1"
    private val aad = "com.mintly.mintly/session/v1".toByteArray(Charsets.UTF_8)

    private fun key(create: Boolean): SecretKey? {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val old = store.getKey(alias, null) as? SecretKey
        if (old != null || !create) return old
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }

    fun save(token: String, expiry: String, origin: String) {
        require(token.length in 32..512 && expiry.length in 10..80 && origin.startsWith("https://"))
        val plain = JSONObject().put("token", token).put("expires_at", expiry).put("origin", origin)
            .toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key(true)); updateAAD(aad) }
        val envelope = JSONObject().put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .put("ciphertext", Base64.encodeToString(cipher.doFinal(plain), Base64.NO_WRAP))
            .toString().toByteArray(Charsets.UTF_8)
        plain.fill(0)
        val stream = file.startWrite()
        try { stream.write(envelope); file.finishWrite(stream) } catch (error: Exception) { file.failWrite(stream); throw error }
    }

    fun read(): Map<String, String>? {
        if (!file.baseFile.exists()) return null
        try {
            require(file.baseFile.length() <= 8192)
            val record = JSONObject(String(file.readFully(), Charsets.UTF_8))
            val iv = Base64.decode(record.getString("iv"), Base64.NO_WRAP)
            require(iv.size == 12)
            val secret = key(false) ?: return clearAndNull()
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, secret, GCMParameterSpec(128, iv)); updateAAD(aad)
            }
            val plain = cipher.doFinal(Base64.decode(record.getString("ciphertext"), Base64.NO_WRAP))
            val session = JSONObject(String(plain, Charsets.UTF_8)); plain.fill(0)
            return mapOf("token" to session.getString("token"), "expires_at" to session.getString("expires_at"), "origin" to session.getString("origin"))
        } catch (_: Exception) { return clearAndNull() }
    }

    private fun clearAndNull(): Map<String, String>? { clear(); return null }
    fun clear() { file.delete() }
}
