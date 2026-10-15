from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache

import yt_dlp
from ytmusicapi import YTMusic

from app.logging_config import ytdlp_logger
from app.providers.base import AlbumInfo, ExternalPlaylist, TrackInfo
from app.services.ytdlp_runtime import with_js_runtimes

logger = logging.getLogger(__name__)


class YoutubeError(Exception):
    pass


def _base_opts() -> dict:
    return {
        "quiet": True,
        # Plutôt que `no_warnings` : les avertissements utiles remontent.
        "logger": ytdlp_logger,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 15,
    }


def _track_from_entry(entry: dict) -> TrackInfo:
    thumbnails = entry.get("thumbnails") or []
    cover = thumbnails[-1]["url"] if thumbnails else entry.get("thumbnail")
    return TrackInfo(
        source="youtube",
        source_id=entry.get("id") or "",
        title=entry.get("track") or entry.get("title") or "Titre inconnu",
        artist=entry.get("artist") or entry.get("channel") or entry.get("uploader") or "Chaîne inconnue",
        album=entry.get("album"),
        year=str(entry.get("release_year")) if entry.get("release_year") else None,
        duration_seconds=int(entry["duration"]) if entry.get("duration") else None,
        cover_url=cover,
    )


def _extract_sync(url: str, opts: dict) -> dict:
    with yt_dlp.YoutubeDL(with_js_runtimes(opts)) as ydl:
        return ydl.extract_info(url, download=False)


async def get_video_info(video_id: str) -> TrackInfo:
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        entry = await asyncio.to_thread(_extract_sync, url, _base_opts())
    except yt_dlp.utils.DownloadError as exc:
        raise YoutubeError("Vidéo YouTube indisponible.") from exc
    return _track_from_entry(entry)


async def get_playlist_info(playlist_id: str) -> AlbumInfo:
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    opts = _base_opts()
    opts["noplaylist"] = False
    opts["extract_flat"] = True
    try:
        entry = await asyncio.to_thread(_extract_sync, url, opts)
    except yt_dlp.utils.DownloadError as exc:
        raise YoutubeError("Playlist YouTube indisponible.") from exc

    tracks: list[TrackInfo] = []
    for item in entry.get("entries") or []:
        if not item:
            continue
        tracks.append(
            TrackInfo(
                source="youtube",
                source_id=item.get("id") or "",
                title=item.get("title") or "Titre inconnu",
                artist=item.get("uploader") or item.get("channel") or "Chaîne inconnue",
                album=None,
                year=None,
                duration_seconds=int(item["duration"]) if item.get("duration") else None,
                cover_url=item.get("thumbnails", [{}])[-1].get("url") if item.get("thumbnails") else None,
            )
        )
    return AlbumInfo(
        source="youtube",
        source_id=playlist_id,
        title=entry.get("title") or "Playlist YouTube",
        artist=entry.get("uploader") or entry.get("channel") or "YouTube",
        artist_source_id=None,
        year=None,
        cover_url=tracks[0].cover_url if tracks else None,
        track_count=len(tracks),
        duration_seconds=sum((t.duration_seconds or 0) for t in tracks) or None,
        tracks=tracks,
    )


# -- Import d'une playlist YouTube / YouTube Music ---------------------------

# Mentions de clip qui ne font pas partie du titre du morceau.
_VIDEO_NOISE_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(?:official|officiel(?:le)?|clip|video|vidéo|lyrics?|paroles|audio|visuali[sz]er|hd|4k|mv)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def split_video_title(title: str, channel: str | None) -> tuple[str, str]:
    """« Artiste - Titre (Clip officiel) » publié par « ArtisteVEVO » →
    (« Titre », « Artiste ») : ce qu'il faut pour retrouver le morceau au
    catalogue."""
    title = _VIDEO_NOISE_RE.sub("", title or "").strip() or (title or "Titre inconnu")
    channel = (channel or "").strip()
    artist = re.sub(r"\s*-\s*Topic$", "", channel)
    artist = re.sub(r"VEVO$", "", artist).strip()
    if " - " in title:
        left, right = (part.strip() for part in title.split(" - ", 1))
        if left and right:
            return right, left
    return title, artist or "Artiste inconnu"


@lru_cache(maxsize=1)
def _ytmusic() -> YTMusic:
    return YTMusic()


def _ytmusic_playlist_sync(playlist_id: str, limit: int) -> dict:
    return _ytmusic().get_playlist(playlist_id, limit=limit)


def _track_from_ytmusic(item: dict) -> TrackInfo | None:
    video_id = item.get("videoId")
    if not video_id or item.get("isAvailable") is False:
        return None
    artists = [a.get("name") for a in item.get("artists") or [] if a.get("name")]
    title = item.get("title") or "Titre inconnu"
    # Vidéo d'un particulier (pas un titre du catalogue YouTube Music) : le
    # titre contient souvent « Artiste - Titre ».
    if item.get("videoType") == "MUSIC_VIDEO_TYPE_UGC" or not artists:
        title, artist = split_video_title(title, artists[0] if artists else None)
    else:
        artist = ", ".join(artists)
    thumbnails = item.get("thumbnails") or []
    return TrackInfo(
        source="youtube",
        source_id=video_id,
        title=title,
        artist=artist,
        album=(item.get("album") or {}).get("name"),
        year=None,
        duration_seconds=item.get("duration_seconds"),
        cover_url=thumbnails[-1].get("url") if thumbnails else None,
    )


async def get_playlist_for_import(playlist_id: str, max_tracks: int = 1000) -> ExternalPlaylist:
    """Playlist YouTube ou YouTube Music publique, titres nettoyés : YouTube
    Music d'abord (titre, artistes et album propres), sinon yt-dlp."""
    try:
        data = await asyncio.to_thread(_ytmusic_playlist_sync, playlist_id, max_tracks)
        # `limit` est un minimum pour ytmusicapi (il lit par pages de 100).
        tracks = [t for t in (_track_from_ytmusic(i) for i in data.get("tracks") or []) if t]
        count = max(data.get("trackCount") or 0, len(tracks))
        tracks = tracks[:max_tracks]
        thumbnails = data.get("thumbnails") or []
        if tracks:
            return ExternalPlaylist(
                name=data.get("title") or "Playlist YouTube",
                description=data.get("description") or None,
                cover_url=thumbnails[-1].get("url") if thumbnails else tracks[0].cover_url,
                tracks=tracks,
                note=f"Import partiel : les {max_tracks} premiers titres sur {count}." if count > max_tracks else None,
            )
    except Exception as exc:  # noqa: BLE001 — ytmusicapi lève ce qu'il veut
        logger.info("Playlist %s illisible via YouTube Music (%s) : essai avec yt-dlp", playlist_id, exc)
    album = await get_playlist_info(playlist_id)
    tracks = []
    for track in album.tracks[:max_tracks]:
        if not track.source_id:
            continue
        track.title, track.artist = split_video_title(track.title, track.artist)
        tracks.append(track)
    if not tracks:
        raise YoutubeError("Playlist YouTube vide, privée ou introuvable.")
    return ExternalPlaylist(name=album.title, description=None, cover_url=album.cover_url, tracks=tracks)
