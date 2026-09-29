"""« Complète les paroles » : le titre joue jusqu'à une ligne, la musique se
coupe, et il faut trouver la fin de la ligne parmi quatre propositions.

Les paroles synchronisées (LRCLIB) donnent l'instant de chaque ligne : on
fait écouter les ~10 secondes qui précèdent, puis on cache les derniers mots
de la ligne. Les leurres sont des fins de lignes du même titre (même
longueur), sinon d'autres titres de la partie : il faut vraiment connaître
le morceau.
"""

from __future__ import annotations

import logging
import random
import re

from app.providers.base import TrackInfo
from app.providers.lrclib import LyricsError, main_artist
from app.services.blindtest import CHOICES, _dedupe

logger = logging.getLogger(__name__)

LEAD_IN = 10.0  # secondes de musique avant la ligne à compléter
MIN_WORDS = 4
MAX_CANDIDATES = 40
_WORD_RE = re.compile(r"\S+")


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def blank_size(words: list[str]) -> int:
    return 3 if len(words) >= 7 else 2


def question_from(track: TrackInfo, lines: list, rng: random.Random, others: list[str]) -> dict | None:
    """Une question sur ce titre, ou None si ses paroles ne s'y prêtent pas."""
    timed = [ln for ln in lines if ln.time is not None and ln.text.strip() and ln.time >= LEAD_IN + 2]
    if len(timed) < 8:
        return None
    start, end = len(timed) // 4, max(len(timed) // 4 + 1, int(len(timed) * 0.85))
    options = [i for i in range(start, end) if len(_WORD_RE.findall(timed[i].text)) >= MIN_WORDS]
    rng.shuffle(options)
    for index in options:
        line = timed[index]
        words = _WORD_RE.findall(line.text)
        size = blank_size(words)
        answer = " ".join(words[-size:])
        # Leurres : fins de lignes (même nombre de mots) de ce titre d'abord.
        pool = []
        for other in timed:
            other_words = _WORD_RE.findall(other.text)
            if len(other_words) >= size + 1:
                pool.append(" ".join(other_words[-size:]))
        pool += others
        rng.shuffle(pool)
        decoys: list[str] = []
        seen = {_norm(answer)}
        for candidate in pool:
            if _norm(candidate) and _norm(candidate) not in seen:
                seen.add(_norm(candidate))
                decoys.append(candidate)
            if len(decoys) == CHOICES - 1:
                break
        if len(decoys) < CHOICES - 1:
            continue
        choices = [{"title": answer, "artist": ""}] + [{"title": d, "artist": ""} for d in decoys]
        rng.shuffle(choices)
        next_time = timed[index + 1].time if index + 1 < len(timed) else line.time + 5
        return {
            "kind": "lyrics",
            "preview_url": "",
            "cover_url": track.cover_url,
            "answer": next(i for i, c in enumerate(choices) if c["title"] == answer),
            "choices": choices,
            "before": [ln.text for ln in timed[max(0, index - 2): index]],
            "prompt": " ".join(words[:-size]) + " …",
            "clip_start": round(max(0.0, line.time - LEAD_IN), 2),
            "line_time": round(line.time, 2),
            "reveal_end": round(min(next_time + 0.5, line.time + 8), 2),
            "track": {
                "source": track.source, "source_id": track.source_id, "title": track.title,
                "artist": track.artist, "album": track.album, "year": track.year,
                "duration_seconds": track.duration_seconds, "cover_url": track.cover_url,
                "artist_source_id": track.artist_source_id, "album_source_id": track.album_source_id,
            },
        }
    return None


async def build_round(deps, pool: list[TrackInfo], seed, count: int) -> list[dict]:
    rng = random.Random(seed)
    candidates = sorted(_dedupe(pool), key=lambda t: (t.artist.casefold(), t.title.casefold()))
    rng.shuffle(candidates)
    candidates = candidates[:MAX_CANDIDATES]
    # Fins de lignes génériques (autres titres) pour compléter les leurres.
    others: list[str] = []
    questions: list[dict] = []
    for track in candidates:
        if len(questions) >= count:
            break
        try:
            lyrics = await deps.lrclib.get_lyrics(track.title, main_artist(track.artist), track.album, track.duration_seconds)
        except LyricsError as exc:
            logger.info("Paroles indisponibles pour %s : %s", track.title, exc)
            continue
        if lyrics is None or not lyrics.synced or lyrics.instrumental:
            continue
        question = question_from(track, lyrics.lines, rng, others)
        for line in lyrics.lines:
            words = _WORD_RE.findall(line.text)
            if len(words) >= 3:
                others.append(" ".join(words[-2:]))
        if question is not None:
            questions.append(question)
    return questions
