"""Import d'une playlist Deezer, Spotify ou Apple Music dans l'app.

L'import tourne en tâche de fond : la playlist est créée tout de suite
(« import en cours »), l'app suit l'avancement, et les morceaux arrivent
d'un bloc à la fin, dans l'ordre d'origine.

Chaque morceau Spotify ou Apple Music est rapproché de son équivalent
Deezer (par ISRC quand on l'a, sinon par titre, artiste et durée) : c'est
Deezer qui donne pochette, album, fiche artiste et radio dans l'app. Sans
équivalent, le morceau reste sous sa source d'origine — il se lit quand
même (l'audio vient de YouTube dans tous les cas).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

import httpx

from app.providers.apple import AppleMusicError
from app.providers.base import ExternalPlaylist, TrackInfo
from app.providers.deezer import DeezerError
from app.providers.link_detect import resolve_link
from app.providers.spotify import SpotifyError

logger = logging.getLogger(__name__)

_APPLE_PLAYLIST_RE = re.compile(
    r"https?://(?:[a-z]+\.)?music\.apple\.com/[a-z]{2}/playlist/[^\s?#]+", re.IGNORECASE
)
_SPOTIFY_SHORT_RE = re.compile(r"https?://(?:spotify\.link|spotify\.app\.link)/\S+", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")

# Deezer tolère 50 requêtes par 5 s et par adresse IP : on reste en dessous,
# le serveur sert aussi l'app pendant ce temps.
DEEZER_REQUESTS_PER_SECOND = 7
MATCH_CONCURRENCY = 3
DURATION_TOLERANCE_SECONDS = 8


class PlaylistImportError(Exception):
    """Erreur à montrer telle quelle dans l'app."""


@dataclass(slots=True)
class PlaylistLink:
    source: str  # "deezer" | "spotify" | "apple"
    ref: str  # identifiant (Deezer, Spotify) ou URL de la page (Apple)
    url: str


async def detect_playlist_link(text: str) -> PlaylistLink:
    """Lien de playlist Deezer, Spotify ou Apple Music dans un texte collé."""
    match = _URL_RE.search(text or "")
    if not match:
        raise PlaylistImportError("Colle le lien de partage d'une playlist Deezer, Spotify ou Apple Music.")
    url = match.group(0).rstrip(").,;»\"'")

    apple = _APPLE_PLAYLIST_RE.search(url)
    if apple:
        return PlaylistLink("apple", apple.group(0), url)

    if _SPOTIFY_SHORT_RE.match(url):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                url = str((await client.get(url)).url)
        except httpx.HTTPError as exc:
            raise PlaylistImportError(f"Lien Spotify injoignable : {exc}") from exc

    detected = await resolve_link(url)
    if detected and detected.kind == "playlist" and detected.source in ("deezer", "spotify"):
        return PlaylistLink(detected.source, detected.ref, url)
    if detected:
        raise PlaylistImportError("Ce lien n'est pas celui d'une playlist.")
    raise PlaylistImportError("Lien non reconnu : seules les playlists Deezer, Spotify et Apple Music s'importent.")


async def fetch_playlist(deps, link: PlaylistLink) -> ExternalPlaylist:
    try:
        if link.source == "deezer":
            return await deps.deezer.get_playlist_for_import(link.ref)
        if link.source == "spotify":
            return await deps.spotify.get_playlist(link.ref)
        return await deps.apple.get_playlist(link.ref)
    except (DeezerError, SpotifyError, AppleMusicError) as exc:
        raise PlaylistImportError(str(exc)) from exc


# -- Rapprochement avec Deezer ------------------------------------------

def _key(text: str | None) -> str:
    """Forme comparable : sans casse, accents, ponctuation, ni mentions entre
    parenthèses (« (feat. X) », « [Remastered] ») ou après un tiret."""
    text = (text or "").casefold()
    text = re.sub(r"[(\[].*?[)\]]", " ", text)
    text = re.sub(r"\s[-–—]\s.*$", " ", text)
    text = re.sub(r"\b(?:feat|ft)\.?\s.*$", " ", text)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def _first_artist(artist: str) -> str:
    return re.split(r",|&| x | et | feat\.? | ft\.? ", artist, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def is_same_track(wanted: TrackInfo, candidate: TrackInfo) -> bool:
    wanted_title, found_title = _key(wanted.title), _key(candidate.title)
    if not wanted_title or not found_title:
        return False
    if not (wanted_title == found_title or wanted_title.startswith(found_title) or found_title.startswith(wanted_title)):
        return False
    wanted_artist = _key(_first_artist(wanted.artist))
    found_artist = _key(candidate.artist)
    if wanted_artist and found_artist and wanted_artist not in found_artist and found_artist not in _key(wanted.artist):
        return False
    if wanted.duration_seconds and candidate.duration_seconds:
        return abs(wanted.duration_seconds - candidate.duration_seconds) <= DURATION_TOLERANCE_SECONDS
    return True


class _Throttle:
    """Espace les requêtes : au plus `rate` par seconde, toutes tâches confondues."""

    def __init__(self, rate: float) -> None:
        self._interval = 1 / rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


async def _deezer_call(throttle: _Throttle, coro_factory):
    """Appel Deezer espacé ; un dépassement de quota (« Quota limit
    exceeded ») est réessayé une fois après une pause."""
    for attempt in (1, 2):
        await throttle.wait()
        try:
            return await coro_factory()
        except DeezerError as exc:
            if attempt == 1 and "quota" in str(exc).lower():
                await asyncio.sleep(5)
                continue
            raise


async def match_on_deezer(deezer, track: TrackInfo, throttle: _Throttle) -> TrackInfo | None:
    if track.isrc:
        found = await _deezer_call(throttle, lambda: deezer.get_track_by_isrc(track.isrc))
        if found:
            return found
    title = re.sub(r"\s*[(\[].*?[)\]]", "", track.title).strip() or track.title
    artist = _first_artist(track.artist)
    queries = [
        f'artist:"{artist.replace(chr(34), "")}" track:"{title.replace(chr(34), "")}"',
        f"{artist} {title}",
    ]
    for query in queries:
        items, _ = await _deezer_call(throttle, lambda q=query: deezer.search_tracks(q, limit=10))
        for candidate in items:
            if is_same_track(track, candidate):
                return candidate
    return None


async def resolve_tracks(deps, tracks: list[TrackInfo], on_progress=None) -> list[TrackInfo | None]:
    """Équivalent Deezer de chaque morceau (ou le morceau d'origine s'il se
    lit tel quel), dans l'ordre ; None pour un morceau impossible à lire."""
    throttle = _Throttle(DEEZER_REQUESTS_PER_SECOND)
    semaphore = asyncio.Semaphore(MATCH_CONCURRENCY)
    results: list[TrackInfo | None] = [None] * len(tracks)
    done = 0

    async def one(index: int, track: TrackInfo) -> None:
        nonlocal done
        async with semaphore:
            match = None
            if track.source != "deezer":
                try:
                    match = await match_on_deezer(deps.deezer, track, throttle)
                except DeezerError as exc:
                    logger.info("Rapprochement Deezer impossible pour « %s » : %s", track.title, exc)
            else:
                match = track
            # Sans équivalent Deezer, le morceau se lit quand même depuis sa
            # source (identifiant Spotify ou Apple connu).
            results[index] = match or (track if track.source_id else None)
            done += 1
            if on_progress:
                await on_progress(done)

    await asyncio.gather(*(one(i, t) for i, t in enumerate(tracks)))
    return results


# -- Tâche de fond --------------------------------------------------------

_running: set[asyncio.Task] = set()


async def start_import(deps, user_id: int, text: str) -> int:
    """Crée la playlist (import en cours) et lance l'import ; renvoie son id."""
    link = await detect_playlist_link(text)
    playlist_id = await deps.repo.playlist_create(
        user_id, "Import en cours…", origin=link.source, origin_url=link.url, import_status="importing"
    )
    task = asyncio.create_task(run_import(deps, playlist_id, link))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return playlist_id


async def start_reimport(deps, playlist) -> None:
    """« Mettre à jour » une playlist importée : relit la source et remplace
    ses titres (les anciens restent affichés jusqu'à la fin de l'import)."""
    if not playlist.origin_url:
        raise PlaylistImportError("Cette playlist n'a pas été importée : rien à mettre à jour.")
    if playlist.import_status == "importing":
        raise PlaylistImportError("Import déjà en cours.")
    link = await detect_playlist_link(playlist.origin_url)
    await deps.repo.playlist_update(
        playlist.id, import_status="importing", import_total=None, import_done=0,
        import_missing=0, import_error=None,
    )
    task = asyncio.create_task(run_import(deps, playlist.id, link, replace=True))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def run_import(deps, playlist_id: int, link: PlaylistLink, *, replace: bool = False) -> None:
    """`replace` : mise à jour d'une playlist existante — ses titres sont
    remplacés et son nom (peut-être changé dans l'app) est gardé."""
    repo = deps.repo
    try:
        playlist = await fetch_playlist(deps, link)
        if not playlist.tracks:
            raise PlaylistImportError("Cette playlist est vide.")
        total = len(playlist.tracks)
        details = {
            "description": (playlist.description or None) and playlist.description[:1000],
            "cover_url": playlist.cover_url,
            "import_total": total,
        }
        if not replace:
            details["name"] = playlist.name[:200]
        await repo.playlist_update(playlist_id, **details)

        async def progress(done: int) -> None:
            if done % 10 == 0 or done == total:
                await repo.playlist_update(playlist_id, import_done=done)

        resolved = await resolve_tracks(deps, playlist.tracks, progress)
        kept = [t for t in resolved if t is not None]
        if replace:
            await repo.playlist_clear_tracks(playlist_id)
        await repo.playlist_add_tracks(playlist_id, kept)
        await repo.playlist_update(
            playlist_id, import_status="done", import_done=total, import_missing=total - len(kept)
        )
        logger.info(
            "Playlist importée (%s) : « %s », %d/%d morceaux", link.source, playlist.name, len(kept), total
        )
    except PlaylistImportError as exc:
        await repo.playlist_update(playlist_id, import_status="failed", import_error=str(exc))
    except Exception as exc:  # noqa: BLE001 — l'échec doit s'afficher dans l'app, pas disparaître
        logger.exception("Import de playlist %s échoué", link.url)
        await repo.playlist_update(playlist_id, import_status="failed", import_error=f"Import impossible : {exc}")
