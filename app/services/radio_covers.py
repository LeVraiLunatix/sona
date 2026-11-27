"""Covers des radios : un artiste en vue de la station, détouré de sa photo.

La photo vient de Deezer ; le détourage est fait ici par U²-Net (modèle
`u2net_human_seg.onnx`, à poser dans MODELS_DIR ; source : releases de
danielgatis/rembg sur GitHub). Sans le modèle, pas de portrait : la cover
dessinée par le web reste entière.

L'image est fabriquée en arrière-plan (une à la fois) puis gardée une semaine :
la requête qui ne la trouve pas répond tout de suite, sans faire attendre les
autres appels du navigateur.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import Counter
from pathlib import Path

import httpx

from app.services import heavy, radio_mix

logger = logging.getLogger(__name__)

MODEL_NAME = "u2net_human_seg.onnx"
TTL = 7 * 24 * 3600
RETRY_AFTER = 3600
CANDIDATES = 5
SIZE = 600

_lock = asyncio.Lock()
_tasks: dict[str, asyncio.Task] = {}
_failed: dict[str, float] = {}


def cover_dir(settings) -> Path:
    return settings.models_dir.parent / "cache" / "radio_covers"


def candidates(tracks, taken: set[str]) -> list[str]:
    """Artistes de la station, du plus présent au moins présent (à égalité,
    l'ordre de la station), sans ceux qu'une autre cover montre déjà."""
    count = Counter(t.artist_source_id for t in tracks if t.source == "deezer" and t.artist_source_id)
    ordered = [artist_id for artist_id, _ in count.most_common()]
    fresh = [artist_id for artist_id in ordered if artist_id not in taken]
    return (fresh or ordered)[:CANDIDATES]


def cut_out(photo: bytes, mask_of) -> bytes | None:
    """Photo → portrait détouré (WebP transparent, recadré sur la personne).
    `mask_of(image)` rend le masque 0-255. None si le masque ne ressemble pas à
    une personne sur un fond (logo, paysage, image pleine)."""
    from PIL import Image

    image = Image.open(io.BytesIO(photo)).convert("RGB")
    mask = mask_of(image)
    solid = mask.point(lambda v: 255 if v > 128 else 0)
    box = solid.getbbox()
    covered = solid.histogram()[255] / (image.width * image.height)
    if box is None or not 0.12 <= covered <= 0.9:
        return None
    # Une tête n'a pas le dessus plat : un haut presque plein, c'est le fond de la photo resté entier.
    left, top, right, bottom = box
    row = top + (bottom - top) // 50
    if solid.crop((left, row, right, row + 1)).histogram()[255] > 0.75 * (right - left):
        return None
    image.putalpha(mask)
    image = image.crop(box)
    image.thumbnail((SIZE, SIZE))
    out = io.BytesIO()
    image.save(out, "WEBP", quality=86)
    return out.getvalue()


def _mask_with(model: Path):
    """Chargé pour une image puis relâché : ~1 s, plutôt que 400 Mo gardés."""
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])

    def mask_of(image):
        data = np.asarray(image.resize((320, 320), Image.LANCZOS), dtype=np.float32)
        data = data / max(float(data.max()), 1.0)
        data = (data - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        tensor = data.transpose(2, 0, 1)[None].astype(np.float32)
        out = session.run(None, {session.get_inputs()[0].name: tensor})[0][0, 0]
        out = (out - out.min()) / max(float(out.max() - out.min()), 1e-6)
        return Image.fromarray((out * 255).astype(np.uint8)).resize(image.size, Image.LANCZOS)

    return mask_of


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def build(deps, radio_id: str) -> bool:
    folder = cover_dir(deps.settings)
    folder.mkdir(parents=True, exist_ok=True)
    taken = {p.read_text() for p in folder.glob("*.artist") if p.stem != radio_id}
    # Les artistes les mieux placés dans les playlists de la radio ; à défaut, sa station.
    tracks = [t for _, t in (await radio_mix.pool(deps, radio_id))[:60]] or await deps.deezer.get_radio_tracks(radio_id, limit=40)
    model = deps.settings.models_dir / MODEL_NAME
    for artist_id in candidates(tracks, taken):
        artist = await deps.deezer.get_artist(artist_id)
        if not artist.picture_url:
            continue
        photo = await _download(artist.picture_url)
        async with heavy.slot:  # jamais en même temps qu'un téléchargement
            portrait = await asyncio.to_thread(lambda: cut_out(photo, _mask_with(model)))
        if portrait:
            part = folder / f"{radio_id}.part"
            part.write_bytes(portrait)
            part.replace(folder / f"{radio_id}.webp")
            (folder / f"{radio_id}.artist").write_text(artist_id)
            logger.info("Cover de la radio %s : %s", radio_id, artist.name)
            return True
    return False


async def _run(deps, radio_id: str) -> None:
    try:
        async with _lock:
            if not await build(deps, radio_id):
                _failed[radio_id] = time.monotonic()
    except Exception as exc:  # tâche de fond : on note et on réessaiera
        logger.warning("Cover de la radio %s impossible : %s", radio_id, exc)
        _failed[radio_id] = time.monotonic()
    finally:
        _tasks.pop(radio_id, None)


def cover(deps, radio_id: str) -> Path | None:
    """Le portrait déjà prêt, ou None. Lance sa fabrication (ou son
    renouvellement) en arrière-plan quand il manque ou a plus d'une semaine."""
    path = cover_dir(deps.settings) / f"{radio_id}.webp"
    ready = path.is_file()
    stale = not ready or time.time() - path.stat().st_mtime > TTL
    recently_failed = time.monotonic() - _failed.get(radio_id, -RETRY_AFTER) < RETRY_AFTER
    if stale and not recently_failed and radio_id not in _tasks and (deps.settings.models_dir / MODEL_NAME).is_file():
        _tasks[radio_id] = asyncio.get_running_loop().create_task(_run(deps, radio_id))
    return path if ready else None
