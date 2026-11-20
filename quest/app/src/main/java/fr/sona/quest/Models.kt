package fr.sona.quest

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

val SonaJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
}

@Serializable
data class Track(
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val title: String,
    val artist: String,
    val album: String? = null,
    val year: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    @SerialName("artist_source_id") val artistSourceId: String? = null,
    @SerialName("album_source_id") val albumSourceId: String? = null,
    val bpm: Double? = null,
    @SerialName("disc_number") val discNumber: Int? = null,
    @SerialName("track_number") val trackNumber: Int? = null,
    val artists: List<JsonObject> = emptyList(),
    val released: Boolean = true,
    @SerialName("release_date") val releaseDate: String? = null,
)

@Serializable
data class SearchResponse(val tracks: List<Track> = emptyList())

@Serializable
data class LyricsLine(val time: Double? = null, val text: String)

@Serializable
data class LyricsOut(
    val synced: Boolean = false,
    val instrumental: Boolean = false,
    val lines: List<LyricsLine> = emptyList(),
)

// ── Connexion par QR code ────────────────────────────────────────────────────

@Serializable
data class DeviceStartIn(val name: String)

@Serializable
data class DeviceStartOut(
    @SerialName("device_code") val deviceCode: String,
    @SerialName("user_code") val userCode: String,
    @SerialName("verify_url") val verifyUrl: String,
    @SerialName("expires_in") val expiresIn: Int,
    val interval: Int,
)

@Serializable
data class DevicePollIn(@SerialName("device_code") val deviceCode: String)

@Serializable
data class PollOut(
    val status: String,
    @SerialName("session_token") val sessionToken: String? = null,
)

// ── Sona Connect ─────────────────────────────────────────────────────────────

@Serializable
data class ConnectDevice(
    val id: String,
    val name: String,
    val kind: String = "web",
    @SerialName("is_me") val isMe: Boolean = false,
    val playing: Boolean = false,
    val track: Track? = null,
    val volume: Double? = null,
    val position: Double = 0.0,
    val online: Boolean = true,
)

@Serializable
data class SessionOut(
    @SerialName("device_id") val deviceId: String,
    @SerialName("device_name") val deviceName: String,
    val queue: List<Track> = emptyList(),
    val index: Int = 0,
    val name: String = "",
    val track: Track? = null,
    val position: Double = 0.0,
    val paused: Boolean = true,
)

@Serializable
data class RemoteCommand(
    val action: String,
    val from: String = "",
    val position: Double? = null,
    val volume: Double? = null,
    val index: Int? = null,
    val queue: List<Track>? = null,
    val name: String? = null,
)

@Serializable
data class SyncOut(
    val devices: List<ConnectDevice> = emptyList(),
    @SerialName("active_device_id") val activeDeviceId: String? = null,
    val session: SessionOut? = null,
    val commands: List<RemoteCommand> = emptyList(),
)

@Serializable
data class PlaybackState(
    val queue: List<Track>,
    val index: Int,
    val position: Double,
    val paused: Boolean,
    val volume: Double? = null,
    val name: String? = null,
    val shuffle: Boolean? = null,
    val repeat: String? = null,
)

@Serializable
data class SyncIn(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val kind: String = "quest",
    val state: PlaybackState? = null,
    val claim: Boolean = false,
    val wait: Double = 0.0,
)

@Serializable
data class CommandIn(
    @SerialName("device_id") val deviceId: String,
    val target: String,
    val action: String,
    val position: Double? = null,
    val volume: Double? = null,
    val index: Int? = null,
    val queue: List<Track>? = null,
    val name: String? = null,
)

// ── Accueil, bibliothèque, fiches ────────────────────────────────────────────

@Serializable
data class Mix(
    val id: String,
    val title: String,
    val subtitle: String = "",
    val covers: List<String> = emptyList(),
    val tracks: List<Track> = emptyList(),
)

@Serializable
data class DailyOut(val track: Track? = null, val reason: String = "")

@Serializable
data class LibraryItem(
    val kind: String = "",
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val title: String,
    val subtitle: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    val track: Track? = null,
)

@Serializable
data class LibraryResponse(val total: Int = 0, val items: List<LibraryItem> = emptyList())

@Serializable
data class HistoryItem(
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val title: String,
    val subtitle: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
)

@Serializable
data class HistoryResponse(val total: Int = 0, val items: List<HistoryItem> = emptyList())

@Serializable
data class Playlist(
    val id: Int,
    val name: String,
    val description: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    val covers: List<String> = emptyList(),
    @SerialName("track_count") val trackCount: Int = 0,
    @SerialName("duration_seconds") val durationSeconds: Int = 0,
)

@Serializable
data class PlaylistEntry(val track: Track)

@Serializable
data class PlaylistDetail(
    val id: Int,
    val name: String,
    val description: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    val covers: List<String> = emptyList(),
    @SerialName("track_count") val trackCount: Int = 0,
    val entries: List<PlaylistEntry> = emptyList(),
)

@Serializable
data class Album(
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val title: String,
    val artist: String,
    @SerialName("artist_source_id") val artistSourceId: String? = null,
    val year: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    @SerialName("track_count") val trackCount: Int? = null,
    val tracks: List<Track> = emptyList(),
)

@Serializable
data class Artist(
    val source: String,
    @SerialName("source_id") val sourceId: String,
    val name: String,
    @SerialName("picture_url") val pictureUrl: String? = null,
    val fans: Int? = null,
)

@Serializable
data class RadioStation(
    val id: String,
    val title: String,
    @SerialName("picture_url") val pictureUrl: String? = null,
)

@Serializable
data class RadioGroup(val title: String, val radios: List<RadioStation> = emptyList())
