from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import httpx
import yt_dlp
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from mutagen.mp4 import MP4, MP4Cover

from app.config import Settings
from app.providers.base import TrackInfo

logger = logging.getLogger(__name__)

_FORBIDDEN_CHARS_RE = re.compile(r'[\\/*?:"<>|]')
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DownloadError(Exception):
    pass


def _sanitize_filename(name: str) -> str:
    name = _FORBIDDEN_CHARS_RE.sub("", name)
    name = " ".join(name.split())
    return name[:120] or "sona_track"


def _codec_for(format_pref: str) -> str:
    return "mp3" if format_pref == "mp3" else "m4a"


def _format_selector_for(quality: str) -> str:
    if quality == "standard":
        return "bestaudio[abr<=128]/bestaudio/best"
    return "bestaudio/best"


def _download_sync(
    video_id: str, out_template: str, ffmpeg_path: str, quality: str, format_pref: str
) -> Path:
    url = f"https://www.youtube.com/watch?v={video_id}"
    codec = _codec_for(format_pref)
    opts = {
        "format": _format_selector_for(quality),
        "outtmpl": out_template,
        "ffmpeg_location": ffmpeg_path,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"},
        ],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 3,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    final_path = Path(filename).with_suffix(f".{codec}")
    if not final_path.exists():
        candidates = list(final_path.parent.glob(final_path.stem + ".*"))
        if not candidates:
            raise DownloadError("Fichier audio introuvable après téléchargement.")
        final_path = candidates[0]
    return final_path


async def _fetch_cover_bytes(cover_url: str | None) -> bytes | None:
    if not cover_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(cover_url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None
    content_type = resp.headers.get("content-type", "")
    if "jpeg" in content_type or "jpg" in content_type or "png" in content_type:
        return resp.content
    return None


def _tag_mp4(path: Path, track: TrackInfo, cover_bytes: bytes | None) -> None:
    audio = MP4(path)
    audio["\xa9nam"] = [track.title]
    audio["\xa9ART"] = [track.artist]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if track.year:
        audio["\xa9day"] = [track.year]
    if cover_bytes:
        fmt = MP4Cover.FORMAT_PNG if cover_bytes[:8] == _PNG_SIGNATURE else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=fmt)]
    audio.save()


def _tag_mp3(path: Path, track: TrackInfo, cover_bytes: bytes | None) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags["TIT2"] = TIT2(encoding=3, text=track.title)
    tags["TPE1"] = TPE1(encoding=3, text=track.artist)
    if track.album:
        tags["TALB"] = TALB(encoding=3, text=track.album)
    if track.year:
        tags["TDRC"] = TDRC(encoding=3, text=track.year)
    if cover_bytes:
        mime = "image/png" if cover_bytes[:8] == _PNG_SIGNATURE else "image/jpeg"
        tags["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_bytes)
    tags.save(path)


def _tag_sync(path: Path, track: TrackInfo, cover_bytes: bytes | None) -> None:
    try:
        if path.suffix.lower() == ".mp3":
            _tag_mp3(path, track, cover_bytes)
        else:
            _tag_mp4(path, track, cover_bytes)
    except Exception as exc:  # fichier corrompu ou format inattendu
        raise DownloadError("Impossible de préparer les métadonnées du fichier.") from exc


async def download_and_tag(
    settings: Settings,
    video_id: str,
    track: TrackInfo,
    quality: str = "best",
    format_pref: str = "auto",
) -> Path:
    """Télécharge l'audio YouTube correspondant et applique les métadonnées de `track`.

    Le fichier final est nommé et tagué d'après les métadonnées de la source
    d'origine (Deezer/Spotify/Apple/YouTube), pas d'après le titre brut YouTube.
    """
    safe_name = _sanitize_filename(f"{track.artist} - {track.title}")
    out_template = str(settings.downloads_dir / f"{safe_name}.%(ext)s")
    try:
        path = await asyncio.to_thread(
            _download_sync, video_id, out_template, settings.ffmpeg_path, quality, format_pref
        )
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError("Téléchargement audio impossible.") from exc

    cover_bytes = await _fetch_cover_bytes(track.cover_url)
    await asyncio.to_thread(_tag_sync, path, track, cover_bytes)
    return path
