"""Paroles d'un morceau, de la meilleure source disponible.

Trois sources interrogées en parallèle :
- LRCLIB : base ouverte, ligne par ligne (parfois mot par mot), texte brut ;
- NetEase : mot par mot (yrc) pour beaucoup de titres internationaux ;
- Musixmatch : mot par mot (richsync), seulement avec un jeton configuré.

Chaque réponse est vérifiée (titre, artiste, album, durée à ±2 s pour les
paroles synchronisées) : des paroles d'une autre chanson seraient pires que
pas de paroles. Parmi les réponses valables, on garde la plus précise — au
mot près, puis à la ligne, puis le texte brut — et, à précision égale, la
mieux appariée.

Le résultat est gardé en base (`lyrics_cache`), absences comprises : le
lecteur redemande les paroles à chaque titre, sur chaque appareil. Rien à
relancer à la main : une absence est recherchée de nouveau toute seule
(au plus tard 30 min après), et des paroles à la ligne ou brutes restent
affichées pendant qu'on en cherche de meilleures, en arrière-plan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from app.providers.lrclib import (
    _ARTIST_SEP_RE, Lyrics, LyricsError, LyricsLine, LyricsWord, clean_title, main_artist,
)

logger = logging.getLogger(__name__)

# Écart de durée toléré pour garder des paroles synchronisées : au-delà,
# c'est sans doute une autre version, et l'horodatage serait décalé (on
# garde alors le texte seul).
SYNC_DURATION_TOLERANCE = 2.0
# Au-delà, ce n'est plus le même enregistrement du tout.
MAX_DURATION_GAP = 30.0
# Temps laissé à chaque source avant de passer sans elle.
SOURCE_TIMEOUT = 8.0
# Dès qu'une source a répondu avec des paroles synchronisées, les autres ont ce
# délai pour faire mieux (mot par mot) ; passé ce délai on répond tout de suite
# et elles finissent en arrière-plan, le cache s'améliore à leur arrivée.
FAST_GRACE = 0.5
MIN_SCORE = 0.6

# Durées de vie du cache : des paroles au mot près ne s'amélioreront pas ;
# des paroles à la ligne ou brutes, si (les bases s'enrichissent) — passé
# ce délai, elles restent affichées et on en cherche de meilleures en
# arrière-plan. Une absence, elle, est recherchée de nouveau dès la demande
# suivante, une fois le délai passé (bien plus court si une source était en
# panne).
TTL_WORD = timedelta(days=120)
TTL_OTHER = timedelta(days=3)
TTL_MISSING = timedelta(minutes=30)
TTL_MISSING_AFTER_ERROR = timedelta(minutes=5)

# À précision et correspondance égales : LRCLIB (base ouverte, relue par
# des humains), puis Musixmatch, puis NetEase.
SOURCE_PRIORITY = {"lrclib": 3, "musixmatch": 2, "netease": 1}


@dataclass(slots=True)
class LyricsResult:
    lyrics: Lyrics
    source: str
    language: str | None = None

    @property
    def sync(self) -> str:
        """« word » (mot par mot), « line » (ligne par ligne) ou « none »."""
        return sync_level(self.lyrics)


@dataclass(slots=True)
class _Candidate:
    lyrics: Lyrics
    source: str
    score: float
    language: str | None = None


# -- Correspondance ---------------------------------------------------------

def _compact(text: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def _tokens(text: str | None) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    cleaned = "".join(ch if ch.isalnum() else " " for ch in decomposed if not unicodedata.combining(ch))
    return {t for t in cleaned.split() if t}


# Une autre version du morceau, dont les paroles (ou leur absence) ne
# correspondent pas : refusée si le titre demandé ne le dit pas lui-même.
_VERSION_MARKERS = (
    "remix", "instrumental", "live", "acoustic", "acoustique", "karaoke", "cover", "sped up",
    "slowed", "nightcore", "reverb", "8d", "edit", "mix", "version", "acapella", "a cappella",
)


def _markers(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", title.casefold()))
    padded = f" {' '.join(words)} "
    return {m for m in _VERSION_MARKERS if f" {m} " in padded}


def _title_score(wanted: str, found: str) -> float | None:
    if _markers(found) - _markers(wanted):
        return None
    a, b = _compact(clean_title(wanted)), _compact(clean_title(found))
    if not a or not b:
        return None
    if a == b:
        return 1.0
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 4 and longer.startswith(shorter):
        return 0.85
    ta, tb = _tokens(clean_title(wanted)), _tokens(clean_title(found))
    if ta and tb:
        overlap = len(ta & tb) / len(ta | tb)
        if overlap >= 0.6:
            return 0.5 + 0.3 * overlap
    return None


def _artists(text: str | None) -> list[str]:
    return [_compact(part) for part in _ARTIST_SEP_RE.split(text or "") if _compact(part)]


def _artist_score(wanted: str, found: str) -> float | None:
    ours, theirs = _artists(wanted), _artists(found)
    if not ours or not theirs:
        return None
    lead = ours[0]
    if any(lead == t or (len(min(lead, t, key=len)) >= 3 and (lead in t or t in lead)) for t in theirs):
        return 1.0
    if any(o == t for o in ours for t in theirs):
        return 0.8
    return None


def match(
    title: str, artist: str, album: str | None, duration: float | None,
    found_title: str, found_artist: str, found_album: str | None, found_duration: float | None,
) -> tuple[float, bool] | None:
    """Note de correspondance (0 à 1) et « la synchro est utilisable »
    (durées compatibles à ±2 s). None : ce n'est pas le même morceau."""
    title_score = _title_score(title, found_title)
    artist_score = _artist_score(artist, found_artist)
    if title_score is None or artist_score is None:
        return None
    timing_ok = True
    duration_score = 0.5
    if duration and found_duration:
        gap = abs(float(found_duration) - float(duration))
        if gap > MAX_DURATION_GAP:
            return None
        timing_ok = gap <= SYNC_DURATION_TOLERANCE
        duration_score = 1.0 if timing_ok else max(0.0, 1 - gap / MAX_DURATION_GAP) * 0.6
    album_score = 0.5
    if album and found_album:
        album_score = 1.0 if _compact(clean_title(album)) == _compact(clean_title(found_album)) else 0.3
    score = 0.45 * title_score + 0.3 * artist_score + 0.15 * duration_score + 0.1 * album_score
    return (score, timing_ok) if score >= MIN_SCORE else None


# -- Paroles ---------------------------------------------------------------

def sync_level(lyrics: Lyrics) -> str:
    if not lyrics.synced:
        return "none"
    timed = [line for line in lyrics.lines if line.text.strip()]
    with_words = sum(1 for line in timed if line.words)
    return "word" if timed and with_words * 2 >= len(timed) else "line"


def _tier(lyrics: Lyrics) -> int:
    if lyrics.instrumental:
        return 0
    return {"word": 3, "line": 2, "none": 1}[sync_level(lyrics)]


def _without_header(lyrics: Lyrics, title: str, artist: str) -> Lyrics:
    """Certaines sources ouvrent les paroles par « Artiste - Titre » : ce
    n'est pas chanté, on l'enlève."""
    wanted_title, wanted_artist = _compact(clean_title(title)), _compact(main_artist(artist))
    lines = list(lyrics.lines)
    while lines and len(lines) > 1:
        text = _compact(lines[0].text)
        if text and wanted_title and wanted_title in text and wanted_artist and wanted_artist in text:
            lines.pop(0)
            continue
        break
    if len(lines) == len(lyrics.lines):
        return lyrics
    return Lyrics(synced=lyrics.synced, instrumental=lyrics.instrumental, lines=lines)


def _unsynced(lyrics: Lyrics) -> Lyrics:
    """Mêmes paroles sans horodatage (autre version : la synchro serait fausse)."""
    if not lyrics.synced:
        return lyrics
    return Lyrics(synced=False, lines=[LyricsLine(time=None, text=line.text) for line in lyrics.lines])


# Mots outils les plus fréquents par langue : de quoi reconnaître la langue
# de paroles sans dépendance (l'app fait mieux avec NaturalLanguage).
_STOPWORDS = {
    "fr": {"je", "tu", "il", "elle", "nous", "vous", "les", "des", "une", "est", "pas", "que", "qui", "dans", "pour", "mon", "moi", "toi", "mais", "avec", "sur", "suis", "c'est", "j'ai", "ça", "comme", "plus"},
    "en": {"the", "you", "and", "i'm", "my", "me", "your", "it's", "don't", "is", "are", "with", "for", "this", "that", "what", "love", "can", "all", "we", "be", "just", "oh", "baby"},
    "es": {"el", "la", "los", "las", "que", "y", "yo", "tú", "mi", "con", "por", "para", "una", "como", "pero", "más", "eres", "estoy", "quiero", "contigo", "nada"},
    "pt": {"o", "os", "que", "eu", "você", "meu", "minha", "com", "não", "uma", "pra", "mais", "tudo", "sou", "estou", "quero", "amor", "nós"},
    "it": {"il", "che", "non", "di", "sono", "una", "per", "mi", "ti", "con", "come", "ma", "tu", "io", "questo", "sei", "anche", "più"},
    "de": {"ich", "du", "und", "die", "der", "das", "nicht", "ist", "mit", "mich", "dich", "ein", "eine", "wir", "auf", "sie", "es", "bin", "mein"},
}


def detect_language(lyrics: Lyrics) -> str | None:
    text = " ".join(line.text for line in lyrics.lines)
    if not text.strip():
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return None

    def share(predicate) -> float:
        return sum(1 for ch in letters if predicate(ch)) / len(letters)

    scripts = [
        ("ja", lambda ch: "぀" <= ch <= "ヿ"),
        ("ko", lambda ch: "가" <= ch <= "힯"),
        ("zh", lambda ch: "一" <= ch <= "鿿"),
        ("ru", lambda ch: "Ѐ" <= ch <= "ӿ"),
        ("ar", lambda ch: "؀" <= ch <= "ۿ"),
        ("he", lambda ch: "֐" <= ch <= "׿"),
        ("el", lambda ch: "Ͱ" <= ch <= "Ͽ"),
        ("hi", lambda ch: "ऀ" <= ch <= "ॿ"),
        ("th", lambda ch: "฀" <= ch <= "๿"),
    ]
    for code, predicate in scripts:
        if share(predicate) > 0.3:
            return code
    words = re.findall(r"[\w']+", text.casefold())
    if not words:
        return None
    # Mots outils différents (« la la la » n'en fait pas de l'espagnol),
    # et nettement plus que la langue suivante.
    distinct = set(words)
    counts = {code: len(distinct & stop) for code, stop in _STOPWORDS.items()}
    ranked = sorted(counts, key=counts.get, reverse=True)
    best, second = counts[ranked[0]], counts[ranked[1]]
    return ranked[0] if best >= 3 and best > second * 1.5 else None


# -- Sérialisation (cache, API) -------------------------------------------

def lyrics_to_dict(lyrics: Lyrics) -> dict:
    return {
        "synced": lyrics.synced,
        "instrumental": lyrics.instrumental,
        "lines": [
            {
                "time": line.time, "end": line.end, "text": line.text,
                "words": [{"time": w.time, "end": w.end, "text": w.text} for w in line.words] if line.words else None,
            }
            for line in lyrics.lines
        ],
    }


def lyrics_from_dict(data: dict) -> Lyrics:
    return Lyrics(
        synced=bool(data.get("synced")),
        instrumental=bool(data.get("instrumental")),
        lines=[
            LyricsLine(
                time=line.get("time"), text=line.get("text") or "", end=line.get("end"),
                words=[LyricsWord(w["time"], w["text"], end=w.get("end")) for w in line["words"]] if line.get("words") else None,
            )
            for line in data.get("lines") or []
        ],
    )


def base_title(title: str) -> str:
    """Titre sans aucune mention entre parenthèses ni après un tiret
    (« Song (From "Film") - 2019 Mix » → « Song ») : seconde chance quand
    les sources ne connaissent pas le titre complet."""
    stripped = re.sub(r"\s*[\(\[].*?[\)\]]", "", title)
    stripped = re.split(r"\s[-–—]\s", stripped, maxsplit=1)[0]
    return stripped.strip() or title


def cache_key(title: str, artist: str, duration: int | None) -> str:
    """Même morceau, même clé : sans « (feat. X) », « - Remastered », ni
    artistes invités. La durée sépare les versions (live, radio edit)."""
    return f"{_compact(clean_title(title))}|{_compact(main_artist(artist))}|{duration or ''}"


# -- Service -----------------------------------------------------------------

class LyricsService:
    def __init__(self, repo, lrclib, netease=None, musixmatch=None) -> None:
        self._repo = repo
        self._lrclib = lrclib
        self._netease = netease
        self._musixmatch = musixmatch
        # Deux appareils qui demandent le même titre en même temps : une
        # seule recherche.
        self._pending: dict[str, asyncio.Future] = {}
        # Recherches de meilleures paroles en arrière-plan (une par titre).
        self._upgrades: dict[str, asyncio.Task] = {}
        # Sources lentes qui finissent après la réponse (références gardées).
        self._background: set[asyncio.Task] = set()

    async def get(
        self, title: str, artist: str, album: str | None = None, duration: int | None = None, *, refresh: bool = False
    ) -> LyricsResult | None:
        key = cache_key(title, artist, duration)
        if not refresh:
            cached = await self._repo.lyrics_cache_peek(key)
            if cached is not None:
                payload, source, language, expired = cached
                if payload:
                    known = LyricsResult(lyrics_from_dict(payload), source, language)
                    if expired:
                        # Paroles connues tout de suite ; de meilleures, peut-être, au prochain affichage.
                        self._upgrade_later(key, title, artist, album, duration, known)
                    return known
                if not expired:
                    return None
                # Absence périmée : on cherche de nouveau, tout de suite.

        pending = self._pending.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            result = await self._lookup(key, title, artist, album, duration)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            # Personne d'autre n'attend peut-être : on évite l'avertissement
            # « exception jamais récupérée ».
            future.exception()
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._pending.pop(key, None)

    async def forget(self, title: str, artist: str, duration: int | None) -> None:
        await self._repo.lyrics_cache_delete(cache_key(title, artist, duration))

    def _upgrade_later(self, key, title, artist, album, duration, known: LyricsResult) -> None:
        if key in self._upgrades or key in self._pending:
            return
        task = asyncio.create_task(self._upgrade(key, title, artist, album, duration, known))
        self._upgrades[key] = task
        task.add_done_callback(lambda _: self._upgrades.pop(key, None))

    async def _upgrade(self, key, title, artist, album, duration, known: LyricsResult) -> None:
        """Paroles périmées : on cherche de nouveau, et on ne garde le
        nouveau résultat que s'il est au moins aussi précis — sinon les
        anciennes paroles restent, pour un nouveau délai."""
        try:
            found, errors = await self._search(title, artist, album, duration)
        except LyricsError:
            found, errors = None, ["toutes les sources"]
        except Exception:  # noqa: BLE001 — une tâche de fond ne doit rien casser
            logger.exception("Paroles : recherche en arrière-plan de %s - %s", artist, title)
            return
        if found is not None and _tier(found.lyrics) >= _tier(known.lyrics):
            await self._store(key, found, errors)
            if _tier(found.lyrics) > _tier(known.lyrics):
                logger.info("Paroles améliorées pour %s - %s : %s (%s)", artist, title, found.source, found.sync)
            return
        ttl = TTL_MISSING if errors else (TTL_WORD if known.sync == "word" else TTL_OTHER)
        await self._repo.lyrics_cache_set(key, lyrics_to_dict(known.lyrics), known.source, known.language, ttl)

    async def _lookup(
        self, key: str, title: str, artist: str, album: str | None, duration: int | None
    ) -> LyricsResult | None:
        async def late(final: LyricsResult | None, errs: list[str], early: LyricsResult) -> None:
            # Les sources lentes ont fini après la réponse : on garde leurs
            # paroles si elles sont plus précises (au prochain affichage).
            if final is not None and _tier(final.lyrics) > _tier(early.lyrics):
                await self._store(key, final, errs)
                logger.info("Paroles améliorées pour %s - %s : %s (%s)", artist, title, final.source, final.sync)

        result, errors = await self._search(title, artist, album, duration, on_late=late)
        if result is None:
            ttl = TTL_MISSING_AFTER_ERROR if errors else TTL_MISSING
            await self._repo.lyrics_cache_set(key, None, None, None, ttl)
            return None
        await self._store(key, result, errors)
        return result

    async def _store(self, key: str, result: LyricsResult, errors: list[str]) -> None:
        ttl = TTL_WORD if result.sync == "word" else TTL_OTHER
        # Une source muette par erreur aurait peut-être eu mieux : on
        # retentera plus tôt.
        if errors:
            ttl = min(ttl, TTL_MISSING)
        await self._repo.lyrics_cache_set(key, lyrics_to_dict(result.lyrics), result.source, result.language, ttl)

    async def _search(
        self, title: str, artist: str, album: str | None, duration: int | None, on_late=None
    ) -> tuple[LyricsResult | None, list[str]]:
        """Meilleures paroles de toutes les sources (et les sources en
        erreur). Rien trouvé : seconde passe avec le titre sans ses mentions
        (« (From "Film") », « - 2019 Mix »). Lève LyricsError si aucune
        source n'a répondu."""
        result, errors = await self._search_once(title, artist, album, duration, on_late)
        relaxed = base_title(title)
        if result is None and relaxed != clean_title(title):
            again, more = await self._search_once(relaxed, artist, album, duration)
            result, errors = again, errors + more
        return result, errors

    async def _search_once(
        self, title: str, artist: str, album: str | None, duration: int | None, on_late=None
    ) -> tuple[LyricsResult | None, list[str]]:
        """Interroge toutes les sources en même temps. Avec `on_late` (demande de
        l'utilisateur) : dès qu'une a des paroles synchronisées, les autres ont
        `FAST_GRACE` pour faire mieux ; sinon on répond avec ce qu'on a et elles
        finissent en arrière-plan (`on_late` reçoit alors le résultat final, les
        erreurs et la réponse déjà donnée). Sans `on_late` (recherche de fond) :
        on attend toutes les sources."""
        jobs = [("lrclib", self._from_lrclib(title, artist, album, duration))]
        if self._netease is not None:
            jobs.append(("netease", self._from_netease(title, artist, album, duration)))
        if self._musixmatch is not None:
            jobs.append(("musixmatch", self._from_musixmatch(title, artist, album, duration)))
        names: dict[asyncio.Future, str] = {
            asyncio.ensure_future(asyncio.wait_for(job, SOURCE_TIMEOUT)): name for name, job in jobs
        }
        candidates: list[_Candidate] = []
        errors: list[str] = []

        def absorb(done) -> None:
            for task in done:
                name = names[task]
                try:
                    outcome = task.result()
                except (LyricsError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
                    errors.append(f"{name} : {exc or type(exc).__name__}")
                except Exception as exc:  # noqa: BLE001 — une source qui plante ne doit pas tout casser
                    logger.exception("Paroles : la source %s a planté", name, exc_info=exc)
                    errors.append(f"{name} : {exc or type(exc).__name__}")
                else:
                    if outcome is not None:
                        candidates.append(outcome)

        pending = set(names)
        loop = asyncio.get_running_loop()
        deadline: float | None = None
        try:
            while pending:
                timeout = None if deadline is None else max(0.0, deadline - loop.time())
                done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                absorb(done)
                if candidates and on_late is not None:
                    best_tier = max(_tier(c.lyrics) for c in candidates)
                    if best_tier >= 3:
                        break
                    if best_tier >= 2 and deadline is None:
                        deadline = loop.time() + FAST_GRACE
        except asyncio.CancelledError:
            for task in pending:
                task.cancel()
            raise

        if not candidates:
            if pending:
                for task in pending:
                    task.cancel()
            if errors and len(errors) == len(jobs):
                raise LyricsError(" ; ".join(errors))
            return None, errors

        result = self._pick(candidates, title, artist)
        if pending and on_late is not None:
            async def finish() -> None:
                try:
                    done, _ = await asyncio.wait(pending)
                    absorb(done)
                    await on_late(self._pick(candidates, title, artist), errors, result)
                except Exception:  # noqa: BLE001 — tâche de fond
                    logger.exception("Paroles : fin de recherche de %s - %s", artist, title)

            task = asyncio.create_task(finish())
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        else:
            for task in pending:
                task.cancel()
        return result, errors

    def _pick(self, candidates: list[_Candidate], title: str, artist: str) -> LyricsResult:
        for candidate in candidates:
            candidate.lyrics = _without_header(candidate.lyrics, title, artist)
        best = max(candidates, key=lambda c: (_tier(c.lyrics), c.score, SOURCE_PRIORITY.get(c.source, 0)))
        language = best.language or (None if best.lyrics.instrumental else detect_language(best.lyrics))
        result = LyricsResult(best.lyrics, best.source, language)
        logger.info(
            "Paroles %s - %s : %s (%s, note %.2f)", artist, title, best.source, result.sync, best.score,
        )
        return result

    async def _from_lrclib(self, title, artist, album, duration) -> _Candidate | None:
        # LRCLIB fait déjà sa propre correspondance (titre nettoyé, artiste
        # principal, durée à ±3 s) : on lui fait confiance.
        lyrics = await self._lrclib.get_lyrics(title, artist, album, duration)
        return _Candidate(lyrics, "lrclib", 0.9) if lyrics else None

    async def _from_netease(self, title, artist, album, duration) -> _Candidate | None:
        songs = await self._netease.search(clean_title(title), main_artist(artist))
        scored = []
        for song in songs:
            verdict = match(title, artist, album, duration, song.title, song.artist, song.album, song.duration)
            if verdict:
                scored.append((verdict, song))
        scored.sort(key=lambda item: item[0][0], reverse=True)
        # Les deux meilleurs : le premier n'a parfois pas de paroles (autre
        # édition du même titre).
        for (score, timing_ok), song in scored[:2]:
            lyrics = await self._netease.lyrics(song.id)
            if lyrics:
                return _Candidate(lyrics if timing_ok else _unsynced(lyrics), "netease", score)
        return None

    async def _from_musixmatch(self, title, artist, album, duration) -> _Candidate | None:
        found = await self._musixmatch.find(clean_title(title), main_artist(artist), album, duration)
        if not found:
            return None
        meta, lyrics = found
        verdict = match(title, artist, album, duration, meta["title"], meta["artist"], meta.get("album"), meta.get("duration"))
        if not verdict:
            logger.debug("Musixmatch propose %r - %r : écarté", meta["artist"], meta["title"])
            return None
        score, timing_ok = verdict
        return _Candidate(lyrics if timing_ok else _unsynced(lyrics), "musixmatch", score, meta.get("language"))
