"""« Reconnaître un titre » : conversion, identification, recherche dans Sona."""

from __future__ import annotations

import io
import math
import shutil
import struct
import wave

import pytest

from app.providers.base import TrackInfo
from app.services import recognize, search
from tests.test_party_blindtest_concerts import client, login  # noqa: F401


def tone(seconds=3, rate=44100):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<hh", v, v) for v in (int(8000 * math.sin(i / 20)) for i in range(rate * seconds))))
    return buf.getvalue()


def test_parse_shazam_answer():
    answer = {"track": {"title": "Onizuka", "subtitle": "PNL", "images": {"coverart": "https://img/1.jpg"},
                        "sections": [{"metadata": [{"title": "Album", "text": "Dans la légende"}]}]}}
    assert recognize.parse(answer) == {"title": "Onizuka", "artist": "PNL", "album": "Dans la légende", "cover_url": "https://img/1.jpg"}
    assert recognize.parse({"matches": []}) is None


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_recognize_finds_the_track_in_sona(client, monkeypatch):
    seen = {}

    async def fake_identify(wav):
        seen["wav"] = wav
        return {"title": "Onizuka", "artist": "PNL", "album": None, "cover_url": None}

    async def fake_search(deps, query, index=0, limit=20):
        seen["query"] = query.text
        return [TrackInfo("deezer", "42", "Onizuka", "PNL", None, None, 200, None)], 1

    monkeypatch.setattr(recognize, "identify", fake_identify)
    monkeypatch.setattr(search, "search_tracks", fake_search)
    me = login(client, "alice")
    got = client.post("/recognize", headers={**me, "Content-Type": "audio/wav"}, content=tone()).json()
    assert got["found"]["title"] == "Onizuka" and got["track"]["source_id"] == "42"
    assert seen["query"] == "Onizuka PNL"
    # Converti en WAV mono 16 kHz pour la reconnaissance.
    with wave.open(io.BytesIO(seen["wav"])) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_recognize_nothing_found_and_errors(client, monkeypatch):
    async def nothing(wav):
        return None

    monkeypatch.setattr(recognize, "identify", nothing)
    me = login(client, "alice")
    assert client.post("/recognize", headers=me, content=tone()).json() == {"found": None, "track": None}
    assert client.post("/recognize", headers=me, content=b"x" * 10).status_code == 400
    assert client.post("/recognize", headers=me, content=b"pas du son" * 500).status_code == 502

    async def down(wav):
        raise recognize.RecognizeError("Le service de reconnaissance ne répond pas.")

    monkeypatch.setattr(recognize, "identify", down)
    r = client.post("/recognize", headers=me, content=tone())
    assert r.status_code == 502 and "ne répond pas" in r.json()["detail"]
