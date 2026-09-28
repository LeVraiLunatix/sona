from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db.repository import Account, Repository
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.lastfm_auth import LastfmAuthClient
from app.providers.lrclib import LrclibClient
from app.providers.spotify import SpotifyClient


@dataclass(slots=True)
class ApiDeps:
    """Équivalent de `app.bot.deps.Deps` pour l'API. Partagé par toutes les
    requêtes ; `require_token` en renvoie une copie rattachée au compte qui
    appelle (`account`, `user_id`)."""

    settings: Settings
    repo: Repository
    deezer: DeezerClient
    apple: AppleMusicClient
    spotify: SpotifyClient
    lrclib: LrclibClient
    lastfm_auth: LastfmAuthClient | None = None
    account: Account | None = None
    is_admin: bool = False
    user_id_override: int | None = None

    @property
    def user_id(self) -> int:
        """Espace de données de l'appelant : celui de son compte, ou celui de
        l'ancien jeton unique (API_USER_ID)."""
        return self.user_id_override if self.user_id_override is not None else self.settings.api_user_id
