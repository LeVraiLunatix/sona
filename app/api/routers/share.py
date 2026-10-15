"""Liens de partage d'un titre, d'un album ou d'une playlist Sona
(services/share.py).

- Membres (jeton requis) : créer un lien (`POST /me/shares`, expiration au
  choix), lister ses liens, en révoquer un, et ouvrir un lien reçu dans Sona
  (`GET /shares/{token}`).
- Tout le monde : la page publique `/s/{token}` — pochette, titres et
  extraits officiels de 30 s (servis par Deezer), aperçu riche (Open Graph)
  pour les messageries. Jamais l'audio complet : Sona est privé.
"""

from __future__ import annotations

import html
import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.api.auth import get_deps, require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.db.repository import ShareLink
from app.providers.link_detect import track_url
from app.services import share
from app.services.artwork import resize_artwork_url

router = APIRouter(tags=["partage"])

# Pages publiques : 120 requêtes par 5 min et par adresse, extraits compris.
RATE_LIMIT = 120
RATE_WINDOW = 300
_hits: dict[str, deque[float]] = defaultdict(deque)


class ShareCreate(BaseModel):
    kind: str = Field(description="track, album ou playlist")
    source: str = Field(default="deezer", max_length=20)
    id: str = Field(min_length=1, max_length=200)
    # Sans valeur : le lien ne périme pas (il reste révocable).
    expires_in_hours: int | None = Field(default=None, ge=1, le=share.MAX_HOURS)


class ShareOut(BaseModel):
    token: str
    url: str
    kind: str
    source: str
    id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    created_at: str
    expires_at: str | None
    views: int
    active: bool

    @classmethod
    def build(cls, link: ShareLink, url: str) -> "ShareOut":
        return cls(
            token=link.token, url=url, kind=link.kind, source=link.source, id=link.ref, title=link.title,
            subtitle=link.subtitle, cover_url=link.cover_url, created_at=link.created_at,
            expires_at=link.expires_at, views=link.views, active=link.active,
        )


class ShareContentOut(BaseModel):
    """Lien reçu, ouvert par un membre dans Sona."""

    kind: str
    source: str
    id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    tracks: list[Track]


def _base(request: Request) -> str:
    return str(request.base_url)


@router.post("/me/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
async def create_share(payload: ShareCreate, request: Request, deps: ApiDeps = Depends(require_token)) -> ShareOut:
    try:
        link = await share.create(deps, deps.user_id, payload.kind, payload.source, payload.id, payload.expires_in_hours)
    except share.ShareError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ShareOut.build(link, share.public_url(deps.settings, link.token, _base(request)))


@router.get("/me/shares", response_model=list[ShareOut])
async def list_shares(request: Request, deps: ApiDeps = Depends(require_token)) -> list[ShareOut]:
    return [
        ShareOut.build(link, share.public_url(deps.settings, link.token, _base(request)))
        for link in await deps.repo.share_list(deps.user_id)
    ]


@router.delete("/me/shares/{token}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_share(token: str, deps: ApiDeps = Depends(require_token)) -> None:
    """Révoque un lien : la page publique dit aussitôt qu'il n'existe plus."""
    if not await deps.repo.share_revoke(deps.user_id, token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien introuvable.")
    share.reset()


@router.get("/shares/{token}", response_model=ShareContentOut)
async def open_share(token: str, deps: ApiDeps = Depends(require_token)) -> ShareContentOut:
    """« Ouvrir dans Sona » : ce que le lien partage, pour un membre."""
    link = await share.resolve(deps, token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ce lien n'existe pas, a expiré ou a été révoqué.")
    found = await share.tracks(deps, link)
    return ShareContentOut(
        kind=link.kind, source=link.source, id=link.ref, title=link.title, subtitle=link.subtitle,
        cover_url=link.cover_url, tracks=[Track.from_info(t) for t in found],
    )


# -- Page publique ------------------------------------------------------------

def _client_ip(request: Request) -> str:
    """Adresse du visiteur : derrière le reverse proxy local, celle qu'il transmet."""
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or host
    return host


def _rate_limited(request: Request) -> bool:
    now = time.monotonic()
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    if len(_hits) > 5000:  # adresses de passage : on oublie les plus anciennes
        for key in list(_hits)[:1000]:
            _hits.pop(key, None)
    return False


_SECURITY_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; img-src https: data:; media-src https:; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


@router.get("/s/{token}", include_in_schema=False)
async def share_page(token: str, request: Request, deps: ApiDeps = Depends(get_deps)) -> HTMLResponse:
    if _rate_limited(request):
        return HTMLResponse(_message_page("Trop de visites", "Réessaie dans quelques minutes."), status_code=429, headers=_SECURITY_HEADERS)
    link = await share.resolve(deps, token)
    if link is None:
        known = await deps.repo.share_get(token) if 16 <= len(token) <= 64 else None
        title = "Ce lien a expiré" if known is not None and not known.revoked else "Ce lien n'existe plus"
        return HTMLResponse(
            _message_page(title, "La personne qui l'a partagé l'a peut-être retiré. Demande-lui un nouveau lien."),
            status_code=status.HTTP_410_GONE if known else status.HTTP_404_NOT_FOUND, headers=_SECURITY_HEADERS,
        )
    await deps.repo.share_viewed(token)
    found = await share.tracks(deps, link)
    page = _share_page(
        link, found, share.public_url(deps.settings, token, _base(request)),
        deps.settings.web_app_url, await share.bot_username(deps.settings),
    )
    return HTMLResponse(page, headers={**_SECURITY_HEADERS, "Cache-Control": "public, max-age=60"})


@router.get("/s/{token}/preview/{index}", include_in_schema=False)
async def share_preview(token: str, index: int, request: Request, deps: ApiDeps = Depends(get_deps)):
    """Extrait de 30 s : redirection vers le fichier officiel de Deezer."""
    if _rate_limited(request):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de requêtes.")
    link = await share.resolve(deps, token)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien inconnu.")
    url = await share.preview_url(deps, link, index)
    if not url or not url.startswith("https://"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas d'extrait pour ce titre.")
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})


# -- Gabarits -----------------------------------------------------------------

_e = html.escape


def _duration(seconds: int | None) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def _external(link: ShareLink, found: list) -> tuple[str, str] | None:
    """« Écouter sur … » : la plateforme d'origine, pour qui n'est pas membre."""
    names = {"deezer": "Deezer", "spotify": "Spotify", "youtube": "YouTube", "apple": "Apple Music", "soundcloud": "SoundCloud"}
    if link.kind == "track" and found:
        url = track_url(found[0])
        if url and found[0].source in names:
            return url.replace("api.soundcloud.com/tracks/", "soundcloud.com/tracks/"), names[found[0].source]
    if link.kind == "album" and link.source == "deezer":
        return f"https://www.deezer.com/album/{link.ref}", "Deezer"
    if link.kind == "album" and link.source == "spotify":
        return f"https://open.spotify.com/album/{link.ref}", "Spotify"
    return None


_STYLE = """
:root { color-scheme: dark; --fg: #f5f5f7; --muted: rgba(245,245,247,.62); --faint: rgba(245,245,247,.38); --fill: rgba(255,255,255,.08); --line: rgba(255,255,255,.09); }
* { box-sizing: border-box; }
html, body { margin: 0; background: #050507; color: var(--fg); font: 16px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
.bg { position: fixed; inset: -20%; background-size: cover; background-position: center; filter: blur(80px) saturate(1.6) brightness(.55); transform: scale(1.1); z-index: 0; }
.bg::after { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0,0,0,.15), rgba(0,0,0,.65)); }
main { position: relative; z-index: 1; max-width: 560px; margin: 0 auto; padding: 48px 16px 40px; display: flex; flex-direction: column; align-items: center; text-align: center; }
.cover { width: min(300px, 78vw); aspect-ratio: 1; border-radius: 14px; object-fit: cover; background: var(--fill); box-shadow: 0 30px 80px rgba(0,0,0,.55), 0 2px 8px rgba(0,0,0,.4); }
.kind { margin-top: 26px; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
h1 { margin: 6px 0 4px; font-size: clamp(26px, 6vw, 34px); line-height: 1.1; letter-spacing: -.02em; font-weight: 800; }
.sub { color: var(--muted); font-size: 17px; }
.play { margin-top: 26px; display: inline-flex; align-items: center; gap: 12px; padding: 0 22px 0 8px; height: 56px; border: 0; border-radius: 999px; background: #fff; color: #000; font: inherit; font-weight: 700; cursor: pointer; }
.play svg { width: 40px; height: 40px; }
.play .ring { transition: stroke-dashoffset .2s linear; }
.play[disabled] { opacity: .5; cursor: default; }
.note { margin-top: 10px; font-size: 13px; color: var(--faint); }
.cta { margin-top: 28px; display: grid; gap: 10px; width: 100%; }
.btn { display: flex; align-items: center; justify-content: center; gap: 10px; height: 50px; border-radius: 14px; background: var(--fill); color: var(--fg); text-decoration: none; font-weight: 600; backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); }
.btn.primary { background: rgba(255,255,255,.92); color: #000; }
.btn:hover { filter: brightness(1.12); }
ol { list-style: none; margin: 30px 0 0; padding: 0; width: 100%; text-align: left; border-top: 1px solid var(--line); }
li { display: grid; grid-template-columns: 28px 1fr auto 36px; align-items: center; gap: 10px; padding: 9px 4px; border-bottom: 1px solid var(--line); }
li .n { color: var(--faint); font-variant-numeric: tabular-nums; text-align: right; font-size: 14px; }
li b { display: block; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
li span { display: block; color: var(--muted); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
li .d { color: var(--faint); font-size: 13px; font-variant-numeric: tabular-nums; }
li button { width: 34px; height: 34px; border-radius: 50%; border: 0; background: var(--fill); color: var(--fg); cursor: pointer; display: grid; place-items: center; }
li button svg { width: 14px; height: 14px; }
li.on b { color: #fff; } li.on button { background: #fff; color: #000; }
.more { margin-top: 12px; color: var(--faint); font-size: 14px; }
footer { margin-top: 40px; color: var(--faint); font-size: 12.5px; max-width: 420px; }
footer b { color: var(--muted); }
.logo { display: inline-flex; align-items: center; gap: 8px; font-weight: 800; color: var(--muted); letter-spacing: -.01em; margin-bottom: 8px; }
.logo i { width: 22px; height: 22px; border-radius: 6px; background: #fff; color: #000; font-style: normal; font-size: 15px; display: grid; place-items: center; }
@media (prefers-reduced-motion: reduce) { .play .ring { transition: none; } }
"""

_SCRIPT = """
(() => {
  const audio = new Audio();
  audio.preload = "none";
  const main = document.querySelector("[data-main]");
  const ring = main && main.querySelector(".ring");
  const label = main && main.querySelector("[data-label]");
  const rows = [...document.querySelectorAll("li[data-i]")];
  let current = null;
  const PLAY = '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>';
  const PAUSE = '<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor"/>';
  const icon = (el, on) => { const s = el && el.querySelector("[data-icon]"); if (s) s.innerHTML = on ? PAUSE : PLAY; };
  function stop() {
    audio.pause();
    rows.forEach((r) => { r.classList.remove("on"); icon(r, false); });
    icon(main, false);
    if (label) label.textContent = main.dataset.idle;
    if (ring) ring.style.strokeDashoffset = 113;
    current = null;
  }
  function play(i) {
    if (current === i && !audio.paused) return stop();
    stop();
    current = i;
    audio.src = location.pathname.replace(/\\/$/, "") + "/preview/" + i;
    audio.play().catch(() => { stop(); if (label) label.textContent = "Extrait indisponible"; });
    const row = rows.find((r) => Number(r.dataset.i) === i);
    if (row) { row.classList.add("on"); icon(row, true); }
    icon(main, true);
    if (label) label.textContent = "Extrait en lecture";
  }
  audio.addEventListener("timeupdate", () => {
    if (!ring || !audio.duration) return;
    ring.style.strokeDashoffset = 113 * (1 - audio.currentTime / audio.duration);
  });
  audio.addEventListener("ended", stop);
  audio.addEventListener("error", () => { if (current !== null) { stop(); if (label) label.textContent = "Extrait indisponible"; } });
  if (main) main.addEventListener("click", () => play(Number(main.dataset.i || 0)));
  rows.forEach((r) => r.querySelector("button").addEventListener("click", () => play(Number(r.dataset.i))));
})();
"""

_PLAY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" data-icon><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>'


def _cover(url: str | None, size: int) -> str:
    return resize_artwork_url(url, size) if url else ""


def _share_page(link: ShareLink, found: list, url: str, web_app: str | None, bot: str | None) -> str:
    kind_label = share.KIND_LABELS.get(link.kind, "")
    cover = _cover(link.cover_url, 600)
    og_image = _cover(link.cover_url, 1000)
    description = f"{kind_label} · {link.subtitle}" if link.subtitle else kind_label
    og_type = {"track": "music.song", "album": "music.album", "playlist": "music.playlist"}.get(link.kind, "website")
    meta = [
        ("og:type", og_type), ("og:title", link.title), ("og:description", f"{description} — extrait sur Sona"),
        ("og:url", url), ("og:site_name", "Sona"), ("twitter:card", "summary_large_image"),
        ("twitter:title", link.title), ("twitter:description", description),
    ]
    if og_image:
        meta += [("og:image", og_image), ("og:image:width", "1000"), ("og:image:height", "1000"),
                 ("og:image:alt", f"Pochette de {link.title}"), ("twitter:image", og_image)]
    meta_tags = "\n".join(
        f'<meta {"name" if key.startswith("twitter:") else "property"}="{_e(key)}" content="{_e(value)}">'
        for key, value in meta
    )
    ld = {"@context": "https://schema.org", "@type": {"track": "MusicRecording", "album": "MusicAlbum"}.get(link.kind, "MusicPlaylist"),
          "name": link.title, "url": url}
    if og_image:
        ld["image"] = og_image
    # « < » échappé : le JSON ne peut pas fermer la balise <script>.
    ld_json = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")
    cover_html = (
        f'<img class="cover" src="{_e(cover)}" alt="Pochette de {_e(link.title)}">' if cover else '<div class="cover"></div>'
    )

    buttons = []
    if web_app:
        buttons.append(f'<a class="btn primary" href="{_e(web_app)}/#/s/{_e(link.token)}">Ouvrir dans Sona</a>')
    if bot:
        buttons.append(f'<a class="btn{"" if web_app else " primary"}" href="https://t.me/{_e(bot)}?start=s_{_e(link.token)}">Ouvrir dans Telegram</a>')
    buttons.append(f'<a class="btn" href="encre://share?token={_e(link.token)}">Ouvrir dans l\'app iPhone</a>')
    external = _external(link, found)
    if external:
        buttons.append(f'<a class="btn" href="{_e(external[0])}" rel="noopener noreferrer">Écouter sur {_e(external[1])}</a>')

    rows = ""
    if link.kind != "track" and found:
        items = "".join(
            f'<li data-i="{i}"><span class="n">{i + 1}</span><div><b>{_e(t.title)}</b><span>{_e(t.artist)}</span></div>'
            f'<span class="d">{_duration(t.duration_seconds)}</span>'
            f'<button aria-label="Écouter l\'extrait de {_e(t.title)}">{_PLAY_ICON}</button></li>'
            for i, t in enumerate(found)
        )
        rows = f"<ol>{items}</ol>"
        if link.kind == "playlist" and link.subtitle and len(found) >= share.MAX_PUBLIC_TRACKS:
            rows += f'<p class="more">Les {share.MAX_PUBLIC_TRACKS} premiers titres.</p>'

    main_button = (
        f'<button class="play" data-main data-i="0" data-idle="Écouter un extrait" {"" if found else "disabled"}>'
        '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="18" fill="#000"/>'
        '<circle class="ring" cx="20" cy="20" r="18" fill="none" stroke="#fff" stroke-width="2" '
        'stroke-dasharray="113" stroke-dashoffset="113" transform="rotate(-90 20 20)"/>'
        '<g transform="translate(8 8)" color="#fff" data-icon><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></g></svg>'
        '<span data-label>Écouter un extrait</span></button>'
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#050507">
<title>{_e(link.title)} · {_e(link.subtitle or kind_label)} — Sona</title>
<meta name="description" content="{_e(description)}">
{meta_tags}
<script type="application/ld+json">{ld_json}</script>
<style>{_STYLE}</style>
</head>
<body>
<div class="bg" style="background-image:url('{_e(_cover(link.cover_url, 300))}')"></div>
<main>
  <div class="logo"><i>S</i>Sona</div>
  {cover_html}
  <div class="kind">{_e(kind_label)}</div>
  <h1>{_e(link.title)}</h1>
  <div class="sub">{_e(link.subtitle or "")}</div>
  {main_button}
  <div class="note">Extraits officiels de 30 s</div>
  <div class="cta">{"".join(buttons)}</div>
  {rows}
  <footer>Partagé depuis <b>Sona</b>, un service de musique privé, sur invitation. Cette page ne diffuse que des extraits de 30 secondes.</footer>
</main>
<script>{_SCRIPT}</script>
</body>
</html>"""


def _message_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{_e(title)} — Sona</title><style>{_STYLE}</style></head>
<body><main style="min-height:80vh;justify-content:center"><div class="logo"><i>S</i>Sona</div><h1>{_e(title)}</h1>
<p class="sub">{_e(message)}</p></main></body></html>"""
