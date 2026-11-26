<div align="center">

<img src="https://raw.githubusercontent.com/trysona/sona/master/.github/assets/banner.svg" alt="Sona" width="100%">

[English](README.md) · [Français](README.fr.md) · **Español** · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

### Tu música, en claro.

Letras palabra por palabra, tus propios archivos sin pérdida, escucha en grupo y una reproducción que te sigue del móvil al PC y a la tele.

## [**Consigue Sona →**](https://trysona.fr/presentation)

[![Tests](https://github.com/trysona/sona/actions/workflows/tests.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/tests.yml)
[![iOS](https://github.com/trysona/sona/actions/workflows/ios.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/ios.yml)
[![Windows](https://github.com/trysona/sona/actions/workflows/windows.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/windows.yml)

</div>

## Instalación

| Dispositivo | Cómo |
|---|---|
| **Android** | Abre [el sitio](https://trysona.fr/presentation) en Chrome, menú ⋮, **Instalar aplicación** |
| **iPhone / iPad** | Abre [el sitio](https://trysona.fr/presentation) en Safari, **Compartir**, **Añadir a pantalla de inicio** (hay un `.ipa` nativo para sideload en [Releases](https://github.com/trysona/sona/releases)) |
| **Windows** | [Descarga el instalador](https://github.com/trysona/sona/releases/tag/windows) |

Abierto a todos: crea una cuenta con correo, Google, Discord o GitHub (o una clave de acceso), o prueba sin cuenta. Last.fm es opcional. Por defecto nadie es amigo de nadie. Configuración: [docs/AUTH_SETUP.md](docs/AUTH_SETUP.md).

## Funciones

### 🎧 Escuchar
- Letras sincronizadas, karaoke con IA (separa voz e instrumental) y reconocimiento de canciones
- Tus archivos FLAC, ALAC y WAV servidos tal cual
- Ecualizador de 5 bandas, volumen nivelado, fundido, temporizador y despertador musical
- El audio se compara con el fragmento oficial antes de sonar

### 🎛️ Mezclar
- AutoMix: transiciones al compás según tempo, compases y tonalidad
- Radios, mix diario, radio DJ con voz de DJ

### 🤝 Compartir
- Sona Connect: controla la reproducción en cualquiera de tus dispositivos
- Escucha en grupo, amigos y Blend, listas colaborativas, rankings semanales

### ✨ Descubrir
- Próximos lanzamientos con cuenta atrás, estadísticas, mapa de escuchas, resúmenes tipo historias

## Alojarlo tú mismo

Python 3.11–3.13 (se recomienda 3.12) y [FFmpeg](https://ffmpeg.org/).

```bash
git clone https://github.com/trysona/sona.git
cd sona
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # luego define API_TOKEN
.venv/bin/python run_api.py                   # API + web en http://127.0.0.1:8000/web/
```

Pruebas (sin llamadas de red): `pip install pytest && python -m pytest tests -q`

Más, en francés: [guía completa](docs/GUIDE.md) · [despliegue](docs/DEPLOIEMENT.md) · [app de Windows](desktop/README.md) · [app de iPhone](ios/Encre/README.md)

## Conviene saber

Sona está pensado para **uso privado**: un servidor por persona o grupo de amigos, no un servicio público. El audio se obtiene de YouTube y SoundCloud, por eso la app de iPhone no está en la App Store. Piensa quién puede acceder a tu API antes de exponerla.

Sona lo hace una sola persona, Lunatix, con Claude (IA).
