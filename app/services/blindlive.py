"""Blind test en direct : plusieurs joueurs, les mêmes extraits au même
moment, un classement qui bouge à chaque question.

Même principe que l'écoute ensemble (services/party.py) : tout est en
mémoire, chacun relit l'état toutes les secondes. Le déroulé n'a pas besoin
d'une horloge côté serveur : il avance à la lecture de l'état, d'après
l'heure. Les heures envoyées (`starts_at`, `deadline`) sont des heures
serveur, que chaque téléphone recale avec `server_time`.

Déroulé : salon (l'hôte choisit le thème) → pour chaque extrait, un court
compte à rebours, 15 s pour répondre (fini plus tôt si tout le monde a
répondu), 5 s de correction avec les points de chacun → podium.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from app.services.party import CODE_LENGTH, CODE_LETTERS

QUESTION_SECONDS = 15.0
REVEAL_SECONDS = 5.0
# Laisse aux téléphones le temps de charger l'extrait avant qu'il démarre.
LEAD_SECONDS = 3.0
MEMBER_TIMEOUT = 30
HOST_TIMEOUT = 120
MAX_PLAYERS = 20


class LiveError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Player:
    user_id: int
    name: str
    avatar_url: str | None
    last_seen: float
    score: int = 0
    correct: int = 0
    streak: int = 0


@dataclass
class Answer:
    choice: int
    elapsed: float
    points: int


@dataclass
class Room:
    code: str
    host_user_id: int
    players: dict[int, Player] = field(default_factory=dict)
    # Thème choisi par l'hôte.
    mode: str = "solo"
    ref: str | None = None
    label: str | None = None
    count: int = 10
    guess: str = "title"
    phase: str = "lobby"  # lobby | question | reveal | finished
    # « Complète les paroles » : plus de temps (extrait avant la ligne) et
    # plus d'avance (le titre complet doit se charger).
    question_seconds: float = QUESTION_SECONDS
    lead_seconds: float = LEAD_SECONDS
    questions: list[dict] = field(default_factory=list)
    index: int = 0
    starts_at: float = 0.0
    revealed_at: float = 0.0
    answers: dict[int, Answer] = field(default_factory=dict)
    version: int = 0

    @property
    def host(self) -> Player | None:
        return self.players.get(self.host_user_id)

    @property
    def deadline(self) -> float:
        return self.starts_at + self.question_seconds

    def bump(self) -> None:
        self.version += 1


_rooms: dict[str, Room] = {}


def reset() -> None:
    """Pour les tests."""
    _rooms.clear()


def _now() -> float:
    return time.time()


def _new_code() -> str:
    while True:
        code = "".join(random.choice(CODE_LETTERS) for _ in range(CODE_LENGTH))
        if code not in _rooms:
            return code


def _cleanup(now: float) -> None:
    for code in list(_rooms):
        room = _rooms[code]
        host = room.host
        if host is None or now - host.last_seen > HOST_TIMEOUT:
            del _rooms[code]
            continue
        gone = [u for u, p in room.players.items() if u != room.host_user_id and now - p.last_seen > MEMBER_TIMEOUT]
        for user_id in gone:
            del room.players[user_id]
        if gone:
            room.bump()


def get(code: str) -> Room:
    now = _now()
    _cleanup(now)
    room = _rooms.get(code.upper().strip())
    if room is None:
        raise LiveError(404, "Partie introuvable ou terminée.")
    advance(room, now)
    return room


def all_rooms() -> list[Room]:
    _cleanup(_now())
    return list(_rooms.values())


def hosted_by(user_id: int) -> Room | None:
    _cleanup(_now())
    return next((r for r in _rooms.values() if r.host_user_id == user_id), None)


def leave_all(user_id: int) -> None:
    for room in list(_rooms.values()):
        if user_id in room.players:
            leave(room, user_id)


def create(user_id: int, name: str, avatar_url: str | None) -> Room:
    existing = hosted_by(user_id)
    if existing is not None:
        existing.players[user_id].last_seen = _now()
        return existing
    leave_all(user_id)
    room = Room(code=_new_code(), host_user_id=user_id)
    room.players[user_id] = Player(user_id, name, avatar_url, _now())
    _rooms[room.code] = room
    return room


def join(code: str, user_id: int, name: str, avatar_url: str | None) -> Room:
    room = get(code)
    if user_id not in room.players:
        if len(room.players) >= MAX_PLAYERS:
            raise LiveError(400, "La partie est complète.")
        leave_all(user_id)
        room = get(code)
        room.players[user_id] = Player(user_id, name, avatar_url, _now())
        room.bump()
    room.players[user_id].last_seen = _now()
    return room


def leave(room: Room, user_id: int) -> None:
    if user_id == room.host_user_id:
        _rooms.pop(room.code, None)  # l'hôte part : la partie s'arrête
        return
    if room.players.pop(user_id, None) is not None:
        room.bump()


def touch(room: Room, user_id: int) -> None:
    player = room.players.get(user_id)
    if player is None:
        raise LiveError(403, "Tu ne fais pas partie de cette partie.")
    player.last_seen = _now()


def _require_host(room: Room, user_id: int) -> None:
    if user_id != room.host_user_id:
        raise LiveError(403, "Seul l'hôte choisit et lance la partie.")


def configure(room: Room, user_id: int, mode: str, ref: str | None, label: str | None, count: int, guess: str) -> None:
    _require_host(room, user_id)
    if room.phase in ("question", "reveal"):
        raise LiveError(409, "Une partie est en cours.")
    room.mode, room.ref, room.label, room.count, room.guess = mode, ref, label, count, guess
    room.bump()


def start(room: Room, user_id: int, questions: list[dict]) -> None:
    """Nouvelle partie (ou revanche) : scores remis à zéro."""
    _require_host(room, user_id)
    if len(questions) < 3:
        raise LiveError(422, "Pas assez de titres avec extrait pour ce thème : essaie-en un autre.")
    for player in room.players.values():
        player.score = player.correct = player.streak = 0
    room.questions = questions
    lyrics = questions[0].get("kind") == "lyrics"
    room.question_seconds = QUESTION_SECONDS + (10 if lyrics else 0)
    room.lead_seconds = LEAD_SECONDS + (3 if lyrics else 0)
    room.index = 0
    room.answers = {}
    room.phase = "question"
    room.starts_at = _now() + room.lead_seconds
    room.bump()


def points(elapsed: float, streak: int, total: float = QUESTION_SECONDS) -> int:
    remaining = max(0.0, total - elapsed)
    return 100 + int(remaining * 10) + (50 if streak >= 3 else 0)


def answer(room: Room, user_id: int, index: int, choice: int) -> None:
    touch(room, user_id)
    now = _now()
    advance(room, now)
    if room.phase != "question" or index != room.index:
        raise LiveError(409, "Trop tard pour cette question.")
    if user_id in room.answers:
        return
    if now < room.starts_at:
        raise LiveError(409, "L'extrait n'a pas encore commencé.")
    question = room.questions[room.index]
    if not 0 <= choice < len(question["choices"]):
        raise LiveError(400, "Réponse inconnue.")
    player = room.players[user_id]
    elapsed = now - room.starts_at
    if choice == question["answer"]:
        player.streak += 1
        player.correct += 1
        # Paroles : le chrono ne compte qu'une fois la ligne atteinte.
        head = question["line_time"] - question["clip_start"] if question.get("kind") == "lyrics" else 0.0
        gained = points(max(0.0, elapsed - head), player.streak, room.question_seconds - head)
        player.score += gained
    else:
        player.streak = 0
        gained = 0
    room.answers[user_id] = Answer(choice, round(elapsed, 2), gained)
    room.bump()
    advance(room, now)


def advance(room: Room, now: float) -> None:
    """Fait avancer le déroulé d'après l'heure (appelé à chaque lecture)."""
    while True:
        if room.phase == "question":
            everyone = room.players and all(u in room.answers for u in room.players)
            if now >= room.deadline or everyone:
                for user_id, player in room.players.items():
                    if user_id not in room.answers:
                        player.streak = 0
                room.phase = "reveal"
                room.revealed_at = min(now, room.deadline)
                room.bump()
                continue
        elif room.phase == "reveal" and now >= room.revealed_at + REVEAL_SECONDS:
            if room.index + 1 >= len(room.questions):
                room.phase = "finished"
            else:
                room.index += 1
                room.answers = {}
                room.phase = "question"
                room.starts_at = room.revealed_at + REVEAL_SECONDS + room.lead_seconds
            room.bump()
            continue
        return


def _question_view(room: Room, viewer_id: int) -> dict | None:
    if room.phase not in ("question", "reveal") or not room.questions:
        return None
    q = room.questions[room.index]
    reveal = room.phase == "reveal"
    mine = room.answers.get(viewer_id)
    lyrics = {k: q[k] for k in ("kind", "before", "prompt", "clip_start", "line_time", "reveal_end") if k in q}
    return {
        **lyrics,
        # Paroles : le titre complet (flux de l'app) joue autour de la ligne.
        "stream": {"source": q["track"]["source"], "source_id": q["track"]["source_id"]} if lyrics else None,
        "index": room.index,
        "preview_url": q["preview_url"],
        "choices": q["choices"],
        # La bonne réponse et le titre seulement à la correction.
        "answer": q["answer"] if reveal else None,
        "track": q["track"] if reveal else None,
        "cover_url": q["cover_url"] if reveal else None,
        "my_choice": mine.choice if mine else None,
        "answered": len(room.answers),
    }


def snapshot(room: Room, viewer_id: int) -> dict:
    now = _now()
    host = room.host
    reveal = room.phase in ("reveal", "finished")
    ranking = sorted(room.players.values(), key=lambda p: (-p.score, -p.correct, p.name.casefold()))
    return {
        "code": room.code,
        "is_host": viewer_id == room.host_user_id,
        "host_name": host.name if host else None,
        "phase": room.phase,
        "mode": room.mode,
        "ref": room.ref,
        "label": room.label,
        "count": room.count,
        "guess": room.guess,
        "total": len(room.questions),
        "server_time": now,
        "starts_at": room.starts_at if room.phase == "question" else None,
        "deadline": room.deadline if room.phase == "question" else None,
        "next_at": room.revealed_at + REVEAL_SECONDS if room.phase == "reveal" else None,
        "question": _question_view(room, viewer_id),
        "players": [
            {
                "name": p.name,
                "avatar_url": p.avatar_url,
                "is_host": p.user_id == room.host_user_id,
                "is_me": p.user_id == viewer_id,
                "score": p.score,
                "correct": p.correct,
                "streak": p.streak,
                "answered": p.user_id in room.answers,
                # Points de la dernière question, montrés à la correction.
                "gained": room.answers[p.user_id].points if reveal and p.user_id in room.answers else None,
                "was_right": (room.answers[p.user_id].points > 0) if reveal and p.user_id in room.answers else None,
            }
            for p in ranking
        ],
        "tracks": [q["track"] for q in room.questions] if room.phase == "finished" else [],
        "version": room.version,
    }
