"""Liens de partage d'un titre, d'un album ou d'une playlist Sona.

Sona est privé (liste blanche, invitations) : un lien de partage ne donne
jamais accès à l'audio complet. Il mène à une page publique en lecture
seule (routers/share.py) — pochette, titres, extraits officiels de 30 s
servis par Deezer, jamais par Sona — avec, pour les membres, de quoi
l'ouvrir dans Sona (l'app, le site, le bot Telegram).

Le jeton est aléatoire (128 bits, impossible à deviner), révocable à tout
moment, et peut expirer (24 h, 7 jours, 30 jours…). Partagé par le bot et
l'API.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.bot import lookup
from app.db.repository import ShareLink
from app.providers.base import TrackInfo
from app.services.preview import complete_preview

logger = logging.getLogger(__name__)

KINDS = ("track", "album", "playlist")
KIND_LABELS = {"track": "Titre", "album": "Album", "playlist": "Playlist"}
# Titres montrés (avec leur extrait) sur la page d'un album ou d'une playlist.
MAX_PUBLIC_TRACKS = 50
# Durée maximale d'un lien qui expire (un an) ; sans expiration sinon.
MAX_HOURS = 24 * 365
_TRACKS_TTL = 300
_tracks_cache: dict[str, tuple[float, list[TrackInfo]]] = {}
_bot_username: tuple[float, str | None] | None = None


class ShareError(Exception):
    """Erreur à montrer telle quelle."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def describe(deps, user_id: int, kind: str, source: str, ref: str) -> tuple[str, str | None, str | None]:
    """Titre, sous-titre et pochette du contenu partagé (vérifie qu'il existe
    et, pour une playlist, que le compte y a accès)."""
    try:
        if kind == "track":
            track = await lookup.get_track(deps, source, ref)
            return track.title, track.artist, track.cover_url
        if kind == "album":
            album = await lookup.get_album(deps, source, ref)
            return album.title, album.artist, album.cover_url
    except (lookup.UnknownSourceError, *lookup.ProviderErrors) as exc:
        raise ShareError("Contenu introuvable : impossible de le partager.") from exc
    if kind == "playlist":
        playlist = await _playlist(deps, user_id, ref)
        owner = await deps.repo.account_by_user_id(playlist.user_id)
        by = (owner.display_name or owner.lastfm_username) if owner else None
        count = f"{playlist.track_count} titre{'s' if playlist.track_count > 1 else ''}"
        subtitle = f"Playlist de {by} · {count}" if by else count
        return playlist.name, subtitle, playlist.cover_url or (playlist.covers[0] if playlist.covers else None)
    raise ShareError("On ne partage qu'un titre, un album ou une playlist.")


async def _playlist(deps, user_id: int, ref: str):
    playlist = await deps.repo.playlist_by_id(int(ref)) if ref.isdigit() else None
    if playlist is None or (playlist.user_id != user_id and playlist.visibility not in ("friends", "collaborative")):
        raise ShareError("Playlist introuvable.")
    return playlist


async def create(
    deps, user_id: int, kind: str, source: str, ref: str, expires_in_hours: int | None = None
) -> ShareLink:
    """Nouveau lien (ou le lien permanent déjà créé pour ce contenu)."""
    if kind not in KINDS:
        raise ShareError("On ne partage qu'un titre, un album ou une playlist.")
    if kind == "playlist":
        source = "sona"
    if expires_in_hours is not None and not 1 <= expires_in_hours <= MAX_HOURS:
        raise ShareError("Durée de validité impossible.")
    if expires_in_hours is None:
        existing = await deps.repo.share_find_active(user_id, kind, source, ref)
        if existing is not None:
            return existing
    title, subtitle, cover = await describe(deps, user_id, kind, source, ref)
    now = _now()
    link = ShareLink(
        token=secrets.token_urlsafe(16), user_id=user_id, kind=kind, source=source, ref=ref,
        title=title[:300], subtitle=(subtitle or None) and subtitle[:300], cover_url=cover,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=expires_in_hours)).isoformat() if expires_in_hours else None,
    )
    await deps.repo.share_create(link)
    logger.info("Lien de partage créé (%s %s:%s) par %s", kind, source, ref, user_id)
    return link


async def resolve(deps, token: str) -> ShareLink | None:
    """Lien actif (ni révoqué ni expiré), sinon None."""
    if not 16 <= len(token) <= 64:
        return None
    link = await deps.repo.share_get(token)
    return link if link is not None and link.active else None


async def tracks(deps, link: ShareLink) -> list[TrackInfo]:
    """Titres du contenu partagé (les 50 premiers), gardés quelques minutes :
    chaque extrait écouté sur la page les redemande."""
    cached = _tracks_cache.get(link.token)
    if cached and time.monotonic() - cached[0] < _TRACKS_TTL:
        return cached[1]
    try:
        if link.kind == "track":
            found = [await lookup.get_track(deps, link.source, link.ref)]
        elif link.kind == "album":
            found = list((await lookup.get_album(deps, link.source, link.ref)).tracks)
        else:
            found = [e.track for e in await deps.repo.playlist_tracks(int(link.ref))]
    except (lookup.UnknownSourceError, ValueError, *lookup.ProviderErrors) as exc:
        logger.info("Contenu du lien %s indisponible : %s", link.token[:6], exc)
        found = []
    found = found[:MAX_PUBLIC_TRACKS]
    _tracks_cache[link.token] = (time.monotonic(), found)
    return found


async def preview_url(deps, link: ShareLink, index: int) -> str | None:
    """Extrait officiel de 30 s du titre `index` (Deezer, signé et de courte
    durée : redemandé à chaque écoute, jamais servi par Sona)."""
    found = await tracks(deps, link)
    if not 0 <= index < len(found):
        return None
    track = found[index]
    if track.source == "deezer" and not track.preview_url:
        try:
            track = await lookup.get_track(deps, "deezer", track.source_id)
        except lookup.ProviderErrors:
            return None
    if not track.preview_url:
        try:
            track = await complete_preview(deps.deezer, track)
        except Exception as exc:  # noqa: BLE001 — pas d'extrait, pas de lecture
            logger.info("Extrait introuvable pour %s : %s", track.title, exc)
            return None
    return track.preview_url


def public_url(settings, token: str, request_base: str | None = None) -> str:
    base = settings.share_base_url or (request_base or "").rstrip("/")
    return f"{base}/s/{token}"


async def bot_username(settings) -> str | None:
    """Nom du bot Telegram (pour « Ouvrir dans Telegram »), demandé une fois."""
    global _bot_username
    if not settings.bot_token:
        return None
    if _bot_username and time.monotonic() - _bot_username[0] < (86400 if _bot_username[1] else 600):
        return _bot_username[1]
    name = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            data = (await client.get(f"https://api.telegram.org/bot{settings.bot_token}/getMe")).json()
        name = (data.get("result") or {}).get("username")
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
        logger.info("Nom du bot Telegram inconnu : %s", exc)
    _bot_username = (time.monotonic(), name)
    return name


def reset() -> None:
    global _bot_username
    _tracks_cache.clear()
    _bot_username = None
