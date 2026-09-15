from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Pochettes affichées (écrans Morceau, Album, Artiste) et intégrées au fichier :
# assez grandes pour rester nettes en plein écran dans Telegram.
DISPLAY_SIZE = 1000
# Vignettes des suggestions en direct, affichées en tout petit.
LIST_SIZE = 250
# Contraintes de Telegram pour la vignette d'un fichier audio : JPEG, 320 px
# de côté au plus, moins de 200 ko.
AUDIO_THUMBNAIL_SIZE = 320
AUDIO_THUMBNAIL_MAX_BYTES = 200_000
AUDIO_THUMBNAIL_NAME = "vignette.jpg"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"

# Les CDN de pochettes encodent la taille dans l'adresse : la même image
# existe dans d'autres résolutions sans rien recalculer.
_SIZED_URL_PATTERNS = (
    # Deezer : …/images/cover/<hash>/250x250-000000-80-0-0.jpg
    (re.compile(r"/\d+x\d+(-[0-9a-f]{6}-\d+-\d+-\d+\.(?:jpg|png))$"), "/{size}x{size}\\1"),
    # Apple : …/100x100bb.jpg
    (re.compile(r"/\d+x\d+bb\."), "/{size}x{size}bb."),
    # YouTube Music (googleusercontent) : …=w120-h120-l90-rj
    (re.compile(r"=w\d+-h\d+"), "=w{size}-h{size}"),
)


def resize_artwork_url(url: str | None, size: int) -> str | None:
    """Adresse de la même pochette en `size`×`size` quand le CDN le permet
    (Deezer, Apple, YouTube Music), sinon l'adresse inchangée."""
    if not url:
        return url
    for pattern, template in _SIZED_URL_PATTERNS:
        resized, count = pattern.subn(template.format(size=size), url, count=1)
        if count:
            return resized
    return url


def is_embeddable(image: bytes) -> bool:
    """Les tags MP4 et ID3 n'acceptent que du JPEG ou du PNG (pas le WebP de
    certaines miniatures YouTube)."""
    return image[:8] == _PNG_SIGNATURE or image[:3] == _JPEG_SIGNATURE


def audio_thumbnail_path(audio: Path) -> Path:
    """Emplacement de la vignette d'un fichier audio, dans son dossier de travail."""
    return audio.parent / AUDIO_THUMBNAIL_NAME


def make_audio_thumbnail(ffmpeg_path: str, image: bytes, dest: Path) -> Path | None:
    """Vignette carrée de la bulle d'un message audio.

    Telegram ne se sert pas de la pochette intégrée au fichier pour la
    conversation : sans vignette envoyée à part, le son s'affiche sans image.
    L'image est recadrée au centre, les miniatures YouTube étant en 16:9.
    """
    source = dest.with_name(dest.stem + "-source")
    source.write_bytes(image)
    size = AUDIO_THUMBNAIL_SIZE
    try:
        subprocess.run(
            [
                ffmpeg_path, "-nostdin", "-v", "error", "-y", "-i", str(source),
                "-vf", f"scale={size}:{size}:force_original_aspect_ratio=increase:flags=lanczos,crop={size}:{size}",
                "-frames:v", "1", "-q:v", "2", str(dest),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Vignette audio impossible : %s", exc)
        dest.unlink(missing_ok=True)
        return None
    finally:
        source.unlink(missing_ok=True)
    if not dest.is_file() or dest.stat().st_size > AUDIO_THUMBNAIL_MAX_BYTES:
        dest.unlink(missing_ok=True)
        return None
    return dest
