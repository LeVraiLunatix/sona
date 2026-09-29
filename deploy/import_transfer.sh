#!/usr/bin/env bash
# À lancer sur le NOUVEAU serveur avec le code affiché par
# export_from_old_server.sh : récupère la configuration, la base et les
# cookies, puis relance Sona. Voir docs/MIGRATION_ORACLE.md.
#
#   cd ~/sona && ./deploy/import_transfer.sh 7-mot-mot
set -euo pipefail

main() {
    local code="${1:-}"
    if [ -z "$code" ]; then
        echo "Usage : ./deploy/import_transfer.sh <code affiché sur l'ancien serveur>" >&2
        exit 1
    fi
    cd "$HOME/sona"
    archive="$HOME/sona-transfer.tgz"
    .venv/bin/wormhole receive --accept-file -o "$archive" "$code"

    # La base actuelle (vide ou non) est gardée de côté, au cas où.
    [ -f data/sona.db ] && mv data/sona.db "data/sona.db.avant-import.$(date +%s)"
    tar xzf "$archive" -C "$HOME/sona"
    rm -f "$archive"
    sed -i 's/^API_HOST=.*/API_HOST=127.0.0.1/' .env

    pm2 restart sona-api --update-env >/dev/null
    if grep -q '^BOT_TOKEN=.\+' .env; then
        if pm2 describe sona >/dev/null 2>&1; then
            pm2 restart sona --update-env >/dev/null
        else
            pm2 start .venv/bin/python --name sona --cwd "$HOME/sona" -- run.py >/dev/null
        fi
    fi
    pm2 save >/dev/null
    ip=$(curl -fsS -4 https://api.ipify.org || curl -fsS -4 https://ifconfig.me)
    domain="${ip//./-}.sslip.io"
    sleep 3
    if curl -fsS "https://$domain/health" >/dev/null; then
        echo "✅ Données importées, Sona tourne : https://$domain"
    else
        echo "⚠️  Données importées, mais l'API ne répond pas : regarde « pm2 logs sona-api »."
    fi
}

main "$@"
