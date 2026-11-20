package fr.sona.quest

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * « Sona Paroles » : un petit panneau à poser où tu veux dans la pièce, avec la
 * pochette, les paroles synchronisées et les contrôles. Il suit la lecture de
 * l'app principale, quel que soit l'appareil qui la lance (Sona Connect).
 */
class LyricsPanelActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Hub.ensureService()
        setContent { SonaTheme { LookBackground { Panel() } } }
    }
}

@Composable
private fun Panel() {
    val loggedIn by Hub.loggedIn.collectAsState()
    val queue by Hub.queue.collectAsState()
    val index by Hub.index.collectAsState()
    val track = queue.getOrNull(index)
    when {
        !loggedIn -> EmptyState("Connecte Sona", "Ouvre l'app Sona dans le casque et autorise-la depuis ton iPhone.")
        track == null -> EmptyState("Rien en lecture", "Lance un titre depuis l'app, ton iPhone ou le site.")
        else -> Column(Modifier.fillMaxSize().padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Cover(track.coverUrl, Modifier.size(76.dp))
                Column(Modifier.weight(1f)) {
                    SonaText(track.title, 21.sp, FontWeight.ExtraBold, maxLines = 1, title = true)
                    SonaText(track.artist, 15.sp, tone = 1, maxLines = 1)
                }
            }
            LyricsView(Modifier.weight(1f).fillMaxWidth(), fontSize = 26.sp)
            TransportControls(Modifier.fillMaxWidth(), compact = true)
        }
    }
}
