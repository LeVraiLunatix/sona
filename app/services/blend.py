"""Blend : une playlist commune à deux amis, qui mélange leurs goûts — les
titres qu'ils écoutent tous les deux d'abord, puis leurs favoris en
alternance. Change chaque jour (tirage du jour, le même pour les deux)."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date

from app.db.repository import Play
from app.services.smart_playlists import playable

SIZE = 40


def _key(p: Play) -> tuple[str, str]:
    return (p.title.casefold(), p.artist.casefold())


def mix(mine: list[Play], theirs: list[Play], seed: str) -> tuple[list[dict], int, int]:
    rng = random.Random(seed)
    my_counts = Counter(_key(p) for p in mine)
    their_counts = Counter(_key(p) for p in theirs)
    shared = sorted(set(my_counts) & set(their_counts), key=lambda k: -(my_counts[k] + their_counts[k]))
    my_top = [k for k, _ in my_counts.most_common(60) if k not in shared]
    their_top = [k for k, _ in their_counts.most_common(60) if k not in shared]
    rng.shuffle(my_top)
    rng.shuffle(their_top)
    keys: list[tuple[str, str]] = list(shared[: SIZE // 3])
    from_me = from_them = 0
    while len(keys) < SIZE and (my_top or their_top):
        if my_top and (from_me <= from_them or not their_top):
            keys.append(my_top.pop())
            from_me += 1
        elif their_top:
            keys.append(their_top.pop())
            from_them += 1
    rest = keys[len(shared[: SIZE // 3]):]
    rng.shuffle(rest)
    ordered = keys[: len(shared[: SIZE // 3])] + rest
    return playable(mine + theirs, ordered), len(shared), len(ordered)


def seed_for(a: int, b: int, day: date | None = None) -> str:
    low, high = sorted((a, b))
    return f"blend-{low}-{high}-{(day or date.today()).isoformat()}"
