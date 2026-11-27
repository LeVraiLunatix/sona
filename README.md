<div align="center">

<img src="https://raw.githubusercontent.com/trysona/sona/master/.github/assets/banner.svg" alt="Sona" width="100%">

**English** · [Français](README.fr.md) · [Español](README.es.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

### Your music, clear.

Word-by-word lyrics, your own lossless files, listening together, and playback that follows you from phone to PC to TV.

## [**Get Sona →**](https://trysona.fr/presentation)

[![Tests](https://github.com/trysona/sona/actions/workflows/tests.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/tests.yml)
[![iOS](https://github.com/trysona/sona/actions/workflows/ios.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/ios.yml)
[![Windows](https://github.com/trysona/sona/actions/workflows/windows.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/windows.yml)

</div>

## Install

| Device | How |
|---|---|
| **Android** | Open [the site](https://trysona.fr/presentation) in Chrome, menu ⋮, **Install app** |
| **iPhone / iPad** | Open [the site](https://trysona.fr/presentation) in Safari, **Share**, **Add to Home Screen** (a native `.ipa` for sideloading is in [Releases](https://github.com/trysona/sona/releases)) |
| **Windows** | [Download the installer](https://github.com/trysona/sona/releases/tag/windows) |

Open to everyone: create an account with e-mail, Google, Discord or GitHub (or a passkey), or try it without an account. Last.fm is optional. Nobody is friends with anyone by default. Setup for self-hosters: [docs/AUTH_SETUP.md](docs/AUTH_SETUP.md).

## Features

### 🎧 Listen
- Synced lyrics, AI karaoke (vocal / instrumental split) and song recognition
- Your own FLAC, ALAC and WAV files served as they are
- 5-band equalizer, volume levelling, crossfade, sleep timer, music alarm
- Audio is checked against the official preview before it plays

### 🎛️ Mix
- AutoMix: beat-matched transitions using tempo, bar and key analysis
- Radios, daily mix, DJ radio with a DJ voice

### 🤝 Share
- Sona Connect: control playback on any of your devices
- Listen together, friends and Blend, collaborative playlists, weekly charts

### ✨ Discover
- Upcoming releases with a countdown, listening stats, a map of your plays, story-style recaps

## Self-host

Python 3.11–3.13 (3.12 recommended) and [FFmpeg](https://ffmpeg.org/).

```bash
git clone https://github.com/trysona/sona.git
cd sona
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # then set API_TOKEN
.venv/bin/python run_api.py                   # API + web app on http://127.0.0.1:8000/web/
```

Tests (no network calls): `pip install pytest && python -m pytest tests -q`

More, in French: [full guide](docs/GUIDE.md) · [deployment](docs/DEPLOIEMENT.md) · [Windows app](desktop/README.md) · [iPhone app](ios/Encre/README.md)

## Good to know

Sona is built for **private use**: one server per person or group of friends, not a public service. Audio is fetched from YouTube and SoundCloud, so the iPhone app is not on the App Store. Think about who can reach your API before you expose it.

Sona is made by one person, Lunatix, with Claude (AI).
