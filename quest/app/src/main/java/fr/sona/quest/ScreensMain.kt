package fr.sona.quest

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.core.tween
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cast
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar

@Composable
fun Root() {
    val loggedIn by Hub.loggedIn.collectAsState()
    LookBackground { if (loggedIn) Shell() else LoginScreen() }
}

private data class NavItem(val label: String, val icon: ImageVector, val route: Route)

private val navItems = listOf(
    NavItem("Accueil", Icons.Filled.Home, Route.Home),
    NavItem("Recherche", Icons.Filled.Search, Route.Search),
    NavItem("Bibliothèque", Icons.Filled.LibraryMusic, Route.Library),
    NavItem("Appareils", Icons.Filled.Devices, Route.Devices),
    NavItem("Réglages", Icons.Filled.Settings, Route.Settings),
)

@Composable
fun Shell() {
    val stack by Nav.stack.collectAsState()
    val playerOpen by Nav.playerOpen.collectAsState()
    val route = stack.last()
    val compact = LocalConfiguration.current.screenWidthDp < 780
    val snackbar = remember { SnackbarHostState() }
    val message by Hub.message.collectAsState()
    LaunchedEffect(message) {
        message?.let {
            snackbar.showSnackbar(it)
            Hub.message.value = null
        }
    }
    BackHandler(enabled = playerOpen || stack.size > 1) { Nav.back() }
    Box(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxSize()) {
            if (!compact) Sidebar(stack.first())
            Column(Modifier.weight(1f).fillMaxHeight()) {
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    AnimatedContent(
                        targetState = route,
                        transitionSpec = { fadeIn(tween(240)) togetherWith fadeOut(tween(120)) },
                        label = "route",
                    ) { r -> RouteContent(r, stack.size > 1) }
                }
                MiniPlayer()
                if (compact) BottomNav(stack.first())
            }
        }
        AnimatedVisibility(
            visible = playerOpen,
            enter = slideInVertically(tween(380)) { it } + fadeIn(tween(380)),
            exit = slideOutVertically(tween(300)) { it } + fadeOut(tween(300)),
        ) { PlayerScreen() }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(bottom = 110.dp))
    }
}

@Composable
private fun RouteContent(route: Route, canGoBack: Boolean) {
    Column(Modifier.fillMaxSize()) {
        if (canGoBack) BackBar()
        Box(Modifier.weight(1f)) {
            when (route) {
                Route.Home -> HomeScreen()
                Route.Search -> SearchScreen()
                Route.Library -> LibraryScreen()
                Route.Devices -> DevicesScreen()
                Route.Settings -> SettingsScreen()
                is Route.AlbumPage -> AlbumPageScreen(route)
                is Route.PlaylistPage -> PlaylistPageScreen(route)
                is Route.ArtistPage -> ArtistPageScreen(route)
                is Route.MixPage -> CollectionPage(route.mix.title, route.mix.subtitle, route.mix.covers.firstOrNull(), route.mix.tracks, "Mix")
            }
        }
    }
}

@Composable
private fun BackBar() {
    Row(
        Modifier.padding(start = 20.dp, top = 14.dp).clip(RoundedCornerShape(50)).pressable { Nav.back() }.padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SonaText("‹  Retour", 16.sp, FontWeight.SemiBold, tone = 3)
    }
}

@Composable
private fun Sidebar(root: Route) {
    val look = LocalLook.current
    val devices by Hub.devices.collectAsState()
    Column(
        Modifier
            .width(250.dp)
            .fillMaxHeight()
            .background(look.surface)
            .padding(horizontal = 16.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        SonaText("Sona", 34.sp, FontWeight.ExtraBold, tone = 0, modifier = Modifier.padding(start = 12.dp, bottom = 22.dp), title = true)
        navItems.forEach { item ->
            val selected = item.route == root
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(look.corner))
                    .background(if (selected) look.surfaceStrong else androidx.compose.ui.graphics.Color.Transparent)
                    .pressable { Nav.tab(item.route) }
                    .padding(horizontal = 12.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Icon(item.icon, null, tint = if (selected) look.accent else look.secondary, modifier = Modifier.size(24.dp))
                SonaText(item.label, 17.sp, if (selected) FontWeight.Bold else FontWeight.Medium, tone = if (selected) 0 else 1)
            }
        }
        Spacer(Modifier.weight(1f))
        Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.size(9.dp).clip(CircleShape).background(if (devices.isNotEmpty()) look.accent else look.tertiary))
            SonaText(if (devices.isNotEmpty()) "Sona Connect · ${devices.size} appareil${if (devices.size > 1) "s" else ""}" else "Hors ligne", 13.sp, tone = 1, maxLines = 1)
        }
    }
}

@Composable
private fun BottomNav(root: Route) {
    val look = LocalLook.current
    Row(Modifier.fillMaxWidth().background(look.surface).padding(vertical = 6.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
        navItems.forEach { item ->
            val selected = item.route == root
            Column(
                Modifier.clip(RoundedCornerShape(look.corner)).pressable { Nav.tab(item.route) }.padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(item.icon, null, tint = if (selected) look.accent else look.secondary, modifier = Modifier.size(24.dp))
                SonaText(item.label, 11.sp, FontWeight.SemiBold, tone = if (selected) 0 else 1, maxLines = 1)
            }
        }
    }
}

// ── Mini-lecteur ─────────────────────────────────────────────────────────────────────────

@Composable
fun MiniPlayer() {
    val look = LocalLook.current
    val queue by Hub.queue.collectAsState()
    val index by Hub.index.collectAsState()
    val position by Hub.positionMs.collectAsState()
    val duration by Hub.durationMs.collectAsState()
    val track = queue.getOrNull(index) ?: return
    Column(
        Modifier
            .padding(horizontal = 14.dp, vertical = 10.dp)
            .fillMaxWidth()
            .glass(corner = look.corner + 6.dp, strong = true)
            .pressable { Nav.openPlayer() },
    ) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Cover(track.coverUrl, Modifier.size(54.dp))
            Column(Modifier.weight(1f)) {
                SonaText(track.title, 16.sp, FontWeight.SemiBold, maxLines = 1)
                SonaText(track.artist, 14.sp, tone = 1, maxLines = 1)
            }
            TransportControls(compact = true)
        }
        val frac = if (duration > 0) (position.toFloat() / duration).coerceIn(0f, 1f) else 0f
        Box(Modifier.fillMaxWidth().height(3.dp).background(look.separator)) {
            Box(Modifier.fillMaxWidth(frac).fillMaxHeight().background(look.accent))
        }
    }
}

// ── Accueil ──────────────────────────────────────────────────────────────────────────────

private fun greeting(): String {
    val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    return if (h in 5..17) "Bonjour" else "Bonsoir"
}

@Composable
fun HomeScreen() {
    val daily by load("daily") { Hub.api.daily() }
    val mixes by load("mixes") { Hub.api.mixes() }
    val radios by load("radios") { Hub.api.radios() }
    val session by Hub.session.collectAsState()
    val me = Hub.settings.deviceId
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 30.dp, vertical = 26.dp)) {
        item { PageTitle(greeting(), "Ta musique, en clair.", Modifier.reveal(0)) }

        val s = session
        if (s != null && s.deviceId != me && s.track != null) {
            item {
                Row(
                    Modifier.padding(top = 14.dp).fillMaxWidth().glass().reveal(1).padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(18.dp),
                ) {
                    Cover(s.track.coverUrl, Modifier.size(84.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        SonaText("Reprendre sur ce casque", 13.sp, FontWeight.Bold, tone = 3)
                        SonaText(s.track.title, 20.sp, FontWeight.Bold, maxLines = 1)
                        SonaText("${s.track.artist} · sur ${s.deviceName}", 14.sp, tone = 1, maxLines = 1)
                    }
                    PillButton("Écouter ici", { Hub.remote(me, "transfer") }, icon = Icons.Filled.Cast)
                }
            }
        }

        item {
            Loaded(daily) { d ->
                val t = d.track
                if (t != null) {
                    Row(
                        Modifier.padding(top = 14.dp).fillMaxWidth().glass().reveal(2).padding(18.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(20.dp),
                    ) {
                        Cover(t.coverUrl, Modifier.size(130.dp))
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            SonaText("Titre du jour", 13.sp, FontWeight.Bold, tone = 3)
                            SonaText(t.title, 26.sp, FontWeight.Bold, maxLines = 2, title = true)
                            SonaText(t.artist, 16.sp, tone = 1, maxLines = 1)
                            if (d.reason.isNotBlank()) SonaText(d.reason, 13.sp, tone = 2, maxLines = 2)
                            Spacer(Modifier.height(8.dp))
                            PillButton("Lecture", { Hub.playQueue(listOf(t), 0, "Titre du jour") }, icon = Icons.Filled.PlayArrow)
                        }
                    }
                }
            }
        }

        item { SectionHeader("Tes mix") }
        item {
            Loaded(mixes) { list ->
                HorizontalShelf(list, Modifier.reveal(3)) { _, mix ->
                    CoverCard(mix.covers.firstOrNull(), mix.title, mix.subtitle, { Nav.go(Route.MixPage(mix)) })
                }
            }
        }

        item { SectionHeader("Radios") }
        item {
            Loaded(radios) { groups ->
                val all = groups.flatMap { it.radios }.take(24)
                HorizontalShelf(all, Modifier.reveal(4)) { _, radio ->
                    val scope = rememberCoroutineScope()
                    CoverCard(radio.pictureUrl, radio.title, "Radio", {
                        scope.launch {
                            runCatching { withContext(Dispatchers.IO) { Hub.api.radioTracks(radio.id) } }
                                .onSuccess { Hub.playQueue(it, 0, "Radio ${radio.title}") }
                                .onFailure { Hub.message.value = it.message ?: "Radio indisponible" }
                        }
                    }, size = 160.dp, round = true)
                }
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

// ── Recherche ────────────────────────────────────────────────────────────────────────────

private data class SearchResults(val tracks: List<Track>, val artists: List<Artist>, val albums: List<Album>)

@Composable
fun SearchScreen() {
    val look = LocalLook.current
    var q by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<SearchResults?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun run() {
        val text = q.trim()
        if (text.isEmpty() || loading) return
        loading = true
        scope.launch {
            results = withContext(Dispatchers.IO) {
                coroutineScope {
                    val tracks = async { runCatching { Hub.api.search(text) }.getOrElse { Hub.message.value = it.message; emptyList() } }
                    val artists = async { runCatching { Hub.api.searchArtists(text) }.getOrDefault(emptyList()) }
                    val albums = async { runCatching { Hub.api.searchAlbums(text) }.getOrDefault(emptyList()) }
                    SearchResults(tracks.await(), artists.await(), albums.await())
                }
            }
            loading = false
        }
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 30.dp, vertical = 26.dp)) {
        item { PageTitle("Recherche", "Un titre, un artiste, un album — ou colle un lien.", Modifier.reveal(0)) }
        item {
            Row(
                Modifier.padding(vertical = 14.dp).fillMaxWidth().glass().padding(horizontal = 18.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Icon(Icons.Filled.Search, null, tint = look.secondary)
                Box(Modifier.weight(1f)) {
                    if (q.isEmpty()) SonaText("Rechercher dans Sona", 18.sp, tone = 2)
                    BasicTextField(
                        value = q, onValueChange = { q = it }, singleLine = true,
                        textStyle = TextStyle(color = look.primary, fontSize = 18.sp, fontFamily = look.font),
                        cursorBrush = SolidColor(look.accent),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { run() }),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                PillButton("Chercher", { run() }, Modifier.height(42.dp))
            }
        }
        if (loading) item { Loaded<Unit>(Load.Loading) { } }
        val r = results
        if (r != null && !loading) {
            if (r.tracks.isEmpty() && r.artists.isEmpty() && r.albums.isEmpty()) {
                item { SonaText("Rien trouvé pour « ${q.trim()} ».", 16.sp, tone = 1, modifier = Modifier.padding(top = 20.dp)) }
            }
            if (r.artists.isNotEmpty()) {
                item { SectionHeader("Artistes") }
                item {
                    HorizontalShelf(r.artists) { _, a ->
                        CoverCard(a.pictureUrl, a.name, "Artiste", { Nav.go(Route.ArtistPage(a.source, a.sourceId, a.name, a.pictureUrl)) }, size = 150.dp, round = true)
                    }
                }
            }
            if (r.albums.isNotEmpty()) {
                item { SectionHeader("Albums") }
                item {
                    HorizontalShelf(r.albums) { _, a ->
                        CoverCard(a.coverUrl, a.title, a.artist, { Nav.go(Route.AlbumPage(a.source, a.sourceId, a.title, a.coverUrl)) }, size = 170.dp)
                    }
                }
            }
            if (r.tracks.isNotEmpty()) {
                item { SectionHeader("Titres") }
                itemsIndexed(r.tracks) { i, t ->
                    TrackItem(t, { Hub.playQueue(r.tracks, i, "Recherche : ${q.trim()}") }, current = isCurrent(t))
                }
            }
        }
    }
}

fun isCurrent(t: Track): Boolean {
    val c = Hub.current ?: return false
    return c.source == t.source && c.sourceId == t.sourceId
}

// ── Bibliothèque ─────────────────────────────────────────────────────────────────────────

private enum class LibTab(val label: String) { Titres("Titres"), Albums("Albums"), Artistes("Artistes"), Playlists("Playlists") }

private fun LibraryItem.asTrack() = track ?: Track(
    source = source, sourceId = sourceId, title = title, artist = subtitle.orEmpty(), coverUrl = coverUrl,
)

@Composable
fun LibraryScreen() {
    val look = LocalLook.current
    var tab by remember { mutableStateOf(LibTab.Titres) }
    Column(Modifier.fillMaxSize().padding(horizontal = 30.dp, vertical = 26.dp)) {
        PageTitle("Bibliothèque", modifier = Modifier.reveal(0))
        Row(Modifier.padding(vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LibTab.entries.forEach { t ->
                val on = t == tab
                Box(
                    Modifier
                        .clip(RoundedCornerShape(50))
                        .background(if (on) look.buttonFill else look.surfaceStrong)
                        .pressable { tab = t }
                        .padding(horizontal = 20.dp, vertical = 10.dp),
                ) { SonaText(t.label, 15.sp, FontWeight.SemiBold, color = if (on) look.buttonText else look.primary) }
            }
        }
        Box(Modifier.weight(1f)) {
            when (tab) {
                LibTab.Titres -> {
                    val s by load("lib-track") { Hub.api.library("track") }
                    Loaded(s) { r ->
                        if (r.items.isEmpty()) EmptyState("Aucun titre aimé", "Ajoute des titres à ta bibliothèque depuis l'iPhone ou le site.")
                        else {
                            val tracks = r.items.map { it.asTrack() }
                            LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
                                itemsIndexed(tracks) { i, t -> TrackItem(t, { Hub.playQueue(tracks, i, "Bibliothèque") }, current = isCurrent(t)) }
                            }
                        }
                    }
                }
                LibTab.Albums -> {
                    val s by load("lib-album") { Hub.api.library("album") }
                    Loaded(s) { r ->
                        if (r.items.isEmpty()) EmptyState("Aucun album")
                        else LazyVerticalGrid(GridCells.Adaptive(190.dp), verticalArrangement = Arrangement.spacedBy(20.dp), horizontalArrangement = Arrangement.spacedBy(18.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
                            items(r.items) { a -> CoverCard(a.coverUrl, a.title, a.subtitle, { Nav.go(Route.AlbumPage(a.source, a.sourceId, a.title, a.coverUrl)) }) }
                        }
                    }
                }
                LibTab.Artistes -> {
                    val s by load("lib-artist") { Hub.api.library("artist") }
                    Loaded(s) { r ->
                        if (r.items.isEmpty()) EmptyState("Aucun artiste")
                        else LazyVerticalGrid(GridCells.Adaptive(160.dp), verticalArrangement = Arrangement.spacedBy(20.dp), horizontalArrangement = Arrangement.spacedBy(18.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
                            items(r.items) { a -> CoverCard(a.coverUrl, a.title, null, { Nav.go(Route.ArtistPage(a.source, a.sourceId, a.title, a.coverUrl)) }, size = 150.dp, round = true) }
                        }
                    }
                }
                LibTab.Playlists -> {
                    val s by load("lib-playlists") { Hub.api.playlists() }
                    Loaded(s) { list ->
                        if (list.isEmpty()) EmptyState("Aucune playlist")
                        else LazyVerticalGrid(GridCells.Adaptive(190.dp), verticalArrangement = Arrangement.spacedBy(20.dp), horizontalArrangement = Arrangement.spacedBy(18.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
                            items(list) { p -> CoverCard(p.coverUrl ?: p.covers.firstOrNull(), p.name, "${p.trackCount} titres", { Nav.go(Route.PlaylistPage(p.id, p.name)) }) }
                        }
                    }
                }
            }
        }
    }
}

// ── Fiches : album, playlist, artiste, mix ───────────────────────────────────────────────

@Composable
fun CollectionPage(title: String, sub: String?, cover: String?, tracks: List<Track>, kind: String, round: Boolean = false) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 30.dp, vertical = 20.dp)) {
        item {
            Row(Modifier.fillMaxWidth().reveal(0), horizontalArrangement = Arrangement.spacedBy(28.dp), verticalAlignment = Alignment.Bottom) {
                Cover(cover, Modifier.size(230.dp), round)
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    SonaText(kind, 13.sp, FontWeight.Bold, tone = 3, title = true)
                    SonaText(title, 40.sp, FontWeight.ExtraBold, maxLines = 3, title = true)
                    if (!sub.isNullOrBlank()) SonaText(sub, 16.sp, tone = 1, maxLines = 2)
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        PillButton("Lecture", { Hub.playQueue(tracks, 0, title) }, Modifier.width(180.dp), icon = Icons.Filled.PlayArrow)
                        PillButton("Aléatoire", { Hub.playQueue(tracks.shuffled(), 0, title) }, Modifier.width(180.dp), primary = false, icon = Icons.Filled.Shuffle)
                    }
                }
            }
            Spacer(Modifier.height(18.dp))
        }
        itemsIndexed(tracks) { i, t ->
            TrackItem(t, { Hub.playQueue(tracks, i, title) }, number = i + 1, current = isCurrent(t), showCover = false)
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
fun AlbumPageScreen(route: Route.AlbumPage) {
    val s by load(route) { Hub.api.album(route.source, route.id) }
    Loaded(s) { a ->
        CollectionPage(a.title, listOfNotNull(a.artist, a.year).joinToString(" · "), a.coverUrl ?: route.cover, a.tracks, "Album")
    }
}

@Composable
fun PlaylistPageScreen(route: Route.PlaylistPage) {
    val s by load(route) { Hub.api.playlist(route.id) }
    Loaded(s) { p ->
        CollectionPage(p.name, p.description ?: "${p.trackCount} titres", p.coverUrl ?: p.covers.firstOrNull(), p.entries.map { it.track }, "Playlist")
    }
}

@Composable
fun ArtistPageScreen(route: Route.ArtistPage) {
    val s by load(route) { Hub.api.artistTopTracks(route.source, route.id) }
    Loaded(s) { tracks ->
        CollectionPage(route.name, "Titres populaires", route.picture, tracks, "Artiste", round = true)
    }
}
