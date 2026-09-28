from __future__ import annotations

import base64
import logging
import time
from html.parser import HTMLParser

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, ExternalPlaylist, TrackInfo
from app.providers.page_data import BROWSER_HEADERS, script_json, walk

logger = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
OEMBED_URL = "https://open.spotify.com/oembed"
TRACK_PAGE_URL = "https://open.spotify.com/track/{track_id}"
EMBED_PLAYLIST_URL = "https://open.spotify.com/embed/playlist/{playlist_id}"
# Au-delà, un import prendrait plusieurs minutes pour une playlist qu'on
# n'écoutera jamais en entier.
PLAYLIST_MAX_TRACKS = 1000

# Réponses qui disent « pas pour toi » plutôt qu'une panne : identifiants
# rejetés à l'obtention du jeton, accès interdit, quota dépassé. Depuis 2026,
# Spotify délivre bien un jeton mais répond 403 à chaque requête (« Active
# premium subscription required for the owner of the app ») quand le compte
# qui a créé l'app n'est pas Premium.
_TOKEN_REFUSALS = frozenset({400, 401, 403, 429})
_API_REFUSALS = frozenset({401, 403, 429})
# Après un refus, l'API n'est plus interrogée pendant ce délai : chaque lien
# paierait sinon une requête perdue, et un 429 s'aggraverait.
REFUSAL_COOLDOWN_SECONDS = 3600

# Horloge des délais, remplaçable dans les tests sans toucher à celle d'asyncio.
_clock = time.monotonic


class SpotifyError(Exception):
    pass


class SpotifyUnavailable(SpotifyError):
    """L'API officielle ne peut pas servir : identifiants absents ou refusés.

    Les morceaux passent alors par les données publiques (oEmbed et page du
    morceau) ; les albums et artistes, eux, n'ont pas d'équivalent public.
    """


class SpotifyNotConfigured(SpotifyUnavailable):
    pass


class SpotifyRefused(SpotifyUnavailable):
    pass


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _track_from_json(d: dict) -> TrackInfo:
    album = d.get("album") or {}
    artists = d.get("artists") or []
    images = album.get("images") or []
    cover = images[0]["url"] if images else None
    return TrackInfo(
        source="spotify",
        source_id=d["id"],
        title=d.get("name") or "Titre inconnu",
        artist=", ".join(a["name"] for a in artists) if artists else "Artiste inconnu",
        album=album.get("name"),
        year=_year_from_date(album.get("release_date")),
        duration_seconds=(d["duration_ms"] // 1000) if d.get("duration_ms") else None,
        cover_url=cover,
        artist_source_id=artists[0]["id"] if artists else None,
        album_source_id=album.get("id"),
        preview_url=d.get("preview_url") or None,
        # Deezer sait retrouver un enregistrement par son ISRC : c'est ce qui
        # rend un morceau Spotify vérifiable, Spotify ne servant plus
        # d'extrait sur une bonne partie de son catalogue.
        isrc=(d.get("external_ids") or {}).get("isrc") or None,
    )


def _album_from_json(d: dict, tracks: list[TrackInfo] | None = None) -> AlbumInfo:
    artists = d.get("artists") or []
    images = d.get("images") or []
    return AlbumInfo(
        source="spotify",
        source_id=d["id"],
        title=d.get("name") or "Album inconnu",
        artist=", ".join(a["name"] for a in artists) if artists else "Artiste inconnu",
        artist_source_id=artists[0]["id"] if artists else None,
        year=_year_from_date(d.get("release_date")),
        cover_url=images[0]["url"] if images else None,
        track_count=d.get("total_tracks"),
        duration_seconds=sum((t.duration_seconds or 0) for t in tracks) if tracks else None,
        tracks=tracks or [],
    )


class _PreviewTags(HTMLParser):
    """Balises <meta> d'aperçu d'une page (Open Graph, `music:*`).

    Ce sont celles que lisent Telegram, Discord ou Facebook pour afficher un
    lien : bien plus stables que la structure de la page elle-même.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name")
        content = (attributes.get("content") or "").strip()
        if key and content:
            self.tags.setdefault(key, []).append(content)


def _preview_tags(page: str) -> dict[str, list[str]]:
    parser = _PreviewTags()
    # Les balises d'aperçu sont dans <head> : inutile d'analyser le reste.
    parser.feed(page.split("</head>", 1)[0])
    return parser.tags


def _track_from_public_data(track_id: str, oembed: dict, tags: dict[str, list[str]]) -> TrackInfo:
    """Morceau reconstitué sans l'API : titre et pochette d'oEmbed, artistes,
    album, année et durée tirés des balises d'aperçu de la page publique.

    `og:description` vaut « Artistes · Album · Song · 2020 » : l'album n'en est
    tiré que si la description a bien cette forme.
    """

    def first(key: str) -> str | None:
        values = tags.get(key)
        return values[0] if values else None

    description = [part.strip() for part in (first("og:description") or "").split("·")]
    well_formed = len(description) == 4
    artist = first("music:musician_description") or (description[0] if well_formed else None)
    duration = first("music:duration")
    return TrackInfo(
        source="spotify",
        source_id=track_id,
        title=first("og:title") or oembed.get("title") or "Titre inconnu",
        artist=artist or "Artiste inconnu",
        album=description[1] if well_formed else None,
        year=_year_from_date(first("music:release_date")),
        duration_seconds=int(duration) if duration and duration.isdigit() else None,
        cover_url=first("og:image") or oembed.get("thumbnail_url"),
    )


def _largest_source(sources) -> str | None:
    images = [s for s in (sources or []) if isinstance(s, dict) and s.get("url")]
    if not images:
        return None
    return max(images, key=lambda s: s.get("width") or s.get("maxWidth") or 0)["url"]


def parse_embed_playlist(page: str) -> ExternalPlaylist:
    """Playlist lue dans le lecteur intégrable public de Spotify (données
    `__NEXT_DATA__` de la page) : titre, pochette et liste des morceaux, sans
    identifiants d'API. Artistes dans `subtitle` (« A, B »), durée en ms."""
    entity = None
    for document in script_json(page, script_id="__NEXT_DATA__"):
        entity = next((d for d in walk(document) if isinstance(d.get("trackList"), list)), None)
        if entity is not None:
            break
    if entity is None:
        raise SpotifyError("Spotify n'a pas renvoyé cette playlist (privée ou supprimée ?)")
    tracks = []
    for item in entity["trackList"]:
        uri = item.get("uri") or ""
        if not uri.startswith("spotify:track:"):
            continue  # épisode de podcast, fichier local...
        artist = " ".join((item.get("subtitle") or "").replace("\u00a0", " ").split())
        duration = item.get("duration")
        tracks.append(TrackInfo(
            source="spotify",
            source_id=uri.rsplit(":", 1)[-1],
            title=item.get("title") or "Titre inconnu",
            artist=artist or "Artiste inconnu",
            album=None,
            year=None,
            duration_seconds=duration // 1000 if isinstance(duration, int) and duration > 0 else None,
            cover_url=None,
            preview_url=(item.get("audioPreview") or {}).get("url") or None,
        ))
    cover = _largest_source((entity.get("coverArt") or {}).get("sources")) or _largest_source(entity.get("images"))
    return ExternalPlaylist(
        name=entity.get("name") or entity.get("title") or "Playlist Spotify",
        description=None,
        cover_url=cover,
        tracks=tracks[:PLAYLIST_MAX_TRACKS],
    )


class SpotifyClient:
    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None
        self._token: str | None = None
        self._token_expiry = 0.0
        self._refused_until = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def api_available(self) -> bool:
        """Identifiants présents, et pas de refus de l'API depuis moins d'une heure."""
        return self.is_configured and _clock() >= self._refused_until

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _refusal(self, status: int, body: str) -> SpotifyRefused:
        """Note un refus de l'API et le signale une fois par période de refus."""
        if _clock() >= self._refused_until:
            detail = " ".join(body.split())[:160]
            logger.warning(
                "API Spotify refusée (Premium exigé pour le propriétaire de l'app ?) : repli oEmbed "
                "— HTTP %s « %s », nouvel essai dans %d min",
                status, detail, REFUSAL_COOLDOWN_SECONDS // 60,
            )
        self._refused_until = _clock() + REFUSAL_COOLDOWN_SECONDS
        self._token = None
        return SpotifyRefused(f"API Spotify refusée (HTTP {status})")

    async def _ensure_token(self) -> str:
        if self._token and _clock() < self._token_expiry:
            return self._token
        creds = f"{self._client_id}:{self._client_secret}".encode()
        auth = base64.b64encode(creds).decode()
        try:
            resp = await self._client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {auth}"},
            )
        except httpx.HTTPError as exc:
            raise SpotifyError(f"Jeton Spotify indisponible : {exc}") from exc
        if resp.status_code in _TOKEN_REFUSALS:
            raise self._refusal(resp.status_code, resp.text)
        if resp.is_error:
            raise SpotifyError(f"Jeton Spotify indisponible : HTTP {resp.status_code}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = _clock() + payload.get("expires_in", 3600) - 30
        return self._token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.is_configured:
            raise SpotifyNotConfigured("Identifiants de l'API Spotify absents")
        if not self.api_available:
            raise SpotifyRefused("API Spotify refusée il y a moins d'une heure")
        for attempt in (1, 2):
            token = await self._ensure_token()
            try:
                resp = await self._client.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise SpotifyError(str(exc)) from exc
            if resp.status_code == 401 and attempt == 1:
                # Jeton expiré plus tôt que prévu : on en redemande un avant
                # de conclure à un refus.
                self._token = None
                continue
            break
        if resp.status_code in _API_REFUSALS:
            raise self._refusal(resp.status_code, resp.text)
        if resp.is_error:
            raise SpotifyError(f"API Spotify : HTTP {resp.status_code} pour {path}")
        return resp.json()

    async def get_track(self, track_id: str) -> TrackInfo:
        """Morceau Spotify : par l'API quand elle répond, sinon par les données
        publiques. Un refus de l'API ne doit jamais rendre inutilisable un lien
        de morceau, qui fonctionne très bien sans identifiants."""
        if self.api_available:
            try:
                return _track_from_json(await self._get(f"/tracks/{track_id}"))
            except SpotifyRefused:
                pass  # déjà journalisé : les données publiques prennent le relais
        return await self._get_track_via_oembed(track_id)

    async def get_album(self, album_id: str) -> AlbumInfo:
        data = await self._get(f"/albums/{album_id}")
        tracks = []
        for t in (data.get("tracks") or {}).get("items", []):
            merged = dict(t)
            merged["album"] = data
            tracks.append(_track_from_json(merged))
        return _album_from_json(data, tracks)

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        data = await self._get(f"/artists/{artist_id}")
        images = data.get("images") or []
        return ArtistInfo(
            source="spotify",
            source_id=data["id"],
            name=data.get("name") or "Artiste inconnu",
            picture_url=images[0]["url"] if images else None,
        )

    async def get_artist_top_tracks(self, artist_id: str, market: str = "FR") -> list[TrackInfo]:
        data = await self._get(f"/artists/{artist_id}/top-tracks", {"market": market})
        return [_track_from_json(t) for t in data.get("tracks", [])]

    async def get_artist_albums(self, artist_id: str) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        data = await self._get(
            f"/artists/{artist_id}/albums",
            {"include_groups": "album,single", "limit": 50},
        )
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for d in data.get("items", []):
            info = _album_from_json(d)
            if (d.get("album_group") or d.get("album_type")) == "album":
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles

    async def _get_track_via_oembed(self, track_id: str) -> TrackInfo:
        page_url = TRACK_PAGE_URL.format(track_id=track_id)
        try:
            resp = await self._client.get(OEMBED_URL, params={"url": page_url})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpotifyError(str(exc)) from exc
        return _track_from_public_data(track_id, resp.json(), await self._page_tags(page_url))

    async def _page_tags(self, page_url: str) -> dict[str, list[str]]:
        """Balises d'aperçu de la page publique du morceau.

        oEmbed ne donne que le titre et la pochette. Sans artiste, le résolveur
        ne peut pas écarter les homonymes et `preview.complete_preview` ne
        cherche pas d'extrait : la page publique comble ce manque. Si elle ne
        répond pas, on garde ce qu'oEmbed a donné.
        """
        try:
            resp = await self._client.get(page_url, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("Page publique Spotify indisponible (%s) : artiste et durée inconnus", exc)
            return {}
        return _preview_tags(resp.text)

    async def get_playlist(self, playlist_id: str) -> ExternalPlaylist:
        """Playlist publique : par l'API quand elle répond (liste complète,
        avec ISRC), sinon par le lecteur intégrable public (les 100 premiers
        titres environ, sans ISRC)."""
        if self.api_available:
            try:
                return await self._get_playlist_via_api(playlist_id)
            except SpotifyError as exc:
                # Refus, ou playlist éditoriale fermée aux nouvelles apps
                # (404) : le lecteur intégrable, lui, la sert.
                logger.info("Playlist Spotify %s via l'API impossible (%s) : lecteur intégrable", playlist_id, exc)
        try:
            resp = await self._client.get(
                EMBED_PLAYLIST_URL.format(playlist_id=playlist_id),
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise SpotifyError(f"Spotify injoignable : {exc}") from exc
        if resp.status_code == 404:
            raise SpotifyError("Playlist Spotify introuvable (privée ou supprimée ?)")
        if resp.is_error:
            raise SpotifyError(f"Spotify : HTTP {resp.status_code}")
        return parse_embed_playlist(resp.text)

    async def _get_playlist_via_api(self, playlist_id: str) -> ExternalPlaylist:
        meta = await self._get(f"/playlists/{playlist_id}", {"fields": "name,description,images"})
        tracks: list[TrackInfo] = []
        offset = 0
        while len(tracks) < PLAYLIST_MAX_TRACKS:
            page = await self._get(f"/playlists/{playlist_id}/tracks", {"limit": 100, "offset": offset})
            items = page.get("items") or []
            for item in items:
                track = item.get("track") or {}
                if track.get("type", "track") != "track" or not track.get("id") or item.get("is_local"):
                    continue
                tracks.append(_track_from_json(track))
            if not page.get("next") or not items:
                break
            offset += len(items)
        images = meta.get("images") or []
        return ExternalPlaylist(
            name=meta.get("name") or "Playlist Spotify",
            description=meta.get("description") or None,
            cover_url=images[0]["url"] if images else None,
            tracks=tracks[:PLAYLIST_MAX_TRACKS],
        )
