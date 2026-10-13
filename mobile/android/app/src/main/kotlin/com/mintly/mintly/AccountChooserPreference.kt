package com.mintly.mintly

import android.content.Context
import java.security.MessageDigest

/** Non-secret navigation preference. It never grants access to the account vault. */
class AccountChooserPreference(context: Context) {
    private val preferences = context.getSharedPreferences("mintly.account-chooser", Context.MODE_PRIVATE)
    private fun key(origin: String) = MessageDigest.getInstance("SHA-256")
        .digest(origin.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    fun show(origin: String) = preferences.getBoolean(key(origin), false)
    fun set(origin: String, show: Boolean): Boolean {
        require(origin.startsWith("https://"))
        return preferences.edit().putBoolean(key(origin), show).commit()
    }
}
