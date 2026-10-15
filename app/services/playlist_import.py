"""Import d'une playlist dans l'app : Deezer, Spotify, Apple Music, YouTube /
YouTube Music et SoundCloud (playlists et likes publics).

L'import tourne en tâche de fond : la playlist est créée tout de suite
(« import en cours »), l'app suit l'avancement, et les morceaux arrivent
d'un bloc à la fin, dans l'ordre d'origine.

Chaque morceau est rapproché de son équivalent Deezer (par ISRC quand on
l'a, sinon par titre, artiste, version et durée) : c'est Deezer qui donne
pochette, album, fiche artiste et radio dans l'app. Le rapport d'import
(`playlist_import_items`) garde, titre par titre, ce qui a été retenu :
- « trouvé » : même enregistrement, sans doute possible ;
- « incertain » : retenu, mais à vérifier (durée un peu différente, titre
  approchant, ou pas d'équivalent au catalogue : l'audio sera cherché
  d'après le titre) ;
- « introuvable ».
Chaque titre se corrige à la main (`fix_item`) : valider, retirer, choisir
un autre titre, ou coller un lien YouTube / SoundCloud.

La resynchronisation (`start_reimport`, et chaque jour toute seule) relit
la playlist d'origine et n'ajoute que les nouveaux titres : les corrections
et l'ordre choisi dans Sona sont gardés.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.db.repository import ImportItem
from app.providers import youtube
from app.providers.apple import AppleMusicError
from app.providers.base import ExternalPlaylist, TrackInfo
from app.providers.deezer import DeezerError
from app.providers.link_detect import resolve_link
from app.providers.soundcloud import SoundcloudError, shared_client as soundcloud_client
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
# En dessous, même enregistrement sans hésiter ; au-delà (jusqu'à la
# tolérance), « incertain ».
SURE_DURATION_GAP = 3
# Resynchronisation automatique des playlists importées.
AUTO_SYNC_EVERY = timedelta(hours=24)
AUTO_SYNC_CHECK_SECONDS = 3600

SOURCE_LABELS = {
    "deezer": "Deezer", "spotify": "Spotify", "apple": "Apple Music",
    "youtube": "YouTube", "soundcloud": "SoundCloud", "appareil": "l'iPhone",
}


class PlaylistImportError(Exception):
    """Erreur à montrer telle quelle dans l'app."""


@dataclass(slots=True)
class PlaylistLink:
    source: str  # "deezer" | "spotify" | "apple" | "youtube" | "soundcloud"
    ref: str  # identifiant (Deezer, Spotify, YouTube) ou URL de la page (Apple, SoundCloud)
    url: str
    kind: str = "playlist"  # ou « likes » (SoundCloud)


async def detect_playlist_link(text: str) -> PlaylistLink:
    """Lien de playlist (ou de likes SoundCloud) dans un texte collé."""
    match = _URL_RE.search(text or "")
    if not match:
        raise PlaylistImportError(
            "Colle le lien de partage d'une playlist Deezer, Spotify, Apple Music, YouTube ou SoundCloud."
        )
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
    if detected and detected.kind == "playlist" and detected.source in ("deezer", "spotify", "youtube", "soundcloud"):
        return PlaylistLink(detected.source, detected.ref, url)
    if detected and detected.kind == "likes":
        return PlaylistLink(detected.source, detected.ref, url, kind="likes")
    if detected:
        raise PlaylistImportError("Ce lien n'est pas celui d'une playlist.")
    raise PlaylistImportError(
        "Lien non reconnu : seules les playlists Deezer, Spotify, Apple Music, YouTube (Music) "
        "et SoundCloud (playlists et likes) s'importent."
    )


async def fetch_playlist(deps, link: PlaylistLink) -> ExternalPlaylist:
    try:
        if link.source == "deezer":
            return await deps.deezer.get_playlist_for_import(link.ref)
        if link.source == "spotify":
            return await deps.spotify.get_playlist(link.ref)
        if link.source == "youtube":
            return await youtube.get_playlist_for_import(link.ref)
        if link.source == "soundcloud":
            soundcloud = getattr(deps, "soundcloud", None) or soundcloud_client()
            if link.kind == "likes":
                return await soundcloud.get_likes(link.ref)
            return await soundcloud.get_playlist(link.ref)
        return await deps.apple.get_playlist(link.ref)
    except (DeezerError, SpotifyError, AppleMusicError, youtube.YoutubeError, SoundcloudError) as exc:
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


# Une autre version que l'enregistrement demandé (« - Live », « (Remix) ») :
# `_key` ne garde pas ces mentions, on les compare à part.
_VERSION_RE = re.compile(
    r"\b(live|remix|rmx|acoustic|acoustique|unplugged|instrumental|karaoke|cover|sped\s*up|slowed|"
    r"nightcore|extended|a\s*cappella|acapella|demo)\b",
    re.IGNORECASE,
)


def _versions(title: str | None) -> set[str]:
    return {re.sub(r"\s+", "", m.lower()) for m in _VERSION_RE.findall(title or "")}


def is_same_track(wanted: TrackInfo, candidate: TrackInfo) -> bool:
    wanted_title, found_title = _key(wanted.title), _key(candidate.title)
    if not wanted_title or not found_title:
        return False
    if not (wanted_title == found_title or wanted_title.startswith(found_title) or found_title.startswith(wanted_title)):
        return False
    if _versions(wanted.title) != _versions(candidate.title):
        return False
    wanted_artist = _key(_first_artist(wanted.artist))
    found_artist = _key(candidate.artist)
    if wanted_artist and found_artist and wanted_artist not in found_artist and found_artist not in _key(wanted.artist):
        return False
    if wanted.duration_seconds and candidate.duration_seconds:
        return abs(wanted.duration_seconds - candidate.duration_seconds) <= DURATION_TOLERANCE_SECONDS
    return True


def match_quality(wanted: TrackInfo, candidate: TrackInfo) -> tuple[str, str | None]:
    """« found » ou « uncertain » (avec la raison) pour un équivalent retenu."""
    if wanted.isrc and candidate.isrc and wanted.isrc.upper() == candidate.isrc.upper():
        return "found", None
    if wanted.duration_seconds and candidate.duration_seconds:
        gap = abs(wanted.duration_seconds - candidate.duration_seconds)
        if gap > SURE_DURATION_GAP:
            return "uncertain", f"Durée différente ({gap} s d'écart) : peut-être une autre version."
    if _key(wanted.title) != _key(candidate.title):
        return "uncertain", f"Titre approchant : « {candidate.title} »."
    return "found", None


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


@dataclass(slots=True)
class Match:
    track: TrackInfo | None
    status: str  # « found » | « uncertain » | « missing »
    reason: str | None = None


async def match_track(deps, track: TrackInfo, throttle: _Throttle) -> Match:
    """Ce que l'import retient pour un titre de la playlist d'origine."""
    if track.source == "deezer":
        return Match(track, "found")
    found = None
    try:
        found = await match_on_deezer(deps.deezer, track, throttle)
    except DeezerError as exc:
        logger.info("Rapprochement Deezer impossible pour « %s » : %s", track.title, exc)
    if found:
        status, reason = match_quality(track, found)
        return Match(found, status, reason)
    label = SOURCE_LABELS.get(track.source, track.source)
    if not track.source_id:
        return Match(None, "missing", "Introuvable sur Deezer, et illisible depuis la source.")
    if track.source in ("youtube", "soundcloud"):
        # L'audio d'origine lui-même : c'est bien ce titre-là.
        return Match(track, "found", f"Lu depuis {label} (pas d'équivalent au catalogue).")
    # Sans équivalent Deezer, le morceau se lit quand même : l'audio est
    # cherché d'après son titre (identifiant Spotify ou Apple connu).
    return Match(track, "uncertain", f"Pas trouvé sur Deezer : l'audio sera cherché d'après le titre ({label}).")


async def match_tracks(deps, tracks: list[TrackInfo], on_progress=None) -> list[Match]:
    """Ce que l'import retient pour chaque morceau, dans l'ordre."""
    throttle = _Throttle(DEEZER_REQUESTS_PER_SECOND)
    semaphore = asyncio.Semaphore(MATCH_CONCURRENCY)
    results: list[Match | None] = [None] * len(tracks)
    done = 0

    async def one(index: int, track: TrackInfo) -> None:
        nonlocal done
        async with semaphore:
            results[index] = await match_track(deps, track, throttle)
            done += 1
            if on_progress:
                await on_progress(done)

    await asyncio.gather(*(one(i, t) for i, t in enumerate(tracks)))
    return [r for r in results if r is not None]


def origin_key(track: TrackInfo) -> str:
    """Identité d'un titre à sa source, pour le reconnaître à la
    resynchronisation."""
    if track.source_id:
        return f"{track.source}:{track.source_id}"
    return f"meta:{_key(track.title)}|{_key(_first_artist(track.artist))}"


# -- Tâche de fond --------------------------------------------------------

_running: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def start_import(deps, user_id: int, text: str) -> int:
    """Crée la playlist (import en cours) et lance l'import ; renvoie son id."""
    link = await detect_playlist_link(text)
    playlist_id = await deps.repo.playlist_create(
        user_id, "Import en cours…", origin=link.source, origin_url=link.url, import_status="importing"
    )
    _spawn(run_import(deps, playlist_id, link))
    return playlist_id


async def start_reimport(deps, playlist) -> None:
    """« Resynchroniser » une playlist importée : relit la source et ajoute
    les titres apparus depuis (les corrections et l'ordre sont gardés)."""
    link = await _prepare_sync(deps, playlist)
    _spawn(run_import(deps, playlist.id, link, replace=True))


async def _prepare_sync(deps, playlist) -> PlaylistLink:
    if not playlist.origin_url:
        raise PlaylistImportError("Cette playlist n'a pas été importée : rien à mettre à jour.")
    if playlist.import_status == "importing":
        raise PlaylistImportError("Import déjà en cours.")
    link = await detect_playlist_link(playlist.origin_url)
    await deps.repo.playlist_update(
        playlist.id, import_status="importing", import_total=None, import_done=0, import_error=None,
    )
    return link


async def start_import_from_tracks(deps, user_id: int, name: str, tracks: list[TrackInfo]) -> int:
    """Playlist envoyée par l'app elle-même (lue dans la bibliothèque Musique
    de l'iPhone, liste complète) : seulement le rapprochement avec Deezer."""
    if not tracks:
        raise PlaylistImportError("Cette playlist est vide.")
    playlist_id = await deps.repo.playlist_create(user_id, name[:200], origin="apple", import_status="importing")
    playlist = ExternalPlaylist(name=name, description=None, cover_url=None, tracks=tracks)
    _spawn(run_import(deps, playlist_id, None, playlist=playlist))
    return playlist_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_import(
    deps, playlist_id: int, link: PlaylistLink | None, *, replace: bool = False,
    playlist: ExternalPlaylist | None = None,
) -> None:
    """`replace` : resynchronisation d'une playlist déjà importée — seuls
    les nouveaux titres sont rapprochés et ajoutés à la fin, son nom (peut-
    être changé dans l'app) est gardé. Une playlist importée avant le
    rapport d'import est reprise entièrement.
    `playlist` : déjà lue (envoyée par l'app), rien à aller chercher."""
    repo = deps.repo
    origin = link.source if link else "appareil"
    try:
        if playlist is None:
            playlist = await fetch_playlist(deps, link)
        if not playlist.tracks:
            raise PlaylistImportError("Cette playlist est vide.")

        known: list[ImportItem] = await repo.import_items(playlist_id) if replace else []
        if replace and not known:
            # Importée avant le rapport titre par titre : on reprend tout.
            await repo.playlist_clear_tracks(playlist_id)
        incremental = bool(known)
        seen = Counter(item.origin_key for item in known)
        source_keys = Counter()
        wanted: list[tuple[int, TrackInfo]] = []
        for position, track in enumerate(playlist.tracks):
            key = origin_key(track)
            source_keys[key] += 1
            # Un titre présent deux fois à la source l'est deux fois ici.
            if source_keys[key] > seen.get(key, 0):
                wanted.append((position, track))
        removed = sum(max(0, n - source_keys.get(key, 0)) for key, n in seen.items())

        total = len(wanted)
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

        matches = await match_tracks(deps, [t for _, t in wanted], progress)
        kept = [m.track for m in matches if m.track is not None]
        entry_ids = iter(await repo.playlist_add_tracks(playlist_id, kept) or [])
        items = []
        for (position, original), found in zip(wanted, matches):
            items.append(ImportItem(
                id=None, playlist_id=playlist_id, position=position, origin_key=origin_key(original),
                original=original, status=found.status, reason=found.reason, matched=found.track,
                entry_id=next(entry_ids, None) if found.track is not None else None,
            ))
        await repo.import_items_add(playlist_id, items)

        counts = await repo.import_counts(playlist_id)
        notes = [n for n in (
            playlist.note,
            f"{removed} titre(s) retiré(s) de la playlist d'origine restent ici." if incremental and removed else None,
        ) if n]
        await repo.playlist_update(
            playlist_id, import_uncertain=counts.get("uncertain", 0),
            import_added=len(kept) if incremental else 0, synced_at=_now(),
        )
        await repo.playlist_update(
            playlist_id, import_status="done", import_done=total, import_missing=counts.get("missing", 0),
            import_error=" ".join(notes) or None,
        )
        logger.info(
            "Playlist %s (%s) : « %s », %d/%d morceaux retenus, %d à vérifier",
            "resynchronisée" if incremental else "importée", origin, playlist.name, len(kept), total,
            counts.get("uncertain", 0),
        )
    except PlaylistImportError as exc:
        await repo.playlist_update(playlist_id, import_status="failed", import_error=str(exc))
    except Exception as exc:  # noqa: BLE001 — l'échec doit s'afficher dans l'app, pas disparaître
        logger.exception("Import de playlist %s échoué", link.url if link else origin)
        await repo.playlist_update(playlist_id, import_status="failed", import_error=f"Import impossible : {exc}")


# -- Corrections ------------------------------------------------------------

FIX_ACTIONS = ("accept", "remove", "replace")


async def fix_item(deps, playlist, item_id: int, action: str, track: TrackInfo | None = None) -> ImportItem:
    """Corrige un titre du rapport : « accept » (c'est le bon), « remove »
    (le retirer de la playlist), « replace » (mettre `track` à sa place :
    un titre choisi dans la recherche, ou lu depuis un lien collé). Un titre
    corrigé n'est plus jamais remis en cause par la resynchronisation."""
    repo = deps.repo
    item = await repo.import_item(playlist.id, item_id)
    if item is None:
        raise PlaylistImportError("Ce titre n'est pas dans le rapport d'import.")
    if action == "accept":
        if item.matched is None:
            raise PlaylistImportError("Rien à valider : ce titre n'a pas été trouvé.")
        status, reason, matched, entry_id = "found", "Validé à la main.", item.matched, item.entry_id
    elif action == "remove":
        if item.entry_id is not None:
            await repo.playlist_remove_entry(playlist.id, item.entry_id)
        status, reason, matched, entry_id = "missing", "Retiré à la main.", None, None
    elif action == "replace" and track is not None:
        entry_id = item.entry_id
        if entry_id is None or not await repo.playlist_replace_entry(playlist.id, entry_id, track):
            entry_id = (await repo.playlist_add_tracks(playlist.id, [track]))[0]
        status, reason, matched = "found", "Corrigé à la main.", track
    else:
        raise PlaylistImportError("Correction inconnue.")
    await repo.import_item_update(item.id, status=status, reason=reason, matched=matched, entry_id=entry_id, fixed=True)
    counts = await repo.import_counts(playlist.id)
    await repo.playlist_update(
        playlist.id, import_uncertain=counts.get("uncertain", 0), import_missing=counts.get("missing", 0),
    )
    return await repo.import_item(playlist.id, item.id)


async def track_from_link(url: str) -> TrackInfo:
    """Titre lu depuis un lien YouTube ou SoundCloud collé pour corriger un
    import : il se lira depuis cet audio-là."""
    from app.services.resolver import ResolutionError, source_from_url

    try:
        source_id = await source_from_url(url)
    except ResolutionError as exc:
        raise PlaylistImportError(str(exc)) from exc
    try:
        if source_id.startswith("soundcloud:"):
            return await soundcloud_client().get_track(source_id.split(":", 1)[1])
        track = await youtube.get_video_info(source_id)
    except (SoundcloudError, youtube.YoutubeError) as exc:
        raise PlaylistImportError(str(exc)) from exc
    track.title, track.artist = youtube.split_video_title(track.title, track.artist)
    return track


# -- Resynchronisation automatique ----------------------------------------

async def auto_sync_loop(deps) -> None:
    """Toutes les heures : les playlists importées depuis un lien et pas
    resynchronisées depuis un jour récupèrent leurs nouveaux titres, l'une
    après l'autre (sans bousculer les quotas des plateformes)."""
    while True:
        await asyncio.sleep(AUTO_SYNC_CHECK_SECONDS)
        try:
            before = (datetime.now(timezone.utc) - AUTO_SYNC_EVERY).isoformat()
            for playlist in await deps.repo.playlists_to_sync(before):
                try:
                    link = await _prepare_sync(deps, playlist)
                except PlaylistImportError as exc:
                    logger.info("Resynchronisation de « %s » impossible : %s", playlist.name, exc)
                    await deps.repo.playlist_update(playlist.id, synced_at=_now())
                    continue
                await run_import(deps, playlist.id, link, replace=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais mourir
            logger.exception("Resynchronisation automatique des playlists")
