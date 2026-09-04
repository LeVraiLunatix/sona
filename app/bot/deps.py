from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot

from app.config import Settings
from app.db.repository import Repository
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.spotify import SpotifyClient


@dataclass(slots=True)
class Deps:
    bot: Bot
    settings: Settings
    repo: Repository
    deezer: DeezerClient
    apple: AppleMusicClient
    spotify: SpotifyClient
