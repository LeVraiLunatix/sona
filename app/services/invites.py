from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

INVITE_PREFIX = "invite_"

# Jeton produit par `secrets.token_urlsafe(12)` : 16 caractères de l'alphabet
# URL-safe. On accepte une fourchette plus large pour rester compatible avec
# d'anciens liens.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def build_invite_link(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={INVITE_PREFIX}{token}"


def _token_from_payload(payload: str) -> str | None:
    payload = payload.strip()
    if payload.startswith(INVITE_PREFIX):
        payload = payload[len(INVITE_PREFIX) :]
    return payload if _TOKEN_RE.match(payload) else None


def extract_invite_token(text: str | None) -> str | None:
    """Retrouve un jeton d'invitation dans un texte quelconque.

    Telegram ne transmet pas toujours le paramètre d'un lien `?start=` — c'est
    notamment le cas quand la conversation avec le bot existe déjà côté invité,
    qui se retrouve alors à taper `/start` tout court et à se faire refuser.
    On accepte donc le jeton sous toutes ses formes : argument de `/start`,
    lien complet collé dans la conversation, ou jeton brut.
    """
    if not text:
        return None
    text = text.strip()

    if text.startswith("/start"):
        text = text[len("/start") :].strip()
    if not text:
        return None

    url_match = _URL_RE.search(text)
    if url_match:
        parsed = urlparse(url_match.group(0).rstrip(".,;)"))
        start = parse_qs(parsed.query).get("start", [""])[0]
        token = _token_from_payload(start)
        if token:
            return token
        # Format alternatif parfois partagé : t.me/<bot>/invite_<token>
        last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if last_segment.startswith(INVITE_PREFIX):
            return _token_from_payload(last_segment)
        return None

    if " " in text:
        return None
    return _token_from_payload(text)
