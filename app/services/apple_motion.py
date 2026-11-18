"""Vidéos animées d'Apple Music (pochettes d'albums et portraits d'artistes en
boucle), lues par l'API du lecteur web music.apple.com avec le jeton public
embarqué dans son code JavaScript — le même que celui du site, aucun compte.

Les boucles sont des flux HLS sans piste audio. Seule une partie des albums et
des artistes en ont une : sans vidéo, la réponse est « rien » et l'app garde la
pochette fixe. Réponses (y compris « rien ») gardées 24 h en mémoire ; en cas de
panne rien n'est mémorisé."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import httpx

from app.providers.page_data import BROWSER_HEADERS

logger = logging.getLogger(__name__)

WEB_ORIGIN = "https://music.apple.com"
MEDIA_API = "https://amp-api.music.apple.com"
STOREFRONT = "fr"
CACHE_TTL = 24 * 3600
TOKEN_MAX_AGE = 12 * 3600
# Luminance (0-1) sous laquelle un logo se perd sur le fond noir (le rouge pur, 0,21, passe).
DARK_LOGO = 0.08
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
    """URL du logo de l'artiste (PNG transparent), s'il en a un."""
    art = (artwork or {}).get("musicContentColorLogoTrimmed") or {}
    url, width, height = art.get("url"), art.get("width"), art.get("height")
    if not (isinstance(url, str) and url.startswith("https://") and isinstance(width, int) and isinstance(height, int)):
        return None
    if width <= 0 or height <= 0:
        return None
    wide = 1200
    url = url.replace("{w}", str(wide)).replace("{h}", str(max(1, round(wide * height / width)))).replace("{f}", "png")
    return re.sub(r"\.jpe?g$", ".png", url)


def average_color(png: bytes) -> str | None:
    """Couleur moyenne (hexadécimale) des pixels opaques d'un PNG : celle du
    logo. `bgColor` d'Apple n'est pas fiable (Favé : fond noir, logo blanc)."""
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGBA")
    image.thumbnail((200, 200))
    data = image.tobytes()
    opaque = [data[i:i + 3] for i in range(0, len(data), 4) if data[i + 3] > 200]
    if not opaque:
        return None
    red, green, blue = (sum(p[c] for p in opaque) // len(opaque) for c in range(3))
    return f"{red:02x}{green:02x}{blue:02x}"


def luminance(color: str) -> float:
    red, green, blue = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


async def _logo_look(url: str) -> tuple[str, bool]:
    """`(couleur d'accent, logo sombre)`. Un logo sombre disparaîtrait sur le
    fond noir : l'app le dessine en blanc et garde un accent blanc. Mesure
    impossible (réseau, Pillow absent) : logo blanc, accent blanc."""
    try:
        resp = await _http().get(url)
        resp.raise_for_status()
        color = await asyncio.to_thread(average_color, resp.content)
    except (httpx.HTTPError, ImportError, OSError, ValueError):
        return "ffffff", False
    if color is None:
        return "ffffff", False
    return ("ffffff", True) if luminance(color) < DARK_LOGO else (color, False)


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
    """`{"square", "wide", "logo", "accent", "dark_logo"}` (chacun peut manquer) :
    portrait animé, logo de l'artiste, sa couleur (accent des boutons) et si le
    logo est trop sombre pour le fond noir."""

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
        accent, dark = await _logo_look(logo) if logo else (None, False)
        found = {"square": square, "wide": wide, "logo": logo, "accent": accent, "dark_logo": dark}
        return found if square or wide or logo else None

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


# ── Fichier MP4 pour l'écran verrouillé ─────────────────────────────────────
# iOS 26 n'accepte pour l'artwork animé de l'écran verrouillé qu'un fichier
# vidéo local (ni HLS ni flux) : le serveur recopie la boucle HLS en MP4, sans
# réencoder (`-c copy`), et la garde sur disque.
MP4_MIN_WIDTH = 600  # assez net pour l'écran verrouillé, sans prendre la plus lourde
MP4_KEEP = 60  # fichiers gardés
MP4_TIMEOUT = 90
_STREAM_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]*)\n(\S+)")
_conversion = asyncio.Semaphore(2)


def pick_variant(master: str, base: str) -> str | None:
    """Variante H.264 (lue partout) d'une liste HLS : la plus légère d'au moins
    `MP4_MIN_WIDTH` de large, à défaut la plus large."""
    found: list[tuple[int, str]] = []
    for attributes, uri in _STREAM_RE.findall(master):
        size = re.search(r"RESOLUTION=(\d+)x\d+", attributes)
        if size and 'CODECS="avc1' in attributes:
            found.append((int(size.group(1)), uri if uri.startswith("http") else base.rsplit("/", 1)[0] + "/" + uri))
    if not found:
        return None
    wide_enough = sorted(item for item in found if item[0] >= MP4_MIN_WIDTH)
    return (wide_enough[0] if wide_enough else max(found))[1]


async def mp4_for(video_url: str, folder: Path, ffmpeg_path: str) -> Path | None:
    """Le MP4 de la boucle HLS `video_url` (venue de l'API d'Apple), converti
    la première fois ; `None` si la conversion échoue."""
    if not video_url.startswith("https://") or ".apple.com/" not in video_url:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{hashlib.sha1(video_url.encode()).hexdigest()[:20]}.mp4"
    if dest.is_file():
        return dest
    async with _conversion:
        if dest.is_file():
            return dest
        try:
            master = await _http().get(video_url, headers=BROWSER_HEADERS)
            master.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("Liste HLS Apple illisible : %s", exc)
            return None
        source = pick_variant(master.text, video_url) or video_url
        part = dest.with_suffix(".part")
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "https,tls,tcp,crypto,http",
            "-i", source, "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(part),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, error = await asyncio.wait_for(process.communicate(), MP4_TIMEOUT)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            part.unlink(missing_ok=True)
            logger.warning("Conversion de la boucle Apple trop longue : abandon")
            return None
        if process.returncode != 0 or not part.is_file() or part.stat().st_size == 0:
            logger.warning("Conversion de la boucle Apple impossible : %s", (error or b"").decode(errors="replace")[-300:])
            part.unlink(missing_ok=True)
            return None
        part.replace(dest)
    # Garde les plus récents seulement.
    files = sorted(folder.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[MP4_KEEP:]:
        old.unlink(missing_ok=True)
    return dest
