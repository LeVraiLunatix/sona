# Déploiement automatique depuis GitHub

Sona se déploie tout seul : chaque fusion sur `master` lance les tests, puis —
s'ils passent — une connexion SSH au VPS Oracle qui exécute `~/sona/deploy.sh`
(`git fetch`, `git reset --hard origin/master`, `pip install -r
requirements.txt`, `pm2 restart sona --update-env`).

Deux workflows :

| Fichier | Quand | Ce qu'il fait |
| --- | --- | --- |
| `.github/workflows/tests.yml` | chaque *pull request*, chaque push sur `master` | `python -m pytest -q` sous Python 3.12 |
| `.github/workflows/deploy.yml` | push sur `master`, ou lancement manuel (*Run workflow*) | relance les tests, puis déploie sur le VPS |

Le déploiement ne démarre jamais si les tests échouent, et `concurrency`
garantit qu'il n'y a qu'un déploiement à la fois : deux `git reset --hard`
concurrents laisseraient le serveur dans un état indéterminé.

Tant que les trois secrets ci-dessous n'existent pas, l'étape de déploiement
est **ignorée avec un avertissement** — le workflow reste vert. Rien ne casse
tant que la configuration n'est pas faite ; rien ne se déploie non plus.

---

## À faire une seule fois, depuis mon PC

### 1. Créer une clé SSH dédiée au déploiement

Une clé à part, qui ne sert qu'à ça : elle vit dans les secrets GitHub, et on
doit pouvoir la révoquer sans toucher à sa propre clé d'administration.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/sona_deploy -C "deploiement sona (github actions)" -N ""
```

- `-N ""` : sans phrase de passe, sinon le runner ne peut pas s'en servir.
- Deux fichiers sont créés : `~/.ssh/sona_deploy` (clé **privée**, pour le
  secret GitHub) et `~/.ssh/sona_deploy.pub` (clé **publique**, pour le
  serveur).
- La clé privée ne doit jamais être collée ailleurs que dans le secret
  GitHub — ni dans un commit, ni dans une conversation.

### 2. Autoriser cette clé sur le serveur, mais seulement pour déployer

La clé publique est ajoutée dans `~/.ssh/authorized_keys` du VPS **précédée
d'options** : une commande forcée, et le reste désactivé. Ainsi, même si la
clé fuitait, elle ne donnerait pas un shell sur le serveur — elle ne pourrait
que lancer le déploiement.

Affiche la clé publique sur le PC :

```bash
cat ~/.ssh/sona_deploy.pub
```

Puis, sur le serveur (connecté avec ta clé habituelle), ajoute la ligne
suivante à `~/.ssh/authorized_keys`, en remplaçant
`ssh-ed25519 AAAA… deploiement sona (github actions)` par ce qui vient d'être
affiché :

```
command="cd ~/sona && ./deploy.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA… deploiement sona (github actions)
```

Tout sur **une seule ligne**, les options collées à la clé (une virgule entre
chaque option, une espace avant `ssh-ed25519`).

Vérifie ensuite que le script est bien exécutable :

```bash
chmod +x ~/sona/deploy.sh
```

Test depuis le PC — la commande envoyée est ignorée, c'est la commande forcée
qui s'exécute :

```bash
ssh -i ~/.ssh/sona_deploy ubuntu@<adresse-du-serveur> "peu-importe"
```

Tu dois voir passer la sortie de `deploy.sh`, et **pas** un shell.

### 3. Relever l'empreinte du serveur

Le workflow refuse de se connecter à un serveur qu'il ne reconnaît pas
(jamais de `StrictHostKeyChecking=no`, qui accepterait n'importe quelle
machine répondant à cette adresse). Il faut donc lui fournir l'empreinte,
relevée depuis le PC :

```bash
ssh-keyscan -t ed25519 <adresse-du-serveur>
```

Copie la ligne renvoyée (elle commence par l'adresse, puis `ssh-ed25519`), en
ignorant les lignes de commentaire qui commencent par `#`.

Si le serveur écoute sur un autre port que 22, relève l'empreinte avec
`ssh-keyscan -p <port> …` : la ligne obtenue est alors de la forme
`[adresse]:<port> ssh-ed25519 …`.

### 4. Créer les trois secrets dans le dépôt

Sur GitHub : **Settings → Secrets and variables → Actions → New repository
secret**. Trois secrets, exactement ces noms :

| Nom | Contenu |
| --- | --- |
| `ORACLE_HOST` | `utilisateur@adresse`, par exemple `ubuntu@129.153.0.42` — l'utilisateur fait partie de la valeur |
| `ORACLE_SSH_KEY` | tout le contenu de `~/.ssh/sona_deploy`, de `-----BEGIN OPENSSH PRIVATE KEY-----` à `-----END OPENSSH PRIVATE KEY-----` inclus, retour à la ligne final compris |
| `ORACLE_KNOWN_HOSTS` | la ligne renvoyée par `ssh-keyscan` à l'étape 3 |

Pour copier la clé privée sans l'ouvrir dans un éditeur :

```bash
# Linux / macOS
pbcopy < ~/.ssh/sona_deploy        # macOS
xclip -sel clip < ~/.ssh/sona_deploy   # Linux
# Windows (PowerShell)
Get-Content ~/.ssh/sona_deploy | Set-Clipboard
```

### 5. Vérifier

Onglet **Actions → Déploiement → Run workflow** (branche `master`). Le job
`tests` doit passer, puis `Déployer sur le VPS` afficher la sortie de
`deploy.sh`. Sur le serveur, `pm2 logs sona` doit montrer un redémarrage.

---

## En cas de problème

- **« Déploiement ignoré : … n'est pas configuré »** : un des trois secrets
  manque ou est vide. Le workflow reste vert exprès.
- **`Host key verification failed`** : `ORACLE_KNOWN_HOSTS` ne correspond pas
  au serveur (adresse différente de celle de `ORACLE_HOST`, port non standard,
  ou serveur réinstallé). Refais l'étape 3.
- **`Permission denied (publickey)`** : la clé publique n'est pas dans
  `~/.ssh/authorized_keys` du bon utilisateur, ou `ORACLE_SSH_KEY` a été
  tronqué (il faut la clé **privée** entière).
- **La connexion réussit mais rien ne se déploie** : `deploy.sh` n'est pas
  exécutable, ou la commande forcée pointe sur un mauvais chemin. Relis la
  ligne d'`authorized_keys`.
- **Le bot redémarre mais le code est l'ancien** : `deploy.sh` doit faire un
  `git reset --hard origin/master` après le `git fetch`, sinon une
  modification locale sur le serveur bloque la mise à jour.

## Révoquer la clé

Retire sa ligne de `~/.ssh/authorized_keys` sur le serveur, supprime le secret
`ORACLE_SSH_KEY` sur GitHub, et refais les étapes 1, 2 et 4 avec une nouvelle
clé.

## Ce que le déploiement ne touche jamais

`.env`, `data/sona.db` et `data/cookies.txt` vivent uniquement sur le serveur
et ne sont pas suivis par git : une mise à jour ne les remplace pas. Un
nouveau réglage dans `.env.example` doit donc être reporté à la main dans le
`.env` du VPS avant le déploiement qui s'en sert.
