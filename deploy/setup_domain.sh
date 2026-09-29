#!/usr/bin/env bash
# Adresse fixe et gratuite pour Sona (DuckDNS) : `https://<nom>.duckdns.org`,
# qui suit le serveur même s'il change d'adresse IP ou de machine — plus
# jamais besoin de changer l'adresse dans l'app.
#
# 1. Sur https://www.duckdns.org : connecte-toi (GitHub, Google…), crée un
#    sous-domaine (ex. « sona-lunatix ») et copie ton « token ».
# 2. Sur le serveur :
#      cd ~/sona && ./deploy/setup_domain.sh sona-lunatix <token>
set -euo pipefail

main() {
    local name="${1:-}" token="${2:-}"
    name="${name%.duckdns.org}"
    if [ -z "$name" ] || [ -z "$token" ]; then
        echo "Usage : ./deploy/setup_domain.sh <sous-domaine> <token DuckDNS>" >&2
        exit 1
    fi
    local domain="$name.duckdns.org"

    echo "▶ Mise à jour de l'adresse IP chez DuckDNS"
    local answer
    answer=$(curl -fsS "https://www.duckdns.org/update?domains=$name&token=$token&ip=")
    if [ "$answer" != "OK" ]; then
        echo "DuckDNS a refusé (réponse : $answer) : vérifie le sous-domaine et le token." >&2
        exit 1
    fi

    echo "▶ Mise à jour automatique toutes les 5 minutes"
    mkdir -p "$HOME/.duckdns"
    chmod 700 "$HOME/.duckdns"
    cat > "$HOME/.duckdns/update.sh" <<SCRIPT
#!/usr/bin/env bash
curl -fsS "https://www.duckdns.org/update?domains=$name&token=$token&ip=" > "$HOME/.duckdns/last.log" 2>&1
SCRIPT
    chmod 700 "$HOME/.duckdns/update.sh"
    (crontab -l 2>/dev/null | grep -v '.duckdns/update.sh'; echo "*/5 * * * * $HOME/.duckdns/update.sh") | crontab -

    echo "▶ HTTPS pour $domain (Caddy)"
    local file=/etc/caddy/Caddyfile
    if ! grep -qF "$domain" "$file"; then
        sudo cp "$file" "$file.avant-duckdns"
        printf '\n# Adresse fixe (DuckDNS).\n%s {\n    reverse_proxy 127.0.0.1:8000\n}\n' "$domain" | sudo tee -a "$file" >/dev/null
        if ! sudo caddy validate --config "$file" --adapter caddyfile >/dev/null 2>&1; then
            sudo cp "$file.avant-duckdns" "$file"
            echo "Configuration Caddy refusée : ancienne configuration remise." >&2
            exit 1
        fi
        sudo systemctl reload caddy
    fi

    echo "▶ Vérification (le certificat HTTPS peut prendre une minute)"
    for _ in $(seq 1 20); do
        if curl -fsS "https://$domain/health" >/dev/null 2>&1; then
            cat <<INFO

✅ Sona répond sur https://$domain

À faire :
  • dans l'app : Réglages → adresse du serveur → https://$domain
  • sur GitHub : secret IOS_API_BASE_URL → https://$domain
    (les prochaines versions de l'app l'auront directement)
L'ancienne adresse sslip.io continue de marcher.
INFO
            return
        fi
        sleep 5
    done
    echo "⚠️  Pas encore de réponse sur https://$domain : réessaie dans quelques minutes (DNS)." >&2
}

main "$@"
