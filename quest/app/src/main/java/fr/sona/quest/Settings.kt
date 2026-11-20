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

    /** Égaliseur 5 bandes (dB) : 60, 250, 1k, 4k, 12k Hz. */
    var eq: List<Int>
        get() = (prefs.getString("eq", null) ?: "0,0,0,0,0").split(",").mapNotNull { it.trim().toIntOrNull() }
            .let { if (it.size == 5) it else List(5) { 0 } }
        set(value) = prefs.edit().putString("eq", value.joinToString(",")).apply()

    /** Volume égalisé : tous les titres au même niveau sonore. */
    var normalize: Boolean
        get() = prefs.getBoolean("normalize", true)
        set(value) = prefs.edit().putBoolean("normalize", value).apply()

    /** Fondu entre les titres (secondes, 0 = aucun). */
    var fade: Int
        get() = prefs.getInt("fade", 0)
        set(value) = prefs.edit().putInt("fade", value).apply()

    /** Qualité des flux (lossless, best, standard) — celle du compte, recopiée ici. */
    var quality: String
        get() = prefs.getString("quality", "best") ?: "best"
        set(value) = prefs.edit().putString("quality", value).apply()

    /** Niveau de la voix guide en karaoké (0 à 1). */
    var guide: Float
        get() = prefs.getFloat("guide", 0f)
        set(value) = prefs.edit().putFloat("guide", value).apply()

    /** Annonces de la radio DJ (voix). */
    var djVoice: Boolean
        get() = prefs.getBoolean("dj_voice", true)
        set(value) = prefs.edit().putBoolean("dj_voice", value).apply()

    /** Réveil musical : activé, heure et minute. */
    var alarmOn: Boolean
        get() = prefs.getBoolean("alarm_on", false)
        set(value) = prefs.edit().putBoolean("alarm_on", value).apply()
    var alarmHour: Int
        get() = prefs.getInt("alarm_hour", 7)
        set(value) = prefs.edit().putInt("alarm_hour", value).apply()
    var alarmMinute: Int
        get() = prefs.getInt("alarm_minute", 30)
        set(value) = prefs.edit().putInt("alarm_minute", value).apply()

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
