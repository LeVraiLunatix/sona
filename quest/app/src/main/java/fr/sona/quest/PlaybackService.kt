package fr.sona.quest

import android.content.Intent
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/**
 * Garde Sona en vie : la musique continue quand tu changes de fenêtre ou que
 * tu lances un jeu VR, et le casque reste joignable par Sona Connect.
 */
class PlaybackService : MediaSessionService() {
    private var mediaSession: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        mediaSession = MediaSession.Builder(this, Hub.player()).build()
        Hub.startConnect()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    /** Fermer la fenêtre ne coupe pas la musique ; sans lecture en cours, le service s'arrête. */
    override fun onTaskRemoved(rootIntent: Intent?) {
        val player = mediaSession?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        Hub.stopConnect()
        mediaSession?.release()
        mediaSession = null
        Hub.releasePlayer()
        super.onDestroy()
    }
}
