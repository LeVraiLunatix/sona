"""« Écoute ensemble » : une session où tout le monde entend le même titre au
même moment, chacun sur son téléphone.

Tout est en mémoire (une session ne survit pas à un redémarrage, et n'a pas
à le faire). L'hôte pilote : il envoie le titre en cours, sa position et
l'état lecture/pause ; les autres suivent en relisant l'état toutes les deux
secondes. La position est donnée par une « ancre » : l'heure (serveur) à
laquelle le titre aurait commencé — chacun en déduit où en être maintenant,
quel que soit le moment où il demande.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # sans I ni O (confondus avec 1 et 0)
CODE_LENGTH = 5
# Un membre qui n'a pas relu l'état depuis ce délai n'est plus compté.
MEMBER_TIMEOUT = 30
# Hôte silencieux depuis ce délai : la session est close.
HOST_TIMEOUT = 120
REACTION_TTL = 12
MAX_QUEUE = 100


class PartyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Member:
    user_id: int
    name: str
    avatar_url: str | None
    last_seen: float


@dataclass
class QueueItem:
    id: int
    track: dict
    by: str
    # Soirée : les membres votent pour les propositions ; les plus votées
    # passent devant dans la file de l'hôte.
    votes: set[int] = field(default_factory=set)


@dataclass
class Reaction:
    id: int
    emoji: str
    by: str
    at: float


@dataclass
class Party:
    code: str
    host_user_id: int
    members: dict[int, Member] = field(default_factory=dict)
    track: dict | None = None
    # Heure serveur où la position 0 du titre en cours tombe (lecture), ou
    # position figée (pause).
    anchor: float | None = None
    paused: bool = True
    paused_position: float = 0.0
    queue: list[QueueItem] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    version: int = 0
    next_id: int = 1
    created_at: float = field(default_factory=time.time)

    @property
    def host(self) -> Member | None:
        return self.members.get(self.host_user_id)

    def position(self, now: float) -> float:
        if self.paused or self.anchor is None:
            return self.paused_position
        return max(0.0, now - self.anchor)

    def bump(self) -> None:
        self.version += 1


_parties: dict[str, Party] = {}


def reset() -> None:
    """Pour les tests."""
    _parties.clear()


def _now() -> float:
    return time.time()


def _new_code() -> str:
    while True:
        code = "".join(random.choice(CODE_LETTERS) for _ in range(CODE_LENGTH))
        if code not in _parties:
            return code


def _cleanup(now: float) -> None:
    for code in list(_parties):
        party = _parties[code]
        host = party.host
        if host is None or now - host.last_seen > HOST_TIMEOUT:
            del _parties[code]
            continue
        for user_id in [u for u, m in party.members.items() if u != party.host_user_id and now - m.last_seen > MEMBER_TIMEOUT]:
            del party.members[user_id]
        party.reactions = [r for r in party.reactions if now - r.at <= REACTION_TTL]


def get(code: str) -> Party:
    _cleanup(_now())
    party = _parties.get(code.upper().strip())
    if party is None:
        raise PartyError(404, "Session introuvable ou terminée.")
    return party


def hosted_by(user_id: int) -> Party | None:
    _cleanup(_now())
    return next((p for p in _parties.values() if p.host_user_id == user_id), None)


def all_parties() -> list[Party]:
    _cleanup(_now())
    return list(_parties.values())


def create(user_id: int, name: str, avatar_url: str | None) -> Party:
    existing = hosted_by(user_id)
    if existing is not None:
        existing.members[user_id].last_seen = _now()
        return existing
    # Un hôte ne peut pas être en même temps invité ailleurs.
    leave_all(user_id)
    party = Party(code=_new_code(), host_user_id=user_id)
    party.members[user_id] = Member(user_id, name, avatar_url, _now())
    _parties[party.code] = party
    return party


def leave_all(user_id: int) -> None:
    for party in list(_parties.values()):
        if user_id in party.members:
            leave(party, user_id)


def join(code: str, user_id: int, name: str, avatar_url: str | None) -> Party:
    party = get(code)
    if user_id not in party.members:
        leave_all(user_id)
        party = get(code)
        party.members[user_id] = Member(user_id, name, avatar_url, _now())
        party.bump()
    party.members[user_id].last_seen = _now()
    return party


def leave(party: Party, user_id: int) -> None:
    if user_id == party.host_user_id:
        _parties.pop(party.code, None)  # l'hôte part : la session s'arrête
        return
    if party.members.pop(user_id, None) is not None:
        party.bump()


def touch(party: Party, user_id: int) -> None:
    member = party.members.get(user_id)
    if member is None:
        raise PartyError(403, "Tu ne fais pas partie de cette session.")
    member.last_seen = _now()


def set_state(party: Party, user_id: int, track: dict | None, position: float, paused: bool) -> None:
    if user_id != party.host_user_id:
        raise PartyError(403, "Seul l'hôte pilote la lecture.")
    now = _now()
    party.track = track
    party.paused = paused
    party.paused_position = max(0.0, position)
    party.anchor = None if paused else now - max(0.0, position)
    party.members[user_id].last_seen = now
    party.bump()


def propose(party: Party, user_id: int, track: dict) -> QueueItem:
    touch(party, user_id)
    if len(party.queue) >= MAX_QUEUE:
        raise PartyError(400, "La file de la session est pleine.")
    item = QueueItem(party.next_id, track, party.members[user_id].name, {user_id})
    party.next_id += 1
    party.queue.append(item)
    party.bump()
    return item


def vote(party: Party, user_id: int, item_id: int) -> None:
    """Vote (ou retire son vote) pour une proposition."""
    touch(party, user_id)
    item = next((q for q in party.queue if q.id == item_id), None)
    if item is None:
        raise PartyError(404, "Proposition introuvable (déjà jouée ?).")
    if user_id in item.votes:
        item.votes.discard(user_id)
    else:
        item.votes.add(user_id)
    party.bump()


def ordered_queue(party: Party) -> list[QueueItem]:
    """Les plus votées d'abord, puis par ordre d'arrivée."""
    return sorted(party.queue, key=lambda q: (-len(q.votes), q.id))


def consume(party: Party, user_id: int, ids: list[int]) -> None:
    """L'hôte a repris ces propositions dans sa file de lecture."""
    if user_id != party.host_user_id:
        raise PartyError(403, "Seul l'hôte gère la file.")
    wanted = set(ids)
    party.queue = [q for q in party.queue if q.id not in wanted]
    party.bump()


def react(party: Party, user_id: int, emoji: str) -> None:
    touch(party, user_id)
    party.reactions.append(Reaction(party.next_id, emoji[:8], party.members[user_id].name, _now()))
    party.next_id += 1
    party.reactions = party.reactions[-30:]
    party.bump()


def snapshot(party: Party, viewer_id: int) -> dict:
    now = _now()
    host = party.host
    return {
        "code": party.code,
        "is_host": viewer_id == party.host_user_id,
        "host_name": host.name if host else None,
        "members": [
            {"name": m.name, "avatar_url": m.avatar_url, "is_host": m.user_id == party.host_user_id}
            for m in sorted(party.members.values(), key=lambda m: (m.user_id != party.host_user_id, m.name))
        ],
        "track": party.track,
        "paused": party.paused,
        "position": party.position(now),
        "server_time": now,
        "queue": [
            {"id": q.id, "track": q.track, "by": q.by, "votes": len(q.votes), "voted": viewer_id in q.votes}
            for q in ordered_queue(party)
        ],
        "reactions": [{"id": r.id, "emoji": r.emoji, "by": r.by, "age": now - r.at} for r in party.reactions],
        "version": party.version,
    }
