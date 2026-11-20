package fr.sona.quest

import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cast
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Headset
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PhoneIphone
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext

fun kindIcon(kind: String): ImageVector = when (kind) {
    "iphone" -> Icons.Filled.PhoneIphone
    "quest" -> Icons.Filled.Headset
    "desktop" -> Icons.Filled.Computer
    else -> Icons.Filled.Language
}

// ── Connexion : « Autoriser » sur l'iPhone, le QR code en secours ───────────────────────

private fun qrBitmap(text: String, size: Int = 520): ImageBitmap {
    val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
    val pixels = IntArray(size * size) { i -> if (matrix[i % size, i / size]) AndroidColor.BLACK else AndroidColor.WHITE }
    return Bitmap.createBitmap(pixels, size, size, Bitmap.Config.ARGB_8888).asImageBitmap()
}

@Composable
fun LoginScreen() {
    val look = LocalLook.current
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
                    val step = s.interval.coerceAtLeast(2)
                    delay(step * 1000L)
                    waited += step
                    val r = withContext(Dispatchers.IO) { Hub.api.devicePoll(s.deviceCode) }
                    if (r.status == "approved" && r.sessionToken != null) {
                        Hub.login(r.sessionToken)
                        return@LaunchedEffect
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Refus ou code expiré : on en demande un neuf.
                error = e.message
                delay(3000)
            }
        }
    }
    Box(Modifier.fillMaxSize().padding(36.dp), Alignment.Center) {
        Column(
            Modifier.verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            SonaText("Sona", 72.sp, FontWeight.ExtraBold, title = true, modifier = Modifier.reveal(0))
            SonaText("Ta musique, en clair — sur Meta Quest.", 20.sp, tone = 1, modifier = Modifier.reveal(1))
            Spacer(Modifier.height(18.dp))
            val s = start
            if (s == null) {
                CircularProgressIndicator(color = look.accent)
                error?.let { SonaText(it, 14.sp, tone = 2, align = TextAlign.Center) }
            } else {
                Row(
                    Modifier.glass(24.dp).reveal(2).padding(30.dp),
                    horizontalArrangement = Arrangement.spacedBy(40.dp), verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.width(460.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        SonaText("Connecte ce casque à ton compte", 24.sp, FontWeight.Bold, title = true)
                        Step(1, "Ouvre Sona sur ton iPhone ou sur le site, connecté à ton compte.")
                        Step(2, "Une demande « ${Hub.settings.deviceName} veut se connecter » s'affiche : appuie sur Autoriser.")
                        Step(3, "Vérifie que le code est bien :")
                        SonaText(s.userCode, 44.sp, FontWeight.ExtraBold, tone = 3, modifier = Modifier.padding(start = 40.dp))
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            CircularProgressIndicator(Modifier.size(18.dp), color = look.accent, strokeWidth = 2.dp)
                            SonaText("En attente de ton autorisation…", 14.sp, tone = 1)
                        }
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        val bitmap = remember(s.verifyUrl) { qrBitmap(s.verifyUrl) }
                        Image(bitmap, "QR code de connexion", Modifier.size(190.dp).clip(RoundedCornerShape(12.dp)))
                        SonaText("Pas de demande ? Scanne ce code", 13.sp, tone = 2, align = TextAlign.Center, modifier = Modifier.width(190.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun Step(n: Int, text: String) {
    val look = LocalLook.current
    Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.Top) {
        Box(Modifier.size(26.dp).clip(RoundedCornerShape(50)).background(look.surfaceStrong), Alignment.Center) {
            SonaText("$n", 14.sp, FontWeight.Bold)
        }
        SonaText(text, 16.sp, tone = 1, modifier = Modifier.weight(1f))
    }
}

// ── Appareils (Sona Connect) ─────────────────────────────────────────────────────────────

@Composable
fun DevicesScreen() {
    val look = LocalLook.current
    val devices by Hub.devices.collectAsState()
    val active by Hub.activeDeviceId.collectAsState()
    val session by Hub.session.collectAsState()
    val me = Hub.settings.deviceId
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 30.dp, vertical = 26.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            PageTitle(
                "Appareils",
                "Sona Connect : tous tes appareils se voient. Pilote la musique d'ici, ou lance-la depuis ton iPhone ou le site.",
                Modifier.reveal(0),
            )
        }
        val s = session
        if (s != null && s.deviceId != me && s.track != null) {
            item {
                Row(Modifier.fillMaxWidth().glass(strong = true).padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Cover(s.track.coverUrl, Modifier.size(72.dp))
                    Column(Modifier.weight(1f)) {
                        SonaText("Reprendre ici", 14.sp, FontWeight.Bold, tone = 3)
                        SonaText("${s.track.title} — ${s.track.artist}", 17.sp, FontWeight.SemiBold, maxLines = 1)
                        SonaText("Sur ${s.deviceName}", 13.sp, tone = 1)
                    }
                    PillButton("Écouter ici", { Hub.remote(me, "transfer") }, icon = Icons.Filled.Cast)
                }
            }
        }
        if (devices.isEmpty()) {
            item { SonaText("Aucun appareil connecté pour l'instant.", 16.sp, tone = 2) }
        }
        items(devices, key = { it.id }) { d ->
            Row(Modifier.fillMaxWidth().glass().padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Icon(kindIcon(d.kind), null, tint = if (d.id == active) look.accent else look.secondary, modifier = Modifier.size(36.dp))
                Column(Modifier.weight(1f)) {
                    SonaText(if (d.isMe) "${d.name} (ce casque)" else d.name, 17.sp, FontWeight.SemiBold, maxLines = 1)
                    SonaText(
                        d.track?.let { "${if (d.playing) "En lecture" else "En pause"} · ${it.title} — ${it.artist}" } ?: "Rien en lecture",
                        14.sp, tone = 1, maxLines = 1,
                    )
                }
                if (!d.isMe && d.track != null) {
                    IconButton(onClick = { Hub.remote(d.id, "toggle") }) {
                        Icon(if (d.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Lecture / pause", tint = look.primary)
                    }
                    IconButton(onClick = { Hub.remote(d.id, "next") }) { Icon(Icons.Filled.SkipNext, "Suivant", tint = look.primary) }
                }
            }
        }
    }
}

// ── Réglages ─────────────────────────────────────────────────────────────────────────────

@Composable
fun SettingsScreen() {
    val look = LocalLook.current
    val theme by Hub.theme.collectAsState()
    var server by remember { mutableStateOf(Hub.settings.server) }
    var name by remember { mutableStateOf(Hub.settings.deviceName) }
    var keep by remember { mutableStateOf(Hub.settings.keepOverGames) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 30.dp, vertical = 26.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        PageTitle("Réglages", modifier = Modifier.reveal(0))

        SectionHeader("Apparence")
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            ThemeId.entries.forEach { id ->
                val l = lookFor(id)
                val on = id == theme
                Column(
                    Modifier
                        .width(230.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .border(if (on) 2.dp else 1.dp, if (on) look.accent else look.separator, RoundedCornerShape(18.dp))
                        .pressable { Hub.setTheme(id) },
                ) {
                    Box(
                        Modifier.fillMaxWidth().height(110.dp)
                            .then(if (l.backgroundBrush != null) Modifier.background(l.backgroundBrush) else Modifier.background(l.background)),
                        Alignment.Center,
                    ) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(34.dp).clip(RoundedCornerShape(l.corner.coerceAtMost(10.dp))).background(l.surfaceStrong))
                            Box(Modifier.size(width = 70.dp, height = 12.dp).clip(RoundedCornerShape(50)).background(l.accent))
                        }
                    }
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        SonaText(id.label, 17.sp, FontWeight.Bold)
                        SonaText(id.hint, 12.sp, tone = 1, maxLines = 2)
                    }
                }
            }
        }

        SectionHeader("Ce casque")
        OutlinedTextField(name, { name = it }, singleLine = true, label = { SonaText("Nom dans Sona Connect", 14.sp, tone = 1) }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(server, { server = it }, singleLine = true, label = { SonaText("Serveur Sona", 14.sp, tone = 1) }, modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Switch(
                checked = keep,
                onCheckedChange = { keep = it; Hub.setKeepOverGames(it) },
                colors = SwitchDefaults.colors(checkedTrackColor = look.accent, checkedThumbColor = look.onAccent),
            )
            Column {
                SonaText("Continuer pendant les jeux VR", 17.sp, FontWeight.SemiBold)
                SonaText("La musique ne s'arrête pas quand un jeu prend le son. Coupe-le si le jeu et Sona se gênent.", 13.sp, tone = 1)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PillButton("Enregistrer", {
                Hub.settings.server = server
                Hub.settings.deviceName = name
                Hub.message.value = "Enregistré."
            })
            PillButton("Se déconnecter", { Hub.logout() }, primary = false)
        }
        Spacer(Modifier.height(24.dp))
    }
}
