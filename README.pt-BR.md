<div align="center">

<img src="https://raw.githubusercontent.com/trysona/sona/master/.github/assets/banner.svg" alt="Sona" width="100%">

[English](README.md) · [Français](README.fr.md) · [Español](README.es.md) · [Deutsch](README.de.md) · **Português**

### Sua música, às claras.

Letras palavra por palavra, seus próprios arquivos sem perdas, escuta em grupo e uma reprodução que acompanha você do celular ao PC e à TV.

## [**Baixar o Sona →**](https://trysona.fr/presentation)

[![Tests](https://github.com/trysona/sona/actions/workflows/tests.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/tests.yml)
[![iOS](https://github.com/trysona/sona/actions/workflows/ios.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/ios.yml)
[![Windows](https://github.com/trysona/sona/actions/workflows/windows.yml/badge.svg)](https://github.com/trysona/sona/actions/workflows/windows.yml)

</div>

## Instalação

| Aparelho | Como |
|---|---|
| **Android** | Abra [o site](https://trysona.fr/presentation) no Chrome, menu ⋮, **Instalar app** |
| **iPhone / iPad** | Abra [o site](https://trysona.fr/presentation) no Safari, **Compartilhar**, **Adicionar à Tela de Início** (há um `.ipa` nativo para sideload em [Releases](https://github.com/trysona/sona/releases)) |
| **Windows** | [Baixe o instalador](https://github.com/trysona/sona/releases/tag/windows) |

Aberto a todos: crie uma conta com e-mail, Google, Discord ou GitHub (ou passkey), ou teste sem conta. O Last.fm é opcional. Por padrão ninguém é amigo de ninguém. Configuração: [docs/AUTH_SETUP.md](docs/AUTH_SETUP.md).

## Recursos

### 🎧 Ouvir
- Letras sincronizadas, karaokê com IA (separa voz e instrumental) e reconhecimento de músicas
- Seus arquivos FLAC, ALAC e WAV entregues como são
- Equalizador de 5 bandas, volume nivelado, crossfade, timer de sono, despertador musical
- O áudio é comparado com a prévia oficial antes de tocar

### 🎛️ Mixar
- AutoMix: transições no ritmo com análise de tempo, compasso e tom
- Rádios, mix diário, rádio DJ com voz de DJ

### 🤝 Compartilhar
- Sona Connect: controle a reprodução em qualquer aparelho seu
- Ouvir junto, amigos e Blend, playlists colaborativas, paradas semanais

### ✨ Descobrir
- Próximos lançamentos com contagem regressiva, estatísticas, mapa das suas audições, retrospectivas em formato de stories

## Hospede você mesmo

Python 3.11–3.13 (3.12 recomendado) e [FFmpeg](https://ffmpeg.org/).

```bash
git clone https://github.com/trysona/sona.git
cd sona
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # depois defina API_TOKEN
.venv/bin/python run_api.py                   # API + web em http://127.0.0.1:8000/web/
```

Testes (sem chamadas de rede): `pip install pytest && python -m pytest tests -q`

Mais, em francês: [guia completo](docs/GUIDE.md) · [implantação](docs/DEPLOIEMENT.md) · [app Windows](desktop/README.md) · [app iPhone](ios/Encre/README.md)

## Bom saber

O Sona é feito para **uso privado**: um servidor por pessoa ou grupo de amigos, não um serviço público. O áudio vem do YouTube e do SoundCloud, por isso o app para iPhone não está na App Store. Pense em quem pode acessar sua API antes de expô-la.

O Sona é feito por uma única pessoa, Lunatix, com o Claude (IA).
