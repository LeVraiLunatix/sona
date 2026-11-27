#!/usr/bin/env bash
# Mise à jour du serveur : lancé par GitHub Actions (commande forcée de la clé
# de déploiement, voir docs/DEPLOIEMENT.md) ou à la main :
#   cd ~/sona && ./deploy/deploy.sh
#
# Tout le travail est dans une fonction : bash lit le script en entier avant
# de l'exécuter, alors que `git reset` peut remplacer ce fichier en cours de
# route.
set -euo pipefail

# Chaque nuit à 4 h 17 : yt-dlp mis à jour, essayé, et remis à l'ancienne
# version si la nouvelle ne lit plus YouTube (app/services/ytdlp_updater.py).
install_nightly_update() {
    local dir line
    dir="$(pwd)"
    line="17 4 * * * cd $dir && PATH=$PATH .venv/bin/python -m app.services.ytdlp_updater >> data/ytdlp_update.log 2>&1"
    if ! crontab -l 2>/dev/null | grep -qF "app.services.ytdlp_updater"; then
        ({ crontab -l 2>/dev/null || true; }; echo "$line") | crontab - && echo "Mise à jour nocturne de yt-dlp installée"
    fi
}

main() {
    cd "$(dirname "$0")/.."
    git fetch --quiet origin master
    git reset --hard --quiet origin/master
    # Réglages sans lesquels plus personne ne peut se connecter : on s'arrête avant de redémarrer
    # (les processus en cours gardent l'ancien code).
    for key in SONA_ACCOUNTS_URL INTERNAL_API_SECRET STORAGE_KEY; do
        grep -q "^$key=." .env || { echo "ARRÊT : $key manque dans .env (voir docs/AUTH_SETUP.md)." >&2; exit 1; }
    done
    .venv/bin/pip install --quiet --upgrade -r requirements.txt
    install_nightly_update
    # `sona` était le bot Telegram, retiré : seul le serveur de musique redémarre.
    for name in sona-api; do
        if pm2 describe "$name" >/dev/null 2>&1; then
            pm2 restart "$name" --update-env >/dev/null
            echo "Redémarré : $name"
        fi
    done
    echo "Déployé : $(git log -1 --format='%h %s')"
}

main "$@"
