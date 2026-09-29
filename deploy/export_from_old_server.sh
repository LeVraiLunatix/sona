#!/usr/bin/env bash
# À lancer sur l'ANCIEN serveur : envoie au nouveau la configuration (.env),
# la base (comptes, écoutes, playlists…) et les cookies YouTube, chiffrés de
# bout en bout (magic-wormhole). Voir docs/MIGRATION_ORACLE.md.
#
#   curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/export_from_old_server.sh | bash
set -euo pipefail

main() {
    cd "$HOME/sona"
    staging=$(mktemp -d)
    trap 'rm -rf "$staging"' EXIT
    mkdir -p "$staging/data"

    echo "▶ Copie cohérente de la base (même pendant que l'API tourne)"
    .venv/bin/python - "$staging/data/sona.db" <<'PY'
import sqlite3, sys
source = sqlite3.connect("data/sona.db")
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
    .venv/bin/pip install --quiet magic-wormhole
    .venv/bin/wormhole send "$HOME/sona-transfer.tgz"
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
