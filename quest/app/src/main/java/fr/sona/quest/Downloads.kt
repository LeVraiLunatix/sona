package fr.sona.quest

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

@Serializable
data class Offline(val track: Track, val file: String, val bytes: Long, val quality: String)

/**
 * Téléchargements hors ligne : le fichier vérifié du serveur est gardé dans l'app, et le lecteur
 * le préfère au flux (il joue sans réseau). Un fichier par titre, dans la qualité du compte.
 */
object Downloads {
    val items = MutableStateFlow<List<Offline>>(emptyList())

    /** Titres en cours de téléchargement : clé -> avancement (0 à 1, ou -1 si inconnu). */
    val active = MutableStateFlow<Map<String, Float>>(emptyMap())

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        // Le serveur prépare le fichier vérifié avant de répondre : ça peut être long.
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    private val dir: File get() = File(Hub.app.filesDir, "offline").apply { mkdirs() }
    private val indexFile: File get() = File(dir, "index.json")

    private fun key(t: Track) = "${t.source}:${t.sourceId}"

    fun init() {
        items.value = runCatching {
            SonaJson.decodeFromString<List<Offline>>(indexFile.readText()).filter { File(it.file).isFile }
        }.getOrDefault(emptyList())
    }

    private fun save() {
        runCatching { indexFile.writeText(SonaJson.encodeToString(items.value)) }
    }

    fun isDownloaded(t: Track) = items.value.any { key(it.track) == key(t) }

    /** Adresse du fichier local d'un titre téléchargé, ou null. */
    fun uri(t: Track): String? = items.value.firstOrNull { key(it.track) == key(t) }
        ?.file?.takeIf { File(it).isFile }?.let { File(it).toURI().toString() }

    val totalBytes: Long get() = items.value.sumOf { it.bytes }

    /** Télécharge les titres l'un après l'autre (ceux déjà là sont passés). */
    fun download(tracks: List<Track>) {
        val todo = tracks.filter { !isDownloaded(it) && key(it) !in active.value }
        if (todo.isEmpty()) {
            Hub.message.value = "Déjà téléchargé"
            return
        }
        Hub.message.value = "Téléchargement de ${todo.size} titre${if (todo.size > 1) "s" else ""}…"
        todo.forEach { active.value = active.value + (key(it) to -1f) }
        Hub.scope.launch {
            for (t in todo) {
                try {
                    withContext(Dispatchers.IO) { fetch(t) }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Hub.message.value = "« ${t.title} » : ${e.message ?: "échec du téléchargement"}"
                } finally {
                    active.value = active.value - key(t)
                }
            }
        }
    }

    private fun fetch(t: Track) {
        fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
        val quality = Hub.settings.quality
        // live=false : le fichier vérifié complet, pas le relais direct.
        val url = "${Hub.settings.server}/stream/${enc(t.source)}/${enc(t.sourceId)}?quality=$quality&live=false"
        val request = Request.Builder().url(url).header("Authorization", "Bearer ${Hub.settings.token}").build()
        val target = File(dir, "${enc(t.source)}_${enc(t.sourceId)}.audio".replace("%", "_"))
        val temp = File(dir, target.name + ".part")
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw java.io.IOException("Erreur ${response.code}")
            val body = response.body ?: throw java.io.IOException("Réponse vide")
            val total = body.contentLength()
            temp.outputStream().use { out ->
                body.byteStream().use { input ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        out.write(buffer, 0, n)
                        done += n
                        if (total > 0) active.value = active.value + (key(t) to (done.toFloat() / total).coerceIn(0f, 1f))
                    }
                }
            }
        }
        if (target.exists()) target.delete()
        temp.renameTo(target)
        items.value = items.value.filter { key(it.track) != key(t) } + Offline(t, target.absolutePath, target.length(), quality)
        save()
    }

    fun remove(t: Track) {
        items.value.firstOrNull { key(it.track) == key(t) }?.let { runCatching { File(it.file).delete() } }
        items.value = items.value.filter { key(it.track) != key(t) }
        save()
    }

    fun removeAll() {
        items.value.forEach { runCatching { File(it.file).delete() } }
        items.value = emptyList()
        save()
    }
}
