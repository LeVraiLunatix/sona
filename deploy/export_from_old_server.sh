#!/usr/bin/env bash
# À lancer sur l'ANCIEN serveur : envoie au nouveau la configuration (.env),
# la base (comptes, écoutes, playlists…) et les cookies YouTube, chiffrés de
# bout en bout (magic-wormhole). Voir docs/MIGRATION_ORACLE.md.
#
#   curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/export_from_old_server.sh | bash
set -euo pipefail

# Python de Sona sur ce serveur : son environnement virtuel s'il existe
# (quel que soit son nom), sinon celui du système.
find_python() {
    local candidate
    for candidate in .venv venv env .env-py; do
        if [ -x "$candidate/bin/python" ]; then echo "$candidate/bin/python"; return; fi
    done
    command -v python3
}

# magic-wormhole dans l'environnement de Sona, sinon dans un environnement
# jetable, sinon pour l'utilisateur.
wormhole_cmd() {
    if "$PY" -m pip install --quiet magic-wormhole >/dev/null 2>&1; then
        echo "$PY -m wormhole"; return
    fi
    rm -rf /tmp/sona-wormhole
    if ! python3 -m venv /tmp/sona-wormhole >/dev/null 2>&1; then
        # Debian/Ubuntu sans le module venv : on l'installe.
        sudo apt-get install -y -qq python3-venv >/dev/null 2>&1 || true
        rm -rf /tmp/sona-wormhole
        python3 -m venv /tmp/sona-wormhole >/dev/null 2>&1 || true
    fi
    if [ -x /tmp/sona-wormhole/bin/pip ] \
        && /tmp/sona-wormhole/bin/pip install --quiet magic-wormhole >/dev/null 2>&1; then
        echo "/tmp/sona-wormhole/bin/wormhole"; return
    fi
    python3 -m pip install --quiet --user --break-system-packages magic-wormhole >/dev/null 2>&1 \
        || python3 -m pip install --quiet --user magic-wormhole
    echo "python3 -m wormhole"
}

main() {
    cd "$HOME/sona"
    PY=$(find_python)
    staging=$(mktemp -d)
    trap 'rm -rf "$staging"' EXIT
    mkdir -p "$staging/data"

    echo "▶ Copie cohérente de la base (même pendant que l'API tourne)"
    "$PY" - "$staging/data/sona.db" <<'PY'
import sqlite3, sys
import os
path = "data/sona.db"
for line in open(".env", encoding="utf-8"):
    if line.startswith("DATABASE_PATH=") and line.split("=", 1)[1].strip():
        path = line.split("=", 1)[1].strip()
source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[1])
source.backup(target)
target.close()
print("  base copiée")
PY
    cp .env "$staging/.env"
    [ -f data/cookies.txt ] && cp data/cookies.txt "$staging/data/cookies.txt"
    tar czf "$HOME/sona-transfer.tgz" -C "$staging" .
    echo "  archive : $(du -h "$HOME/sona-transfer.tgz" | cut -f1)"

    echo "▶ Envoi (garde cette fenêtre ouverte jusqu'à la fin)"
    wormhole=$(wormhole_cmd)
    $wormhole send "$HOME/sona-transfer.tgz"
    rm -f "$HOME/sona-transfer.tgz"

    # Deux bots Telegram sur le même jeton se gênent : l'ancien s'arrête,
    # le nouveau serveur prend le relais. L'API reste allumée le temps de
    # basculer l'app.
    if pm2 describe sona >/dev/null 2>&1; then
        pm2 stop sona >/dev/null && echo "▶ Bot Telegram de l'ancien serveur arrêté."
    fi
    echo "✅ Envoyé. Sur le nouveau serveur : ./deploy/import_transfer.sh <code>"
}

main "$@"
