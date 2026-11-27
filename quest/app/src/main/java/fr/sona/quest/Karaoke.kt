package fr.sona.quest

import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs

sealed interface KaraokeUi {
    data object Off : KaraokeUi
    data class Preparing(val progress: Float) : KaraokeUi
    data object Ready : KaraokeUi
    data class Failed(val message: String) : KaraokeUi
}

/**
 * Mode chant : le serveur sépare la voix et l'instrumental de chaque titre (quelques dizaines
 * de secondes pour le titre en cours, à l'avance pour les suivants). Le titre courant est alors
 * remplacé par son instrumental ; une seconde piste, la voix, peut rester audible à faible
 * niveau (« voix guide »), calée sur le lecteur.
 */
object Karaoke {
    val on = MutableStateFlow(false)
    val ui = MutableStateFlow<KaraokeUi>(KaraokeUi.Off)
    val guide = MutableStateFlow(0f)

    private var job: Job? = null
    private var guidePlayer: ExoPlayer? = null

    fun init(settings: Settings) {
        guide.value = settings.guide
    }

    /** Identifiant d'un élément de la file remplacé par son instrumental : « source:id:k:qualité ». */
    private fun isSwapped(mediaId: String?) = mediaId?.contains(":k:") == true

    fun setOn(enabled: Boolean) {
        if (enabled == on.value) return
        on.value = enabled
        if (enabled) onTrackChanged() else turnOff()
    }

    fun setGuide(level: Float) {
        guide.value = level
        Hub.settings.guide = level
        Sound.apply()
    }

    /** Appelé à chaque nouveau titre courant. */
    fun onTrackChanged() {
        if (!on.value) return
        job?.cancel()
        stopGuide()
        val player = Hub.currentPlayer() ?: return
        val track = Hub.current ?: return
        prepareUpcoming()
        val id = player.currentMediaItem?.mediaId
        if (isSwapped(id)) {
            ui.value = KaraokeUi.Ready
            startGuide(track, id!!.substringAfterLast(":k:"))
            return
        }
        job = Hub.scope.launch { run(track) }
    }

    private suspend fun run(track: Track) {
        ui.value = KaraokeUi.Preparing(0f)
        try {
            var status = withContext(Dispatchers.IO) { Hub.api.karaokeRequest(track.source, track.sourceId) }
            while (currentCoroutineContext().isActive && status.status != "ready") {
                if (status.status == "failed" || status.available == false) {
                    ui.value = KaraokeUi.Failed(
                        if (status.available == false) "Le karaoké n'est pas disponible sur ce serveur." else "La séparation a échoué pour ce titre.",
                    )
                    return
                }
                ui.value = KaraokeUi.Preparing(status.progress.toFloat().coerceIn(0f, 1f))
                delay(2000)
                status = withContext(Dispatchers.IO) { Hub.api.karaokeStatus(track.source, track.sourceId) }
            }
            if (Hub.current?.let { it.source == track.source && it.sourceId == track.sourceId } != true) return
            swapToInstrumental(track, status.quality ?: "fast")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ui.value = KaraokeUi.Failed(e.message ?: "Karaoké indisponible")
        }
    }

    private fun swapToInstrumental(track: Track, quality: String) {
        val player = Hub.currentPlayer() ?: return
        val index = player.currentMediaItemIndex
        val position = player.currentPosition
        // Le remplacement relance le titre : la transition qui suit démarre la voix guide.
        player.replaceMediaItem(index, Hub.mediaItem(track, stem = "instrumental", quality = quality))
        player.seekTo(index, position)
    }

    /** Titres suivants : séparés à l'avance, pour qu'ils soient prêts quand on y arrive. */
    private fun prepareUpcoming() {
        val queue = Hub.queue.value
        val next = queue.drop(Hub.index.value + 1).take(5)
        if (next.isEmpty()) return
        Hub.scope.launch { withContext(Dispatchers.IO) { runCatching { Hub.api.karaokePrepare(next) } } }
    }

    private fun turnOff() {
        job?.cancel()
        stopGuide()
        ui.value = KaraokeUi.Off
        val player = Hub.currentPlayer() ?: return
        val queue = Hub.queue.value
        val current = player.currentMediaItemIndex
        val position = player.currentPosition
        for (i in 0 until player.mediaItemCount) {
            if (!isSwapped(player.getMediaItemAt(i).mediaId)) continue
            val track = queue.getOrNull(i) ?: continue
            player.replaceMediaItem(i, Hub.mediaItem(track))
        }
        if (isSwapped(player.currentMediaItem?.mediaId).not()) player.seekTo(current, position)
    }

    // ── Voix guide ───────────────────────────────────────────────────────────

    private fun startGuide(track: Track, quality: String) {
        stopGuide()
        val main = Hub.currentPlayer() ?: return
        val g = ExoPlayer.Builder(Hub.app)
            .setMediaSourceFactory(DefaultMediaSourceFactory(Hub.app).setDataSourceFactory(Hub.dataSourceFactory()))
            .build()
        g.setMediaItem(Hub.mediaItem(track, stem = "vocals", quality = quality))
        g.prepare()
        g.seekTo(main.currentPosition)
        g.playWhenReady = main.playWhenReady
        guidePlayer = g
        Sound.apply()
    }

    private fun stopGuide() {
        guidePlayer?.release()
        guidePlayer = null
    }

    fun release() {
        job?.cancel()
        stopGuide()
    }

    /** Volume de la voix guide : son niveau réglé, suivant le volume général. */
    fun setGuideVolume(master: Float) {
        guidePlayer?.volume = (guide.value * master).coerceIn(0f, 1f)
    }

    /** Appelé souvent : la voix suit la lecture (lecture/pause) et se recale si elle dérive. */
    fun tick(main: ExoPlayer) {
        val g = guidePlayer ?: return
        val shouldPlay = main.playWhenReady && main.playbackState == Player.STATE_READY
        if (g.playWhenReady != shouldPlay) g.playWhenReady = shouldPlay
        if (g.playbackState == Player.STATE_READY && abs(g.currentPosition - main.currentPosition) > 300) {
            g.seekTo(main.currentPosition)
        }
    }

    /** Saut dans le titre : la voix saute aussi, tout de suite. */
    fun onSeek(main: ExoPlayer) {
        guidePlayer?.seekTo(main.currentPosition)
    }
}
