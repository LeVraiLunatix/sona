"""Santé de la lecture : Sona sait-il encore sortir du son de YouTube ?

Chaque préparation de titre (réussie ou non) est notée ici avec la cause de
l'échec. Quand les échecs s'accumulent, l'état passe à « dégradé » puis « en
panne », avec la cause la plus probable et quoi faire — affichés dans l'app
(Réglages → Santé de la lecture), sur /health (surveillance GitHub) et
envoyés aux admins sur Telegram.

Les causes :
- `cookies` : YouTube demande de prouver qu'on n'est pas un robot (session
  Google morte ou adresse du serveur repérée) ;
- `ytdlp` : YouTube a changé quelque chose et yt-dlp n'arrive plus à lire
  les formats (signature, défi « n », format introuvable) — une mise à jour
  de yt-dlp règle ça ;
- `network` : YouTube injoignable ou qui refuse (403, délais) ;
- `other` : le reste (titre introuvable, audio non conforme…), sans rapport
  avec une panne.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass

WINDOW_SECONDS = 30 * 60
MAX_EVENTS = 200

ADVICE = {
    "cookies": "YouTube bloque le serveur (vérification anti-robot). Renvoie des cookies YouTube frais : "
               "Réglages → Santé de la lecture → Cookies YouTube.",
    "ytdlp": "YouTube a changé quelque chose. La mise à jour automatique de yt-dlp passe chaque nuit ; "
             "pour la lancer tout de suite : Réglages → Santé de la lecture → Mettre à jour.",
    "network": "YouTube ne répond pas au serveur, ou le refuse. Souvent passager ; si ça dure, "
               "renouvelle les cookies YouTube.",
}
LABELS = {
    "cookies": "cookies YouTube",
    "ytdlp": "yt-dlp dépassé",
    "network": "YouTube injoignable",
    "other": "titres introuvables",
}


@dataclass(slots=True)
class Event:
    at: float
    ok: bool
    cause: str | None = None


_events: deque[Event] = deque(maxlen=MAX_EVENTS)


def reset() -> None:
    """Pour les tests."""
    _events.clear()


def classify(message: str, bot_wall: bool = False) -> str:
    """Cause d'un échec de téléchargement, d'après le message de yt-dlp."""
    text = message.lower()
    if bot_wall or "sign in to confirm" in text or "not a bot" in text or "cookies" in text:
        return "cookies"
    if any(k in text for k in (
        "signature", "nsig", "n challenge", "requested format is not available", "unable to extract",
        "player response", "js challenge", "ejs", "only images are available",
    )):
        return "ytdlp"
    if any(k in text for k in ("http error 403", "http error 429", "timed out", "timeout", "connection", "unreachable")):
        return "network"
    return "other"


def record(ok: bool, cause: str | None = None, now: float | None = None) -> None:
    _events.append(Event(at=now if now is not None else time.time(), ok=ok, cause=None if ok else (cause or "other")))


def status(now: float | None = None) -> dict:
    """État sur la dernière demi-heure. Seuls les échecs « de panne »
    (cookies, yt-dlp, réseau) comptent : un titre introuvable n'est pas une
    panne du serveur."""
    now = now if now is not None else time.time()
    recent = [e for e in _events if now - e.at <= WINDOW_SECONDS]
    outages = [e for e in recent if not e.ok and e.cause != "other"]
    successes = sum(1 for e in recent if e.ok)
    total = successes + len(outages)
    ratio = len(outages) / total if total else 0.0
    # Pas de fausse alerte sur un seul échec : il en faut plusieurs d'affilée.
    last = [e for e in recent if e.ok or e.cause != "other"][-3:]
    streak = len(last) == 3 and all(not e.ok for e in last)
    if len(outages) >= 3 and (ratio >= 0.6 or streak):
        state = "down"
    elif len(outages) >= 2 and ratio >= 0.3:
        state = "degraded"
    else:
        state = "ok"
    cause = Counter(e.cause for e in outages).most_common(1)[0][0] if outages and state != "ok" else None
    last_ok = max((e.at for e in recent if e.ok), default=None) if recent else None
    return {
        "state": state,
        "cause": cause,
        "cause_label": LABELS.get(cause) if cause else None,
        "advice": ADVICE.get(cause) if cause else None,
        "recent_ok": successes,
        "recent_failures": len(outages),
        "last_success_seconds": round(now - last_ok) if last_ok else None,
    }


def alert_for(previous: str, current: dict) -> str | None:
    """Message aux admins quand l'état change (panne, ou retour à la normale)."""
    state = current["state"]
    if state == previous:
        return None
    if state == "down":
        return f"🔴 Lecture en panne sur Sona ({current['cause_label']}).\n\n{current['advice']}"
    if state == "degraded" and previous == "ok":
        return f"🟠 Lecture perturbée sur Sona ({current['cause_label']}).\n\n{current['advice']}"
    if state == "ok" and previous in ("down", "degraded"):
        return "✅ La lecture refonctionne normalement sur Sona."
    return None
