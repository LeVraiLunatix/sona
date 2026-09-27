from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db.repository import Repository
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.spotify import SpotifyClient


@dataclass(slots=True)
class ApiDeps:
    """Équivalent de `app.bot.deps.Deps` pour l'API : pas de bot Telegram,
    et un seul utilisateur (`settings.api_user_id`), l'API étant strictement
    personnelle (voir README)."""

    settings: Settings
    repo: Repository
    deezer: DeezerClient
    apple: AppleMusicClient
    spotify: SpotifyClient

    @property
    def user_id(self) -> int:
        return self.settings.api_user_id
