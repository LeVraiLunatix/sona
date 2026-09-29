from __future__ import annotations

import logging
import unicodedata

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, ExternalPlaylist, TrackInfo

logger = logging.getLogger(__name__)

API_BASE = "https://api.deezer.com"
# Morceaux ramenés d'un coup pour une recherche chez un artiste : le lot est
# filtré par artiste puis paginé. 100 est le maximum par requête chez Deezer.
ARTIST_SEARCH_POOL = 100


def _artist_key(name: str) -> str:
    """Nom d'artiste comparable, sans casse, accents, espaces ni ponctuation :
    « Céline Dion » = « celine dion », « AC/DC » = « ACDC »."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


class DeezerError(Exception):
    pass


def _error_message(error) -> str:
    """`{"type": "…", "message": "Missing parameters: q", "code": 501}` →
    « Deezer : Missing parameters: q (code 501) ». Le dict brut remontait
    tel quel jusqu'à l'écran de l'app."""
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or "erreur inconnue"
        code = error.get("code")
        return f"Deezer : {message}" + (f" (code {code})" if code is not None else "")
    return f"Deezer : {error}"


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _largest_image(d: dict, prefix: str) -> str | None:
    """Plus grande version disponible (`_xl` = 1000 px). La 250 px (`_medium`)
    était pixelisée une fois affichée en grand dans Telegram."""
    return d.get(f"{prefix}_xl") or d.get(f"{prefix}_big") or d.get(f"{prefix}_medium")


def _track_from_json(d: dict) -> TrackInfo:
    album = d.get("album") or {}
    artist = d.get("artist") or {}
    return TrackInfo(
        source="deezer",
        source_id=str(d["id"]),
        title=d.get("title") or d.get("title_short") or "Titre inconnu",
        artist=artist.get("name") or "Artiste inconnu",
        album=album.get("title"),
        year=_year_from_date(album.get("release_date") or d.get("release_date")),
        duration_seconds=d.get("duration"),
        cover_url=_largest_image(album, "cover"),
        artist_source_id=str(artist["id"]) if artist.get("id") else None,
        album_source_id=str(album["id"]) if album.get("id") else None,
        preview_url=d.get("preview") or None,
        isrc=d.get("isrc") or None,
        bpm=float(d["bpm"]) if isinstance(d.get("bpm"), (int, float)) and d["bpm"] > 0 else None,
    )


def _album_from_json(d: dict, tracks: list[TrackInfo] | None = None) -> AlbumInfo:
    artist = d.get("artist") or {}
    return AlbumInfo(
        source="deezer",
        source_id=str(d["id"]),
        title=d.get("title") or "Album inconnu",
        artist=artist.get("name") or "Artiste inconnu",
        artist_source_id=str(artist["id"]) if artist.get("id") else None,
        year=_year_from_date(d.get("release_date")),
        cover_url=_largest_image(d, "cover"),
        track_count=d.get("nb_tracks"),
        duration_seconds=d.get("duration"),
        tracks=tracks or [],
        release_date=d.get("release_date"),
        record_type=d.get("record_type"),
    )


def _artist_from_json(d: dict) -> ArtistInfo:
    return ArtistInfo(
        source="deezer",
        source_id=str(d["id"]),
        name=d.get("name") or "Artiste inconnu",
        picture_url=_largest_image(d, "picture"),
        fans=d.get("nb_fan"),
    )


class DeezerClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = await self._client.get(f"{API_BASE}{path}", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeezerError(str(exc)) from exc
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise DeezerError(_error_message(data["error"]))
        return data

    async def search_tracks(
        self, query: str, index: int = 0, limit: int = 25, order: str | None = None
    ) -> tuple[list[TrackInfo], int]:
        """`order="RANKING"` : les titres les plus écoutés d'abord (recherche
        de l'app) ; par défaut, l'ordre de pertinence de Deezer."""
        params = {"q": query, "index": index, "limit": limit}
        if order:
            params["order"] = order
        data = await self._get("/search/track", params)
        items = [_track_from_json(d) for d in data.get("data", [])]
        total = data.get("total", len(items))
        return items, total

    async def search_tracks_by_artist(
        self, artist_name: str, query: str, index: int = 0, limit: int = 25, order: str | None = None
    ) -> tuple[list[TrackInfo], int]:
        """Morceaux de `artist_name` correspondant à `query`.

        Deezer ne répond plus à sa syntaxe avancée `artist:"…"` (zéro résultat,
        ou des morceaux d'autres artistes, en septembre 2026). On fait donc une
        recherche simple « artiste requête » et on ne garde que les morceaux
        dont l'artiste principal est bien celui demandé. Le `total` de Deezer
        ne vaut plus une fois le lot filtré : la pagination se fait dans le lot.
        """
        params = {"q": f"{artist_name} {query}".strip(), "limit": ARTIST_SEARCH_POOL}
        if order:
            params["order"] = order
        data = await self._get("/search/track", params)
        wanted = _artist_key(artist_name)
        tracks = [_track_from_json(d) for d in data.get("data", [])]
        mine = [t for t in tracks if wanted and _artist_key(t.artist) == wanted]
        return mine[index : index + limit], len(mine)

    async def get_track(self, track_id: str) -> TrackInfo:
        data = await self._get(f"/track/{track_id}")
        return _track_from_json(data)

    async def get_album(self, album_id: str) -> AlbumInfo:
        data = await self._get(f"/album/{album_id}")
        tracks = []
        for t in (data.get("tracks") or {}).get("data", []):
            # Les morceaux imbriqués dans /album/<id> n'ont pas d'objet album complet.
            merged = dict(t)
            merged["album"] = {
                "id": data.get("id"),
                "title": data.get("title"),
                "cover_medium": data.get("cover_medium"),
                "cover_big": data.get("cover_big"),
                "cover_xl": data.get("cover_xl"),
                "release_date": data.get("release_date"),
            }
            tracks.append(_track_from_json(merged))
        return _album_from_json(data, tracks)

    async def get_playlist(self, playlist_id: str) -> AlbumInfo:
        """Playlist Deezer, présentée comme un album.

        Une playlist n'a pas d'artiste : c'est son créateur qui tient ce rôle
        à l'écran. Ses morceaux, eux, portent chacun leur propre album — ils
        sont donc lus tels quels, sans recoller la pochette de la playlist.
        """
        data = await self._get(f"/playlist/{playlist_id}")
        tracks = [_track_from_json(t) for t in (data.get("tracks") or {}).get("data", [])]
        creator = (data.get("creator") or {}).get("name") or "Playlist"
        return AlbumInfo(
            source="deezer",
            source_id=str(data["id"]),
            title=data.get("title") or "Playlist",
            artist=creator,
            artist_source_id=None,
            year=None,
            cover_url=_largest_image(data, "picture"),
            track_count=data.get("nb_tracks") or len(tracks),
            duration_seconds=data.get("duration"),
            tracks=tracks,
        )

    async def get_playlist_for_import(self, playlist_id: str, max_tracks: int = 1000) -> ExternalPlaylist:
        """Playlist complète (au-delà des ~400 titres de `/playlist/{id}`),
        page par page."""
        data = await self._get(f"/playlist/{playlist_id}")
        tracks: list[TrackInfo] = []
        index = 0
        while len(tracks) < max_tracks:
            page = await self._get(f"/playlist/{playlist_id}/tracks", {"index": index, "limit": 100})
            items = page.get("data") or []
            tracks += [_track_from_json(t) for t in items if t.get("id")]
            if not items or not page.get("next"):
                break
            index += len(items)
        return ExternalPlaylist(
            name=data.get("title") or "Playlist Deezer",
            description=data.get("description") or None,
            cover_url=_largest_image(data, "picture"),
            tracks=tracks[:max_tracks],
        )

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        data = await self._get(f"/artist/{artist_id}")
        return _artist_from_json(data)

    async def get_artist_top_tracks(
        self, artist_id: str, limit: int = 25
    ) -> list[TrackInfo]:
        data = await self._get(f"/artist/{artist_id}/top", {"limit": limit})
        return [_track_from_json(d) for d in data.get("data", [])]

    async def get_artist_albums(
        self, artist_id: str
    ) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        """Retourne (albums, singles_et_eps)."""
        data = await self._get(f"/artist/{artist_id}/albums", {"limit": 100})
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for d in data.get("data", []):
            info = _album_from_json(d)
            if (d.get("record_type") or "").lower() == "album":
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles

    async def search_artists(self, query: str, limit: int = 10) -> list[ArtistInfo]:
        """Recherche d'artistes — tolérante aux fautes côté Deezer
        (« eiak » → Ziak), contrairement à la recherche de morceaux."""
        data = await self._get("/search/artist", {"q": query, "limit": limit})
        return [_artist_from_json(d) for d in data.get("data", [])]

    async def search_albums(self, query: str, limit: int = 10) -> list[AlbumInfo]:
        data = await self._get("/search/album", {"q": query, "limit": limit})
        return [_album_from_json(d) for d in data.get("data", [])]

    async def get_related_artists(self, artist_id: str, limit: int = 20) -> list[ArtistInfo]:
        data = await self._get(f"/artist/{artist_id}/related", {"limit": limit})
        return [_artist_from_json(d) for d in data.get("data", [])]

    async def get_artist_radio(self, artist_id: str, limit: int = 25) -> list[TrackInfo]:
        """« Mix » de l'artiste : ses titres et ceux d'artistes proches. Deezer
        en renvoie un nouveau tirage à chaque appel — de quoi alimenter une
        station sans fin."""
        data = await self._get(f"/artist/{artist_id}/radio", {"limit": limit})
        return [_track_from_json(d) for d in data.get("data", [])]

    async def get_chart_tracks(self, limit: int = 50) -> list[TrackInfo]:
        """Titres du moment (classement Deezer)."""
        data = await self._get("/chart/0/tracks", {"limit": limit})
        return [_track_from_json(d) for d in data.get("data", [])]

    async def get_radio_tracks(self, radio_id: str, limit: int = 25) -> list[TrackInfo]:
        data = await self._get(f"/radio/{radio_id}/tracks", {"limit": limit})
        return [_track_from_json(d) for d in data.get("data", [])]

    async def get_track_by_isrc(self, isrc: str) -> TrackInfo | None:
        """Morceau portant ce code ISRC, ou None s'il n'est pas au catalogue.

        L'ISRC identifie l'enregistrement, pas le titre : c'est le seul moyen
        sûr de retrouver sur Deezer exactement le morceau ouvert ailleurs.
        """
        try:
            data = await self._get(f"/track/isrc:{isrc}")
        except DeezerError as exc:
            # Deezer répond « no data » quand l'ISRC est absent du catalogue :
            # ce n'est pas une panne, c'est une réponse.
            logger.info("Aucun morceau Deezer pour l'ISRC %s : %s", isrc, exc)
            return None
        return _track_from_json(data) if data.get("id") else None

    async def get_track_by_isrc_hint(self, title: str, artist: str) -> TrackInfo | None:
        items, _ = await self.search_tracks(f'"{title}" "{artist}"', limit=1)
        return items[0] if items else None
