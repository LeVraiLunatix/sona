"""Karaoké : file de séparation voix / instru, état, pistes servies, et le
calcul lui-même (sans vrai modèle : faux calcul ou faux réseau)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.routers import stream
from app.config import load_settings
from app.services import karaoke, separation

AUTH = {"Authorization": "Bearer test-token"}


class FakeEngine:
    """Remplace le sous-processus : écrit deux petites pistes, et peut être
    retenu (`gate`) pour observer la file pendant un calcul."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.gate: asyncio.Event | None = None
        # Retient seulement la passe fine.
        self.hq_gate: asyncio.Event | None = None
        self.fail: str | None = None

    async def __call__(self, settings, audio, model, vocals, instrumental, on_progress, quality="hq"):
        self.calls.append(f"{Path(audio).stem}:{quality}")
        on_progress(0.5)
        if self.gate is not None:
            await self.gate.wait()
        if quality == "hq" and self.hq_gate is not None:
            await self.hq_gate.wait()
        if self.fail:
            raise karaoke.SeparationError(self.fail)
        # Contenu différent par passe : on voit laquelle est servie.
        vocals.write_bytes((b"V" if quality == "fast" else b"W") * 1000)
        instrumental.write_bytes((b"I" if quality == "fast" else b"J") * 1000)
        on_progress(1.0)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    fake = FakeEngine()

    async def source_audio(deps, source, source_id):
        return tmp_path / f"{source}_{source_id}.m4a"

    async def model(settings, quality="hq"):
        return tmp_path / f"{quality}.onnx"

    monkeypatch.setattr(karaoke, "run_separation", fake)
    monkeypatch.setattr(karaoke, "_source_audio", source_audio)
    monkeypatch.setattr(karaoke, "ensure_model", model)
    monkeypatch.setattr(karaoke, "engine_available", lambda: True)
    return fake


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("KARAOKE_DIR", str(tmp_path / "karaoke"))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        yield test_client


def wait_for(client, path: str, wanted: str, timeout: float = 5, quality: str | None = None) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        state = client.get(path, headers=AUTH).json()
        done = state["status"] == wanted and (quality is None or state.get("quality") == quality)
        if done or time.monotonic() > deadline:
            return state
        time.sleep(0.02)


def test_separation_then_stems_with_range(client, engine):
    assert client.get("/stream/deezer/5/karaoke/vocals", headers=AUTH).status_code == 404
    assert client.get("/karaoke/deezer/5", headers=AUTH).json()["status"] == "absent"

    first = client.post("/karaoke/deezer/5", headers=AUTH).json()
    assert first["status"] in {"queued", "running", "ready"}
    assert wait_for(client, "/karaoke/deezer/5", "ready")["status"] == "ready"
    # Passe rapide d'abord, puis la passe fine la remplace d'elle-même.
    assert wait_for(client, "/karaoke/deezer/5", "ready", quality="hq")["quality"] == "hq"
    assert engine.calls == ["deezer_5:fast", "deezer_5:hq"]
    assert not any((client.app.state.deps.settings.karaoke_dir).glob("*_fast_*"))

    whole = client.get("/stream/deezer/5/karaoke/instrumental", headers=AUTH)
    assert whole.status_code == 200 and whole.content == b"J" * 1000
    assert whole.headers["content-type"] == "audio/mp4"
    assert whole.headers["x-karaoke-quality"] == "hq"
    part = client.get("/stream/deezer/5/karaoke/vocals", headers={**AUTH, "Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"WWWW"
    assert client.get("/stream/deezer/5/karaoke/vocals?quality=fast", headers=AUTH).status_code == 404
    # Lecteur web : jeton dans l'adresse, accepté pour les flux /stream/.
    assert client.get("/stream/deezer/5/karaoke/vocals?token=test-token").status_code == 200
    assert client.get("/stream/deezer/5/karaoke/autre", headers=AUTH).status_code == 404
    # Déjà prêt : redemander ne relance rien.
    assert client.post("/karaoke/deezer/5", headers=AUTH).json()["status"] == "ready"
    assert engine.calls == ["deezer_5:fast", "deezer_5:hq"]


def test_fast_stems_are_served_while_refining(client, engine):
    """Passe rapide prête : l'app peut chanter, la passe fine continue."""
    engine.hq_gate = asyncio.Event()
    client.post("/karaoke/deezer/5", headers=AUTH)
    state = wait_for(client, "/karaoke/deezer/5", "ready")
    assert state["quality"] == "fast"
    assert wait_for(client, "/karaoke/deezer/5", "ready")["refining"]["quality"] == "hq"
    got = client.get("/stream/deezer/5/karaoke/vocals", headers=AUTH)
    assert got.content == b"V" * 1000 and got.headers["x-karaoke-quality"] == "fast"
    assert client.get("/stream/deezer/5/karaoke/instrumental?quality=fast", headers=AUTH).content == b"I" * 1000
    assert client.get("/stream/deezer/5/karaoke/instrumental?quality=hq", headers=AUTH).status_code == 404
    client.portal.call(engine.hq_gate.set)
    assert wait_for(client, "/karaoke/deezer/5", "ready", quality="hq")["quality"] == "hq"


def test_listening_interrupts_a_refine(client, engine):
    """Une passe fine en cours s'efface devant un titre à chanter maintenant."""
    deps = client.app.state.deps
    settings = deps.settings
    settings.karaoke_dir.mkdir(parents=True, exist_ok=True)
    for stem in karaoke.STEMS:
        karaoke.stem_path(settings, "deezer", "old", stem, "fast").write_bytes(b"x")
    engine.gate = asyncio.Event()
    assert client.post("/karaoke/deezer/old", headers=AUTH).json()["quality"] == "fast"
    running = wait_for(client, "/karaoke/deezer/old", "ready")
    assert running["refining"]["status"] == "running"
    client.post("/karaoke/deezer/new", headers=AUTH)
    assert karaoke._jobs[("deezer", "old", "hq")].preempted
    client.portal.call(engine.gate.set)
    wait_for(client, "/karaoke/deezer/new", "ready", quality="hq")


def test_requires_auth(client, engine):
    assert client.post("/karaoke/deezer/5").status_code == 401
    assert client.get("/karaoke/deezer/5?token=test-token").status_code == 401


def test_current_track_goes_before_upcoming(client, engine):
    engine.gate = asyncio.Event()
    client.post("/karaoke/deezer/1", headers=AUTH)
    assert wait_for(client, "/karaoke/deezer/1", "running")["progress"] == 0.5
    upcoming = client.post(
        "/karaoke/prepare", headers=AUTH,
        json={"tracks": [{"source": "deezer", "source_id": "2"}, {"source": "deezer", "source_id": "3"}]},
    ).json()
    assert [t["status"] for t in upcoming] == ["queued", "queued"]
    # Le titre écouté maintenant passe devant les suivants de la file.
    client.post("/karaoke/deezer/4", headers=AUTH)
    state = client.get("/karaoke/deezer/2", headers=AUTH).json()
    assert state["status"] == "queued" and state["ahead"] == 2
    client.portal.call(engine.gate.set)
    wait_for(client, "/karaoke/deezer/4", "ready", quality="hq")
    # Toutes les passes rapides d'abord, puis les passes fines — seulement
    # pour les titres chantés : un titre « à venir » attend d'être chanté.
    assert engine.calls == [
        "deezer_1:fast", "deezer_4:fast", "deezer_2:fast", "deezer_3:fast",
        "deezer_1:hq", "deezer_4:hq",
    ]
    assert client.get("/karaoke/deezer/3", headers=AUTH).json()["quality"] == "fast"
    # Chanté ensuite : sa passe fine est lancée.
    client.post("/karaoke/deezer/3", headers=AUTH)
    assert wait_for(client, "/karaoke/deezer/3", "ready", quality="hq")["quality"] == "hq"


def test_failure_is_reported_and_remembered(client, engine):
    engine.fail = "Titre trop long pour la séparation."
    client.post("/karaoke/deezer/9", headers=AUTH)
    state = wait_for(client, "/karaoke/deezer/9", "failed")
    assert state["status"] == "failed" and "trop long" in state["error"]
    # Pas de nouvel essai immédiat : l'app garde l'ancien mode.
    engine.fail = None
    assert client.post("/karaoke/deezer/9", headers=AUTH).json()["status"] == "failed"
    assert len(engine.calls) == 1


def test_missing_engine_falls_back_cleanly(client, engine, monkeypatch):
    monkeypatch.setattr(karaoke, "engine_available", lambda: False)
    client.post("/karaoke/deezer/7", headers=AUTH)
    state = wait_for(client, "/karaoke/deezer/7", "failed")
    assert "indisponible" in state["error"]
    assert engine.calls == []


def test_night_job_gives_way_to_listening(client, engine):
    deps = client.app.state.deps
    engine.gate = asyncio.Event()
    started = []

    async def queue_night():
        karaoke.request(deps, "deezer", "night", karaoke.NIGHT)

    client.portal.call(queue_night)
    wait_for(client, "/karaoke/deezer/night", "running")
    started.append(karaoke._running.source_id)
    # Pas de vrai sous-processus ici : on vérifie que la séparation de nuit
    # est bien marquée à interrompre et remise en file après le titre écouté.
    client.post("/karaoke/deezer/now", headers=AUTH)
    assert karaoke._jobs[("deezer", "night", "hq")].preempted
    client.portal.call(engine.gate.set)
    wait_for(client, "/karaoke/deezer/now", "ready")
    assert started == ["night"]


def test_wrong_version_forgets_stems(client, engine):
    client.post("/karaoke/deezer/5", headers=AUTH)
    wait_for(client, "/karaoke/deezer/5", "ready", quality="hq")
    assert client.post("/stream/deezer/5/wrong-version", headers=AUTH).status_code == 200
    assert client.get("/karaoke/deezer/5", headers=AUTH).json()["status"] == "absent"


def test_prune_removes_oldest_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DIR", str(tmp_path))
    settings = load_settings()
    from dataclasses import replace

    settings = replace(settings, karaoke_cache_max_mb=0)
    for index, name in enumerate(["old", "mid", "new"]):
        for stem in karaoke.STEMS:
            path = karaoke.stem_path(settings, "deezer", name, stem)
            path.write_bytes(b"x" * 100)
            stamp = 1_000_000 + index * 100
            import os

            os.utime(path, (stamp, stamp))
    assert karaoke.prune(settings, keep=("deezer", "old")) == 2
    assert karaoke.is_ready(settings, "deezer", "old")
    assert not karaoke.is_ready(settings, "deezer", "mid")
    assert not any(tmp_path.glob("deezer_mid_*"))
    # Les pistes rapides d'un titre partent avec lui.
    for stem in karaoke.STEMS:
        karaoke.stem_path(settings, "deezer", "new", stem, "fast").write_bytes(b"x" * 100)
    assert karaoke.prune(settings, keep=("deezer", "old")) == 1
    assert not any(tmp_path.glob("deezer_new*"))


def test_nightly_queues_most_played(client, engine):
    from app.db.repository import Play
    from datetime import datetime, timedelta, timezone

    deps = client.app.state.deps
    now = datetime.now(timezone.utc)

    def play(minutes: int, source_id: str) -> Play:
        stamp = (now - timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
        return Play(played_at=stamp, title=source_id, artist="A", source="deezer", source_id=source_id)

    async def run():
        await deps.repo.plays_add(1, [play(1, "a"), play(2, "b"), play(3, "b"), play(4, "b"), play(5, "c"), play(6, "c")])
        engine.gate = asyncio.Event()
        return await karaoke.queue_top_tracks(deps, limit=2)

    assert client.portal.call(run) == 2
    assert set(karaoke._jobs) == {("deezer", "b", "hq"), ("deezer", "c", "hq")}
    assert all(job.priority == karaoke.NIGHT for job in karaoke._jobs.values())
    client.portal.call(engine.gate.set)


def test_model_download_checks_size(tmp_path, monkeypatch):
    """Téléchargement coupé : jamais pris pour un modèle valide."""
    import httpx

    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    settings = load_settings()
    spec = separation.ModelSpec("m.onnx", 64, 32, 256, 1.0, "instrumental", 10)
    monkeypatch.setattr(karaoke, "model_spec", lambda quality="hq": spec)
    payload = {"body": b"x" * 7}

    def handler(request):
        return httpx.Response(200, content=payload["body"])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(karaoke.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    with pytest.raises(karaoke.SeparationError):
        asyncio.run(karaoke.ensure_model(settings))
    assert not (tmp_path / "m.onnx").exists()
    payload["body"] = b"x" * 10
    karaoke._model_lock = None
    assert asyncio.run(karaoke.ensure_model(settings)) == tmp_path / "m.onnx"


# -- Le calcul lui-même -----------------------------------------------------------


def test_stft_round_trip_matches_torch_convention():
    """STFT puis iSTFT redonne le signal (fenêtre de Hann périodique,
    bords en miroir, comme torch.stft(center=True))."""
    stft = separation._Stft(1024, 256, 513)
    wave = np.random.default_rng(1).standard_normal((2, 256 * 63)).astype(np.float32)
    spec = stft.forward(wave)
    assert spec.shape == (1, 4, 513, 64)
    assert np.abs(stft.inverse(spec, wave.shape[-1]) - wave).max() < 1e-4


def test_separate_splits_into_two_stems_that_sum_to_the_mix(monkeypatch):
    """Faux modèle qui garde la moitié du spectre : l'instru vaut la moitié
    du mix (× compensation), et voix + instru redonne exactement le mix,
    y compris aux raccords entre morceaux."""

    class HalfModel:
        def run(self, _outputs, feeds):
            return [feeds["input"] * 0.5]

    monkeypatch.setattr(separation, "_session", lambda path, threads: HalfModel())
    spec = separation.ModelSpec("fake.onnx", 4096, 2048, 64, 1.0, "instrumental", 0)
    rng = np.random.default_rng(2)
    # Rien sous ~30 Hz (bandes mises à zéro) ni au-dessus de dim_f.
    t = np.arange(44100 * 3) / 44100
    mix = np.stack([0.3 * np.sin(2 * np.pi * 440 * t), 0.2 * np.sin(2 * np.pi * 1000 * t + rng.random())]).astype(np.float32)
    progress = []
    vocals, instrumental = separation.separate(mix, spec, Path("fake.onnx"), progress=progress.append)
    assert vocals.shape == instrumental.shape == mix.shape
    assert np.allclose(vocals + instrumental, mix, atol=1e-5)
    # Écart infime, sauf aux deux bouts où le signal de test commence et
    # s'arrête net.
    assert np.abs(instrumental - 0.5 * mix)[:, 4410:-4410].max() < 1e-3
    assert np.abs(instrumental - 0.5 * mix).max() < 1e-2
    assert progress[-1] == 1.0 and len(progress) > 3


def test_stream_router_still_exports_ensure_file():
    """Le karaoké réutilise le fichier du cache de lecture."""
    assert callable(stream.ensure_file)


def test_new_upcoming_list_replaces_the_old_one(client, engine):
    """Titres passés ou file changée : leurs séparations « à venir »
    quittent la file du serveur."""
    engine.gate = asyncio.Event()
    client.post("/karaoke/deezer/now", headers=AUTH)
    wait_for(client, "/karaoke/deezer/now", "running")
    refs = lambda *ids: {"tracks": [{"source": "deezer", "source_id": i} for i in ids]}
    client.post("/karaoke/prepare", headers=AUTH, json=refs("a", "b", "c"))
    client.post("/karaoke/prepare", headers=AUTH, json=refs("c", "d"))
    queued = {key[1] for key, job in karaoke._jobs.items() if job.status == "queued"}
    assert queued == {"c", "d"}
    client.portal.call(engine.gate.set)


def test_clear_queue(client, engine):
    """« Vider la file » : ses séparations partent, même celle en cours ;
    celles des autres comptes restent."""
    engine.gate = asyncio.Event()
    deps = client.app.state.deps
    client.post("/karaoke/deezer/1", headers=AUTH)
    wait_for(client, "/karaoke/deezer/1", "running")
    client.post("/karaoke/prepare", headers=AUTH, json={"tracks": [{"source": "deezer", "source_id": "2"}]})

    async def other_account():
        from dataclasses import replace

        karaoke.request(replace(deps, user_id_override=99), "deezer", "autre", karaoke.UPCOMING)

    client.portal.call(other_account)
    info = client.get("/karaoke/queue", headers=AUTH).json()
    assert info["queued"] == 2 and info["running"]["source_id"] == "1"

    # Le jeton de test est administrateur : un compte simple ne vide que
    # ses propres demandes.
    async def clear_as_user():
        from dataclasses import replace

        return karaoke.clear_queue(replace(deps, is_admin=False))

    assert client.portal.call(clear_as_user) == 2
    assert karaoke._jobs[("deezer", "1", "fast")].cancelled
    assert ("deezer", "2", "fast") not in karaoke._jobs
    assert ("deezer", "autre", "fast") in karaoke._jobs
    client.portal.call(engine.gate.set)
    # Pas de passe fine pour une séparation abandonnée.
    wait_for(client, "/karaoke/deezer/autre", "ready")
    assert ("deezer", "1", "hq") not in karaoke._jobs
    # Un administrateur vide tout.
    client.post("/karaoke/prepare", headers=AUTH, json={"tracks": [{"source": "deezer", "source_id": "x"}]})
    assert client.delete("/karaoke/queue", headers=AUTH).json()["queued"] == 0
