from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import unquote

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, ExternalPlaylist, TrackInfo
from app.providers.page_data import BROWSER_HEADERS, meta_content, script_json, walk

logger = logging.getLogger(__name__)

LOOKUP_URL = "https://itunes.apple.com/lookup"
SEARCH_URL = "https://itunes.apple.com/search"
# API du lecteur web d'Apple Music : la page publique d'une playlist ne
# contient que ses 300 premiers titres, la suite se charge par là.
WEB_ORIGIN = "https://music.apple.com"
MEDIA_API = "https://amp-api.music.apple.com"
# Jeton « développeur » du lecteur web, embarqué dans son code JavaScript
# (un JWT ES256 : son en-tête encodé commence toujours par « eyJh »).
_TOKEN_RE = re.compile(r"eyJh[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+\.js)["']""", re.I)
_PLAYLIST_ID_RE = re.compile(r"/(pl\.[A-Za-z0-9._-]+)")
TOKEN_TTL_SECONDS = 12 * 3600


class AppleMusicError(Exception):
    pass


def _upsize_artwork(url: str | None, size: int = 1000) -> str | None:
    if not url:
        return None
    return re.sub(r"/\d+x\d+bb\.", f"/{size}x{size}bb.", url)


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _track_from_json(d: dict) -> TrackInfo:
    return TrackInfo(
        source="apple",
        source_id=str(d["trackId"]),
        title=d.get("trackName") or "Titre inconnu",
        artist=d.get("artistName") or "Artiste inconnu",
        album=d.get("collectionName"),
        year=_year_from_date(d.get("releaseDate")),
        duration_seconds=(d["trackTimeMillis"] // 1000) if d.get("trackTimeMillis") else None,
        cover_url=_upsize_artwork(d.get("artworkUrl100")),
        artist_source_id=str(d["artistId"]) if d.get("artistId") else None,
        album_source_id=str(d["collectionId"]) if d.get("collectionId") else None,
        preview_url=d.get("previewUrl") or None,
    )


_SONG_URL_RE = re.compile(r"music\.apple\.com/[a-z]{2}/song/(?:[^/\"?\s]+/)?(\d+)")
_DIGITS_RE = re.compile(r"(\d{5,})")
PLAYLIST_MAX_TRACKS = 1000


def _artwork_template(artwork) -> str | None:
    """`{"dictionary": {"url": ".../{w}x{h}bb.{f}"}}` (ou `{"url": ...}`) →
    URL en 1000 px."""
    if not isinstance(artwork, dict):
        return None
    url = (artwork.get("dictionary") or {}).get("url") or artwork.get("url")
    if not url:
        return None
    return url.replace("{w}", "1000").replace("{h}", "1000").replace("{c}", "bb").replace("{f}", "jpg")


def _song_id(lockup: dict) -> str | None:
    descriptor = lockup.get("contentDescriptor") or {}
    identifiers = descriptor.get("identifiers") or {}
    for value in (identifiers.get("storeAdamID"), identifiers.get("storeAdamId")):
        if value:
            return str(value)
    for value in (descriptor.get("url"), lockup.get("url")):
        if isinstance(value, str):
            m = re.search(r"(?:[?&]i=|/)(\d{5,})(?:$|[?&#])", value)
            if m:
                return m.group(1)
    return None


def _track_from_lockup(lockup: dict) -> TrackInfo | None:
    title = lockup.get("title")
    artist = lockup.get("artistName")
    if not artist:
        links = lockup.get("subtitleLinks") or []
        artist = ", ".join(link.get("title") for link in links if isinstance(link, dict) and link.get("title"))
    if not isinstance(title, str) or not artist:
        return None
    albums = [link.get("title") for link in (lockup.get("tertiaryLinks") or []) if isinstance(link, dict)]
    duration = lockup.get("duration")
    song_id = _song_id(lockup)
    return TrackInfo(
        source="apple",
        source_id=song_id or "",
        title=title,
        artist=artist,
        album=albums[0] if albums else None,
        year=None,
        duration_seconds=duration // 1000 if isinstance(duration, int) and duration > 0 else None,
        cover_url=_artwork_template(lockup.get("artwork")),
    )


def _playlist_name(page: str) -> str:
    name = meta_content(page, "apple:title") or meta_content(page, "og:title") or "Playlist Apple Music"
    # « Nom - Playlist - Apple Music » / « Nom sur Apple Music »
    name = re.sub(r"\s+(?:sur|on|en)\s+Apple\s+Music\s*$", "", name, flags=re.I)
    name = re.sub(r"\s+[-–—|]\s+(?:Playlist\s+[-–—|]\s+)?Apple\s+Music\s*$", "", name, flags=re.I)
    return name.strip() or "Playlist Apple Music"


def parse_playlist_page(page: str) -> tuple[ExternalPlaylist, list[str]]:
    """Playlist lue dans la page publique d'Apple Music.

    Les morceaux viennent des données embarquées (`serialized-server-data`,
    lignes « trackLockup » : titre, artiste, durée, pochette). Si la page
    change de forme, on se rabat sur les identifiants de morceaux qu'elle
    cite (données structurées schema.org ou liens) : renvoyés à part, pour
    être complétés par l'API de recherche iTunes.
    """
    tracks: list[TrackInfo] = []
    for document in script_json(page, script_id="serialized-server-data"):
        sections = [
            d for d in walk(document)
            if d.get("itemKind") == "trackLockup" and isinstance(d.get("items"), list)
        ]
        lockups = [item for section in sections for item in section["items"] if isinstance(item, dict)]
        if not lockups:
            # Forme inconnue : toute ligne qui a un titre, un artiste et une durée.
            lockups = [
                d for d in walk(document)
                if isinstance(d.get("title"), str) and isinstance(d.get("artistName"), str)
                and ("duration" in d or "contentDescriptor" in d)
            ]
        tracks = [t for t in (_track_from_lockup(item) for item in lockups) if t]
        if tracks:
            break

    ids: list[str] = []
    if not tracks:
        for document in script_json(page, script_type="application/ld+json"):
            for d in walk(document):
                if d.get("@type") == "MusicRecording" and isinstance(d.get("url"), str):
                    m = _DIGITS_RE.findall(d["url"])
                    if m:
                        ids.append(m[-1])
        if not ids:
            ids = _SONG_URL_RE.findall(page)
        ids = list(dict.fromkeys(ids))

    playlist = ExternalPlaylist(
        name=_playlist_name(page),
        description=meta_content(page, "og:description"),
        cover_url=meta_content(page, "og:image"),
        tracks=tracks[:PLAYLIST_MAX_TRACKS],
    )
    return playlist, ids[:PLAYLIST_MAX_TRACKS]


def _track_from_media_api(item: dict) -> TrackInfo | None:
    """Morceau de l'API du lecteur web (`/v1/catalog/.../tracks`)."""
    attributes = item.get("attributes") or {}
    if item.get("type", "songs") != "songs" or not attributes.get("name") or not item.get("id"):
        return None
    duration = attributes.get("durationInMillis")
    return TrackInfo(
        source="apple",
        source_id=str(item["id"]),
        title=attributes["name"],
        artist=attributes.get("artistName") or "Artiste inconnu",
        album=attributes.get("albumName"),
        year=_year_from_date(attributes.get("releaseDate")),
        duration_seconds=duration // 1000 if isinstance(duration, int) and duration > 0 else None,
        cover_url=_artwork_template(attributes.get("artwork")),
        isrc=attributes.get("isrc") or None,
    )


def _token_from_page(page: str) -> str | None:
    """Ancienne version du lecteur web : le jeton est dans une balise
    <meta name="desktop-music-app/config/environment"> (JSON encodé URL)."""
    raw = meta_content(page, "desktop-music-app/config/environment")
    if not raw:
        return None
    try:
        return ((json.loads(unquote(raw)).get("MEDIA_API") or {}).get("token")) or None
    except ValueError:
        return None


class AppleMusicClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None
        self._web_token: str | None = None
        self._web_token_expiry = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _lookup(self, params: dict) -> list[dict]:
        try:
            resp = await self._client.get(LOOKUP_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppleMusicError(str(exc)) from exc
        return resp.json().get("results", [])

    async def search_tracks(self, query: str, limit: int = 25) -> list[TrackInfo]:
        """Recherche de morceaux via l'API iTunes Search.

        Sert de source de secours quand Deezer ne répond pas ou ne connaît
        pas le morceau. L'API n'a pas de décalage (`offset`) : on ramène un
        lot une fois pour toutes et l'appelant pagine dedans.
        """
        try:
            resp = await self._client.get(
                SEARCH_URL,
                params={"term": query, "entity": "song", "media": "music", "limit": limit},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppleMusicError(str(exc)) from exc
        results = resp.json().get("results", [])
        return [_track_from_json(r) for r in results if r.get("trackId")]

    async def get_track(self, track_id: str) -> TrackInfo:
        results = await self._lookup({"id": track_id, "entity": "song"})
        for r in results:
            if str(r.get("trackId")) == str(track_id):
                return _track_from_json(r)
        raise AppleMusicError("Morceau introuvable sur Apple Music.")

    async def get_album(self, album_id: str) -> AlbumInfo:
        results = await self._lookup({"id": album_id, "entity": "song"})
        if not results:
            raise AppleMusicError("Album introuvable sur Apple Music.")
        collection = next((r for r in results if r.get("wrapperType") == "collection"), None)
        songs = [r for r in results if r.get("wrapperType") == "track"]
        tracks = [_track_from_json(s) for s in songs]
        if collection:
            return AlbumInfo(
                source="apple",
                source_id=str(collection["collectionId"]),
                title=collection.get("collectionName") or "Album inconnu",
                artist=collection.get("artistName") or "Artiste inconnu",
                artist_source_id=str(collection["artistId"]) if collection.get("artistId") else None,
                year=_year_from_date(collection.get("releaseDate")),
                cover_url=_upsize_artwork(collection.get("artworkUrl100")),
                track_count=collection.get("trackCount"),
                duration_seconds=sum((t.duration_seconds or 0) for t in tracks) or None,
                tracks=tracks,
            )
        first = tracks[0]
        return AlbumInfo(
            source="apple",
            source_id=str(album_id),
            title=first.album or "Album inconnu",
            artist=first.artist,
            artist_source_id=first.artist_source_id,
            year=first.year,
            cover_url=first.cover_url,
            track_count=len(tracks),
            duration_seconds=sum((t.duration_seconds or 0) for t in tracks) or None,
            tracks=tracks,
        )

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        results = await self._lookup({"id": artist_id, "entity": "song", "limit": 1})
        if not results:
            raise AppleMusicError("Artiste introuvable sur Apple Music.")
        artist = results[0]
        return ArtistInfo(
            source="apple",
            source_id=str(artist_id),
            name=artist.get("artistName") or "Artiste inconnu",
            picture_url=None,
        )

    async def get_artist_top_tracks(self, artist_id: str, limit: int = 25) -> list[TrackInfo]:
        results = await self._lookup({"id": artist_id, "entity": "song", "limit": limit})
        return [_track_from_json(r) for r in results if r.get("wrapperType") == "track"]

    async def get_artist_albums(self, artist_id: str) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        results = await self._lookup({"id": artist_id, "entity": "album", "limit": 100})
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for r in results:
            if r.get("wrapperType") != "collection":
                continue
            info = AlbumInfo(
                source="apple",
                source_id=str(r["collectionId"]),
                title=r.get("collectionName") or "Album inconnu",
                artist=r.get("artistName") or "Artiste inconnu",
                artist_source_id=str(artist_id),
                year=_year_from_date(r.get("releaseDate")),
                cover_url=_upsize_artwork(r.get("artworkUrl100")),
                track_count=r.get("trackCount"),
                duration_seconds=None,
            )
            track_count = r.get("trackCount") or 0
            if (r.get("collectionType") or "").lower() == "album" and track_count > 3:
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles

    async def lookup_tracks(self, track_ids: list[str], country: str = "fr") -> list[TrackInfo]:
        """Morceaux par identifiants, dans l'ordre demandé (lots de 150)."""
        found: dict[str, TrackInfo] = {}
        for start in range(0, len(track_ids), 150):
            chunk = track_ids[start:start + 150]
            results = await self._lookup({"id": ",".join(chunk), "country": country, "entity": "song"})
            for r in results:
                if r.get("wrapperType") == "track" and r.get("trackId"):
                    found[str(r["trackId"])] = _track_from_json(r)
        return [found[i] for i in track_ids if i in found]

    async def get_playlist(self, url: str) -> ExternalPlaylist:
        """Playlist publique Apple Music, depuis l'URL de sa page."""
        try:
            resp = await self._client.get(url, headers=BROWSER_HEADERS, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise AppleMusicError(f"Apple Music injoignable : {exc}") from exc
        if resp.status_code == 404:
            raise AppleMusicError("Playlist Apple Music introuvable (privée ou supprimée ?)")
        if resp.is_error:
            raise AppleMusicError(f"Apple Music : HTTP {resp.status_code}")
        page = resp.text
        playlist, ids = parse_playlist_page(page)
        # Liste complète (au-delà des 300 titres de la page, avec les ISRC)
        # par l'API du lecteur web ; la page reste le repli si elle change.
        try:
            full = await self._playlist_tracks_via_web_api(url, page)
        except (AppleMusicError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Playlist Apple Music via l'API du lecteur web impossible (%s) : page seule", exc)
            full = []
            if len(playlist.tracks) >= 300:
                # La page s'arrête à 300 titres : la suite n'a pas pu être lue.
                playlist.note = f"Apple Music n'a donné que les {len(playlist.tracks)} premiers titres ({exc})."
        if len(full) >= len(playlist.tracks):
            playlist.tracks = full
        if not playlist.tracks and ids:
            country = re.search(r"music\.apple\.com/([a-z]{2})/", url)
            playlist.tracks = await self.lookup_tracks(ids, country.group(1) if country else "fr")
        if not playlist.tracks:
            raise AppleMusicError(
                "Aucun morceau lisible sur cette page Apple Music (playlist privée ? "
                "Partage-la en public depuis Musique)."
            )
        return playlist

    async def _web_api_token(self, page: str) -> str:
        if self._web_token and time.monotonic() < self._web_token_expiry:
            return self._web_token
        token = _token_from_page(page)
        if not token:
            scripts = [src for src in _SCRIPT_SRC_RE.findall(page) if "/assets/" in src]
            # Le jeton est dans le script principal (« index… ») : on commence par lui.
            scripts.sort(key=lambda src: 0 if "index" in src else 1)
            for src in scripts[:6]:
                script_url = src if src.startswith("http") else f"{WEB_ORIGIN}{src}"
                try:
                    resp = await self._client.get(script_url, headers=BROWSER_HEADERS)
                except httpx.HTTPError:
                    continue
                match = _TOKEN_RE.search(resp.text) if resp.is_success else None
                if match:
                    token = match.group(0)
                    break
        if not token:
            raise AppleMusicError("jeton du lecteur web introuvable")
        self._web_token = token
        self._web_token_expiry = time.monotonic() + TOKEN_TTL_SECONDS
        return token

    async def _playlist_tracks_via_web_api(self, url: str, page: str) -> list[TrackInfo]:
        playlist_id = _PLAYLIST_ID_RE.search(url)
        storefront = re.search(r"music\.apple\.com/([a-z]{2})/", url)
        if not playlist_id or not storefront:
            raise AppleMusicError("identifiant de playlist absent du lien")
        token = await self._web_api_token(page)
        headers = {
            **BROWSER_HEADERS,
            "Authorization": f"Bearer {token}",
            "Origin": WEB_ORIGIN,
            "Referer": f"{WEB_ORIGIN}/",
        }
        next_url: str | None = (
            f"{MEDIA_API}/v1/catalog/{storefront.group(1)}/playlists/{playlist_id.group(1)}/tracks?limit=100"
        )
        tracks: list[TrackInfo] = []
        while next_url and len(tracks) < PLAYLIST_MAX_TRACKS:
            try:
                resp = await self._client.get(next_url, headers=headers)
            except httpx.HTTPError as exc:
                raise AppleMusicError(str(exc)) from exc
            if resp.status_code in (401, 403):
                self._web_token = None  # jeton renouvelé par Apple : on le relira
                raise AppleMusicError(f"jeton refusé (HTTP {resp.status_code})")
            if resp.is_error:
                raise AppleMusicError(f"HTTP {resp.status_code}")
            data = resp.json()
            items = data.get("data") or []
            tracks += [t for t in (_track_from_media_api(item) for item in items) if t]
            following = data.get("next")
            if not items or not following:
                break
            next_url = following if following.startswith("http") else f"{MEDIA_API}{following}"
            if "limit=" not in next_url:
                next_url += ("&" if "?" in next_url else "?") + "limit=100"
        return tracks[:PLAYLIST_MAX_TRACKS]
