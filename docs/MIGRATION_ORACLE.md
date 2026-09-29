# Passer Sona sur Oracle Cloud (gratuit)

La petite machine Google (e2-micro : 2 cœurs partagés, 1 Go de mémoire)
ralentit tout : lancement des titres, recherche, analyse audio. Oracle Cloud
offre **gratuitement et sans limite de durée** une machine ARM jusqu'à
**4 cœurs et 24 Go de mémoire** (offre « Always Free »). Tout se fait en
quatre commandes ; tes comptes, écoutes, playlists et réglages suivent.

Durée : 20 à 30 minutes.

---

## 1. Créer la machine

Console Oracle Cloud → **Compute → Instances → Create instance**.

- **Name** : `sona`
- **Image** : *Change image* → **Canonical Ubuntu 24.04** (pas 22.04).
- **Shape** : *Change shape* → **Ampere** → `VM.Standard.A1.Flex`,
  **4 OCPU** et **24 GB** de mémoire (le maximum gratuit).
- **Networking** : garde le réseau proposé, avec **Assign a public IPv4
  address** coché.
- **Add SSH keys** : *Generate a key pair for me* → **télécharge la clé
  privée** (fichier `.key`), c'est elle qui te connecte au serveur.
- **Create**.

**« Out of capacity » ?** C'est fréquent sur les machines Ampere gratuites.
Réessaie un peu plus tard ou change d'*Availability domain* (AD-1, AD-2,
AD-3). Autre solution efficace : passer le compte en **Pay As You Go**
(*Billing → Upgrade*) — les ressources « Always Free » restent gratuites,
et la capacité se trouve bien plus facilement. Crée alors un **budget
avec alerte à 1 €** (*Billing → Budgets*) pour être prévenu si quelque
chose devenait payant.

Note l'**adresse IP publique** de l'instance une fois qu'elle est
*Running*.

## 2. Ouvrir le web (ports 80 et 443)

Sur la page de l'instance → **Subnet** (lien) → **Security Lists** →
*Default Security List* → **Add Ingress Rules**, deux fois :

| Source CIDR | IP Protocol | Destination Port Range |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

(Le pare-feu de la machine elle-même est ouvert par le script de l'étape 3.)

## 3. Installer Sona sur la nouvelle machine

Connecte-toi (depuis ton PC, avec la clé téléchargée) :

```bash
ssh -i chemin/vers/la-cle.key ubuntu@<IP-publique>
```

Puis lance l'installation complète :

```bash
curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/install_oracle.sh | bash
```

Le script installe Python, FFmpeg, PM2, Caddy (HTTPS automatique), ouvre
les ports, installe Sona, démarre l'API au boot et prépare la clé de
déploiement. À la fin, il affiche **la nouvelle adresse du serveur**
(`https://<ip-avec-tirets>.sslip.io`) et **les valeurs des secrets
GitHub** à mettre à jour (étape 5).

## 4. Transférer les données de l'ancien serveur

Deux fenêtres de terminal : une sur l'**ancien** serveur (Google), une sur
le **nouveau** (Oracle).

Sur l'**ancien** serveur :

```bash
curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/export_from_old_server.sh | bash
```

Il copie la base, le `.env` et les cookies YouTube, puis affiche un
**code** du genre `7-guitare-soleil`. Laisse la fenêtre ouverte.

Sur le **nouveau** serveur :

```bash
cd ~/sona && ./deploy/import_transfer.sh 7-guitare-soleil
```

Le transfert est chiffré de bout en bout. Une fois fini, Sona tourne sur
le nouveau serveur avec toutes tes données, et le bot Telegram de l'ancien
serveur est arrêté (un seul bot à la fois).

## 5. Mettre à jour GitHub

Dépôt → **Settings → Secrets and variables → Actions**, modifie ces quatre
secrets avec les valeurs affichées à la fin de l'étape 3 :

| Secret | Valeur |
| --- | --- |
| `ORACLE_HOST` | `ubuntu@<IP-publique>` |
| `ORACLE_KNOWN_HOSTS` | la ligne `<IP> ssh-ed25519 …` affichée |
| `ORACLE_SSH_KEY` | le contenu de `cat ~/.ssh/sona_github_deploy` sur le nouveau serveur (de `-----BEGIN` à `-----END…KEY-----` inclus) |
| `IOS_API_BASE_URL` | `https://<ip-avec-tirets>.sslip.io` |

⚠️ La clé privée ne se colle **que** dans le secret GitHub — jamais dans
une conversation ni un fichier du dépôt. Une fois collée, tu peux
l'effacer du serveur : `rm ~/.ssh/sona_github_deploy`.

Vérifie : onglet **Actions → Déploiement → Run workflow**. Il doit
passer au vert (le déploiement automatique remarche).

## 6. Basculer l'app

- **Tout de suite, sans réinstaller** : dans l'app, **Réglages → adresse du
  serveur** → la nouvelle adresse.
- La prochaine version de l'app (construite après la mise à jour de
  `IOS_API_BASE_URL`) contient directement la nouvelle adresse.
- **Pour les amis qui ont encore l'ancienne adresse** : sur l'**ancien**
  serveur, redirige-la vers le nouveau (ils n'ont rien à faire) :

  ```bash
  curl -fsSL https://raw.githubusercontent.com/LeVraiLunatix/sona/master/deploy/forward_old_server.sh | bash -s https://<nouvelle-adresse>
  ```

  Ça arrête aussi Sona sur l'ancien serveur, qui ne sert plus que de relais.

---

## Au quotidien

- Journaux : `pm2 logs sona-api` (API), `pm2 logs sona` (bot Telegram).
- Mise à jour à la main : `cd ~/sona && ./deploy/deploy.sh`.
- Cookies YouTube : `~/sona/data/cookies.txt`, comme avant.
- Après un redémarrage de la machine, tout repart seul (PM2 et Caddy
  démarrent au boot).
