"""Vidéos animées d'Apple Music (pochettes d'albums et portraits d'artistes en
boucle), lues par l'API du lecteur web music.apple.com avec le jeton public
embarqué dans son code JavaScript — le même que celui du site, aucun compte.

Les boucles sont des flux HLS sans piste audio. Seule une partie des albums et
des artistes en ont une : sans vidéo, la réponse est « rien » et l'app garde la
pochette fixe. Réponses (y compris « rien ») gardées 24 h en mémoire ; en cas de
panne rien n'est mémorisé."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import unicodedata

import httpx

from app.providers.page_data import BROWSER_HEADERS

logger = logging.getLogger(__name__)

WEB_ORIGIN = "https://music.apple.com"
MEDIA_API = "https://amp-api.music.apple.com"
STOREFRONT = "fr"
CACHE_TTL = 24 * 3600
TOKEN_MAX_AGE = 12 * 3600
# Le jeton du lecteur web (JWT) : trois sont embarqués, celui du lecteur a
# `iss = AMPWebPlay`. L'en-tête encodé commence par « eyJ » (pas « eyJh »).
_TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_INDEX_RE = re.compile(r"""(?:src|href)=["'](/assets/index[^"']*\.js)["']""", re.I)
# Suffixes d'édition à ignorer pour comparer des titres d'album.
_EDITION_RE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]|\s+-\s+(single|ep)\s*$", re.IGNORECASE)

_cache: dict[str, tuple[float, dict | None]] = {}
_token: tuple[str, float] | None = None
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15, follow_redirects=True)
    return _client


def reset() -> None:
    global _token
    _cache.clear()
    _token = None


def _key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def _album_key(title: str) -> str:
    return _key(_EDITION_RE.sub("", title))


def pick_token(script: str, now: float | None = None) -> tuple[str, float] | None:
    """Le jeton du lecteur web (`iss = AMPWebPlay`, pas expiré) dans un script,
    avec son échéance (secondes epoch)."""
    now = time.time() if now is None else now
    for candidate in _TOKEN_RE.findall(script):
        try:
            part = candidate.split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        except ValueError:
            continue
        if payload.get("iss") == "AMPWebPlay" and float(payload.get("exp", 0)) > now + 300:
            return candidate, float(payload["exp"])
    return None


async def _web_token(force: bool = False) -> str:
    global _token
    if not force and _token and _token[1] > time.monotonic():
        return _token[0]
    page = await _http().get(f"{WEB_ORIGIN}/{STOREFRONT}/new", headers=BROWSER_HEADERS)
    page.raise_for_status()
    for src in _INDEX_RE.findall(page.text):
        script = await _http().get(f"{WEB_ORIGIN}{src}", headers=BROWSER_HEADERS)
        picked = pick_token(script.text) if script.is_success else None
        if picked:
            token, expiry = picked
            life = min(TOKEN_MAX_AGE, expiry - time.time() - 300)
            _token = (token, time.monotonic() + life)
            return token
    raise httpx.HTTPError("jeton du lecteur web Apple Music introuvable")


async def _get(path: str, params: dict) -> dict:
    """GET sur l'API du lecteur web ; jeton relu une fois s'il est refusé."""
    for attempt in (0, 1):
        headers = {
            **BROWSER_HEADERS,
            "Authorization": f"Bearer {await _web_token(force=attempt == 1)}",
            "Origin": WEB_ORIGIN,
            "Referer": f"{WEB_ORIGIN}/",
        }
        resp = await _http().get(f"{MEDIA_API}/v1/catalog/{STOREFRONT}/{path}", params=params, headers=headers)
        if resp.status_code in (401, 403) and attempt == 0:
            continue
        resp.raise_for_status()
        return resp.json()
    raise httpx.HTTPError("jeton refusé")  # pragma: no cover


def _video(video: dict | None) -> str | None:
    url = (video or {}).get("video")
    return url if isinstance(url, str) and url.startswith("https://") else None


def logo_url(artwork: dict | None) -> str | None:
    """Logo de l'artiste (PNG transparent, dans la couleur de la marque), s'il
    en a un. Un logo sombre est écarté : il disparaîtrait sur le fond noir."""
    art = (artwork or {}).get("musicContentColorLogoTrimmed") or {}
    url, width, height = art.get("url"), art.get("width"), art.get("height")
    if not (isinstance(url, str) and url.startswith("https://") and isinstance(width, int) and isinstance(height, int)):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        red, green, blue = (int(art.get("bgColor", "")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    if 0.2126 * red + 0.7152 * green + 0.0722 * blue < 0.2:
        return None
    wide = 1200
    url = url.replace("{w}", str(wide)).replace("{h}", str(max(1, round(wide * height / width)))).replace("{f}", "png")
    return re.sub(r"\.jpe?g$", ".png", url)


def pick_artist(results: list[dict], name: str) -> str | None:
    """Identifiant du résultat dont le nom est celui de l'artiste (jamais un
    homonyme approximatif : mieux vaut pas de vidéo que celle d'un autre)."""
    wanted = _key(name)
    for item in results:
        if _key((item.get("attributes") or {}).get("name") or "") == wanted:
            return item.get("id")
    return None


def pick_album(results: list[dict], title: str, artist: str) -> str | None:
    wanted_title, wanted_artist = _album_key(title), _key(artist)
    for item in results:
        attrs = item.get("attributes") or {}
        if _album_key(attrs.get("name") or "") == wanted_title and wanted_artist in _key(attrs.get("artistName") or ""):
            return item.get("id")
    return None


async def _cached(key: str, fetch) -> dict | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        found = await fetch()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.info("Vidéo Apple Music indisponible (%s) : %s", key, exc)
        return None  # panne : pas gardée, on réessaiera
    _cache[key] = (time.monotonic() + CACHE_TTL, found)
    return found


async def artist_motion(name: str) -> dict | None:
    """`{"square", "wide", "logo"}` (chacun peut manquer) : portrait animé et
    logo de l'artiste."""

    async def fetch() -> dict | None:
        search = await _get("search", {"term": name, "types": "artists", "limit": 5})
        artist_id = pick_artist(((search.get("results") or {}).get("artists") or {}).get("data") or [], name)
        if not artist_id:
            return None
        data = (await _get(f"artists/{artist_id}", {"extend": "editorialVideo,editorialArtwork"}))["data"][0]
        attrs = data.get("attributes") or {}
        video = attrs.get("editorialVideo") or {}
        square, wide = _video(video.get("motionArtistSquare1x1")), _video(video.get("motionArtistWide16x9"))
        logo = logo_url(attrs.get("editorialArtwork"))
        return {"square": square, "wide": wide, "logo": logo} if square or wide or logo else None

    return await _cached(f"artist:{_key(name)}", fetch)


async def album_motion(title: str, artist: str) -> dict | None:
    """`{"tall": url|None, "square": url|None}` : pochette animée de l'album."""

    async def fetch() -> dict | None:
        search = await _get("search", {"term": f"{title} {artist}", "types": "albums", "limit": 5})
        album_id = pick_album(((search.get("results") or {}).get("albums") or {}).get("data") or [], title, artist)
        if not album_id:
            return None
        data = (await _get(f"albums/{album_id}", {"extend": "editorialVideo"}))["data"][0]
        video = (data.get("attributes") or {}).get("editorialVideo") or {}
        tall, square = _video(video.get("motionTallVideo3x4")), _video(video.get("motionSquareVideo1x1"))
        return {"tall": tall, "square": square} if tall or square else None

    return await _cached(f"album:{_album_key(title)}:{_key(artist)}", fetch)
