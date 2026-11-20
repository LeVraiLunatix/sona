package fr.sona.quest

import android.media.audiofx.Equalizer
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.log10
import kotlin.math.min
import kotlin.math.pow

/**
 * Le son de Sona : égaliseur 5 bandes, volume égalisé (tous les titres au même niveau, d'après
 * l'analyse du serveur), fondu entre les titres. Plusieurs sources règlent le volume du lecteur
 * (toi, l'égalisation, le fondu, le minuteur de sommeil, la voix du DJ, le réveil) : leur produit
 * donne le volume réel (voir `apply`).
 */
object Sound {
    val BANDS = listOf(60, 250, 1000, 4000, 12000)
    val LABELS = listOf("60", "250", "1k", "4k", "12k")
    val PRESETS = listOf(
        "Normal" to listOf(0, 0, 0, 0, 0),
        "Basses" to listOf(6, 3, 0, 0, 1),
        "Grosses basses" to listOf(9, 5, -1, 0, 2),
        "Voix" to listOf(-2, -1, 3, 4, 1),
        "Soirée" to listOf(5, 2, -1, 2, 4),
        "Voiture" to listOf(4, 1, 0, 2, 3),
        "Casque" to listOf(3, 1, 0, 1, 2),
        "Aigus" to listOf(0, 0, 0, 3, 6),
        "Doux" to listOf(2, 1, 0, -2, -3),
    )

    /** Niveau visé, en LUFS : le même que l'app iPhone et le site. */
    private const val TARGET_LOUDNESS = -10.0

    val eq = MutableStateFlow(List(5) { 0 })
    val normalize = MutableStateFlow(true)
    val fadeSeconds = MutableStateFlow(0)

    /** Faux si l'appareil ne propose pas d'égaliseur matériel. */
    val eqAvailable = MutableStateFlow(true)

    var userVolume = 1f
    var normGain = 1f
    var fadeGain = 1f
    var sleepGain = 1f
    var duckGain = 1f
    var alarmGain = 1f

    private var effect: Equalizer? = null
    private val loudness = HashMap<String, Double>()
    private var trackKey = ""

    fun init(settings: Settings) {
        eq.value = settings.eq
        normalize.value = settings.normalize
        fadeSeconds.value = settings.fade
    }

    /** Volume réel du lecteur : le produit de tous les réglages. */
    fun apply() {
        val volume = (userVolume * normGain * fadeGain * sleepGain * duckGain * alarmGain).coerceIn(0f, 1f)
        Hub.currentPlayer()?.volume = volume
        Karaoke.setGuideVolume(volume)
    }

    // ── Égaliseur ────────────────────────────────────────────────────────────

    /** (Ré)accroche l'égaliseur à la sortie audio du lecteur. */
    fun attach(sessionId: Int) {
        runCatching { effect?.release() }
        effect = null
        if (sessionId == 0) return
        try {
            effect = Equalizer(0, sessionId).apply { enabled = true }
            eqAvailable.value = true
            pushEq()
        } catch (_: Exception) {
            eqAvailable.value = false
        }
    }

    fun release() {
        runCatching { effect?.release() }
        effect = null
    }

    /** Pose les 5 gains de Sona (dB) sur les bandes de l'appareil, par proximité de fréquence. */
    private fun pushEq() {
        val e = effect ?: return
        try {
            val range = e.bandLevelRange
            for (band in 0 until e.numberOfBands) {
                val hz = (e.getCenterFreq(band.toShort()) / 1000.0).coerceAtLeast(20.0)
                val nearest = BANDS.indices.minByOrNull { abs(ln(BANDS[it].toDouble()) - ln(hz)) } ?: 0
                val level = (eq.value[nearest] * 100).coerceIn(range[0].toInt(), range[1].toInt())
                e.setBandLevel(band.toShort(), level.toShort())
            }
        } catch (_: Exception) {
            eqAvailable.value = false
        }
    }

    fun setBand(index: Int, db: Int) {
        val next = eq.value.toMutableList().also { it[index] = db.coerceIn(-12, 12) }
        setEq(next)
    }

    fun setEq(levels: List<Int>) {
        eq.value = levels
        Hub.settings.eq = levels
        pushEq()
    }

    // ── Volume égalisé ───────────────────────────────────────────────────────

    fun setNormalize(on: Boolean) {
        normalize.value = on
        Hub.settings.normalize = on
        onTrackChanged(Hub.current)
    }

    /** Nouveau titre : on cherche sa sonie (analyse du serveur) pour ramener son volume au niveau visé. */
    fun onTrackChanged(track: Track?) {
        normGain = 1f
        fadeGain = 1f
        apply()
        if (track == null || !normalize.value) return
        val key = "${track.source}:${track.sourceId}"
        trackKey = key
        loudness[key]?.let { gainFrom(it); return }
        Hub.scope.launch {
            val found = withContext(Dispatchers.IO) { runCatching { Hub.api.analysis(track.source, track.sourceId).loudness }.getOrNull() }
            if (found != null) {
                loudness[key] = found
                if (trackKey == key) gainFrom(found)
            }
        }
    }

    private fun gainFrom(lufs: Double) {
        normGain = min(1.0, 10.0.pow((TARGET_LOUDNESS - lufs) / 20.0)).toFloat()
        apply()
    }

    // ── Fondu entre les titres ───────────────────────────────────────────────

    fun setFade(seconds: Int) {
        fadeSeconds.value = seconds
        Hub.settings.fade = seconds
        if (seconds == 0) {
            fadeGain = 1f
            apply()
        }
    }

    /** Appelé souvent par le lecteur : monte le son au début du titre, le baisse à la fin. */
    fun tick(player: ExoPlayer) {
        val fade = fadeSeconds.value
        if (fade <= 0) return
        val window = fade * 1000f
        val position = player.currentPosition.toFloat()
        val duration = player.duration.takeIf { it > 0 }?.toFloat()
        val fadeIn = if (position < window) (position / window).coerceIn(0f, 1f) else 1f
        val fadeOut = if (duration != null && duration - position < window && player.repeatMode != androidx.media3.common.Player.REPEAT_MODE_ONE) {
            ((duration - position) / window).coerceIn(0f, 1f)
        } else 1f
        val gain = min(fadeIn, fadeOut).coerceAtLeast(0.001f)
        if (abs(gain - fadeGain) > 0.01f) {
            fadeGain = gain
            apply()
        }
    }

    @Suppress("unused")
    private fun dbOf(gain: Float) = 20 * log10(gain.toDouble())
}
