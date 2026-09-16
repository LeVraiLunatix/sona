from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import (
    AccessCB,
    AdminCB,
    AlbumCB,
    ArtistCB,
    HistoryCB,
    LibraryCB,
    NavCB,
    SearchCB,
    SettingsCB,
    TrackCB,
)
from app.db.repository import FORMAT_CHOICES, QUALITY_CHOICES
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo

PAGE_SIZE = 5

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _rows(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def _back_row(back_cb: str, label: str = "← Retour") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=label, callback_data=back_cb)]


def _home_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="Accueil", callback_data=NavCB(action="home").pack())]


def home_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Rechercher", callback_data=SearchCB(action="prompt").pack())],
        [InlineKeyboardButton(text="Coller un lien", callback_data=NavCB(action="link_help").pack())],
        [
            InlineKeyboardButton(text="Bibliothèque", callback_data=LibraryCB(action="menu").pack()),
            InlineKeyboardButton(text="Historique", callback_data=HistoryCB(action="menu").pack()),
        ],
        [InlineKeyboardButton(text="Paramètres", callback_data=SettingsCB(action="menu").pack())],
    )


def link_help_keyboard() -> InlineKeyboardMarkup:
    return _rows(_back_row(NavCB(action="back").pack()))


def search_prompt_keyboard(suggestions: list | None = None) -> InlineKeyboardMarkup:
    """Écran de recherche : un menu de morceaux récents plutôt qu'un écran nu.

    Les suggestions viennent de l'historique — un clic relance l'écran morceau
    sans avoir à retaper quoi que ce soit."""
    rows = [
        # `switch_inline_query_current_chat` pré-remplit le champ de saisie avec
        # "@<bot> " : Telegram ouvre alors le panneau de suggestions au-dessus
        # du clavier et le rafraîchit à chaque frappe (voir handlers/inline.py).
        [
            InlineKeyboardButton(
                text="🔍 Suggestions en direct", switch_inline_query_current_chat=""
            )
        ]
    ]
    for item in suggestions or []:
        artist = (item.subtitle or "").split(" • ")[0]
        label = f"{artist} — {item.title}" if artist else item.title
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=TrackCB(action="view", source=item.source, id=item.source_id).pack(),
                )
            ]
        )
    return _rows(*rows, _back_row(NavCB(action="back").pack()))


def _pagination_row(page: int, total_pages: int, on_page_cb) -> list[InlineKeyboardButton]:
    if total_pages <= 1:
        return []
    row = []
    if page > 1:
        row.append(InlineKeyboardButton(text="←", callback_data=on_page_cb(page - 1)))
    row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        row.append(InlineKeyboardButton(text="→", callback_data=on_page_cb(page + 1)))
    return row


def search_results_keyboard(
    qid: str, page: int, total_pages: int, tracks: list[TrackInfo]
) -> InlineKeyboardMarkup:
    rows = []
    for i, track in enumerate(tracks):
        emoji = NUM_EMOJI[i] if i < len(NUM_EMOJI) else str(i + 1)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{emoji} {track.title}",
                    callback_data=TrackCB(action="view", source=track.source, id=track.source_id).pack(),
                )
            ]
        )
    pag = _pagination_row(page, total_pages, lambda p: SearchCB(action="page", qid=qid, page=p).pack())
    return _rows(
        *rows,
        pag,
        [InlineKeyboardButton(text="Nouvelle recherche", callback_data=SearchCB(action="prompt").pack())],
        _home_row(),
    )


def no_results_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Nouvelle recherche", callback_data=SearchCB(action="prompt").pack())],
        _home_row(),
    )


def track_keyboard(track: TrackInfo, in_library: bool) -> InlineKeyboardMarkup:
    row2 = []
    if track.album_source_id:
        row2.append(InlineKeyboardButton(text="Album", callback_data=AlbumCB(action="view", source=track.source, id=track.album_source_id).pack()))
    if track.artist_source_id:
        row2.append(InlineKeyboardButton(text="Artiste", callback_data=ArtistCB(action="view", source=track.source, id=track.artist_source_id).pack()))

    lib_action = "lib_del" if in_library else "lib_add"
    lib_label = "Retirer de la bibliothèque" if in_library else "Ajouter à la bibliothèque"

    return _rows(
        [InlineKeyboardButton(text="Écouter", callback_data=TrackCB(action="play", source=track.source, id=track.source_id).pack())],
        row2,
        [InlineKeyboardButton(text=lib_label, callback_data=TrackCB(action=lib_action, source=track.source, id=track.source_id).pack())],
        _back_row(NavCB(action="back").pack()),
    )


def album_keyboard(
    album: AlbumInfo, in_library: bool, page: int, total_pages: int, page_tracks: list[TrackInfo]
) -> InlineKeyboardMarkup:
    rows = []
    for i, track in enumerate(page_tracks):
        idx = (page - 1) * PAGE_SIZE + i + 1
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{idx}. {track.title}",
                    callback_data=TrackCB(action="view", source=track.source, id=track.source_id).pack(),
                )
            ]
        )
    pag = _pagination_row(
        page, total_pages, lambda p: AlbumCB(action="page", source=album.source, id=album.source_id, page=p).pack()
    )
    lib_action = "lib_del" if in_library else "lib_add"
    lib_label = "Retirer de la bibliothèque" if in_library else "Ajouter à la bibliothèque"
    return _rows(
        *rows,
        pag,
        [InlineKeyboardButton(text="Tout écouter", callback_data=AlbumCB(action="playall", source=album.source, id=album.source_id).pack())],
        [InlineKeyboardButton(text=lib_label, callback_data=AlbumCB(action=lib_action, source=album.source, id=album.source_id).pack())],
        _back_row(NavCB(action="back").pack()),
    )


def artist_keyboard(artist: ArtistInfo) -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Titres populaires", callback_data=ArtistCB(action="top", source=artist.source, id=artist.source_id).pack())],
        [InlineKeyboardButton(text="Albums", callback_data=ArtistCB(action="albums", source=artist.source, id=artist.source_id).pack())],
        [InlineKeyboardButton(text="Singles & EP", callback_data=ArtistCB(action="singles", source=artist.source, id=artist.source_id).pack())],
        [InlineKeyboardButton(text="Rechercher chez cet artiste", callback_data=ArtistCB(action="search", source=artist.source, id=artist.source_id).pack())],
        _back_row(NavCB(action="back").pack()),
    )


def artist_top_tracks_keyboard(artist: ArtistInfo, tracks: list[TrackInfo]) -> InlineKeyboardMarkup:
    rows = []
    for i, track in enumerate(tracks, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{i}. {track.title}",
                    callback_data=TrackCB(action="view", source=track.source, id=track.source_id).pack(),
                )
            ]
        )
    # Sans titre à envoyer, le bouton ne ferait qu'afficher une alerte.
    playall_row = (
        [
            InlineKeyboardButton(
                text="Tout écouter",
                callback_data=ArtistCB(action="playall", source=artist.source, id=artist.source_id).pack(),
            )
        ]
        if tracks
        else []
    )
    return _rows(*rows, playall_row, _back_row(NavCB(action="back").pack()))


def album_list_keyboard(albums: list[AlbumInfo]) -> InlineKeyboardMarkup:
    rows = []
    for album in albums:
        label = album.title + (f" ({album.year})" if album.year else "")
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=AlbumCB(action="view", source=album.source, id=album.source_id).pack(),
                )
            ]
        )
    return _rows(*rows, _back_row(NavCB(action="back").pack()))


def library_menu_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Morceaux", callback_data=LibraryCB(action="tab", kind="track").pack())],
        [InlineKeyboardButton(text="Albums", callback_data=LibraryCB(action="tab", kind="album").pack())],
        [InlineKeyboardButton(text="Artistes", callback_data=LibraryCB(action="tab", kind="artist").pack())],
        _back_row(NavCB(action="home").pack(), "← Accueil"),
    )


def library_empty_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Rechercher", callback_data=SearchCB(action="prompt").pack())],
        _back_row(NavCB(action="back").pack()),
    )


_OPEN_CB = {
    "track": lambda it: TrackCB(action="view", source=it.source, id=it.source_id).pack(),
    "album": lambda it: AlbumCB(action="view", source=it.source, id=it.source_id).pack(),
    "artist": lambda it: ArtistCB(action="view", source=it.source, id=it.source_id).pack(),
}


def library_list_keyboard(kind: str, items: list, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(text=item.title, callback_data=_OPEN_CB[kind](item)),
                InlineKeyboardButton(
                    text="✕",
                    callback_data=LibraryCB(action="remove", kind=kind, source=item.source, id=item.source_id, page=page).pack(),
                ),
            ]
        )
    pag = _pagination_row(page, total_pages, lambda p: LibraryCB(action="tab", kind=kind, page=p).pack())
    return _rows(*rows, pag, _back_row(LibraryCB(action="menu").pack()))


def history_keyboard(items: list, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        artist_part = (item.subtitle or "").split(" • ")[0]
        label = f"{artist_part} — {item.title}" if artist_part else item.title
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=HistoryCB(action="open", source=item.source, id=item.source_id).pack(),
                )
            ]
        )
    pag = _pagination_row(page, total_pages, lambda p: HistoryCB(action="menu", page=p).pack())
    return _rows(
        *rows,
        pag,
        [InlineKeyboardButton(text="Effacer l'historique", callback_data=HistoryCB(action="clear").pack())],
        _back_row(NavCB(action="home").pack(), "← Accueil"),
    )


def history_empty_keyboard() -> InlineKeyboardMarkup:
    return _rows(_back_row(NavCB(action="home").pack(), "← Accueil"))


def history_clear_confirm_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="Confirmer", callback_data=HistoryCB(action="clear_confirm").pack()),
            InlineKeyboardButton(text="Annuler", callback_data=HistoryCB(action="clear_cancel").pack()),
        ]
    )


def settings_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    admin_row = (
        [InlineKeyboardButton(text="Gestion des accès", callback_data=AdminCB(action="menu").pack())]
        if is_admin
        else []
    )
    return _rows(
        [InlineKeyboardButton(text="Qualité audio", callback_data=SettingsCB(action="quality").pack())],
        [InlineKeyboardButton(text="Format", callback_data=SettingsCB(action="format").pack())],
        [InlineKeyboardButton(text="Notifications", callback_data=SettingsCB(action="notif_toggle").pack())],
        [InlineKeyboardButton(text="Lecture automatique", callback_data=SettingsCB(action="autoplay_toggle").pack())],
        admin_row,
        _back_row(NavCB(action="home").pack(), "← Accueil"),
    )


def admin_menu_keyboard(pending_count: int = 0) -> InlineKeyboardMarkup:
    requests_row = (
        [
            InlineKeyboardButton(
                text=f"Demandes en attente ({pending_count})",
                callback_data=AdminCB(action="requests").pack(),
            )
        ]
        if pending_count
        else []
    )
    return _rows(
        requests_row,
        [InlineKeyboardButton(text="Inviter quelqu'un", callback_data=AdminCB(action="invite").pack())],
        [
            InlineKeyboardButton(
                text="Lien de groupe (10 personnes)",
                callback_data=AdminCB(action="invite_multi").pack(),
            )
        ],
        [InlineKeyboardButton(text="Retirer un accès", callback_data=AdminCB(action="remove_list").pack())],
        _back_row(SettingsCB(action="menu").pack()),
    )


def admin_requests_keyboard(requests: list) -> InlineKeyboardMarkup:
    rows = []
    for req in requests:
        label = req.display_name or (f"@{req.username}" if req.username else str(req.user_id))
        rows.append([InlineKeyboardButton(text=label, callback_data="noop")])
        rows.append(
            [
                InlineKeyboardButton(
                    text="✓ Autoriser",
                    callback_data=AdminCB(action="approve", id=str(req.user_id)).pack(),
                ),
                InlineKeyboardButton(
                    text="✕ Refuser",
                    callback_data=AdminCB(action="deny", id=str(req.user_id)).pack(),
                ),
            ]
        )
    return _rows(*rows, _back_row(AdminCB(action="menu").pack()))


def admin_request_notice_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Clavier du message envoyé aux admins quand quelqu'un demande l'accès.

    Ce message est hors pile de navigation (c'est une notification, pas un
    écran) : ses boutons agissent donc directement sans « Retour »."""
    return _rows(
        [
            InlineKeyboardButton(
                text="✓ Autoriser", callback_data=AdminCB(action="approve", id=str(user_id)).pack()
            ),
            InlineKeyboardButton(
                text="✕ Refuser", callback_data=AdminCB(action="deny", id=str(user_id)).pack()
            ),
        ]
    )


def access_request_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(
                text="Demander l'accès", callback_data=AccessCB(action="request").pack()
            )
        ]
    )


def admin_invite_keyboard(share_url: str, token: str) -> InlineKeyboardMarkup:
    return _rows(
        [InlineKeyboardButton(text="Partager le lien", url=share_url)],
        [
            InlineKeyboardButton(
                text="Annuler ce lien", callback_data=AdminCB(action="revoke", id=token).pack()
            )
        ],
        _back_row(AdminCB(action="menu").pack()),
    )


def admin_remove_list_keyboard(users: list) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        label = u.display_name or str(u.user_id)
        if u.is_admin:
            rows.append([InlineKeyboardButton(text=f"{label} (admin)", callback_data="noop")])
        else:
            rows.append(
                [
                    InlineKeyboardButton(text=label, callback_data="noop"),
                    InlineKeyboardButton(
                        text="✕ Retirer", callback_data=AdminCB(action="remove", id=str(u.user_id)).pack()
                    ),
                ]
            )
    return _rows(*rows, _back_row(AdminCB(action="menu").pack()))


def settings_quality_keyboard(current: str) -> InlineKeyboardMarkup:
    rows = []
    for value, label in QUALITY_CHOICES.items():
        text = f"• {label}" if value == current else label
        rows.append([InlineKeyboardButton(text=text, callback_data=SettingsCB(action="quality_set", value=value).pack())])
    return _rows(*rows, _back_row(SettingsCB(action="menu").pack()))


def settings_format_keyboard(current: str) -> InlineKeyboardMarkup:
    rows = []
    for value, label in FORMAT_CHOICES.items():
        text = f"• {label}" if value == current else label
        rows.append([InlineKeyboardButton(text=text, callback_data=SettingsCB(action="format_set", value=value).pack())])
    return _rows(*rows, _back_row(SettingsCB(action="menu").pack()))


def error_keyboard(retry_callback_data: str, back_callback_data: str | None = None) -> InlineKeyboardMarkup:
    """`back_callback_data` par défaut sur NavCB(action=back) (dépile la pile) —
    à utiliser pour l'échec d'entrée d'un écran fraîchement empilé. Passer
    NavCB(action=dismiss) pour une erreur affichée en place sur un écran déjà
    normalement rendu (ex: échec du bouton "Écouter"), afin que '← Retour'
    restaure cet écran plutôt que de dépiler par-dessus."""
    back_cb = back_callback_data or NavCB(action="back").pack()
    return _rows(
        [InlineKeyboardButton(text="Réessayer", callback_data=retry_callback_data)],
        _back_row(back_cb),
    )
