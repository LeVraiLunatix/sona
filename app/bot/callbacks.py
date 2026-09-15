from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCB(CallbackData, prefix="nav"):
    action: str  # home | back | link_help


class SearchCB(CallbackData, prefix="search"):
    action: str  # prompt | page | new
    qid: str | None = None
    page: int = 1


class TrackCB(CallbackData, prefix="track"):
    action: str  # view | play | lib_add | lib_del
    source: str
    id: str


class AlbumCB(CallbackData, prefix="album"):
    action: str  # view | page | playall | lib_add | lib_del
    source: str
    id: str
    page: int = 1


class ArtistCB(CallbackData, prefix="artist"):
    action: str  # view | top | albums | singles | search
    source: str
    id: str


class LibraryCB(CallbackData, prefix="library"):
    action: str  # menu | tab | remove | open
    kind: str | None = None
    source: str | None = None
    id: str | None = None
    page: int = 1


class HistoryCB(CallbackData, prefix="history"):
    action: str  # menu | open | clear | clear_confirm | clear_cancel | page
    source: str | None = None
    id: str | None = None
    page: int = 1


class SettingsCB(CallbackData, prefix="settings"):
    action: str  # menu | quality | quality_set | format | format_set | notif_toggle
    value: str | None = None


class AdminCB(CallbackData, prefix="admin"):
    action: str  # menu | invite | invite_multi | revoke | remove_list | remove | requests | approve | deny
    id: str | None = None


class AccessCB(CallbackData, prefix="access"):
    """Boutons accessibles aux utilisateurs pas encore autorisés (voir
    `app/bot/access.py`) — le filtre de whitelist les laisse volontairement
    passer."""

    action: str  # request
