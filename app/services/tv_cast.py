"""« Écouter sur la TV / PS5 » : l'appli YouTube de la PS5 (et des TV
connectées) se pilote à distance, comme quand on « caste » depuis YouTube.

On s'associe une fois avec le code affiché par l'appli (Paramètres →
« Associer un appareil » / « Link with TV code »), puis le serveur envoie
à l'écran la vidéo YouTube de chaque titre — celle que Sona a trouvée pour
le lire (`stream_sources`), sinon la meilleure trouvée par le résolveur.

Protocole « Lounge » de YouTube (le même que les applis mobiles) : un
jeton par écran, une session ouverte à la demande, et des commandes
(`setPlaylist`, `addVideo`, `play`, `pause`, `next`…). Écrit ici avec
httpx plutôt qu'avec pyytlounge, qui imposerait une version d'aiohttp
incompatible avec le bot Telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.providers.base import TrackInfo
from app.services.resolver import ResolutionError, iter_audio_sources

logger = logging.getLogger(__name__)

API = "https://www.youtube.com/api/lounge"
DEVICE_NAME = "Sona"
# Titres ajoutés à la file de l'écran après le premier.
QUEUE_AHEAD = 15
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_SID = re.compile(r'\["c","([^"]+)"')
_GSESSION = re.compile(r'\["S","([^"]+)"')
_EVENT_ID = re.compile(r"\[(\d+),\[")
ACTIONS = {"play": "play", "pause": "pause", "next": "next", "previous": "previous", "stop": "stopVideo"}
# États annoncés par l'appli YouTube de l'écran (onStateChange).
_STATES = {-1: "idle", 0: "ended", 1: "playing", 2: "paused", 3: "buffering", 5: "idle"}


class CastError(Exception):
    pass


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15)


@dataclass
class Screen:
    screen_id: str
    name: str
    lounge_token: str


async def pair(code: str) -> Screen:
    """Associe l'écran qui affiche `code` (chiffres, espaces ignorés)."""
    digits = re.sub(r"\D", "", code)
    if len(digits) < 8:
        raise CastError("Code incomplet : recopie tout le code affiché sur la TV.")
    async with _http() as client:
        resp = await client.post(f"{API}/pairing/get_screen", data={"pairing_code": digits})
    if resp.status_code != 200:
        raise CastError("Code refusé par YouTube : vérifie-le, ou affiches-en un nouveau sur la TV.")
    screen = resp.json().get("screen") or {}
    if not screen.get("screenId") or not screen.get("loungeToken"):
        raise CastError("Code refusé par YouTube.")
    return Screen(screen["screenId"], screen.get("name") or "TV", screen["loungeToken"])


async def refresh_token(screen_id: str) -> str:
    async with _http() as client:
        resp = await client.post(f"{API}/pairing/get_lounge_token_batch", data={"screen_ids": screen_id})
    try:
        return resp.json()["screens"][0]["loungeToken"]
    except (ValueError, KeyError, IndexError) as exc:
        raise CastError("L'écran n'est plus associé : refais l'association avec un nouveau code.") from exc


@dataclass
class Session:
    screen_id: str
    token: str
    sid: str | None = None
    gsession: str | None = None
    last_event: str = "0"
    offset: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Ce que l'écran annonce (position, durée, état, vidéo, volume).
    video_id: str | None = None
    position: float = 0.0
    duration: float = 0.0
    state: int = -1
    volume: int | None = None
    updated: float = 0.0
    # Vidéo YouTube -> titre Sona envoyé, pour savoir lequel joue à l'écran.
    videos: dict[str, tuple[str, str]] = field(default_factory=dict)
    listener: asyncio.Task | None = None

    def apply_event(self, name: str, data: dict) -> None:
        if name in ("nowPlaying", "onStateChange"):
            if name == "nowPlaying" and not data:
                self.video_id, self.state, self.position, self.duration = None, -1, 0.0, 0.0
            else:
                self.video_id = data.get("videoId") or self.video_id
                for key, attr in (("currentTime", "position"), ("duration", "duration")):
                    try:
                        setattr(self, attr, float(data[key]))
                    except (KeyError, TypeError, ValueError):
                        pass
                try:
                    self.state = int(data["state"])
                except (KeyError, TypeError, ValueError):
                    pass
            self.updated = time.monotonic()
        elif name == "onVolumeChanged":
            try:
                self.volume = int(data.get("volume"))
            except (TypeError, ValueError):
                pass
        elif name == "loungeScreenDisconnected":
            self.state = -1
            self.updated = time.monotonic()

    def snapshot(self) -> dict:
        position = self.position
        if self.state == 1 and self.updated:
            position += time.monotonic() - self.updated
            if self.duration:
                position = min(position, self.duration)
        mapped = self.videos.get(self.video_id or "")
        return {
            "connected": self.connected,
            "state": _STATES.get(self.state, "idle"),
            "position": round(position, 1),
            "duration": self.duration,
            "video_id": self.video_id,
            "track": {"source": mapped[0], "source_id": mapped[1]} if mapped else None,
            "volume": self.volume,
        }

    def feed(self, text: str) -> None:
        """Lit les événements d'un morceau de flux : des lignes « longueur »
        puis un tableau JSON `[[index, ["nom", {...}]], ...]`."""
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                events = json.loads(line)
            except ValueError:
                continue
            for event in events:
                try:
                    index, (name, *rest) = event
                except (TypeError, ValueError):
                    continue
                self.last_event = str(index)
                data = rest[0] if rest and isinstance(rest[0], dict) else {}
                self.apply_event(name, data)

    async def listen(self) -> None:
        """Écoute l'écran tant que la session vit (longue requête rouverte à
        chaque fin) : c'est ce qui donne le temps de lecture et l'état."""
        while self.connected:
            params = {
                "name": DEVICE_NAME, "loungeIdToken": self.token, "SID": self.sid, "AID": self.last_event,
                "gsessionid": self.gsession, "device": "REMOTE_CONTROL", "app": "youtube-desktop",
                "VER": 8, "v": 2, "RID": "rpc", "CI": 0, "TYPE": "xmlhttp",
            }
            try:
                async with _http() as client:
                    async with client.stream("GET", f"{API}/bc/bind", params=params) as resp:
                        if resp.status_code != 200:
                            self.sid = self.gsession = None
                            return
                        async for chunk in resp.aiter_text():
                            self.feed(chunk)
                await asyncio.sleep(0.5)
            except httpx.TimeoutException:
                continue
            except httpx.HTTPError:
                await asyncio.sleep(2)
            except Exception:
                logger.exception("Écoute de l'écran interrompue")
                return

    def ensure_listener(self) -> None:
        if self.connected and (self.listener is None or self.listener.done()):
            self.listener = asyncio.create_task(self.listen())
            _background.add(self.listener)
            self.listener.add_done_callback(_background.discard)

    @property
    def connected(self) -> bool:
        return bool(self.sid and self.gsession)

    async def connect(self) -> None:
        body = {
            "app": "web", "mdx-version": "3", "name": DEVICE_NAME, "id": self.screen_id,
            "device": "REMOTE_CONTROL", "capabilities": "que,dsdtr,atp", "magnaKey": "cloudPairedDevice",
            "ui": "false", "theme": "cl", "loungeIdToken": self.token,
        }
        async with _http() as client:
            resp = await client.post(
                f"{API}/bc/bind", params={"RID": 1, "VER": 8, "CVER": 1, "auth_failure_option": "send_error"},
                data=body,
            )
        if resp.status_code == 401:
            raise CastError("expired")
        if resp.status_code != 200:
            raise CastError(f"Connexion à l'écran impossible ({resp.status_code}).")
        text = resp.text
        sid, gsession = _SID.search(text), _GSESSION.search(text)
        if not sid or not gsession:
            raise CastError("L'écran ne répond pas : ouvre l'appli YouTube sur la TV / PS5.")
        self.sid, self.gsession = sid.group(1), gsession.group(1)
        ids = _EVENT_ID.findall(text)
        self.last_event = ids[-1] if ids else "0"
        self.offset = 0
        self.state = -1

    async def command(self, name: str, parameters: dict | None = None) -> None:
        self.offset += 1
        body = {"count": 1, "ofs": self.offset, "req0__sc": name}
        for key, value in (parameters or {}).items():
            body[f"req0_{key}"] = value
        params = {
            "name": DEVICE_NAME, "loungeIdToken": self.token, "SID": self.sid, "AID": self.last_event,
            "gsessionid": self.gsession, "device": "REMOTE_CONTROL", "app": "youtube-desktop",
            "VER": 8, "v": 2, "RID": self.offset,
        }
        async with _http() as client:
            resp = await client.post(f"{API}/bc/bind", params=params, data=body)
        if resp.status_code in (400, 401, 404, 410):
            self.sid = self.gsession = None
            raise CastError("expired" if resp.status_code == 401 else "lost")
        if resp.status_code != 200:
            raise CastError(f"Commande refusée par l'écran ({resp.status_code}).")


_sessions: dict[str, Session] = {}


def reset() -> None:
    """Pour les tests."""
    _sessions.clear()


async def _session(repo, user_id: int, screen_id: str) -> Session:
    stored = await repo.tv_screen_get(user_id, screen_id)
    if stored is None:
        raise CastError("Écran inconnu : associe-le d'abord.")
    session = _sessions.get(screen_id)
    if session is None or session.token != stored["lounge_token"]:
        session = _sessions[screen_id] = Session(screen_id, stored["lounge_token"])
    return session


async def state(repo, user_id: int, screen_id: str) -> dict:
    """Ce que joue l'écran (position, durée, état), sans rien lui envoyer
    sauf une demande d'état à la première connexion."""
    session = await _session(repo, user_id, screen_id)
    if not session.connected or session.listener is None or session.listener.done():
        try:
            await send(repo, user_id, screen_id, "getNowPlaying")
        except CastError:
            return session.snapshot()
    return session.snapshot()


async def send(repo, user_id: int, screen_id: str, name: str, parameters: dict | None = None) -> None:
    """Envoie une commande, en (re)connectant la session au besoin : une
    session expirée ou perdue est rouverte une fois, jeton rafraîchi."""
    session = await _session(repo, user_id, screen_id)
    async with session.lock:
        for attempt in range(2):
            try:
                if not session.connected:
                    await session.connect()
                await session.command(name, parameters)
                session.ensure_listener()
                return
            except CastError as exc:
                if attempt or str(exc) not in ("expired", "lost"):
                    raise CastError(
                        "L'écran ne répond pas : ouvre l'appli YouTube sur la TV / PS5." if str(exc) in ("expired", "lost")
                        else str(exc)
                    ) from exc
                if str(exc) == "expired":
                    session.token = await refresh_token(screen_id)
                    await repo.tv_screen_set_token(user_id, screen_id, session.token)
                session.sid = session.gsession = None


async def video_id_for(repo, track: TrackInfo, cookies_file=None) -> str | None:
    """Vidéo YouTube d'un titre : celle déjà retenue par Sona pour le lire,
    sinon la première source YouTube proposée par le résolveur."""
    known = await repo.stream_source_get(track.source, track.source_id)
    if known and _YOUTUBE_ID.match(known):
        return known
    excluded = await repo.rejected_sources(track.source, track.source_id)
    try:
        async for candidate in iter_audio_sources(track, cookies_file, excluded):
            if candidate.platform == "youtube" and _YOUTUBE_ID.match(candidate.video_id):
                return candidate.video_id
    except ResolutionError as exc:
        logger.info("Pas de vidéo pour « %s » : %s", track.title, exc)
    return None


async def play(repo, user_id: int, screen_id: str, tracks: list[TrackInfo], cookies_file=None) -> str:
    """Lance `tracks[0]` sur l'écran tout de suite, puis ajoute la suite à
    sa file en arrière-plan (résolue titre par titre)."""
    first = await video_id_for(repo, tracks[0], cookies_file)
    if first is None:
        raise CastError("Titre introuvable sur YouTube.")
    session = await _session(repo, user_id, screen_id)
    session.videos = {first: (tracks[0].source, tracks[0].source_id)}
    await send(repo, user_id, screen_id, "setPlaylist", {"videoId": first, "currentTime": 0, "currentIndex": 0})

    async def queue_rest() -> None:
        for track in tracks[1 : QUEUE_AHEAD + 1]:
            try:
                video = await video_id_for(repo, track, cookies_file)
                if video:
                    session.videos.setdefault(video, (track.source, track.source_id))
                    await send(repo, user_id, screen_id, "addVideo", {"videoId": video})
            except CastError as exc:
                logger.info("File de l'écran interrompue : %s", exc)
                return
            except Exception:  # un titre qui échoue n'arrête pas la file
                logger.exception("Ajout à la file de l'écran impossible")

    if len(tracks) > 1:
        task = asyncio.create_task(queue_rest())
        _background.add(task)
        task.add_done_callback(_background.discard)
    return first


_background: set[asyncio.Task] = set()
