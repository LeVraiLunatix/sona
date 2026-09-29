#!/usr/bin/env bash
# Installation complète de Sona sur un serveur neuf (Oracle Cloud, Ubuntu
# 24.04, ARM ou x86) — voir docs/MIGRATION_ORACLE.md.
#
#   curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/install_oracle.sh | bash
#
# Relançable sans risque : chaque étape vérifie ce qui est déjà fait.
set -euo pipefail

REPO="https://github.com/LeVraiLunatix/sona.git"
DIR="$HOME/sona"

step() { printf '\n\033[1;35m▶ %s\033[0m\n' "$1"; }

main() {
    step "Paquets système (Python, FFmpeg, Git, Node/PM2, Caddy)"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        git curl python3 python3-venv python3-pip ffmpeg sqlite3 nodejs npm \
        iptables-persistent debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
    python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("Python 3.11 ou plus est nécessaire : choisis l'image Ubuntu 24.04 pour le serveur.")
PY
    if ! command -v caddy >/dev/null; then
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
        sudo apt-get update -qq
        sudo apt-get install -y -qq caddy >/dev/null
    fi
    command -v pm2 >/dev/null || sudo npm install -g pm2 --silent >/dev/null

    step "Pare-feu : ports 80 et 443 (HTTPS)"
    # Les images Ubuntu d'Oracle rejettent tout sauf SSH : on ouvre le web
    # juste avant la règle REJECT, et on l'enregistre pour les redémarrages.
    for port in 80 443; do
        if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
            reject=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
            if [ -n "$reject" ]; then
                sudo iptables -I INPUT "$reject" -p tcp --dport "$port" -m state --state NEW -j ACCEPT
            else
                sudo iptables -A INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT
            fi
        fi
    done
    sudo netfilter-persistent save >/dev/null

    step "Code de Sona"
    if [ ! -d "$DIR/.git" ]; then
        git clone --quiet "$REPO" "$DIR"
    else
        git -C "$DIR" fetch --quiet origin master
        git -C "$DIR" reset --hard --quiet origin/master
    fi
    cd "$DIR"
    [ -d .venv ] || python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt magic-wormhole
    mkdir -p data
    [ -f .env ] || cp .env.example .env
    # L'API n'écoute qu'en local : c'est Caddy qui l'expose en HTTPS.
    grep -q '^API_HOST=' .env && sed -i 's/^API_HOST=.*/API_HOST=127.0.0.1/' .env || echo 'API_HOST=127.0.0.1' >> .env

    step "Adresse HTTPS (Caddy + sslip.io)"
    ip=$(curl -fsS -4 https://api.ipify.org || curl -fsS -4 https://ifconfig.me)
    domain="${ip//./-}.sslip.io"
    sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
# Sona : HTTPS automatique (certificat Let's Encrypt) devant l'API locale.
$domain {
    reverse_proxy 127.0.0.1:8000
}
CADDY
    sudo systemctl enable --now caddy >/dev/null 2>&1
    sudo systemctl reload caddy

    step "Processus (PM2) et démarrage automatique"
    if ! pm2 describe sona-api >/dev/null 2>&1; then
        pm2 start .venv/bin/python --name sona-api --cwd "$DIR" -- run_api.py >/dev/null
    fi
    if grep -q '^BOT_TOKEN=.\+' .env && ! pm2 describe sona >/dev/null 2>&1; then
        pm2 start .venv/bin/python --name sona --cwd "$DIR" -- run.py >/dev/null
    fi
    pm2 save >/dev/null
    sudo env PATH="$PATH:/usr/bin" "$(command -v pm2)" startup systemd -u "$USER" --hp "$HOME" >/dev/null

    step "Clé de déploiement GitHub (déploiement automatique)"
    key="$HOME/.ssh/sona_github_deploy"
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    if [ ! -f "$key" ]; then
        ssh-keygen -q -t ed25519 -N "" -C "deploiement sona (github actions)" -f "$key"
    fi
    touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys"
    if ! grep -qF "$(cut -d' ' -f2 "$key.pub")" "$HOME/.ssh/authorized_keys"; then
        # Commande forcée : cette clé ne peut que lancer le déploiement.
        echo "command=\"cd ~/sona && ./deploy/deploy.sh\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $(cat "$key.pub")" \
            >> "$HOME/.ssh/authorized_keys"
    fi
    chmod +x deploy/*.sh

    step "Vérification"
    ok=false
    for _ in $(seq 1 30); do
        if curl -fsS "https://$domain/health" >/dev/null 2>&1; then ok=true; break; fi
        sleep 4
    done

    cat <<INFO

════════════════════════════════════════════════════════════════════
 Sona est installé.

 Adresse du serveur : https://$domain
 $( $ok && echo "✅ elle répond." || echo "⚠️  pas encore de réponse : vérifie les ports 80/443 dans la « Security List » Oracle (docs/MIGRATION_ORACLE.md, étape 2)." )

 Secrets GitHub à mettre à jour (Settings → Secrets and variables → Actions) :
   ORACLE_HOST         $USER@$ip
   ORACLE_KNOWN_HOSTS  $(ssh-keyscan -t ed25519 localhost 2>/dev/null | sed "s/^localhost/$ip/")
   ORACLE_SSH_KEY      la clé privée : affiche-la avec
                         cat ~/.ssh/sona_github_deploy
                       et colle-la UNIQUEMENT dans le secret GitHub.
   IOS_API_BASE_URL    https://$domain

 Étape suivante : récupérer les données de l'ancien serveur
   (docs/MIGRATION_ORACLE.md, étape 4).
════════════════════════════════════════════════════════════════════
INFO
}

main "$@"
