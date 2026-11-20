package fr.sona.quest

import android.app.Application
import android.content.Intent
import android.net.Uri
import androidx.core.graphics.drawable.toBitmap
import androidx.palette.graphics.Palette
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.URLEncoder

/**
 * Tout ce que l'app sait de la lecture : file, titre en cours, paroles, appareils Sona Connect.
 * Vit tant que le processus vit ; le service de lecture (PlaybackService) le garde éveillé.
 */
object Hub {
    lateinit var app: Application
        private set
    lateinit var settings: Settings
        private set
    lateinit var api: Api
        private set

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    val loggedIn = MutableStateFlow(false)
    val queue = MutableStateFlow<List<Track>>(emptyList())
    val index = MutableStateFlow(0)
    val queueName = MutableStateFlow("")
    val playing = MutableStateFlow(false)
    val buffering = MutableStateFlow(false)
    val positionMs = MutableStateFlow(0L)
    val durationMs = MutableStateFlow(0L)
    val shuffle = MutableStateFlow(false)
    val repeat = MutableStateFlow(Player.REPEAT_MODE_OFF)
    val lyrics = MutableStateFlow<LyricsOut?>(null)
    val devices = MutableStateFlow<List<ConnectDevice>>(emptyList())
    val activeDeviceId = MutableStateFlow<String?>(null)
    val session = MutableStateFlow<SessionOut?>(null)
    val audioSessionId = MutableStateFlow(0)
    val message = MutableStateFlow<String?>(null)

    /** Thème choisi (Sona, Archive, GTA VI). */
    val theme = MutableStateFlow(ThemeId.Sona)

    /** Couleur dominante (sombre) de la pochette en cours : fond du lecteur, comme dans Musique. */
    val coverColor = MutableStateFlow<Int?>(null)

    /** Fin du minuteur de sommeil (ms), s'il est réglé. */
    val sleepEndsAt = MutableStateFlow<Long?>(null)

    private var player: ExoPlayer? = null
    private var lyricsJob: Job? = null
    private var connectJob: Job? = null
    private var tickerJob: Job? = null
    private var coverJob: Job? = null
    private var sleepJob: Job? = null

    /** « Je viens de lancer la lecture ici » : les autres appareils se mettent en pause. */
    private var claimNext = false

    /** Type d'appareil annoncé à Sona Connect (« quest », ou « desktop » face à un vieux serveur). */
    private var deviceKind = "quest"

    /** Réveille la boucle Sona Connect pour qu'elle publie tout de suite l'état. */
    private val kick = Channel<Unit>(Channel.CONFLATED)

    val current: Track? get() = queue.value.getOrNull(index.value)

    fun init(application: Application) {
        if (this::app.isInitialized) return
        app = application
        settings = Settings(application)
        api = Api(settings)
        loggedIn.value = settings.token.isNotBlank()
        theme.value = ThemeId.fromKey(settings.theme)
    }

    fun setTheme(id: ThemeId) {
        settings.theme = id.key
        theme.value = id
    }

    // ── Lecteur ──────────────────────────────────────────────────────────────

    fun player(): ExoPlayer {
        player?.let { return it }
        val http = DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(30_000)
            .setReadTimeoutMs(60_000)
            .setAllowCrossProtocolRedirects(true)
        // Le jeton est relu à chaque requête : une reconnexion n'oblige pas à tout reconstruire.
        val dataSource = DataSource.Factory {
            http.createDataSource().also { it.setRequestProperty("Authorization", "Bearer ${settings.token}") }
        }
        val p = ExoPlayer.Builder(app)
            .setMediaSourceFactory(DefaultMediaSourceFactory(app).setDataSourceFactory(dataSource))
            .setAudioAttributes(musicAttributes(), !settings.keepOverGames)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()
        p.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing.value = isPlaying
                kick.trySend(Unit)
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                if (p.mediaItemCount > 0) index.value = p.currentMediaItemIndex
                loadLyrics()
                loadCoverColor()
                kick.trySend(Unit)
            }

            override fun onPlaybackStateChanged(state: Int) {
                buffering.value = state == Player.STATE_BUFFERING
                kick.trySend(Unit)
            }

            override fun onAudioSessionIdChanged(audioSessionId: Int) {
                this@Hub.audioSessionId.value = audioSessionId
            }

            override fun onShuffleModeEnabledChanged(shuffleModeEnabled: Boolean) {
                shuffle.value = shuffleModeEnabled
                kick.trySend(Unit)
            }

            override fun onRepeatModeChanged(repeatMode: Int) {
                repeat.value = repeatMode
                kick.trySend(Unit)
            }

            override fun onPlayerError(error: PlaybackException) {
                message.value = "Lecture impossible (${error.errorCodeName}). Titre suivant…"
                if (p.hasNextMediaItem()) {
                    p.seekToNextMediaItem()
                    p.prepare()
                }
            }
        })
        audioSessionId.value = p.audioSessionId
        player = p
        startTicker()
        return p
    }

    fun releasePlayer() {
        tickerJob?.cancel()
        player?.release()
        player = null
        playing.value = false
    }

    private fun musicAttributes() = AudioAttributes.Builder()
        .setUsage(C.USAGE_MEDIA)
        .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
        .build()

    /** Garder (ou non) la musique pendant un jeu VR : se joue sans prendre le focus audio. */
    fun setKeepOverGames(keep: Boolean) {
        settings.keepOverGames = keep
        player?.setAudioAttributes(musicAttributes(), !keep)
    }

    private fun startTicker() {
        tickerJob?.cancel()
        tickerJob = scope.launch {
            while (isActive) {
                player?.let { p ->
                    positionMs.value = p.currentPosition
                    val d = p.duration
                    durationMs.value = if (d == C.TIME_UNSET || d <= 0) {
                        (current?.durationSeconds ?: 0) * 1000L
                    } else d
                }
                delay(250)
            }
        }
    }

    /** Démarre le service de lecture (notification, session média, Sona Connect). */
    fun ensureService() {
        try {
            app.startService(Intent(app, PlaybackService::class.java))
        } catch (_: IllegalStateException) {
            // App en arrière-plan : le service tourne déjà ou démarrera à la prochaine ouverture.
        }
    }

    private fun mediaItem(t: Track): MediaItem {
        fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
        val meta = MediaMetadata.Builder()
            .setTitle(t.title)
            .setArtist(t.artist)
            .setAlbumTitle(t.album)
            .setArtworkUri(t.coverUrl?.let { Uri.parse(it) })
            .build()
        return MediaItem.Builder()
            .setMediaId("${t.source}:${t.sourceId}")
            .setUri("${settings.server}/stream/${enc(t.source)}/${enc(t.sourceId)}")
            .setMediaMetadata(meta)
            .build()
    }

    fun playQueue(
        tracks: List<Track>,
        start: Int = 0,
        name: String = "",
        positionSec: Double = 0.0,
        play: Boolean = true,
    ) {
        if (tracks.isEmpty()) return
        ensureService()
        val p = player()
        val list = tracks.take(MAX_QUEUE)
        val from = start.coerceIn(0, list.lastIndex)
        queue.value = list
        queueName.value = name
        index.value = from
        p.setMediaItems(list.map(::mediaItem), from, (positionSec * 1000).toLong())
        p.prepare()
        p.playWhenReady = play
        if (play) claimNext = true
        loadLyrics()
        loadCoverColor()
        kick.trySend(Unit)
    }

    fun toggle() {
        val p = player ?: return
        if (p.playWhenReady) p.pause() else {
            p.play()
            claimNext = true
        }
    }

    fun next() { player?.takeIf { it.hasNextMediaItem() }?.seekToNextMediaItem() }

    fun previous() {
        val p = player ?: return
        if (p.currentPosition > 3000 || !p.hasPreviousMediaItem()) p.seekTo(0) else p.seekToPreviousMediaItem()
    }

    fun seekTo(seconds: Double) { player?.seekTo((seconds * 1000).toLong()) }

    /** « À suivre » : lance le titre d'index `i` de la file. */
    fun jumpTo(i: Int) {
        val p = player ?: return
        if (i in 0 until p.mediaItemCount) {
            p.seekTo(i, 0)
            p.play()
            claimNext = true
        }
    }

    fun toggleShuffle() { player?.let { it.shuffleModeEnabled = !it.shuffleModeEnabled } }

    fun cycleRepeat() {
        val p = player ?: return
        p.repeatMode = when (p.repeatMode) {
            Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
            Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
            else -> Player.REPEAT_MODE_OFF
        }
    }

    // ── Paroles ──────────────────────────────────────────────────────────────

    private fun loadLyrics() {
        lyricsJob?.cancel()
        val track = current
        lyrics.value = null
        if (track == null) return
        lyricsJob = scope.launch {
            lyrics.value = withContext(Dispatchers.IO) { runCatching { api.lyrics(track) }.getOrNull() }
        }
    }

    // ── Couleur de la pochette, minuteur de sommeil ──────────────────────────

    private fun loadCoverColor() {
        coverJob?.cancel()
        val url = current?.coverUrl
        if (url == null) {
            coverColor.value = null
            return
        }
        coverJob = scope.launch {
            coverColor.value = withContext(Dispatchers.IO) {
                runCatching {
                    val request = ImageRequest.Builder(app).data(url).allowHardware(false).size(96).build()
                    val bitmap = (app.imageLoader.execute(request) as? SuccessResult)?.drawable?.toBitmap()
                        ?: return@runCatching null
                    val palette = Palette.from(bitmap).maximumColorCount(12).generate()
                    palette.getDarkVibrantColor(palette.getDarkMutedColor(palette.getDominantColor(0xFF1C1C24.toInt())))
                }.getOrNull()
            }
        }
    }

    /** Éteint la musique après `minutes` (fondu sur les 10 dernières secondes) ; null : annule. */
    fun setSleepTimer(minutes: Int?) {
        sleepJob?.cancel()
        player?.volume = 1f
        if (minutes == null) {
            sleepEndsAt.value = null
            return
        }
        val end = System.currentTimeMillis() + minutes * 60_000L
        sleepEndsAt.value = end
        sleepJob = scope.launch {
            while (isActive) {
                val left = end - System.currentTimeMillis()
                if (left <= 0) break
                if (left < 10_000) player?.volume = (left / 10_000f).coerceIn(0f, 1f)
                delay(500)
            }
            player?.pause()
            player?.volume = 1f
            sleepEndsAt.value = null
        }
    }

    // ── Compte ───────────────────────────────────────────────────────────────

    fun login(token: String) {
        settings.token = token
        loggedIn.value = true
        kick.trySend(Unit)
    }

    fun logout() {
        settings.token = ""
        loggedIn.value = false
        player?.run { stop(); clearMediaItems() }
        queue.value = emptyList()
        devices.value = emptyList()
        session.value = null
    }

    // ── Sona Connect ─────────────────────────────────────────────────────────

    /** Remote : envoie une commande à un autre appareil du compte (ou à ce casque). */
    fun remote(target: String, action: String) {
        scope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.command(CommandIn(deviceId = settings.deviceId, target = target, action = action))
                }
            }.onFailure { message.value = it.message }
            kick.trySend(Unit)
        }
    }

    fun startConnect() {
        if (connectJob?.isActive == true) return
        connectJob = scope.launch { connectLoop() }
    }

    fun stopConnect() {
        connectJob?.cancel()
        connectJob = null
    }

    private fun buildState(): PlaybackState? {
        val p = player ?: return null
        val q = queue.value
        if (q.isEmpty()) return null
        return PlaybackState(
            queue = q,
            index = index.value.coerceIn(0, q.lastIndex),
            position = p.currentPosition / 1000.0,
            paused = !p.playWhenReady,
            volume = p.volume.toDouble(),
            name = queueName.value,
            shuffle = p.shuffleModeEnabled,
            repeat = when (p.repeatMode) {
                Player.REPEAT_MODE_ALL -> "all"
                Player.REPEAT_MODE_ONE -> "one"
                else -> "off"
            },
        )
    }

    private suspend fun connectLoop() {
        var backoff = 2_000L
        while (currentCoroutineContext().isActive) {
            if (!loggedIn.value) {
                delay(1_500)
                continue
            }
            try {
                val claim = claimNext
                claimNext = false
                val input = SyncIn(
                    deviceId = settings.deviceId,
                    name = settings.deviceName,
                    kind = deviceKind,
                    state = buildState(),
                    claim = claim,
                    // Long polling : la réponse arrive dès qu'une commande attend.
                    wait = if (playing.value) 12.0 else 25.0,
                )
                val out: SyncOut? = try {
                    coroutineScope {
                        val call = async(Dispatchers.IO) { api.sync(input) }
                        val interrupt = launch { kick.receive(); call.cancel() }
                        try { call.await() } finally { interrupt.cancel() }
                    }
                } catch (e: CancellationException) {
                    if (!currentCoroutineContext().isActive) throw e
                    null // interrompu par un changement local : on republie l'état
                }
                if (out != null) {
                    devices.value = out.devices
                    activeDeviceId.value = out.activeDeviceId
                    session.value = out.session
                    out.commands.forEach(::handle)
                    backoff = 2_000L
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                if (e.code == 401) {
                    message.value = "Session expirée : reconnecte-toi."
                    logout()
                } else if (e.code == 422 && deviceKind == "quest") {
                    // Serveur pas encore à jour (il ne connaît pas le type « quest ») : on
                    // se signale comme un ordinateur, au lieu de rester déconnecté de Sona Connect.
                    deviceKind = "desktop"
                } else {
                    message.value = e.message
                    delay(backoff)
                    backoff = (backoff * 2).coerceAtMost(15_000L)
                }
            } catch (e: Exception) {
                delay(backoff)
                backoff = (backoff * 2).coerceAtMost(15_000L)
            }
        }
    }

    private fun handle(c: RemoteCommand) {
        val p = player()
        when (c.action) {
            "play" -> p.play()
            "pause" -> p.pause()
            "toggle" -> if (p.playWhenReady) p.pause() else p.play()
            "next" -> next()
            "previous" -> previous()
            "seek" -> c.position?.let { seekTo(it) }
            "volume" -> c.volume?.let { p.volume = it.toFloat().coerceIn(0f, 1f) }
            "shuffle" -> toggleShuffle()
            "repeat" -> cycleRepeat()
            "play_index" -> c.index?.let { i ->
                if (i in 0 until p.mediaItemCount) {
                    p.seekTo(i, 0)
                    p.play()
                }
            }
            "transfer", "play_tracks" -> c.queue?.let {
                playQueue(it, c.index ?: 0, c.name.orEmpty(), c.position ?: 0.0)
            }
            else -> Unit // « like » : géré par les autres appareils
        }
        kick.trySend(Unit)
    }

    private const val MAX_QUEUE = 150
}
