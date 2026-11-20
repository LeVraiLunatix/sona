package fr.sona.quest

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import android.media.audiofx.Visualizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Headset
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PhoneIphone
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.pow

enum class Tab(val label: String, val icon: ImageVector) {
    Player("Lecteur", Icons.Filled.MusicNote),
    Search("Recherche", Icons.Filled.Search),
    Devices("Appareils", Icons.Filled.Devices),
    Visualizer("Visualiseur", Icons.Filled.GraphicEq),
    Settings("Réglages", Icons.Filled.Settings),
}

@Composable
fun Root() {
    val loggedIn by Hub.loggedIn.collectAsState()
    if (loggedIn) MainScreen() else LoginScreen()
}

@Composable
fun MainScreen() {
    var tab by remember { mutableStateOf(Tab.Player) }
    val compact = LocalConfiguration.current.screenWidthDp < 720
    val snackbar = remember { SnackbarHostState() }
    val message by Hub.message.collectAsState()
    LaunchedEffect(message) {
        message?.let {
            snackbar.showSnackbar(it)
            Hub.message.value = null
        }
    }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (compact) {
                NavigationBar {
                    Tab.entries.forEach {
                        NavigationBarItem(
                            selected = tab == it,
                            onClick = { tab = it },
                            icon = { Icon(it.icon, it.label) },
                            label = { Text(it.label, maxLines = 1) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        Row(Modifier.padding(padding).fillMaxSize()) {
            if (!compact) {
                NavigationRail {
                    Spacer(Modifier.height(12.dp))
                    Tab.entries.forEach {
                        NavigationRailItem(
                            selected = tab == it,
                            onClick = { tab = it },
                            icon = { Icon(it.icon, it.label) },
                            label = { Text(it.label) },
                        )
                    }
                }
            }
            Box(Modifier.weight(1f).fillMaxSize()) {
                when (tab) {
                    Tab.Player -> PlayerScreen(compact)
                    Tab.Search -> SearchScreen { tab = Tab.Player }
                    Tab.Devices -> DevicesScreen()
                    Tab.Visualizer -> VisualizerScreen()
                    Tab.Settings -> SettingsScreen()
                }
            }
        }
    }
}

// ── Connexion par QR code ────────────────────────────────────────────────────

private fun qrBitmap(text: String, size: Int = 640): ImageBitmap {
    val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
    val pixels = IntArray(size * size) { i ->
        if (matrix[i % size, i / size]) AndroidColor.BLACK else AndroidColor.WHITE
    }
    return Bitmap.createBitmap(pixels, size, size, Bitmap.Config.ARGB_8888).asImageBitmap()
}

@Composable
fun LoginScreen() {
    var start by remember { mutableStateOf<DeviceStartOut?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        while (isActive) {
            try {
                val s = withContext(Dispatchers.IO) { Hub.api.deviceStart(Hub.settings.deviceName) }
                start = s
                error = null
                var waited = 0
                while (waited < s.expiresIn) {
                    delay(s.interval.coerceAtLeast(2) * 1000L)
                    waited += s.interval.coerceAtLeast(2)
                    val r = withContext(Dispatchers.IO) { Hub.api.devicePoll(s.deviceCode) }
                    if (r.status == "approved" && r.sessionToken != null) {
                        Hub.login(r.sessionToken)
                        return@LaunchedEffect
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = e.message
                delay(4000)
            }
        }
    }
    val s = start
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Sona", fontSize = 44.sp, fontWeight = FontWeight.Bold, color = Accent)
        Text("Ta musique, en clair — sur Meta Quest", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(28.dp))
        if (s == null) {
            CircularProgressIndicator(color = Accent)
            error?.let {
                Spacer(Modifier.height(12.dp))
                Text(it, color = Color(0xFFFF8A8A), textAlign = TextAlign.Center)
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(36.dp), verticalAlignment = Alignment.CenterVertically) {
                val bitmap = remember(s.verifyUrl) { qrBitmap(s.verifyUrl) }
                Image(bitmap, "QR code de connexion", Modifier.size(300.dp))
                Column(Modifier.width(380.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Scanne ce code avec ton iPhone", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                    Text(
                        "Ouvre l'appareil photo, vise le QR code, puis autorise le casque dans Sona. " +
                            "Pas de clavier à utiliser dans le casque.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(s.userCode, fontSize = 40.sp, fontWeight = FontWeight.Bold, letterSpacing = 6.sp)
                    Text(
                        "Ou ouvre le site Sona connecté et entre ce code.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 13.sp,
                    )
                    Text("En attente de ton autorisation…", color = Accent)
                }
            }
        }
    }
}

// ── Lecteur ──────────────────────────────────────────────────────────────────

@Composable
fun PlayerScreen(compact: Boolean) {
    val queue by Hub.queue.collectAsState()
    val index by Hub.index.collectAsState()
    val position by Hub.positionMs.collectAsState()
    val duration by Hub.durationMs.collectAsState()
    val track = queue.getOrNull(index)
    if (track == null) {
        CenterMessage(
            "Rien en lecture",
            "Cherche un titre, ou lance la musique depuis ton iPhone ou le site avec Sona Connect : " +
                "ce casque s'appelle « ${Hub.settings.deviceName} ».",
        )
        return
    }
    var drag by remember { mutableStateOf<Float?>(null) }
    val total = duration.coerceAtLeast(1L).toFloat()
    val info: @Composable (Modifier) -> Unit = { modifier ->
        Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(track.title, fontSize = 28.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(track.artist, fontSize = 18.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            Slider(
                value = (drag ?: position.toFloat()).coerceIn(0f, total),
                onValueChange = { drag = it },
                onValueChangeFinished = {
                    drag?.let { Hub.seekTo(it / 1000.0) }
                    drag = null
                },
                valueRange = 0f..total,
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(formatTime((drag ?: position.toFloat()).toLong()), fontSize = 13.sp)
                Text(formatTime(duration), fontSize = 13.sp)
            }
            TransportControls(Modifier.fillMaxWidth())
        }
    }
    if (compact) {
        Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Cover(track.coverUrl, Modifier.size(120.dp))
                info(Modifier.weight(1f))
            }
            LyricsView(Modifier.weight(1f).fillMaxWidth(), fontSize = 22.sp)
        }
    } else {
        Row(Modifier.fillMaxSize().padding(28.dp), horizontalArrangement = Arrangement.spacedBy(32.dp)) {
            Column(Modifier.width(400.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Cover(track.coverUrl, Modifier.size(400.dp))
                info(Modifier.fillMaxWidth())
            }
            LyricsView(Modifier.weight(1f).fillMaxSize(), fontSize = 30.sp)
        }
    }
}

// ── Recherche ────────────────────────────────────────────────────────────────

@Composable
fun SearchScreen(onPlay: () -> Unit) {
    var q by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Track>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun run() {
        if (q.isBlank() || loading) return
        loading = true
        scope.launch {
            results = withContext(Dispatchers.IO) {
                runCatching { Hub.api.search(q.trim()) }.getOrElse {
                    Hub.message.value = it.message ?: "Recherche impossible"
                    emptyList()
                }
            }
            loading = false
        }
    }
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = q,
                onValueChange = { q = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                label = { Text("Rechercher un titre, un artiste…") },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { run() }),
            )
            Button(onClick = { run() }) { Text("Chercher") }
        }
        if (loading) {
            Box(Modifier.fillMaxWidth().padding(24.dp), Alignment.Center) { CircularProgressIndicator(color = Accent) }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            itemsIndexed(results) { i, t ->
                TrackRow(t) {
                    Hub.playQueue(results, i, "Recherche : ${q.trim()}")
                    onPlay()
                }
            }
        }
    }
}

// ── Appareils (Sona Connect) ─────────────────────────────────────────────────

private fun kindIcon(kind: String): ImageVector = when (kind) {
    "iphone" -> Icons.Filled.PhoneIphone
    "quest" -> Icons.Filled.Headset
    "desktop" -> Icons.Filled.Computer
    else -> Icons.Filled.Language
}

@Composable
fun DevicesScreen() {
    val devices by Hub.devices.collectAsState()
    val active by Hub.activeDeviceId.collectAsState()
    val session by Hub.session.collectAsState()
    val me = Hub.settings.deviceId
    LazyColumn(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("Sona Connect", fontSize = 26.sp, fontWeight = FontWeight.Bold)
            Text(
                "Tous tes appareils se voient. Pilote la musique d'ici, ou lance-la depuis ton iPhone ou le site : ce casque apparaît dans leur liste.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        val s = session
        if (s != null && s.deviceId != me && s.track != null) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Cover(s.track.coverUrl, Modifier.size(64.dp))
                        Column(Modifier.weight(1f)) {
                            Text("Reprendre ici", fontWeight = FontWeight.Bold)
                            Text("${s.track.title} — ${s.track.artist}", maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("Sur ${s.deviceName}", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
                        }
                        Button(onClick = { Hub.remote(me, "transfer") }) { Text("Écouter ici") }
                    }
                }
            }
        }
        items(devices, key = { it.id }) { d ->
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Icon(kindIcon(d.kind), null, tint = if (d.id == active) Accent else Color.Gray, modifier = Modifier.size(36.dp))
                    Column(Modifier.weight(1f)) {
                        Text(if (d.isMe) "${d.name} (ce casque)" else d.name, fontWeight = FontWeight.SemiBold)
                        Text(
                            d.track?.let { "${if (d.playing) "En lecture" else "En pause"} · ${it.title} — ${it.artist}" } ?: "Rien en lecture",
                            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 14.sp,
                        )
                    }
                    if (!d.isMe && d.track != null) {
                        IconButton(onClick = { Hub.remote(d.id, "toggle") }) {
                            Icon(if (d.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Lecture / pause")
                        }
                        IconButton(onClick = { Hub.remote(d.id, "next") }) { Icon(Icons.Filled.SkipNext, "Suivant") }
                    }
                }
            }
        }
    }
}

// ── Visualiseur ──────────────────────────────────────────────────────────────

private fun fftToBars(fft: ByteArray, n: Int, previous: FloatArray): FloatArray {
    val bins = fft.size / 2 - 1
    val out = FloatArray(n)
    if (bins < 8) return out
    for (i in 0 until n) {
        val lo = bins.toDouble().pow(i.toDouble() / n).toInt().coerceIn(1, bins - 1)
        val hi = bins.toDouble().pow((i + 1).toDouble() / n).toInt().coerceIn(lo + 1, bins)
        var m = 0f
        for (k in lo until hi) {
            m = max(m, hypot(fft[2 * k].toFloat(), fft[2 * k + 1].toFloat()))
        }
        val v = (m / 128f).coerceIn(0f, 1f).pow(0.6f)
        out[i] = max(v, previous.getOrElse(i) { 0f } * 0.86f)
    }
    return out
}

@Composable
fun VisualizerScreen() {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    if (!granted) {
        Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Text("Visualiseur", fontSize = 26.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            Text(
                "Il analyse le son que Sona joue lui-même, jamais le micro. Android appelle ça « enregistrer l'audio », d'où cette autorisation.",
                color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(16.dp))
            Button(onClick = { launcher.launch(Manifest.permission.RECORD_AUDIO) }) { Text("Autoriser") }
        }
        return
    }
    val sessionId by Hub.audioSessionId.collectAsState()
    val track by Hub.queue.collectAsState()
    var bars by remember { mutableStateOf(FloatArray(48)) }
    DisposableEffect(sessionId) {
        var viz: Visualizer? = null
        try {
            viz = Visualizer(sessionId).apply {
                captureSize = Visualizer.getCaptureSizeRange()[1].coerceAtMost(1024)
                setDataCaptureListener(object : Visualizer.OnDataCaptureListener {
                    override fun onWaveFormDataCapture(v: Visualizer?, waveform: ByteArray?, samplingRate: Int) = Unit
                    override fun onFftDataCapture(v: Visualizer?, fft: ByteArray?, samplingRate: Int) {
                        if (fft != null) bars = fftToBars(fft, 48, bars)
                    }
                }, Visualizer.getMaxCaptureRate() / 2, false, true)
                enabled = true
            }
        } catch (e: Exception) {
            Hub.message.value = "Visualiseur indisponible : ${e.message}"
        }
        onDispose {
            runCatching {
                viz?.enabled = false
                viz?.release()
            }
        }
    }
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            val n = bars.size
            val gap = 6.dp.toPx()
            val w = (size.width - gap * (n + 1)) / n
            val mid = size.height / 2f
            val bass = (bars.take(5).average().toFloat()).coerceIn(0f, 1f)
            // Pulsation au rythme des basses, derrière les barres.
            drawCircle(Accent.copy(alpha = 0.10f + 0.25f * bass), radius = size.minDimension * (0.22f + 0.22f * bass), center = Offset(size.width / 2, mid))
            for (i in 0 until n) {
                val h = (size.height * 0.46f * bars[i]).coerceAtLeast(4.dp.toPx())
                val color = Color.hsv((250f + i * 2.6f) % 360f, 0.55f, 1f)
                val x = gap + i * (w + gap)
                drawRoundRect(color, Offset(x, mid - h), Size(w, h * 2), CornerRadius(w / 2, w / 2))
            }
        }
        if (track.isEmpty()) {
            CenterMessage("Lance une musique", "Le visualiseur réagit au son pendant la lecture.")
        }
    }
}

// ── Réglages ─────────────────────────────────────────────────────────────────

@Composable
fun SettingsScreen() {
    var server by remember { mutableStateOf(Hub.settings.server) }
    var name by remember { mutableStateOf(Hub.settings.deviceName) }
    var keep by remember { mutableStateOf(Hub.settings.keepOverGames) }
    Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Réglages", fontSize = 26.sp, fontWeight = FontWeight.Bold)
        OutlinedTextField(
            value = name, onValueChange = { name = it }, singleLine = true,
            label = { Text("Nom de ce casque dans Sona Connect") }, modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = server, onValueChange = { server = it }, singleLine = true,
            label = { Text("Serveur Sona") }, modifier = Modifier.fillMaxWidth(),
        )
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Switch(checked = keep, onCheckedChange = {
                keep = it
                Hub.setKeepOverGames(it)
            })
            Column {
                Text("Continuer pendant les jeux VR", fontWeight = FontWeight.SemiBold)
                Text(
                    "La musique ne s'arrête pas quand un jeu prend le son. Coupe-le si le jeu et Sona se gênent.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                Hub.settings.server = server
                Hub.settings.deviceName = name
                Hub.message.value = "Enregistré. Les changements de serveur s'appliquent aux prochaines requêtes."
            }) { Text("Enregistrer") }
            OutlinedButton(onClick = { Hub.logout() }) { Text("Se déconnecter") }
        }
    }
}
