# Guide d'installation

Ce document explique comment mettre en place le Daily News Newsletter Agent de A à Z.

---

## Prérequis

- Python 3.11+
- Node.js 18+ (pour les MCP Claude Desktop)
- Un compte Gmail
- Un compte GitHub
- Un compte Google Cloud Platform (gratuit)
- Un compte Railway ou Render (gratuit, pour l'auth server)

---

## Étape 1 — Cloner et installer

```bash
git clone https://github.com/yousmaaza/newletter-ai
cd newletter-ai
pip install -r requirements.txt
cp .env.example .env
```

---

## Étape 2 — Clé Anthropic

1. Va sur [console.anthropic.com](https://console.anthropic.com)
2. Crée une clé API
3. Ajoute dans `.env` :
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Étape 3 — Clé Brave Search

Obtenir une clé gratuite sur [https://brave.com/search/api/](https://brave.com/search/api/) puis l'ajouter dans `.env` :

```
BRAVE_API_KEY=<votre_clé>
```

---

## Étape 4 — Configurer Gmail OAuth2

### 4a. Créer le projet Google Cloud

1. Va sur [console.cloud.google.com](https://console.cloud.google.com)
2. Crée un nouveau projet (ex: `newsletter-agent`)
3. Menu → **API et services → Bibliothèque** → recherche `Gmail API` → **Activer**

### 4b. Configurer l'écran de consentement OAuth

1. Menu → **API et services → Écran de consentement OAuth**
2. Type : **Externe** → **Créer**
3. Remplis le nom de l'application et ton email d'assistance
4. Dans **Utilisateurs test** → ajoute ton adresse Gmail
5. **Enregistrer**

### 4c. Créer les credentials OAuth2 (pour usage local)

1. Menu → **API et services → Identifiants → Créer des identifiants → ID client OAuth**
2. Type : **Application de bureau**
3. Nom : `newsletter-local`
4. **Créer** → télécharge le JSON

```bash
mkdir -p ~/.gmail-mcp
mv ~/Downloads/client_secret_*.json ~/.gmail-mcp/credentials.json
```

### 4d. Générer le token OAuth (première authentification)

```bash
python main.py --now
```

Une fenêtre de navigateur s'ouvre → sélectionne ton compte Gmail → autorise l'accès.

Le token est sauvegardé dans `~/.gmail-mcp/token.json`.

### 4e. Configurer `.env`

```
GMAIL_FROM=ton-email@gmail.com
GMAIL_TO=destinataire@example.com
GMAIL_CREDENTIALS_PATH=~/.gmail-mcp/credentials.json
GMAIL_TOKEN_PATH=~/.gmail-mcp/token.json
```

---

## Étape 5 — Gmail App Password (pour les notifications)

Le App Password est utilisé pour envoyer l'email de re-authentification quand le token OAuth expire.

1. Va sur [myaccount.google.com](https://myaccount.google.com)
2. **Sécurité** → activer la **Validation en deux étapes**
3. Recherche **"Mots de passe des applications"**
4. Crée un mot de passe pour `Newsletter Agent`
5. Copie le code à 16 caractères (sans espaces)

```
GMAIL_APP_PASSWORD=abcdefghijklmnop
```

---

## Étape 6 — Déployer l'auth server (renouvellement automatique du token)

L'auth server gère le renouvellement automatique du token Gmail via une interface web.

### 6a. Créer un client OAuth Web Application

1. Dans Google Cloud Console → **Identifiants → Créer des identifiants → ID client OAuth**
2. Type : **Application Web** (important — pas "Application de bureau")
3. Nom : `newsletter-auth-server`
4. **URI de redirection autorisées** → ajoute : `https://ton-app.railway.app/callback`
5. **Créer** → note le Client ID et Client Secret

### 6b. Créer le PAT GitHub

Un seul jeton sert au serveur, au pipeline et à l'Apps Script.

1. GitHub → **Settings → Developer settings → Fine-grained personal access tokens**
2. **Generate new token**
3. Repository access → *Only select repositories* → coche **les deux** :
   `newletter-ai` **et** `newsletter-data`
4. Repository permissions :

   | Permission | Niveau | Pourquoi |
   |---|---|---|
   | **Contents** | Read and write | Lire et écrire les TOML et les CSV |
   | **Actions** | Read **and write** | Lecture pour la carte « Fiabilité de l'envoi » ; écriture pour que le veilleur puisse relancer un envoi manquant |
   | **Secrets** | Read and write | Le serveur réécrit `GMAIL_TOKEN_JSON` après ré-authentification |

5. **Generate token** → copie-le immédiatement, GitHub ne le réaffiche jamais

> ⚠️ **Ne pas confondre avec `secrets.GITHUB_TOKEN`**, le jeton que GitHub
> ⚠️ Sans le **write** sur Actions, le veilleur d'envoi voit tout et ne peut
> rien relancer : GitHub répond 403, l'erreur est journalisée, et l'édition
> manquante le reste.

> Actions fournit automatiquement. Celui-là est limité au dépôt courant *par
> conception* : il ne peut pas lire le dépôt de données, quelles que soient les
> permissions accordées. D'où ce PAT distinct, stocké sous le nom `GIT_TOKEN`.

> ⚠️ **L'expiration est un mode de panne.** Le jour où le jeton expire, la
> récupération des abonnés échoue et la newsletter ne part pas. Prends la durée
> la plus longue proposée et pose-toi un rappel une semaine avant.

### 6c. Déployer sur Railway

```bash
# Installer Railway CLI
npm install -g @railway/cli

# Depuis le dossier auth_server/
cd auth_server
railway login
railway init
railway up
```

Variables d'environnement à configurer dans le dashboard Railway :

| Variable | Valeur |
|----------|--------|
| `GOOGLE_CLIENT_ID` | Client ID du client Web Application |
| `GOOGLE_CLIENT_SECRET` | Client Secret du client Web Application |
| `AUTH_SERVER_URL` | URL publique Railway (ex: `https://mon-app.railway.app`) |
| `GITHUB_TOKEN` | PAT GitHub avec permission secrets |
| `GITHUB_REPO` | `yousmaaza/newletter-ai` |

Puis ajoute dans `.env` :
```
AUTH_SERVER_URL=https://ton-app.railway.app
```

---

## Étape 7 — Configurer les secrets GitHub Actions

Dans ton repo → **Settings → Secrets and variables → Actions** :

| Secret | Valeur | Comment l'obtenir |
|--------|--------|-------------------|
| `ANTHROPIC_API_KEY` | Clé Anthropic | console.anthropic.com |
| `BRAVE_API_KEY` | Clé Brave Search | Depuis le MCP configuré |
| `GMAIL_FROM` | Email expéditeur | Ton adresse Gmail |
| `GMAIL_TO` | Email(s) destinataire(s) | Séparés par des virgules |
| `GMAIL_CREDENTIALS_JSON` | Contenu de `credentials.json` | `cat ~/.gmail-mcp/credentials.json` |
| `GMAIL_TOKEN_JSON` | Contenu de `token.json` | `cat ~/.gmail-mcp/token.json` |
| `GMAIL_APP_PASSWORD` | App Password Gmail | Étape 5 ci-dessus |
| `AUTH_SERVER_URL` | URL Railway | `https://ton-app.railway.app` |

```bash
# Commandes pour copier les fichiers JSON dans le presse-papier (macOS)
cat ~/.gmail-mcp/credentials.json | pbcopy
cat ~/.gmail-mcp/token.json | pbcopy
```

---

## Étape 8 — Tester

### Test local

```bash
python main.py --now
```

### Test GitHub Actions

1. GitHub → **Actions → Daily Newsletter → Run workflow → Run workflow**
2. Consulte les logs en direct

### Test du renouvellement automatique du token

1. Remplace `GMAIL_TOKEN_JSON` dans les secrets GitHub par un token invalide :
```json
{"token":"invalid","refresh_token":"invalid","token_uri":"https://oauth2.googleapis.com/token","client_id":"fake","client_secret":"fake","scopes":["https://www.googleapis.com/auth/gmail.send"]}
```
2. Lance le workflow → tu reçois l'email de re-auth → clique → le secret est mis à jour automatiquement

---

---

## Étape 9 — Sync automatique des destinataires (Google Form)

Cette étape permet d'ajouter automatiquement dans la liste des destinataires
toute personne ayant rempli le formulaire Google d'inscription.

### 9a. Partager la Google Sheet avec le compte projet

La Google Sheet liée au formulaire doit être accessible par le compte Google
utilisé dans le projet (celui des credentials Gmail OAuth) :

1. Ouvre la Google Sheet des réponses du formulaire
2. **Partager** → ajoute l'adresse Gmail du compte projet → rôle **Éditeur**

### 9b. Jeton GitHub pour l'Apps Script

Réutilise le PAT de l'étape 6b — il couvre déjà les deux dépôts.

> ⚠️ Il lui faut impérativement accès à **`newsletter-data`**, où l'Apps Script
> écrit désormais. Sans cet accès, GitHub répond 404 — le même code que pour un
> fichier absent — et la synchronisation croit que personne ne s'est désabonné.
> Voir le diagnostic en 9e.

### 9c. Déployer le Apps Script

1. Ouvre la Google Sheet des réponses du formulaire
2. **Extensions → Apps Script**
3. Supprime le contenu par défaut et colle le contenu de `scripts/sync_recipients.gs`
4. **Fichier → Propriétés du projet → Propriétés du script** → Ajoute les 2 propriétés suivantes :
   - Clé : `GITHUB_TOKEN` / Valeur : le PAT copié à l'étape 9b
   - Clé : `GOOGLE_SHEET_ID` / Valeur : l'ID de la Sheet (dans l'URL : `docs.google.com/spreadsheets/d/**<ID>**/edit`)
5. **Enregistrer**

### 9d. Configurer le déclencheur onFormSubmit

1. Dans l'éditeur Apps Script → icône **Déclencheurs** (horloge) → **Ajouter un déclencheur**
2. Paramètres :
   - Fonction à exécuter : `onFormSubmit`
   - Source de l'événement : **Depuis le formulaire**
   - Type d'événement : **À l'envoi du formulaire**
3. **Enregistrer**

### 9e. Tester

Dans l'éditeur Apps Script, lance manuellement `testSync`. Le journal doit
montrer des compteurs **non nuls** :

```
Emails depuis la Sheet : 30
Emails déjà dans recipients.toml : 26     ← doit être > 0
Emails désinscrits : 6                    ← doit refléter la réalité
Fichier mis à jour : config/recipients.toml (HTTP 200)
```

Le fichier est mis à jour **dans le dépôt privé `newsletter-data`**, pas ici.

> ⚠️ **Si tu vois `0` et `0`, arrête-toi.** Le jeton n'a pas accès au dépôt de
> données. GitHub répond alors 404 — le même code que pour un fichier absent —
> et la synchronisation croit que personne ne s'est désabonné : elle
> **réinscrirait les désabonnés** au prochain formulaire soumis.
>
> `assertRepoReachable_` interrompt normalement l'exécution dans ce cas, en
> vérifiant l'accès au dépôt avant toute lecture de fichier. Si l'exécution
> continue malgré des compteurs à zéro, c'est qu'une version ancienne du script
> est collée dans l'éditeur.

### Fonctionnement

- À chaque nouvelle réponse, le Apps Script lit les emails de la Sheet,
  déduplique, filtre les désinscrits et commit `config/recipients.toml` dans
  **`DATA_REPO`** (`yousmaaza/newsletter-data`, privé)
- Au démarrage de chaque envoi, l'étape « Récupérer les données d'abonnés »
  rapatrie ce fichier — les nouveaux destinataires sont inclus automatiquement
- `GMAIL_TO` reste un **repli** si `recipients.toml` est absent ou vide

> ⚠️ En local, lance **toujours** `scripts/fetch_subscriber_data.py` avant un
> envoi. Sans lui, `config.GMAIL_TO` retombe sur la variable d'environnement et
> l'édition part aux mauvaises adresses. Détail dans
> [ABONNES.md](ABONNES.md#2-où-vivent-les-données).

---

## Résumé des fichiers de configuration

```
~/.gmail-mcp/credentials.json    # Credentials OAuth2 Google (client local)
~/.gmail-mcp/token.json          # Token d'accès Gmail (renouvelé auto)
.env                             # Variables d'environnement locales
scripts/sync_recipients.gs       # Copie de référence — à coller dans Apps Script
.github/workflows/newsletter.yml # Cron GitHub Actions

# Rapatriés depuis DATA_REPO, gitignorés ici :
config/recipients.toml           # abonnés actifs
config/unsubscribed.toml         # désinscrits
config/tracking_optout.toml      # refus de mesure
config/subscriber_ids.toml       # identifiants de mesure
```
