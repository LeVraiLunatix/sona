from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import time
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
_AUDIO_SUFFIXES = (".m4a", ".mp3", ".opus", ".ogg", ".webm", ".aac", ".flac", ".wav", ".mp4")
_TEMP_PREFIX = "sona-dl-"


class DownloadError(Exception):
    pass


def _sanitize_filename(name: str) -> str:
    name = _FORBIDDEN_CHARS_RE.sub("", name)
    name = " ".join(name.split())
    name = name.strip(". ")
    return name[:120] or "sona_track"


def _codec_for(format_pref: str) -> str:
    return "mp3" if format_pref == "mp3" else "m4a"


def _format_selector_for(quality: str, broad: bool = False) -> str:
    """Sélecteur de flux yt-dlp.

    On privilégie le m4a quand il existe : c'est le format que Telegram lit
    nativement, et ça évite un ré-encodage ffmpeg inutile (donc une source
    d'échec en moins). `broad` sert aux dernières tentatives : on prend
    n'importe quoi plutôt que d'échouer.
    """
    if broad:
        return "bestaudio/best/bestaudio*"
    if quality == "standard":
        return "bestaudio[abr<=128][ext=m4a]/bestaudio[abr<=128]/bestaudio/best"
    return "bestaudio[ext=m4a]/bestaudio/best"


# Stratégies successives : YouTube casse régulièrement l'un ou l'autre de ses
# clients (déchiffrement JS, mur anti-bot). Ce qui échoue avec le client par
# défaut passe très souvent avec le client "tv", et inversement — d'où cette
# cascade plutôt que trois fois la même tentative.
_ATTEMPTS: tuple[dict, ...] = (
    {"label": "client par défaut"},
    {"label": "client tv", "player_client": ["tv"]},
    {"label": "client web_safari", "player_client": ["web_safari", "mweb"]},
    {"label": "sans cookies", "drop_cookies": True, "broad_format": True},
)


def _build_opts(
    attempt: dict,
    out_template: str,
    ffmpeg_path: str,
    quality: str,
    codec: str,
    cookies_file: Path | None,
) -> dict:
    opts = {
        "format": _format_selector_for(quality, broad=attempt.get("broad_format", False)),
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
    if cookies_file is not None and not attempt.get("drop_cookies"):
        # Contourne le mur anti-bot YouTube ("Sign in to confirm you're not
        # a bot"), fréquent sur les IP de datacenter (VPS) mais rare sur une
        # IP résidentielle — voir README pour comment exporter ce fichier.
        opts["cookiefile"] = str(cookies_file)
    if attempt.get("player_client"):
        opts["extractor_args"] = {"youtube": {"player_client": attempt["player_client"]}}
    return opts


def _find_output(expected: Path) -> Path:
    """Retrouve le fichier produit par yt-dlp.

    Le nom exact dépend du post-traitement ffmpeg (titre nettoyé, extension
    changée) : on liste le dossier de travail — unique à ce téléchargement —
    au lieu de deviner. Un `glob` sur le nom attendu ne conviendrait pas, les
    crochets des titres YouTube y étant des métacaractères.
    """
    if expected.exists():
        return expected
    if not expected.parent.is_dir():
        raise DownloadError("Fichier audio introuvable après téléchargement.")
    found = [p for p in expected.parent.iterdir() if p.is_file()]
    audio = [p for p in found if p.suffix.lower() in _AUDIO_SUFFIXES and not p.name.endswith(".part")]
    if not audio:
        raise DownloadError("Fichier audio introuvable après téléchargement.")
    # Le fichier au format demandé prime (c'est celui qu'a produit ffmpeg) ;
    # sinon on prend le plus récent, le flux brut étant écrit en premier.
    converted = [p for p in audio if p.suffix.lower() == expected.suffix.lower()]
    return max(converted or audio, key=lambda p: p.stat().st_mtime)


def _download_sync(
    video_id: str,
    out_template: str,
    ffmpeg_path: str,
    quality: str,
    format_pref: str,
    cookies_file: Path | None,
) -> Path:
    url = f"https://www.youtube.com/watch?v={video_id}"
    codec = _codec_for(format_pref)
    last_error: Exception | None = None

    for index, attempt in enumerate(_ATTEMPTS):
        opts = _build_opts(attempt, out_template, ffmpeg_path, quality, codec, cookies_file)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
            return _find_output(Path(filename).with_suffix(f".{codec}"))
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Téléchargement de %s : tentative %d/%d (%s) échouée: %s",
                video_id,
                index + 1,
                len(_ATTEMPTS),
                attempt["label"],
                exc,
            )
            if index < len(_ATTEMPTS) - 1:
                time.sleep(2)

    raise DownloadError("Téléchargement audio impossible.") from last_error


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
    except Exception as exc:
        # Un tag raté ne doit pas priver l'utilisateur de son morceau : le
        # fichier est lisible, il lui manque juste la pochette/les métadonnées.
        logger.warning("Métadonnées non appliquées sur %s: %s", path.name, exc)


def cleanup_download(path: Path) -> None:
    """Supprime le fichier et son dossier de travail temporaire."""
    parent = path.parent
    path.unlink(missing_ok=True)
    if parent.name.startswith(_TEMP_PREFIX):
        shutil.rmtree(parent, ignore_errors=True)


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
    Il atterrit dans un dossier temporaire dédié : deux utilisateurs qui
    demandent le même morceau en même temps ne se marchent pas dessus, et
    `cleanup_download` efface tout, y compris les flux intermédiaires.
    """
    safe_name = _sanitize_filename(f"{track.artist} - {track.title}")
    work_dir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=settings.downloads_dir))
    out_template = str(work_dir / f"{safe_name}.%(ext)s")
    try:
        path = await asyncio.to_thread(
            _download_sync,
            video_id,
            out_template,
            settings.ffmpeg_path,
            quality,
            format_pref,
            settings.youtube_cookies_file,
        )
    except DownloadError:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise DownloadError("Téléchargement audio impossible.") from exc

    cover_bytes = await _fetch_cover_bytes(track.cover_url)
    await asyncio.to_thread(_tag_sync, path, track, cover_bytes)
    return path
