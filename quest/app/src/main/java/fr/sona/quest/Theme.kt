package fr.sona.quest

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Les trois thèmes de Sona : le noir de base, Archive (mono, doré) et GTA VI (néons Vice City). */
enum class ThemeId(val key: String, val label: String, val hint: String) {
    Sona("sona", "Sona", "Noir profond, verre fumé, la couleur vient des pochettes"),
    Archive("archive", "Archive", "Monospace, noir et doré"),
    Gta("gta", "GTA VI", "Coucher de soleil de Vice City, rose et cyan néon");

    companion object {
        fun fromKey(key: String) = entries.firstOrNull { it.key == key } ?: Sona
    }
}

/** Direction artistique de Sona : noir, blanc, gris par transparence — et l'accent rose du site. */
@Immutable
class Look(
    val id: ThemeId,
    val background: Color,
    /** Fond dégradé (GTA VI) ; sinon le fond uni. */
    val backgroundBrush: Brush? = null,
    val surface: Color,
    val surfaceStrong: Color,
    val separator: Color,
    val primary: Color,
    val secondary: Color,
    val tertiary: Color,
    val accent: Color,
    val onAccent: Color,
    val corner: Dp,
    val font: FontFamily,
    val uppercaseTitles: Boolean,
    /** Boutons principaux : blanc plein sur noir (Sona), accent (Archive, GTA VI). */
    val buttonFill: Color,
    val buttonText: Color,
    val neon: Color? = null,
)

val SonaLook = Look(
    id = ThemeId.Sona,
    background = Color.Black,
    surface = Color.White.copy(alpha = 0.07f),
    surfaceStrong = Color.White.copy(alpha = 0.12f),
    separator = Color.White.copy(alpha = 0.08f),
    primary = Color.White,
    secondary = Color.White.copy(alpha = 0.60f),
    tertiary = Color.White.copy(alpha = 0.35f),
    accent = Color(0xFFFA2D6C),
    onAccent = Color.White,
    corner = 14.dp,
    font = FontFamily.Default,
    uppercaseTitles = false,
    buttonFill = Color.White,
    buttonText = Color.Black,
)

val ArchiveLook = Look(
    id = ThemeId.Archive,
    background = Color(0xFF0B0B0E),
    surface = Color(0xFF14141A),
    surfaceStrong = Color(0xFF1F1F27),
    separator = Color(0xFFC8B890).copy(alpha = 0.22f),
    primary = Color(0xFFE8E2D0),
    secondary = Color(0xFF9A9684),
    tertiary = Color(0xFF6A6858),
    accent = Color(0xFFC8B890),
    onAccent = Color(0xFF0B0B0E),
    corner = 2.dp,
    font = FontFamily.Monospace,
    uppercaseTitles = true,
    buttonFill = Color(0xFFC8B890),
    buttonText = Color(0xFF0B0B0E),
)

val GtaLook = Look(
    id = ThemeId.Gta,
    background = Color(0xFF0D0220),
    backgroundBrush = Brush.verticalGradient(
        0.00f to Color(0xFF080224),
        0.35f to Color(0xFF2A1070),
        0.62f to Color(0xFF7A24B8),
        0.82f to Color(0xFFC52FB0),
        1.00f to Color(0xFFFF5FA8),
    ),
    surface = Color(0xFF1E0736).copy(alpha = 0.62f),
    surfaceStrong = Color(0xFF50167F).copy(alpha = 0.72f),
    separator = Color(0xFFFF82D7).copy(alpha = 0.28f),
    primary = Color(0xFFFFF4FB),
    secondary = Color(0xFFFFE2F4).copy(alpha = 0.74f),
    tertiary = Color(0xFFFFCDEC).copy(alpha = 0.48f),
    accent = Color(0xFFFF4FA3),
    onAccent = Color(0xFF1A0230),
    corner = 18.dp,
    font = FontFamily.Default,
    uppercaseTitles = true,
    buttonFill = Color(0xFFFF4FA3),
    buttonText = Color(0xFF1A0230),
    neon = Color(0xFF25E8FF),
)

fun lookFor(id: ThemeId): Look = when (id) {
    ThemeId.Sona -> SonaLook
    ThemeId.Archive -> ArchiveLook
    ThemeId.Gta -> GtaLook
}

val LocalLook = compositionLocalOf { SonaLook }

@Composable
fun SonaTheme(content: @Composable () -> Unit) {
    val id by Hub.theme.collectAsState()
    val look = lookFor(id)
    androidx.compose.runtime.CompositionLocalProvider(LocalLook provides look) {
        MaterialTheme(
            colorScheme = darkColorScheme(
                primary = look.accent,
                onPrimary = look.onAccent,
                background = look.background,
                onBackground = look.primary,
                surface = look.background,
                onSurface = look.primary,
                surfaceVariant = look.surfaceStrong,
                onSurfaceVariant = look.secondary,
                outline = look.separator,
                secondary = look.accent,
            ),
            content = content,
        )
    }
}
