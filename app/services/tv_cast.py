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
import logging
import re
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


async def send(repo, user_id: int, screen_id: str, name: str, parameters: dict | None = None) -> None:
    """Envoie une commande, en (re)connectant la session au besoin : une
    session expirée ou perdue est rouverte une fois, jeton rafraîchi."""
    stored = await repo.tv_screen_get(user_id, screen_id)
    if stored is None:
        raise CastError("Écran inconnu : associe-le d'abord.")
    session = _sessions.get(screen_id)
    if session is None or session.token != stored["lounge_token"]:
        session = _sessions[screen_id] = Session(screen_id, stored["lounge_token"])
    async with session.lock:
        for attempt in range(2):
            try:
                if not session.connected:
                    await session.connect()
                await session.command(name, parameters)
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
    await send(repo, user_id, screen_id, "setPlaylist", {"videoId": first, "currentTime": 0, "currentIndex": 0})

    async def queue_rest() -> None:
        for track in tracks[1 : QUEUE_AHEAD + 1]:
            try:
                video = await video_id_for(repo, track, cookies_file)
                if video:
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
