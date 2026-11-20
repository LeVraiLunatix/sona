package fr.sona.quest

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderColors
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import kotlin.math.roundToInt

/** Une pastille de choix : pleine quand elle est active (comme les onglets du site). */
@Composable
fun Chip(text: String, on: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val look = LocalLook.current
    Box(
        modifier
            .clip(RoundedCornerShape(50))
            .background(if (on) look.buttonFill else look.surfaceStrong)
            .pressable(onClick)
            .padding(horizontal = 18.dp, vertical = 9.dp),
    ) { SonaText(text, 14.sp, FontWeight.SemiBold, color = if (on) look.buttonText else look.primary) }
}

@Composable
fun lookSliderColors(): SliderColors {
    val look = LocalLook.current
    return SliderDefaults.colors(
        thumbColor = look.primary,
        activeTrackColor = look.accent,
        inactiveTrackColor = look.primary.copy(alpha = 0.22f),
    )
}


/** Égaliseur 5 bandes, volume égalisé et fondu entre les titres. */
@Composable
fun SoundDialog(onDismiss: () -> Unit) {
    val look = LocalLook.current
    val eq by Sound.eq.collectAsState()
    val normalize by Sound.normalize.collectAsState()
    val fade by Sound.fadeSeconds.collectAsState()
    val available by Sound.eqAvailable.collectAsState()
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .fillMaxWidth()
                .heightIn(max = 680.dp)
                .background(look.background, RoundedCornerShape(26.dp))
                .glass(26.dp, strong = true)
                .verticalScroll(rememberScrollState())
                .padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            SonaText("Son", 26.sp, FontWeight.Bold, title = true)
            if (!available) {
                SonaText("Cet appareil ne propose pas d'égaliseur : les réglages sont gardés mais ne s'entendent pas.", 13.sp, tone = 2)
            }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Sound.PRESETS.forEach { (name, gains) -> Chip(name, eq == gains, { Sound.setEq(gains) }) }
            }
            Spacer(Modifier.height(4.dp))
            Sound.LABELS.forEachIndexed { i, label ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SonaText("$label Hz", 14.sp, FontWeight.SemiBold, tone = 1, modifier = Modifier.width(78.dp))
                    Slider(
                        value = eq[i].toFloat(),
                        onValueChange = { Sound.setBand(i, it.roundToInt()) },
                        valueRange = -12f..12f,
                        steps = 23,
                        colors = lookSliderColors(),
                        modifier = Modifier.weight(1f),
                    )
                    SonaText("${if (eq[i] > 0) "+" else ""}${eq[i]} dB", 14.sp, tone = 1, modifier = Modifier.width(62.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Switch(
                    checked = normalize,
                    onCheckedChange = { Sound.setNormalize(it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = look.accent, checkedThumbColor = look.onAccent),
                )
                Column {
                    SonaText("Volume égalisé", 17.sp, FontWeight.SemiBold)
                    SonaText("Tous les titres au même niveau sonore.", 13.sp, tone = 1)
                }
            }
            SonaText("Fondu entre les titres", 17.sp, FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(0, 3, 6, 9, 12).forEach { s -> Chip(if (s == 0) "Aucun" else "$s s", fade == s, { Sound.setFade(s) }) }
            }
            Spacer(Modifier.height(6.dp))
            PillButton("Fermer", onDismiss, Modifier.fillMaxWidth(), primary = false)
        }
    }
}

/** Mode chant : bouton, avancement de la préparation, et réglage de la voix guide. */
@Composable
fun KaraokeBar(modifier: Modifier = Modifier) {
    val look = LocalLook.current
    val on by Karaoke.on.collectAsState()
    val ui by Karaoke.ui.collectAsState()
    val guide by Karaoke.guide.collectAsState()
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Chip("Karaoké", on, { Karaoke.setOn(!on) })
            when (val state = ui) {
                is KaraokeUi.Preparing -> Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    SonaText(
                        "Préparation du karaoké… ${(state.progress * 100).roundToInt()} %  (le titre continue en attendant)",
                        13.sp, tone = 1, maxLines = 1,
                    )
                    LinearProgressIndicator(
                        progress = { state.progress },
                        modifier = Modifier.fillMaxWidth(),
                        color = look.accent,
                        trackColor = look.separator,
                    )
                }
                KaraokeUi.Ready -> Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    SonaText("Voix guide", 13.sp, tone = 1, modifier = Modifier.width(86.dp))
                    Slider(value = guide, onValueChange = { Karaoke.setGuide(it) }, colors = lookSliderColors(), modifier = Modifier.weight(1f))
                }
                is KaraokeUi.Failed -> SonaText(state.message, 13.sp, tone = 2, maxLines = 2, modifier = Modifier.weight(1f))
                KaraokeUi.Off -> Unit
            }
        }
    }
}

/** Qualité du son du compte : la même sur tous les appareils. */
@Composable
fun QualityChips() {
    val account by Hub.account.collectAsState()
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("lossless" to "Lossless", "best" to "Meilleure", "standard" to "Standard").forEach { (key, label) ->
            Chip(label, account.quality == key, { Hub.setQuality(key) })
        }
    }
}
