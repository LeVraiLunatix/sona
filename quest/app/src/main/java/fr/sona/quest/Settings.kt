package fr.sona.quest

import android.content.Context
import android.os.Build
import java.util.UUID

/** Réglages de l'app : serveur, session, nom de l'appareil dans Sona Connect. */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("sona", Context.MODE_PRIVATE)

    var server: String
        get() = (prefs.getString("server", null) ?: DEFAULT_SERVER).trimEnd('/')
        set(value) = prefs.edit().putString("server", value.trim().trimEnd('/')).apply()

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(value) = prefs.edit().putString("token", value).apply()

    /** Identifiant stable de ce casque dans Sona Connect. */
    val deviceId: String
        get() {
            val saved = prefs.getString("device_id", null)
            if (!saved.isNullOrBlank()) return saved
            val fresh = "quest-" + UUID.randomUUID().toString().replace("-", "").take(14)
            prefs.edit().putString("device_id", fresh).apply()
            return fresh
        }

    var deviceName: String
        get() = prefs.getString("device_name", null) ?: defaultName()
        set(value) = prefs.edit().putString("device_name", value.trim().ifEmpty { defaultName() }).apply()

    /** Thème de Sona : « sona » (noir), « archive » ou « gta ». */
    var theme: String
        get() = prefs.getString("theme", "sona") ?: "sona"
        set(value) = prefs.edit().putString("theme", value).apply()

    /** Garder la musique quand un jeu VR prend le son (pas de focus audio). */
    var keepOverGames: Boolean
        get() = prefs.getBoolean("keep_over_games", true)
        set(value) = prefs.edit().putBoolean("keep_over_games", value).apply()

    private fun defaultName(): String {
        val model = Build.MODEL.orEmpty().ifBlank { "Quest" }
        return if (model.startsWith("Meta", ignoreCase = true)) model else "Meta $model"
    }

    companion object {
        const val DEFAULT_SERVER = "https://141-253-108-13.sslip.io"
    }
}
