package fr.sona.quest

import kotlinx.coroutines.flow.MutableStateFlow

/** Écrans de l'app : cinq onglets, et des fiches (album, playlist, artiste, mix) empilées dessus. */
sealed interface Route {
    data object Home : Route
    data object Search : Route
    data object Library : Route
    data object Devices : Route
    data object Settings : Route
    data class AlbumPage(val source: String, val id: String, val title: String, val cover: String?) : Route
    data class PlaylistPage(val id: Int, val title: String) : Route
    data class ArtistPage(val source: String, val id: String, val name: String, val picture: String?) : Route
    data class MixPage(val mix: Mix) : Route
}

object Nav {
    val stack = MutableStateFlow<List<Route>>(listOf(Route.Home))

    /** Le lecteur plein écran passe par-dessus tout. */
    val playerOpen = MutableStateFlow(false)

    /** Changer d'onglet vide la pile : on repart de la racine de l'onglet. */
    fun tab(route: Route) {
        stack.value = listOf(route)
    }

    fun go(route: Route) {
        stack.value = stack.value + route
    }

    /** Retour ; false s'il ne reste que la racine. */
    fun back(): Boolean {
        if (playerOpen.value) {
            playerOpen.value = false
            return true
        }
        val s = stack.value
        if (s.size <= 1) return false
        stack.value = s.dropLast(1)
        return true
    }

    fun openPlayer() {
        playerOpen.value = true
    }
}
