package fr.sona.quest

import android.net.Uri
import android.util.Base64
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Radio DJ : une station qui se prolonge toute seule (le serveur choisit des titres qui
 * s'enchaînent bien avec le dernier), et un DJ à la voix neuronale qui annonce chaque titre
 * par-dessus le début, en baissant la musique le temps de parler.
 */
object Dj {
    /** Nom de la station en cours (« Radio · … »), ou null hors radio DJ. */
    val station = MutableStateFlow<String?>(null)
    val voice = MutableStateFlow(true)

    private var extending = false
    private var announcer: ExoPlayer? = null

    fun init(settings: Settings) {
        voice.value = settings.djVoice
    }

    fun setVoice(on: Boolean) {
        voice.value = on
        Hub.settings.djVoice = on
        if (!on) stopAnnouncement()
    }

    /** Lance une radio DJ à partir d'un titre. */
    fun start(seed: Track) {
        Hub.message.value = "Radio DJ à partir de « ${seed.title} »…"
        Hub.scope.launch {
            val more = withContext(Dispatchers.IO) { runCatching { Hub.api.djRadio(seed, listOf(seed.sourceId)) } }
            val tracks = more.getOrNull()
            if (tracks == null) {
                Hub.message.value = more.exceptionOrNull()?.message ?: "Radio DJ indisponible"
                return@launch
            }
            val name = "Radio · ${seed.title}"
            Hub.playQueue(listOf(seed) + tracks.filter { it.sourceId != seed.sourceId }, 0, name, keepStation = true)
            station.value = name
        }
    }

    /** Une autre lecture a pris la place : la station s'arrête. */
    fun stop() {
        station.value = null
        stopAnnouncement()
    }

    /** À chaque nouveau titre : la station se prolonge si la file s'épuise, et le DJ annonce. */
    fun onTrackChanged() {
        if (station.value == null) return
        extendIfNeeded()
        if (voice.value) announce()
    }

    private fun extendIfNeeded() {
        val queue = Hub.queue.value
        if (extending || queue.isEmpty() || queue.size - Hub.index.value > 3) return
        extending = true
        Hub.scope.launch {
            val tracks = withContext(Dispatchers.IO) {
                runCatching { Hub.api.djRadio(queue.last(), queue.takeLast(150).map { it.sourceId }) }.getOrNull()
            }
            if (tracks != null && station.value != null) {
                val known = Hub.queue.value.map { it.sourceId }.toSet()
                Hub.appendToQueue(tracks.filter { it.sourceId !in known })
            }
            extending = false
        }
    }

    private fun announce() {
        val queue = Hub.queue.value
        val index = Hub.index.value
        val track = queue.getOrNull(index) ?: return
        val previous = queue.getOrNull(index - 1)
        Hub.scope.launch {
            val intro = withContext(Dispatchers.IO) { runCatching { Hub.api.djIntro(track, previous) }.getOrNull() }
            val audio = intro?.audio ?: return@launch
            // Le titre a changé pendant que la voix se préparait : l'annonce n'a plus de sens.
            if (Hub.current?.sourceId != track.sourceId || station.value == null) return@launch
            val file = withContext(Dispatchers.IO) {
                File(Hub.app.cacheDir, "dj_intro.mp3").also { it.writeBytes(Base64.decode(audio, Base64.DEFAULT)) }
            }
            speak(file)
        }
    }

    private fun speak(file: File) {
        stopAnnouncement()
        val p = ExoPlayer.Builder(Hub.app).build()
        p.setMediaItem(MediaItem.fromUri(Uri.fromFile(file)))
        p.prepare()
        p.playWhenReady = true
        p.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_ENDED) stopAnnouncement()
            }
        })
        announcer = p
        Sound.duckGain = 0.3f
        Sound.apply()
    }

    private fun stopAnnouncement() {
        announcer?.release()
        announcer = null
        Sound.duckGain = 1f
        Sound.apply()
    }

    fun release() {
        station.value = null
        extending = false
        stopAnnouncement()
    }
}
