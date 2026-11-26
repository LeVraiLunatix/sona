<div align="center">

<img src="https://raw.githubusercontent.com/trysona/sona/master/.github/assets/banner.svg" alt="Sona" width="100%">

[English](README.md) · [Français](README.fr.md) · [Español](README.es.md) · **Deutsch** · [Português](README.pt-BR.md)

### Deine Musik, ganz klar.

Wort-für-Wort-Lyrics, deine eigenen verlustfreien Dateien, gemeinsames Hören und Wiedergabe, die dir vom Handy auf den PC und den Fernseher folgt.

## [**Sona holen →**](https://trysona.fr/presentation)

[![Tests](https://github.com/trysona/sona/actions/workflows/tests.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/tests.yml)
[![iOS](https://github.com/trysona/sona/actions/workflows/ios.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/ios.yml)
[![Windows](https://github.com/trysona/sona/actions/workflows/windows.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/windows.yml)

</div>

## Installation

| Gerät | So geht’s |
|---|---|
| **Android** | [Die Seite](https://trysona.fr/presentation) in Chrome öffnen, Menü ⋮, **App installieren** |
| **iPhone / iPad** | [Die Seite](https://trysona.fr/presentation) in Safari öffnen, **Teilen**, **Zum Home-Bildschirm** (eine native `.ipa` zum Sideloaden liegt unter [Releases](https://github.com/trysona/sona/releases)) |
| **Windows** | [Installer herunterladen](https://github.com/trysona/sona/releases/tag/windows) |

Die Anmeldung läuft über ein Last.fm-Konto. Auf dem gehosteten Server muss ein Admin neue Konten freigeben.

## Funktionen

### 🎧 Hören
- Synchrone Lyrics, KI-Karaoke (Gesang / Instrumental getrennt) und Songerkennung
- Deine FLAC-, ALAC- und WAV-Dateien werden unverändert ausgeliefert
- 5-Band-Equalizer, Lautstärkeangleichung, Crossfade, Sleeptimer, Musikwecker
- Das Audio wird vor dem Abspielen mit der offiziellen Hörprobe verglichen

### 🎛️ Mixen
- AutoMix: taktgenaue Übergänge anhand von Tempo, Takten und Tonart
- Radios, Tagesmix, DJ-Radio mit DJ-Stimme

### 🤝 Teilen
- Sona Connect: Wiedergabe auf all deinen Geräten steuern
- Gemeinsam hören, Freunde und Blend, gemeinsame Playlists, Wochencharts

### ✨ Entdecken
- Kommende Releases mit Countdown, Hörstatistiken, Karte deiner Wiedergaben, Rückblicke im Story-Stil

## Selbst hosten

Python 3.11–3.13 (3.12 empfohlen) und [FFmpeg](https://ffmpeg.org/).

```bash
git clone https://github.com/trysona/sona.git
cd sona
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # dann API_TOKEN setzen
.venv/bin/python run_api.py                   # API + Web-App auf http://127.0.0.1:8000/web/
```

Tests (ohne Netzwerkzugriffe): `pip install pytest && python -m pytest tests -q`

Mehr auf Französisch: [Anleitung](docs/GUIDE.md) · [Deployment](docs/DEPLOIEMENT.md) · [Windows-App](desktop/README.md) · [iPhone-App](ios/Encre/README.md)

## Gut zu wissen

Sona ist für den **privaten Gebrauch** gedacht: ein Server pro Person oder Freundeskreis, kein öffentlicher Dienst. Das Audio kommt von YouTube und SoundCloud, deshalb ist die iPhone-App nicht im App Store. Überlege vor dem Freigeben, wer deine API erreichen kann.

Sona wird von einer einzigen Person, Lunatix, mit Claude (KI) entwickelt.
