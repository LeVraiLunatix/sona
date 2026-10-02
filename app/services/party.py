"""« Écoute ensemble » : une session où tout le monde entend le même titre au
même moment, chacun sur son téléphone.

Tout est en mémoire (une session ne survit pas à un redémarrage, et n'a pas
à le faire). L'hôte pilote : il envoie le titre en cours, sa position et
l'état lecture/pause ; les autres suivent en relisant l'état toutes les deux
secondes. La position est donnée par une « ancre » : l'heure (serveur) à
laquelle le titre aurait commencé — chacun en déduit où en être maintenant,
quel que soit le moment où il demande.

En plus : discussion, vote pour passer le titre, contrôle partagé (les
invités peuvent mettre en pause ou passer, si l'hôte l'autorise), titres
déjà joués, retrait d'un membre, et passage de la main — à la demande, ou
tout seul si le téléphone de l'hôte ne répond plus (la session continue au
lieu de s'arrêter pour tout le monde).
"""

from __future__ import annotations

import asyncio
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
MAX_MESSAGES = 50
MAX_MESSAGE_LENGTH = 300
HISTORY_SIZE = 30
# Commandes des invités (contrôle partagé) : l'hôte les exécute à sa
# prochaine lecture de l'état ; trop vieilles, elles n'ont plus de sens.
COMMAND_TTL = 20
COMMANDS = ("play", "pause", "next", "previous")


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
    by_user_id: int | None = None


@dataclass
class Message:
    id: int
    user_id: int
    by: str
    avatar_url: str | None
    text: str
    at: float


@dataclass
class Command:
    id: int
    action: str
    by: str
    at: float


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
    messages: list[Message] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    # Vote pour passer le titre en cours (remis à zéro à chaque titre).
    skip_votes: set[int] = field(default_factory=set)
    # Contrôle partagé : les invités peuvent mettre en pause, reprendre, passer.
    open_controls: bool = False
    banned: set[int] = field(default_factory=set)
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

    def take_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def skip_needed(self) -> int:
        """La moitié des invités (arrondie au-dessus), au moins un."""
        guests = len(self.members) - 1
        return max(1, (guests + 1) // 2)


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
        for user_id in [u for u, m in party.members.items() if u != party.host_user_id and now - m.last_seen > MEMBER_TIMEOUT]:
            del party.members[user_id]
            party.skip_votes.discard(user_id)
            party.bump()
        host = party.host
        if host is None or now - host.last_seen > HOST_TIMEOUT:
            # Téléphone de l'hôte éteint ou hors réseau : le membre le plus
            # présent reprend la main, la musique continue pour les autres.
            others = [m for m in party.members.values() if m.user_id != party.host_user_id]
            if not others:
                del _parties[code]
                continue
            if host is not None:
                del party.members[party.host_user_id]
            _set_host(party, max(others, key=lambda m: m.last_seen).user_id)
        party.reactions = [r for r in party.reactions if now - r.at <= REACTION_TTL]
        party.commands = [c for c in party.commands if now - c.at <= COMMAND_TTL]


def _set_host(party: Party, user_id: int) -> None:
    party.host_user_id = user_id
    party.skip_votes.discard(user_id)
    party.commands = []
    party.bump()


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
    if user_id in party.banned:
        raise PartyError(403, "L'hôte t'a retiré de cette session.")
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
        party.skip_votes.discard(user_id)
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
    if _track_key(track) != _track_key(party.track):
        party.skip_votes = set()
        if track is not None:
            party.history = [h for h in party.history if _track_key(h) != _track_key(track)]
            party.history.insert(0, track)
            del party.history[HISTORY_SIZE:]
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
    if any(_track_key(q.track) == _track_key(track) for q in party.queue):
        raise PartyError(409, "Ce titre est déjà proposé : vote pour lui !")
    item = QueueItem(party.take_id(), track, party.members[user_id].name, {user_id}, user_id)
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


def unpropose(party: Party, user_id: int, item_id: int) -> None:
    """Retire une proposition : l'hôte, ou celui qui l'a faite."""
    touch(party, user_id)
    item = next((q for q in party.queue if q.id == item_id), None)
    if item is None:
        raise PartyError(404, "Proposition introuvable (déjà jouée ?).")
    if user_id not in (party.host_user_id, item.by_user_id):
        raise PartyError(403, "Seul l'hôte ou l'auteur retire une proposition.")
    party.queue.remove(item)
    party.bump()


def react(party: Party, user_id: int, emoji: str) -> None:
    touch(party, user_id)
    party.reactions.append(Reaction(party.take_id(), emoji[:8], party.members[user_id].name, _now()))
    party.reactions = party.reactions[-30:]
    party.bump()


def say(party: Party, user_id: int, text: str) -> None:
    touch(party, user_id)
    text = " ".join(text.split())[:MAX_MESSAGE_LENGTH]
    if not text:
        raise PartyError(400, "Message vide.")
    member = party.members[user_id]
    party.messages.append(Message(party.take_id(), user_id, member.name, member.avatar_url, text, _now()))
    del party.messages[:-MAX_MESSAGES]
    party.bump()


def vote_skip(party: Party, user_id: int) -> None:
    """Vote (ou retire son vote) pour passer le titre en cours."""
    touch(party, user_id)
    if party.track is None:
        raise PartyError(409, "Rien à passer pour l'instant.")
    if user_id == party.host_user_id:
        raise PartyError(400, "Tu es l'hôte : passe le titre directement.")
    if user_id in party.skip_votes:
        party.skip_votes.discard(user_id)
    else:
        party.skip_votes.add(user_id)
    party.bump()


def command(party: Party, user_id: int, action: str) -> None:
    """Contrôle partagé : un invité demande lecture, pause ou titre suivant."""
    touch(party, user_id)
    if action not in COMMANDS:
        raise PartyError(400, f"Action inconnue : {action}")
    if user_id != party.host_user_id and not party.open_controls:
        raise PartyError(403, "L'hôte n'a pas ouvert le contrôle aux invités.")
    party.commands.append(Command(party.take_id(), action, party.members[user_id].name, _now()))
    party.bump()


def configure(party: Party, user_id: int, open_controls: bool | None) -> None:
    if user_id != party.host_user_id:
        raise PartyError(403, "Seul l'hôte règle la session.")
    if open_controls is not None:
        party.open_controls = open_controls
    party.bump()


def transfer(party: Party, user_id: int, new_host: int) -> None:
    """L'hôte passe la main à un autre membre."""
    if user_id != party.host_user_id:
        raise PartyError(403, "Seul l'hôte peut passer la main.")
    if new_host not in party.members or new_host == user_id:
        raise PartyError(404, "Ce membre n'est plus dans la session.")
    _set_host(party, new_host)


def kick(party: Party, user_id: int, member_id: int) -> None:
    if user_id != party.host_user_id:
        raise PartyError(403, "Seul l'hôte peut retirer quelqu'un.")
    if member_id == user_id:
        raise PartyError(400, "Tu ne peux pas te retirer toi-même : quitte la session.")
    if member_id not in party.members:
        raise PartyError(404, "Ce membre n'est plus dans la session.")
    party.banned.add(member_id)
    leave(party, member_id)


def _track_key(track: dict | None) -> tuple | None:
    return (track.get("source"), str(track.get("source_id"))) if track else None


async def wait_change(party: Party, since: int, timeout: float) -> None:
    """Attend un changement de la session (au plus `timeout` s) : les invités
    suivent un changement de titre ou une pause tout de suite, sans relire
    l'état en boucle."""
    deadline = _now() + min(max(timeout, 0.0), 25.0)
    while party.version == since and _now() < deadline and _parties.get(party.code) is party:
        await asyncio.sleep(0.2)


def snapshot(party: Party, viewer_id: int) -> dict:
    now = _now()
    host = party.host
    return {
        "code": party.code,
        "is_host": viewer_id == party.host_user_id,
        "host_name": host.name if host else None,
        "members": [
            {"id": m.user_id, "name": m.name, "avatar_url": m.avatar_url, "is_host": m.user_id == party.host_user_id,
             "is_me": m.user_id == viewer_id}
            for m in sorted(party.members.values(), key=lambda m: (m.user_id != party.host_user_id, m.name))
        ],
        "track": party.track,
        "paused": party.paused,
        "position": party.position(now),
        "server_time": now,
        "queue": [
            {"id": q.id, "track": q.track, "by": q.by, "votes": len(q.votes), "voted": viewer_id in q.votes,
             "mine": q.by_user_id == viewer_id}
            for q in ordered_queue(party)
        ],
        "reactions": [{"id": r.id, "emoji": r.emoji, "by": r.by, "age": now - r.at} for r in party.reactions],
        "messages": [
            {"id": m.id, "by": m.by, "avatar_url": m.avatar_url, "text": m.text, "mine": m.user_id == viewer_id, "age": now - m.at}
            for m in party.messages
        ],
        "skip": {"votes": len(party.skip_votes), "needed": party.skip_needed(), "voted": viewer_id in party.skip_votes},
        "open_controls": party.open_controls,
        # Seul l'hôte exécute les commandes des invités.
        "commands": [{"id": c.id, "action": c.action, "by": c.by} for c in party.commands] if viewer_id == party.host_user_id else [],
        "history": party.history,
        "version": party.version,
    }
