package fr.sona.quest

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.encodeToString
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiError(val code: Int, message: String) : IOException(message)

/** Client de l'API Sona. Toutes les routes sont des suspend : annulables (long polling). */
class Api(private val settings: Settings) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private fun request(path: String, query: Map<String, String> = emptyMap()): Request.Builder {
        val url = (settings.server + path).toHttpUrl().newBuilder().apply {
            query.forEach { (k, v) -> addQueryParameter(k, v) }
        }.build()
        return Request.Builder().url(url).apply {
            val token = settings.token
            if (token.isNotBlank()) header("Authorization", "Bearer $token")
        }
    }

    private suspend fun call(request: Request): String = suspendCancellableCoroutine { cont ->
        val call: Call = client.newCall(request)
        cont.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (cont.isActive) cont.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    val body = it.body?.string().orEmpty()
                    if (!cont.isActive) return
                    if (it.isSuccessful) cont.resume(body)
                    else cont.resumeWithException(ApiError(it.code, errorText(it.code, body)))
                }
            }
        })
    }

    private fun errorText(code: Int, body: String): String {
        // « detail » est une phrase, ou (erreur de validation 422) une liste d'objets avec « msg ».
        val detail = Regex("\"detail\"\\s*:\\s*\"([^\"]*)\"").find(body)?.groupValues?.get(1)
            ?: Regex("\"msg\"\\s*:\\s*\"([^\"]*)\"").find(body)?.groupValues?.get(1)
        return if (detail != null) "$detail ($code)" else "Erreur $code"
    }

    private inline fun <reified T> body(value: T) =
        SonaJson.encodeToString(value).toRequestBody("application/json".toMediaType())

    // ── Connexion par QR code ────────────────────────────────────────────────

    suspend fun deviceStart(name: String): DeviceStartOut = SonaJson.decodeFromString(
        call(request("/auth/device/start").post(body(DeviceStartIn(name))).build()),
    )

    suspend fun devicePoll(deviceCode: String): PollOut = SonaJson.decodeFromString(
        call(request("/auth/device/poll").post(body(DevicePollIn(deviceCode))).build()),
    )

    // ── Catalogue ────────────────────────────────────────────────────────────

    suspend fun search(q: String): List<Track> = SonaJson.decodeFromString<SearchResponse>(
        call(request("/search", mapOf("q" to q, "limit" to "30")).build()),
    ).tracks

    suspend fun lyrics(track: Track): LyricsOut {
        val query = buildMap {
            put("title", track.title)
            put("artist", track.artist)
            track.album?.let { put("album", it) }
            track.durationSeconds?.let { put("duration", it.toString()) }
        }
        return SonaJson.decodeFromString(call(request("/lyrics", query).build()))
    }

    // ── Sona Connect ─────────────────────────────────────────────────────────

    suspend fun sync(input: SyncIn): SyncOut = SonaJson.decodeFromString(
        call(request("/connect/sync").post(body(input)).build()),
    )

    suspend fun command(input: CommandIn) {
        call(request("/connect/command").post(body(input)).build())
    }
}
