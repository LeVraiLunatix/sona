"""Client du service de comptes (`rust/sona-accounts`) : identité, amis, visibilité, scrobbling.

Le serveur musique ne sait rien de Supabase : il présente le jeton de la personne au service, qui vérifie la
signature ET relit le statut du compte (banni, suspendu…) à chaque appel. Les règles de visibilité (amis, blocages,
réglages de confidentialité) sont calculées par la base : on ne les recode jamais ici.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

VERIFY_CACHE_SECONDS = 5  # même durée que le service : un bannissement s'applique à la requête suivante


class InvalidToken(Exception):
    """Jeton absent, expiré ou signé par quelqu'un d'autre."""


class Sanctioned(Exception):
    """Compte banni, suspendu ou en quarantaine : l'interface affiche l'écran de sanction."""

    def __init__(self, status: str, reason: str | None, until: str | None) -> None:
        super().__init__(status)
        self.status, self.reason, self.until = status, reason, until


class Unavailable(Exception):
    """Service de comptes injoignable."""


@dataclass(frozen=True, slots=True)
class Identity:
    uid: str
    username: str
    role: str
    status: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True, slots=True)
class Relation:
    friend: bool = False
    blocked: bool = False
    visible: bool = False
    presence: bool = False
    history: bool = False
    stats: bool = False
    playlists: bool = False
    profile: bool = False


def looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3 and all(parts) and len(token) < 8192


class SonaAccounts:
    def __init__(self, base_url: str, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"x-sona-internal": secret}
        self._http = client or httpx.AsyncClient(timeout=6)
        self._verified: dict[str, tuple[float, Identity]] = {}
        self._profiles: dict[str, tuple[float, dict]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict) -> httpx.Response:
        try:
            return await self._http.post(self._base + path, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise Unavailable(str(exc)) from exc

    async def _get(self, path: str) -> httpx.Response:
        try:
            return await self._http.get(self._base + path, headers=self._headers)
        except httpx.HTTPError as exc:
            raise Unavailable(str(exc)) from exc

    async def verify(self, token: str) -> Identity:
        now = time.monotonic()
        hit = self._verified.get(token)
        if hit is not None and hit[0] > now:
            return hit[1]
        resp = await self._post("/internal/verify", {"token": token})
        if resp.status_code == 403:
            data = resp.json() if resp.content else {}
            raise Sanctioned(data.get("status", "banned"), data.get("reason"), data.get("until"))
        if resp.status_code in (400, 401):
            raise InvalidToken()
        if resp.status_code >= 500:
            raise Unavailable(f"HTTP {resp.status_code}")
        data = resp.json()
        who = Identity(uid=str(data["user_id"]), username=data.get("username") or "", role=data.get("role") or "user", status=data.get("status") or "active")
        if len(self._verified) > 2000:
            self._verified = {t: v for t, v in self._verified.items() if v[0] > now}
        self._verified[token] = (now + VERIFY_CACHE_SECONDS, who)
        return who

    async def friend_ids(self, uid: str) -> list[str]:
        resp = await self._get(f"/internal/friends/{uid}")
        resp.raise_for_status()
        return [str(x) for x in resp.json().get("friends", [])]

    async def relations(self, viewer: str, others: list[str]) -> dict[str, Relation]:
        if not others:
            return {}
        resp = await self._post("/internal/relations", {"viewer": viewer, "others": others[:500]})
        resp.raise_for_status()
        fields = Relation.__dataclass_fields__
        return {k: Relation(**{f: bool(v.get(f)) for f in fields}) for k, v in resp.json().items()}

    async def profiles(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        resp = await self._post("/internal/profiles", {"ids": ids[:500]})
        resp.raise_for_status()
        return {str(p["id"]): p for p in resp.json().get("profiles", [])}

    async def profile(self, uid: str) -> dict:
        """Pseudo / photo, gardés 5 min (le nom affiché ne change pas à chaque requête)."""
        now = time.monotonic()
        hit = self._profiles.get(uid)
        if hit is not None and hit[0] > now:
            return hit[1]
        got = (await self.profiles([uid])).get(uid, {})
        self._profiles[uid] = (now + 300, got)
        return got

    async def text_offensive(self, text: str) -> bool:
        resp = await self._post("/internal/text-check", {"text": text[:4000]})
        resp.raise_for_status()
        return bool(resp.json().get("offensive"))

    async def adopt_lastfm(self, uid: str, username: str, session_key: str) -> bool:
        """Confie au service des comptes la liaison Last.fm d'un ancien compte (il la chiffre ; il ne remplace pas
        une liaison que la personne aurait déjà faite)."""
        try:
            resp = await self._post("/internal/lastfm/adopt", {"user_id": uid, "username": username, "session_key": session_key})
        except Unavailable as exc:
            logger.warning("Liaison Last.fm non reprise : %s", exc)
            return False
        if resp.status_code >= 400:
            logger.warning("Liaison Last.fm non reprise (%s)", resp.status_code)
        return resp.status_code < 400

    async def scrobble(self, uid: str, kind: str, artist: str, track: str, album: str | None, duration: int | None, timestamp: int) -> None:
        """Au mieux : un scrobbling raté ne bloque jamais la lecture."""
        body = {"user_id": uid, "kind": kind, "artist": artist, "track": track, "album": album, "duration": duration, "timestamp": timestamp}
        try:
            resp = await self._post("/internal/scrobble", body)
            if resp.status_code >= 400:
                logger.info("Scrobbling refusé (%s)", resp.status_code)
        except Unavailable as exc:
            logger.info("Scrobbling impossible : %s", exc)
