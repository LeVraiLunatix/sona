from __future__ import annotations

import asyncio
import logging

import yt_dlp

from app.logging_config import ytdlp_logger
from app.providers.base import AlbumInfo, TrackInfo

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
    with yt_dlp.YoutubeDL(opts) as ydl:
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
