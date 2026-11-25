"""Récupère les paroles synchronisées d'un titre AVEC LE CODE DE SONA (app/providers : LRCLIB puis NetEase),
et écrit promo/tiktok/mock/lyrics.local.json (ignoré par git : les paroles ne vont jamais dans le dépôt).

usage : python3 fetch-lyrics.py "Titre" "Artiste" ["Album"] [durée_en_secondes]
Affiche seulement des statistiques (source, finesse de synchro, nombre de lignes), jamais le texte.
Nécessite : pip install httpx · accès réseau à lrclib.net et music.163.com."""
import asyncio, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from app.providers.lrclib import LrclibClient  # noqa: E402
from app.providers.netease import NeteaseClient  # noqa: E402

title, artist = sys.argv[1], sys.argv[2]
album = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].isdigit() else None
duration = int(next((a for a in sys.argv[3:] if a.isdigit()), 0)) or None


def level(ly):
    if not ly or not ly.synced or not ly.lines: return 0
    return 2 if sum(1 for l in ly.lines if l.words) > len(ly.lines) * 0.6 else 1


def describe(name, ly):
    if not ly: return print(f"  {name:8}: rien")
    ts = [l.time for l in ly.lines if l.time is not None]
    print(f"  {name:8}: {'synchro mot par mot' if level(ly) == 2 else 'synchro ligne' if level(ly) == 1 else 'texte brut'} · {len(ly.lines)} lignes"
          + (f" · de {min(ts):.1f}s à {max(ts):.1f}s" if ts else "") + (" · approximatif" if getattr(ly, "approximate", False) else ""))


async def main():
    lr, ne = LrclibClient(), NeteaseClient()
    results = {}
    try: results["LRCLIB"] = await lr.get_lyrics(title, artist, album, duration)
    except Exception as e: print("  LRCLIB   : erreur", type(e).__name__, str(e)[:80])
    try:
        songs = await ne.search(title, artist)
        for s in songs[:5]:  # le premier titre dont la durée colle (±2 s), comme le fait le service de Sona
            if duration and getattr(s, "duration", None) and abs(s.duration - duration) > 2.5: continue
            ly = await ne.lyrics(s.id)
            if ly and ly.lines: results["NetEase"] = ly; break
    except Exception as e: print("  NetEase  : erreur", type(e).__name__, str(e)[:80])
    print(f"« {title} » — {artist} · durée {duration}s")
    for k, v in results.items(): describe(k, v)
    best = max(results.items(), key=lambda kv: (level(kv[1]), not getattr(kv[1], "approximate", False)), default=None)
    if not best or level(best[1]) == 0: print("→ aucune parole synchronisée trouvée"); return 1
    name, ly = best
    SHIFT = float(os.environ.get("LYRICS_SHIFT", "0.15"))  # calage mesuré sur l'audio : la voix attaque ~0,15–0,25 s après l'horodatage de la ligne
    lines = []
    for l in ly.lines:
        if l.time is None or not l.text: continue
        d = {"time": round(l.time + SHIFT, 3), "text": l.text}
        if l.words: d["words"] = [{"time": round(w.time + SHIFT, 3), **({"end": round(w.end + SHIFT, 3)} if w.end is not None else {}), "text": w.text} for w in l.words]
        lines.append(d)
    out = os.path.join(os.path.dirname(__file__), "mock", "lyrics.local.json")
    json.dump({"source": name, "lines": lines}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"→ retenu : {name} ({'mot par mot' if level(ly) == 2 else 'ligne'}), {len(lines)} lignes → {out}")
    await lr.aclose(); await ne.aclose()
    return 0

sys.exit(asyncio.run(main()))
