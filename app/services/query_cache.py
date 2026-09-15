from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

_TTL_SECONDS = 3600


@dataclass(slots=True)
class CachedQuery:
    text: str
    artist_scope_name: str | None = None
    # Source qui a répondu (deezer/apple/youtube) : renseignée à la première
    # page pour que la pagination reste sur le même catalogue.
    provider: str | None = None


_store: dict[str, tuple[float, CachedQuery]] = {}


def _purge() -> None:
    now = time.monotonic()
    expired = [k for k, (exp, _) in _store.items() if exp < now]
    for k in expired:
        _store.pop(k, None)


def put(query: CachedQuery) -> str:
    _purge()
    qid = secrets.token_urlsafe(6)
    _store[qid] = (time.monotonic() + _TTL_SECONDS, query)
    return qid


def get(qid: str) -> CachedQuery | None:
    entry = _store.get(qid)
    if not entry:
        return None
    exp, query = entry
    if exp < time.monotonic():
        _store.pop(qid, None)
        return None
    return query
