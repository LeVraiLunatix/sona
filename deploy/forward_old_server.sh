#!/usr/bin/env bash
# Optionnel, sur l'ANCIEN serveur une fois le nouveau en place : son adresse
# renvoie vers le nouveau serveur. Les iPhone qui ont encore l'ancienne
# adresse (amis pas encore mis à jour) continuent de marcher.
#
#   curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/forward_old_server.sh | bash -s https://<nouvelle-adresse>
set -euo pipefail

main() {
    local target="${1:-}"
    target="${target#https://}"
    target="${target%/}"
    if [ -z "$target" ]; then
        echo "Usage : forward_old_server.sh https://<nouvelle-adresse>" >&2
        exit 1
    fi
    local file=/etc/caddy/Caddyfile
    if [ ! -f "$file" ]; then
        echo "Pas de Caddy sur ce serveur : rien à faire." >&2
        exit 1
    fi
    # Première adresse déclarée dans le Caddyfile actuel.
    local old
    old=$(grep -v '^\s*#' "$file" | awk 'NF && $1 != "{" {print $1; exit}')
    sudo cp "$file" "$file.avant-renvoi"
    sudo tee "$file" >/dev/null <<CADDY
# Sona a déménagé : tout est relayé vers le nouveau serveur.
$old {
    reverse_proxy https://$target {
        header_up Host $target
    }
}
CADDY
    if sudo caddy validate --config "$file" --adapter caddyfile >/dev/null 2>&1; then
        sudo systemctl reload caddy
        pm2 stop all >/dev/null 2>&1 || true
        echo "✅ $old renvoie maintenant vers $target (ancienne config : $file.avant-renvoi)."
    else
        sudo cp "$file.avant-renvoi" "$file"
        echo "⚠️  Configuration refusée par Caddy : rien n'a changé." >&2
        exit 1
    fi
}

main "$@"
