package fr.sona.quest

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.Player
import coil.compose.AsyncImage

val Accent = Color(0xFF9F7BFF)
val Ink = Color(0xFF0B0B12)

@Composable
fun SonaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent,
            onPrimary = Color.Black,
            background = Ink,
            onBackground = Color.White,
            surface = Color(0xFF14141F),
            onSurface = Color.White,
            surfaceVariant = Color(0xFF1E1E2D),
            onSurfaceVariant = Color(0xFFB8B8C8),
        ),
        content = content,
    )
}

fun formatTime(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

@Composable
fun Cover(url: String?, modifier: Modifier = Modifier) {
    AsyncImage(
        model = url,
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    )
}

@Composable
fun CenterMessage(title: String, text: String = "") {
    Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, fontSize = 24.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
            if (text.isNotEmpty()) {
                Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
            }
        }
    }
}

/** Paroles synchronisées : la ligne en cours reste en vue, un appui s'y place. */
@Composable
fun LyricsView(modifier: Modifier = Modifier, fontSize: TextUnit = 26.sp) {
    val lyrics by Hub.lyrics.collectAsState()
    val position by Hub.positionMs.collectAsState()
    val l = lyrics
    val synced = l != null && l.synced && l.lines.any { it.time != null }
    val current = if (synced && l != null) {
        l.lines.indexOfLast { (it.time ?: Double.MAX_VALUE) * 1000 <= position }
    } else -1
    val listState = rememberLazyListState()
    LaunchedEffect(current) {
        if (current >= 0) listState.animateScrollToItem((current - 2).coerceAtLeast(0))
    }
    when {
        l == null -> Box(modifier, Alignment.Center) {
            CircularProgressIndicator(Modifier.size(28.dp), color = Accent)
        }
        l.instrumental -> Box(modifier, Alignment.Center) { Text("Instrumental", color = Color.Gray, fontSize = 22.sp) }
        l.lines.isEmpty() -> Box(modifier, Alignment.Center) { Text("Pas de paroles pour ce titre", color = Color.Gray) }
        else -> LazyColumn(modifier, state = listState, contentPadding = PaddingValues(vertical = 48.dp)) {
            itemsIndexed(l.lines) { i, line ->
                val seekable = synced && line.time != null
                Text(
                    text = line.text.ifBlank { "♪" },
                    fontSize = fontSize,
                    fontWeight = if (i == current) FontWeight.Bold else FontWeight.Medium,
                    color = if (!synced || i == current) Color.White else Color.White.copy(alpha = 0.4f),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(enabled = seekable) { line.time?.let { Hub.seekTo(it) } }
                        .padding(vertical = 8.dp, horizontal = 8.dp),
                )
            }
        }
    }
}

@Composable
fun TransportControls(modifier: Modifier = Modifier, big: Boolean = true) {
    val playing by Hub.playing.collectAsState()
    val buffering by Hub.buffering.collectAsState()
    val shuffle by Hub.shuffle.collectAsState()
    val repeat by Hub.repeat.collectAsState()
    val side = if (big) 56.dp else 44.dp
    Row(modifier, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { Hub.toggleShuffle() }) {
            Icon(Icons.Filled.Shuffle, "Aléatoire", tint = if (shuffle) Accent else Color.Gray)
        }
        IconButton(onClick = { Hub.previous() }, Modifier.size(side)) { Icon(Icons.Filled.SkipPrevious, "Précédent") }
        FilledIconButton(onClick = { Hub.toggle() }, Modifier.padding(horizontal = 8.dp).size(side + 12.dp)) {
            if (buffering && !playing) {
                CircularProgressIndicator(Modifier.size(28.dp), color = Color.Black, strokeWidth = 3.dp)
            } else {
                Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Lecture", Modifier.size(32.dp))
            }
        }
        IconButton(onClick = { Hub.next() }, Modifier.size(side)) { Icon(Icons.Filled.SkipNext, "Suivant") }
        IconButton(onClick = { Hub.cycleRepeat() }) {
            Icon(
                if (repeat == Player.REPEAT_MODE_ONE) Icons.Filled.RepeatOne else Icons.Filled.Repeat,
                "Répéter",
                tint = if (repeat == Player.REPEAT_MODE_OFF) Color.Gray else Accent,
            )
        }
    }
}

@Composable
fun TrackRow(track: Track, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Cover(track.coverUrl, Modifier.size(56.dp))
        Column(Modifier.weight(1f)) {
            Text(track.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                listOfNotNull(track.artist, track.album).joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        track.durationSeconds?.let { Text(formatTime(it * 1000L), color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}
