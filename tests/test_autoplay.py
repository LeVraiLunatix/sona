import asyncio
from types import SimpleNamespace

from app.bot import navigation
from app.bot.callbacks import HistoryCB, TrackCB
from app.bot.handlers import history, links, track
from app.db.repository import UserSettings

USER = 7
PLAY_DATA = TrackCB(action="play", source="deezer", id="783257002").pack()


def fake_deps(autoplay=True):
    """Deps réduit au réglage que consulte la lecture automatique."""

    async def get_settings(_user_id):
        return UserSettings("best", "auto", notifications=True, autoplay=autoplay)

    return SimpleNamespace(repo=SimpleNamespace(get_settings=get_settings))


def fake_callback():
    async def answer(*_args, **_kwargs):
        return None

    return SimpleNamespace(
        answer=answer,
        data="x",
        from_user=SimpleNamespace(id=USER),
        message=SimpleNamespace(chat=SimpleNamespace(id=USER)),
    )


def record_navigation_and_playback(monkeypatch):
    """Remplace la navigation et l'envoi du son par des enregistreurs."""
    calls = []

    async def goto(deps, user_id, chat_id, screen, **_kwargs):
        calls.append(("écran", screen.kind, screen.params))

    async def replace_top(deps, user_id, screen):
        calls.append(("écran", screen.kind, screen.params))

    async def play(deps, user_id, chat_id, source, source_id, retry_data):
        calls.append(("son", source, source_id, retry_data))

    monkeypatch.setattr(navigation, "goto", goto)
    monkeypatch.setattr(navigation, "replace_top", replace_top)
    monkeypatch.setattr(track, "play_track", play)
    monkeypatch.setattr(links, "play_track", play)
    return calls


def test_choosing_a_track_in_a_list_sends_the_sound_right_away(monkeypatch):
    calls = record_navigation_and_playback(monkeypatch)
    choice = TrackCB(action="view", source="deezer", id="783257002")
    asyncio.run(track.on_track_view(fake_callback(), choice, fake_deps()))
    assert calls == [
        ("écran", "track", {"source": "deezer", "id": "783257002"}),
        ("son", "deezer", "783257002", PLAY_DATA),
    ]


def test_reopening_a_track_from_history_sends_it_too(monkeypatch):
    calls = record_navigation_and_playback(monkeypatch)
    choice = HistoryCB(action="open", source="deezer", id="783257002")
    asyncio.run(history.on_history_open(fake_callback(), choice, fake_deps()))
    assert calls[-1] == ("son", "deezer", "783257002", PLAY_DATA)


def test_pasted_track_link_sends_the_sound(monkeypatch):
    calls = record_navigation_and_playback(monkeypatch)
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    link = SimpleNamespace(source="deezer", kind="track", ref="783257002")
    asyncio.run(links._handle_detected_link(fake_deps(), message, link))
    assert calls[-2:] == [
        ("écran", "track", {"source": "deezer", "id": "783257002"}),
        ("son", "deezer", "783257002", PLAY_DATA),
    ]


def test_pasted_album_link_only_opens_the_album(monkeypatch):
    """« Tout écouter » reste un choix explicite : un album peut être long."""
    calls = record_navigation_and_playback(monkeypatch)
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    link = SimpleNamespace(source="deezer", kind="album", ref="1")
    asyncio.run(links._handle_detected_link(fake_deps(), message, link))
    assert not [call for call in calls if call[0] == "son"]


# -- Réglage « Lecture automatique » ----------------------------------


def test_autoplay_off_only_opens_the_track_card(monkeypatch):
    """Réglage désactivé : la carte s'ouvre, mais rien n'est envoyé — le
    bouton « Écouter » reste le seul déclencheur."""
    calls = record_navigation_and_playback(monkeypatch)
    choice = TrackCB(action="view", source="deezer", id="783257002")

    asyncio.run(track.on_track_view(fake_callback(), choice, fake_deps(autoplay=False)))

    assert calls == [("écran", "track", {"source": "deezer", "id": "783257002"})]


def test_autoplay_off_also_applies_to_a_pasted_link(monkeypatch):
    calls = record_navigation_and_playback(monkeypatch)
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    link = SimpleNamespace(source="deezer", kind="track", ref="783257002")

    asyncio.run(links._handle_detected_link(fake_deps(autoplay=False), message, link))

    assert not [call for call in calls if call[0] == "son"]
    assert calls[-1] == ("écran", "track", {"source": "deezer", "id": "783257002"})
