package fr.sona.quest

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.common.Player
import coil.compose.AsyncImage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.min

fun formatTime(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

// ── Mouvement : enfoncement au toucher et apparition en cascade (comme l'app iPhone) ─────

fun Modifier.pressable(onClick: () -> Unit): Modifier = composed {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) 0.96f else 1f, spring(stiffness = 600f), label = "press")
    this
        .graphicsLayer {
            scaleX = scale
            scaleY = scale
            alpha = if (pressed) 0.8f else 1f
        }
        .clickable(interactionSource = source, indication = null, onClick = onClick)
}

fun Modifier.reveal(index: Int = 0): Modifier = composed {
    val progress = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        delay(min(index, 8) * 60L)
        progress.animateTo(1f, tween(480, easing = FastOutSlowInEasing))
    }
    this.graphicsLayer {
        alpha = progress.value
        translationY = (1f - progress.value) * 28f
    }
}

// ── Fonds et surfaces ────────────────────────────────────────────────────────────────────

@Composable
fun LookBackground(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val look = LocalLook.current
    Box(
        modifier
            .fillMaxSize()
            .then(if (look.backgroundBrush != null) Modifier.background(look.backgroundBrush) else Modifier.background(look.background)),
    ) { content() }
}

/** Le « verre fumé » de Sona : une surface à peine détachée du fond, un filet clair. */
fun Modifier.glass(corner: Dp? = null, strong: Boolean = false): Modifier = composed {
    val look = LocalLook.current
    val shape = RoundedCornerShape(corner ?: look.corner)
    this
        .clip(shape)
        .background(if (strong) look.surfaceStrong else look.surface, shape)
        .border(BorderStroke(1.dp, look.separator), shape)
}

@Composable
fun SonaText(
    text: String,
    size: TextUnit = 16.sp,
    weight: FontWeight = FontWeight.Normal,
    tone: Int = 0,
    modifier: Modifier = Modifier,
    maxLines: Int = Int.MAX_VALUE,
    align: TextAlign? = null,
    title: Boolean = false,
    color: Color? = null,
) {
    val look = LocalLook.current
    val tint = color ?: when (tone) {
        1 -> look.secondary
        2 -> look.tertiary
        3 -> look.accent
        else -> look.primary
    }
    Text(
        text = if (title && look.uppercaseTitles) text.uppercase() else text,
        color = tint,
        fontSize = size,
        fontWeight = weight,
        fontFamily = look.font,
        letterSpacing = if (title) (-0.4).sp else 0.sp,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
        textAlign = align,
        modifier = modifier,
    )
}

@Composable
fun PageTitle(text: String, sub: String? = null, modifier: Modifier = Modifier) {
    Column(modifier.padding(bottom = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        SonaText(text, 38.sp, FontWeight.Bold, title = true)
        if (sub != null) SonaText(sub, 16.sp, tone = 1)
    }
}

@Composable
fun SectionHeader(title: String, modifier: Modifier = Modifier) {
    SonaText(title, 24.sp, FontWeight.Bold, modifier = modifier.padding(top = 18.dp, bottom = 10.dp), title = true)
}

@Composable
fun PillButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    primary: Boolean = true,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
) {
    val look = LocalLook.current
    Row(
        modifier
            .height(50.dp)
            .clip(RoundedCornerShape(look.corner))
            .background(if (primary) look.buttonFill else look.surfaceStrong)
            .pressable(onClick)
            .padding(horizontal = 22.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) Icon(icon, null, tint = if (primary) look.buttonText else look.primary, modifier = Modifier.size(22.dp))
        Text(
            text, color = if (primary) look.buttonText else look.primary,
            fontWeight = FontWeight.SemiBold, fontSize = 16.sp, fontFamily = look.font,
        )
    }
}

@Composable
fun Cover(url: String?, modifier: Modifier = Modifier, round: Boolean = false) {
    val look = LocalLook.current
    AsyncImage(
        model = url,
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .clip(if (round) CircleShape else RoundedCornerShape(if (look.corner < 6.dp) look.corner else 10.dp))
            .background(look.surfaceStrong),
    )
}

@Composable
fun CoverCard(
    url: String?,
    title: String,
    subtitle: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 190.dp,
    round: Boolean = false,
) {
    Column(modifier.width(size).pressable(onClick), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Cover(url, Modifier.size(size), round)
        SonaText(title, 15.sp, FontWeight.SemiBold, maxLines = 1, align = if (round) TextAlign.Center else null,
            modifier = Modifier.fillMaxWidth())
        if (!subtitle.isNullOrBlank()) {
            SonaText(subtitle, 13.sp, tone = 1, maxLines = 1, align = if (round) TextAlign.Center else null,
                modifier = Modifier.fillMaxWidth())
        }
    }
}

/** Les petites barres animées de « en lecture » (les barres du site). */
@Composable
fun NowBars(playing: Boolean, modifier: Modifier = Modifier, color: Color = LocalLook.current.accent) {
    val transition = rememberInfiniteTransition(label = "bars")
    val a by transition.animateFloat(0.3f, 1f, infiniteRepeatable(tween(420), RepeatMode.Reverse), label = "a")
    val b by transition.animateFloat(1f, 0.35f, infiniteRepeatable(tween(520), RepeatMode.Reverse), label = "b")
    val c by transition.animateFloat(0.5f, 0.95f, infiniteRepeatable(tween(360), RepeatMode.Reverse), label = "c")
    Canvas(modifier.size(18.dp)) {
        val w = size.width / 5f
        val hs = if (playing) listOf(a, b, c) else listOf(0.3f, 0.3f, 0.3f)
        hs.forEachIndexed { i, h ->
            val bar = size.height * h
            drawRoundRect(color, Offset(i * 2f * w, size.height - bar), Size(w, bar), CornerRadius(w / 2, w / 2))
        }
    }
}

@Composable
fun TrackItem(
    track: Track,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    number: Int? = null,
    current: Boolean = false,
    showCover: Boolean = true,
) {
    val look = LocalLook.current
    val playing by Hub.playing.collectAsState()
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(look.corner))
            .background(if (current) look.accent.copy(alpha = 0.16f) else Color.Transparent)
            .pressable(onClick)
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (number != null && !showCover) {
            Box(Modifier.width(28.dp), Alignment.Center) {
                if (current) NowBars(playing) else SonaText("$number", 15.sp, tone = 2)
            }
        }
        if (showCover) Cover(track.coverUrl, Modifier.size(56.dp))
        Column(Modifier.weight(1f)) {
            SonaText(track.title, 16.sp, FontWeight.Medium, maxLines = 1)
            SonaText(listOfNotNull(track.artist, track.album).joinToString(" · "), 14.sp, tone = 1, maxLines = 1)
        }
        if (current && showCover) NowBars(playing)
        val downloaded by Downloads.items.collectAsState()
        if (downloaded.any { it.track.source == track.source && it.track.sourceId == track.sourceId }) {
            Icon(Icons.Filled.DownloadDone, "Téléchargé", tint = look.accent, modifier = Modifier.size(20.dp))
        }
        track.durationSeconds?.let { SonaText(formatTime(it * 1000L), 14.sp, tone = 2) }
    }
}

// ── Chargement d'une donnée de l'API ─────────────────────────────────────────────────────

sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Done<T>(val value: T) : Load<T>
    data class Failed(val message: String) : Load<Nothing>
}

@Composable
fun <T> load(key: Any?, block: suspend () -> T): State<Load<T>> = produceState<Load<T>>(Load.Loading, key) {
    value = Load.Loading
    value = try {
        Load.Done(withContext(Dispatchers.IO) { block() })
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Load.Failed(e.message ?: "Impossible de charger")
    }
}

/** Affiche la donnée, ou un chargement discret, ou l'erreur. */
@Composable
fun <T> Loaded(state: Load<T>, modifier: Modifier = Modifier, content: @Composable (T) -> Unit) {
    when (state) {
        Load.Loading -> Box(modifier.fillMaxWidth().padding(28.dp), Alignment.Center) {
            CircularProgressIndicator(Modifier.size(26.dp), color = LocalLook.current.accent, strokeWidth = 3.dp)
        }
        is Load.Failed -> SonaText(state.message, 14.sp, tone = 2, modifier = modifier.padding(12.dp))
        is Load.Done -> content(state.value)
    }
}

@Composable
fun EmptyState(title: String, text: String = "") {
    Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SonaText(title, 24.sp, FontWeight.Bold, align = TextAlign.Center, title = true)
            if (text.isNotEmpty()) SonaText(text, 16.sp, tone = 1, align = TextAlign.Center)
        }
    }
}

// ── Paroles synchronisées ────────────────────────────────────────────────────────────────

@Composable
fun LyricsView(modifier: Modifier = Modifier, fontSize: TextUnit = 30.sp) {
    val look = LocalLook.current
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
            CircularProgressIndicator(Modifier.size(28.dp), color = look.accent, strokeWidth = 3.dp)
        }
        l.instrumental -> Box(modifier, Alignment.Center) { SonaText("Instrumental", 22.sp, tone = 2) }
        l.lines.isEmpty() -> Box(modifier, Alignment.Center) { SonaText("Pas de paroles pour ce titre", 18.sp, tone = 2) }
        else -> LazyColumn(modifier, state = listState, contentPadding = PaddingValues(vertical = 60.dp)) {
            itemsIndexed(l.lines) { i, line ->
                val on = !synced || i == current
                val scale by animateFloatAsState(if (i == current) 1f else 0.94f, spring(stiffness = 300f), label = "line")
                Text(
                    text = line.text.ifBlank { "♪" },
                    fontSize = fontSize,
                    fontWeight = if (i == current) FontWeight.Bold else FontWeight.SemiBold,
                    fontFamily = look.font,
                    color = if (on) look.primary else look.primary.copy(alpha = 0.32f),
                    modifier = Modifier
                        .fillMaxWidth()
                        .graphicsLayer {
                            scaleX = scale
                            scaleY = scale
                            transformOrigin = androidx.compose.ui.graphics.TransformOrigin(0f, 0.5f)
                        }
                        .clickable(enabled = synced && line.time != null) { line.time?.let { Hub.seekTo(it) } }
                        .padding(vertical = 9.dp, horizontal = 8.dp),
                )
            }
        }
    }
}

// ── Contrôles de lecture ─────────────────────────────────────────────────────────────────

@Composable
fun TransportControls(modifier: Modifier = Modifier, compact: Boolean = false) {
    val look = LocalLook.current
    val playing by Hub.playing.collectAsState()
    val buffering by Hub.buffering.collectAsState()
    val shuffle by Hub.shuffle.collectAsState()
    val repeat by Hub.repeat.collectAsState()
    val side = if (compact) 44.dp else 56.dp
    Row(modifier, horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        if (!compact) {
            IconButton(onClick = { Hub.toggleShuffle() }) {
                Icon(Icons.Filled.Shuffle, "Aléatoire", tint = if (shuffle) look.accent else look.tertiary)
            }
        }
        IconButton(onClick = { Hub.previous() }, Modifier.size(side)) {
            Icon(Icons.Filled.SkipPrevious, "Précédent", tint = look.primary, modifier = Modifier.size(32.dp))
        }
        Box(
            Modifier
                .padding(horizontal = 10.dp)
                .size(side + 10.dp)
                .clip(CircleShape)
                .background(look.buttonFill)
                .pressable { Hub.toggle() },
            Alignment.Center,
        ) {
            if (buffering && !playing) {
                CircularProgressIndicator(Modifier.size(26.dp), color = look.buttonText, strokeWidth = 3.dp)
            } else {
                Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Lecture", tint = look.buttonText, modifier = Modifier.size(34.dp))
            }
        }
        IconButton(onClick = { Hub.next() }, Modifier.size(side)) {
            Icon(Icons.Filled.SkipNext, "Suivant", tint = look.primary, modifier = Modifier.size(32.dp))
        }
        if (!compact) {
            IconButton(onClick = { Hub.cycleRepeat() }) {
                Icon(
                    if (repeat == Player.REPEAT_MODE_ONE) Icons.Filled.RepeatOne else Icons.Filled.Repeat,
                    "Répéter",
                    tint = if (repeat == Player.REPEAT_MODE_OFF) look.tertiary else look.accent,
                )
            }
        }
    }
}

@Composable
fun <T> HorizontalShelf(items: List<T>, modifier: Modifier = Modifier, content: @Composable (Int, T) -> Unit) {
    LazyRow(modifier, horizontalArrangement = Arrangement.spacedBy(18.dp), contentPadding = PaddingValues(end = 24.dp)) {
        itemsIndexed(items) { i, item -> content(i, item) }
    }
}
