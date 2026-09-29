#!/usr/bin/env bash
# Mise à jour du serveur : lancé par GitHub Actions (commande forcée de la clé
# de déploiement, voir docs/DEPLOIEMENT.md) ou à la main :
#   cd ~/sona && ./deploy/deploy.sh
#
# Tout le travail est dans une fonction : bash lit le script en entier avant
# de l'exécuter, alors que `git reset` peut remplacer ce fichier en cours de
# route.
set -euo pipefail

main() {
    cd "$(dirname "$0")/.."
    git fetch --quiet origin master
    git reset --hard --quiet origin/master
    .venv/bin/pip install --quiet --upgrade -r requirements.txt
    for name in sona-api sona; do
        if pm2 describe "$name" >/dev/null 2>&1; then
            pm2 restart "$name" --update-env >/dev/null
            echo "Redémarré : $name"
        fi
    done
    echo "Déployé : $(git log -1 --format='%h %s')"
}

main "$@"
