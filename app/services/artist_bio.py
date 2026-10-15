"""Biographie d'un artiste, d'après Wikipédia (français) : le résumé de sa
page, avec le lien vers elle. Rien d'inventé : si aucune page ne ressemble à
un musicien, il n'y a pas de biographie.

Les réponses (y compris « rien trouvé ») restent 24 h en mémoire."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://fr.wikipedia.org/w/api.php"
SUMMARY_URL = "https://fr.wikipedia.org/api/rest_v1/page/summary/{title}"
CACHE_TTL = 24 * 3600
USER_AGENT = "Sona/1.0 (bot musical prive; https://github.com/LeVraiLunatix/sona)"
# Une page de musicien le dit dans son résumé : garde-fou contre un homonyme.
_MUSIC_RE = re.compile(
    r"\b(chanteu\w*|rappeu\w*|musici\w*|compositeu\w*|groupe|duo|trio|dj|producteu\w*|"
    r"auteur-compositeur|interprète|album\w*|rap|musique)\b", re.IGNORECASE,
)

_cache: dict[str, tuple[float, dict | None]] = {}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=8, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    return _client


def reset() -> None:
    _cache.clear()


def pick_summary(data: dict) -> dict | None:
    """Résumé Wikipédia → `{"text", "url", "source"}` s'il s'agit d'un musicien."""
    if not isinstance(data, dict) or data.get("type") == "disambiguation":
        return None
    text = (data.get("extract") or "").strip()
    if len(text) < 40 or not _MUSIC_RE.search(f"{data.get('description') or ''} {text}"):
        return None
    url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page")
    return {"text": text, "url": url, "source": "Wikipédia"}


async def _summary(title: str) -> dict | None:
    resp = await _http().get(SUMMARY_URL.format(title=quote(title.replace(" ", "_"), safe="")))
    if resp.status_code != 200:
        return None
    return pick_summary(resp.json())


async def get_bio(name: str) -> dict | None:
    key = name.casefold()
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    bio: dict | None = None
    try:
        bio = await _summary(name)
        if bio is None:
            search = await _http().get(API_URL, params={
                "action": "query", "list": "search", "srsearch": f"{name} musique", "srlimit": 3, "format": "json",
            })
            for hit_ in (search.json().get("query") or {}).get("search", []) if search.status_code == 200 else []:
                bio = await _summary(hit_.get("title") or "")
                if bio:
                    break
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Biographie de %s indisponible : %s", name, exc)
        return None  # panne : pas gardée en cache, on réessaiera
    _cache[key] = (time.monotonic() + CACHE_TTL, bio)
    return bio
