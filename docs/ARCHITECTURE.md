# Architecture

Comment le pipeline est construit, section par section : ce que fait chaque
fichier, dans quel ordre, et avec quelles variables.

Pour la mesure d'audience et les tableaux de bord, voir [MESURE.md](MESURE.md).
Pour la gestion des abonnés, [ABONNES.md](ABONNES.md).

---

## 1. Agent Claude (boucle tool_use)

**Fichier :** `agent.py`

Le cœur du projet. Claude Sonnet 4.6 orchestre l'ensemble du pipeline de manière autonome via une boucle `tool_use`. Il décide quels outils appeler, dans quel ordre, et génère le contenu de la newsletter.

### Signature

```python
run_agent(recipients_override: list[str] | None = None)
```

| Paramètre | Description |
|-----------|-------------|
| `recipients_override` | N'envoie qu'à ces adresses ; la liste d'abonnés n'est jamais lue |

### Outils disponibles

| Outil | Description |
|-------|-------------|
| `search_today_news` | Recherche les actualités du jour via Brave Search |
| `send_newsletter` | Génère le HTML et envoie la newsletter par email |

### Flux d'exécution

```
1. Claude reçoit le prompt "Génère la newsletter du [date]"
2. Appelle search_today_news(topics=[...], count=10)
3. Reçoit les articles bruts
4. Sélectionne les 10 news les plus percutantes
5. Génère le contenu structuré (titre, flash, détail, hype, sources)
6. Appelle send_newsletter(subject, newsletter_title, intro, articles, conclusion)
7. Le HTML est rendu via Jinja2 et envoyé via Gmail
8. Les données sont sauvegardées dans output/newsletter/DATE/data.json
```

### Format des articles générés

| Champ | Type | Description |
|-------|------|-------------|
| `rank` | integer | Rang de 1 à 10 |
| `title` | string | Titre court et percutant (≤ 10 mots) |
| `flash` | string | 1 phrase style journaliste radio |
| `detail` | string | 2-3 phrases de contexte et analyse |
| `topic` | string | Thème (technologie, science, business, monde, santé) |
| `hype` | enum | `viral` / `trending` / `notable` |
| `sources` | array | 1 à 3 articles sources avec titre, URL, publication |

### Niveau d'importance (hype)

| Valeur | Signification | Couleur email |
|--------|---------------|---------------|
| `viral` 🔥 | Breaking news, explosif, tout le monde en parle | Rouge |
| `trending` 📈 | Monte en puissance, forte couverture médiatique | Orange |
| `notable` 💡 | Information importante, plus posée | Vert |

---

## 2. Recherche d'actualités (Brave Search)

**Fichier :** `tools/brave_search.py`

Recherche les actualités du jour via l'API REST Brave Search.

### Fonctionnement

- Effectue une requête par thème configuré (technologie, science, business, monde, santé)
- Filtre les articles des dernières 24h (`freshness=pd`)
- Déduplique les articles par URL
- Respecte le rate limit de l'API (1 requête/seconde)
- Fallback : recherche générale si pas assez d'articles par thème

### Paramètres de recherche

| Paramètre | Valeur |
|-----------|--------|
| Langue | Français (`fr`) |
| Pays | France (`FR`) |
| Fraîcheur | Dernier jour (`pd`) |
| Articles par thème | `count / nb_topics` |

---

## 3. Newsletter HTML

**Fichier :** `newsletter_template.html`

Template Jinja2 générant un email HTML responsive et professionnel.

### Structure de l'email

```
┌─────────────────────────────────┐
│  Header sombre + date + titre   │
├─────────────────────────────────┤
│  Introduction                   │
├─────────────────────────────────┤
│  Article 1                      │
│  [🔥 VIRAL] [technologie] [#1]  │
│  Titre de l'article             │
│  Flash info (1 phrase)          │
│  Détail (2-3 phrases)           │
│  Sources : [Lien 1] [Lien 2]   │
│  ─────────────────────────────  │
│  ...                            │
│  Article 10                     │
├─────────────────────────────────┤
│  Conclusion + footer            │
└─────────────────────────────────┘
```

### Caractéristiques

- Design responsive (max-width 620px, compatible mobile)
- Fond sombre `#1c1917` avec bordure rouge `#b91c1c`
- Badges colorés par niveau hype (rouge / orange / vert)
- Liens vers les sources originales
- Compatible avec les principaux clients email

---

## 4. Envoi email (Gmail API)

**Fichier :** `tools/gmail_tool.py`

Envoie la newsletter par email via l'API Gmail v1 avec authentification OAuth2.

### Caractéristiques

- Authentification OAuth2 (pas de mot de passe en clair)
- Support multi-destinataires (`GMAIL_TO` séparé par des virgules)
- Email MIME multipart (HTML + texte brut en fallback)
- Rafraîchissement automatique du token d'accès
- Détection automatique de l'expiration du token (`invalid_grant`)

### Gestion de l'expiration du token

Quand le token OAuth expire :
1. L'erreur `invalid_grant` est interceptée
2. Un email de notification est envoyé automatiquement via `auth_notifier.py`
3. Une erreur claire est levée avec les instructions de résolution

---

## 5. Renouvellement automatique du token Gmail

**Fichiers :** `tools/auth_notifier.py`, `auth_server/app.py`

Système de renouvellement du token Gmail sans intervention manuelle dans le code.

### Flux de renouvellement

```
Token expiré (invalid_grant)
        ↓
auth_notifier.py envoie un email via SMTP App Password
        ↓
Email reçu : bouton "Renouveler l'accès Gmail →"
        ↓
Clic → auth_server /auth → consentement Google OAuth
        ↓
auth_server /callback → échange le code → nouveau token
        ↓
Mise à jour automatique du secret GMAIL_TOKEN_JSON (GitHub API)
        ↓
Prochaine exécution du workflow → succès
```

### auth_server/app.py (Flask — déployé sur Railway)

| Route | Description |
|-------|-------------|
| `GET /auth` | Redirige vers le consentement Google OAuth |
| `GET /callback` | Reçoit le code OAuth, génère le token, met à jour GitHub Secrets |
| `GET /health` | Vérification que le serveur est actif |

---

## 6. CLI et modes d'exécution

**Fichier :** `main.py`

### Commandes disponibles

| Commande | Description |
|----------|-------------|
| `python main.py` | Démarre le scheduler (envoie chaque jour à l'heure configurée) |
| `python main.py --now` | Envoie la newsletter immédiatement aux abonnés |
| `python main.py --preview [DATE]` | Écrit `output/preview/DATE.html` — aucun réseau, aucun envoi |
| `python main.py --send-test EMAIL [DATE]` | Réexpédie une édition à cette seule adresse |
| `python main.py --send-test EMAIL --data-file F` | Compose depuis un fichier figé, sans générer |
| `python main.py --with-notice` | Ajoute le bloc transparence (avec `--preview` ou `--send-test`) |

> `DATE` est optionnel. Sans argument = date du jour. Format : `YYYY-MM-DD`.

### Flux typique complet

```
python main.py --now
  → Claude cherche les news via Brave Search
  → Déduplique, rédige et valide contre le schéma Pydantic
  → Sauvegarde output/newsletter/DATE/data.json
  → Pousse les articles (rank + title) sur GitHub pour /feedback
  → Rend le HTML par destinataire (pixel et liens signés individuellement)
  → Envoie via l'API Gmail
```

### Données persistées

| Fichier | Description |
|---------|-------------|
| `output/newsletter/DATE/data.json` | Articles, titre, intro, conclusion de la newsletter |
| `config/subscriber_ids.toml` | Identifiants de mesure opaques — **doit être commité** |
| `data/*.csv` | Ouvertures, clics, réactions, motifs de désinscription |

---

## 7. Planification et CI/CD

**Fichiers :** `main.py` + `.github/workflows/`

### Exécution locale (APScheduler)

```bash
python main.py          # scheduler — envoie chaque jour à l'heure configurée
python main.py --now    # exécution immédiate
```

### Les trois workflows

Ils s'exécutent **sans que ton ordinateur soit allumé**.

| Workflow | Déclenchement | Rôle |
|----------|---------------|------|
| `newsletter.yml` | cron `0 5 * * *` + manuel | l'envoi quotidien |
| `retention.yml` | cron `0 4 1 * *` + manuel | applique les durées de conservation |
| `ci-validate.yml` | push / PR / manuel | valide le rendu sans toucher aux abonnés |

`retention.yml` passe à 04:00 UTC, **avant** l'envoi de 05:00, pour ne jamais
réécrire `data/` pendant qu'une newsletter s'exécute.

### Les étapes de `newsletter.yml`

```
Checkout → Python 3.11 → dépendances → credentials Gmail
   → Récupérer les données d'abonnés     (DATA_REPO)
   → Send newsletter                      main.py --now
   → Renvoyer la table d'identifiants     always()
   → Rebuild dashboard data               always()
   → Commit dashboard data                always()
```

Il n'y a **qu'une seule étape d'envoi**, donc un seul bloc `env:`. Une variable
ajoutée vaut pour le cron comme pour le déclenchement manuel : les deux ne
peuvent pas diverger. C'est ce qui manquait quand deux modes coexistaient — les
variables du bloc transparence n'étaient câblées que dans l'un des deux, et un
envoi manuel partait sans le bloc, sans erreur ni log.
`tests/test_workflow_consistency.py` échoue si le chemin est rescindé sans
propager la configuration.

L'étape « Rebuild dashboard data » écarte la copie locale de
`output/newsletter/` avant son `git pull` : `agent.py` écrit ce fichier en local
**et** en pousse une version allégée via l'API, donc les deux divergent dès
qu'un second envoi a lieu le même jour, et `--autostash` laisserait des
marqueurs de conflit dans le fichier.

### Secrets — Settings → Secrets and variables → Actions → **Secrets**

| Secret | Rôle |
|--------|------|
| `ANTHROPIC_API_KEY` | rédaction |
| `BRAVE_API_KEY` | recherche des articles |
| `GMAIL_FROM` | adresse expéditrice |
| `GMAIL_TO` | destinataires de repli, si `recipients.toml` est vide |
| `GMAIL_CREDENTIALS_JSON` / `GMAIL_TOKEN_JSON` | OAuth Gmail, restaurés dans le runner |
| `GMAIL_APP_PASSWORD` | notifications SMTP et repli d'envoi |
| `AUTH_SERVER_URL` | base de tous les liens signés |
| `UNSUBSCRIBE_SECRET` | signature HMAC — **identique à Railway et au `.env` local** |
| `FEEDBACK_FORM_URL` | formulaire de repli |
| `GIT_TOKEN` | PAT scope `repo`, **avec accès aux deux dépôts** |
| `DATA_REPO` | dépôt privé des abonnés |
| `CI_TEST_EMAIL` | destinataire unique de `ci-validate.yml` |

### Variables — même écran, onglet **Variables**

| Variable | Effet |
|----------|-------|
| `SHOW_TRACKING_NOTICE` | `1` affiche le bloc transparence |

Ce n'est délibérément **pas un secret** : l'activation du bloc reste un geste
visible et réversible depuis l'interface GitHub, sans toucher au code.

`DASHBOARD_PUBLIC_URL` et `PRIVACY_URL` n'en sont pas non plus — les workflows
les dérivent d'`AUTH_SERVER_URL` par concaténation, donc aucune dérive n'est
possible entre les deux.

> ⚠️ Un slash final sur `AUTH_SERVER_URL` produirait `//board`, que Flask renvoie
> en 404 — soit un lien mort dans l'encart qui parle de confidentialité.
> `config.py` le rattrape, mais mieux vaut ne pas l'écrire.

### Permissions

`permissions: contents: write` sert au commit de `data/dashboard.json` en fin de
run. La table d'identifiants, elle, ne passe plus par un commit local : elle est
renvoyée au dépôt privé par `push_subscriber_ids.py`.

> Le déploiement de l'`auth_server` sur Railway est décrit dans
> [ABONNES.md](ABONNES.md#7-déployer-lauth_server) : c'est lui qui rend la
> désinscription possible.

---

## 8. Vérification des APIs

**Fichier :** `scripts/check_apis.py`

Script de diagnostic à lancer avant un envoi : si l'une des dépendances est
muette, l'édition du matin ne part pas.

### Usage

```bash
python scripts/check_apis.py
```

### Vérifications effectuées

| Dépendance | Ce qui est testé |
|-----|-----------------|
| **Anthropic** | Un appel minimal — détecte clé refusée (401) et rate limit (429) |
| **Brave Search** | Une recherche à 1 résultat — détecte clé refusée (401/403) et quota épuisé (429) |
| **Gmail** | Le jeton OAuth local, rafraîchi si expiré — détecte `invalid_grant` (jeton révoqué) |
| **Destinataires** | La liste résolue n'est pas vide — un pipeline vert qui n'envoie à personne reste inutile |

### Exemple de sortie

```
=======================================================
Vérification des APIs de l'envoi quotidien
=======================================================
Anthropic — rédaction de la newsletter
  ✅ OK — la clé répond

Brave Search — recherche des articles
  ✅ OK — 1 résultat(s) reçu(s)

Gmail — expédition
  ❌ JETON RÉVOQUÉ (invalid_grant) — le refresh échoue
     Le régénérer : venv/bin/python scripts/reauth_local.py

Destinataires
  ✅ OK — 27 destinataire(s)
```

Le script sort en code 1 dès qu'une vérification échoue.

---

## 9. Configuration

**Fichier :** `config.py`

Toutes les variables sont chargées depuis `.env` via `python-dotenv`.

### Variables Core

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | — | Clé API Claude (console.anthropic.com) |
| `BRAVE_API_KEY` | ✅ | clé projet | Clé Brave Search |
| `NEWS_TOPICS` | ⬜ | `technologie,science,business,monde,santé` | Thèmes à rechercher |
| `NEWS_COUNT` | ⬜ | `10` | Nombre d'articles |

### Variables Gmail

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `GMAIL_FROM` | ✅ | — | Adresse email expéditrice |
| `GMAIL_TO` | ✅ | — | Destinataires (séparés par des virgules) |
| `FROM_NAME` | ⬜ | `Daily News Agent` | Nom de l'expéditeur |
| `GMAIL_CREDENTIALS_PATH` | ⬜ | `~/.gmail-mcp/credentials.json` | Credentials OAuth2 Google |
| `GMAIL_TOKEN_PATH` | ⬜ | `~/.gmail-mcp/token.json` | Token d'accès Gmail |
| `GMAIL_APP_PASSWORD` | ⬜ | — | App Password Gmail pour notifications de re-auth |
| `AUTH_SERVER_URL` | ⬜ | — | URL publique de l'auth server Railway |

### Variables Mesure et transparence

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `UNSUBSCRIBE_SECRET` | ⬜* | — | Secret HMAC signant **tous** les liens personnalisés |
| `SHOW_TRACKING_NOTICE` | ⬜ | — | `1` pour afficher le bloc transparence |
| `DASHBOARD_PUBLIC_URL` | ⬜ | — | Route `/board` — jamais `/dashboard?token=…` |
| `PRIVACY_URL` | ⬜ | — | Page `/vie-privee` |
| `STATS_TOKEN` | ⬜ | — | Protège `/dashboard` et `/stats/<date>` |
| `FEEDBACK_FORM_URL` | ⬜ | — | Formulaire de repli si les boutons signés manquent |

> *Sans lui, ni pixel ni lien de désinscription ne sont rendus. Il doit valoir
> **exactement** la même chose en local, en CI et sur Railway.

### Variables Git

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `GIT_TOKEN` | ⬜ | — | PAT scope `repo` — push des articles et des mesures |
| `GITHUB_REPO` | ⬜ | — | `owner/repo` |
| `GIT_USERNAME` | ⬜ | `yousmaaza` | Repli pour recomposer `GITHUB_REPO` |
| `GIT_REPO` | ⬜ | `newletter-ai` | Repli pour recomposer `GITHUB_REPO` |

### Variables Scheduler

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `SCHEDULE_TIME` | ⬜ | `08:00` | Heure d'envoi (scheduler local) |
| `TIMEZONE` | ⬜ | `Europe/Paris` | Fuseau horaire |

---

## Voir aussi

- [MESURE.md](MESURE.md) — suivi, identifiants, tableaux de bord, rétention
- [ABONNES.md](ABONNES.md) — cycle de vie d'un abonné, dépôt privé, déploiement Railway
- [TESTS.md](TESTS.md) — comment vérifier tout ce qui précède
- [PROMPTS.md](PROMPTS.md) — les prompts, externalisés dans `config/prompts.toml`

## Le veilleur d'envoi

Le planificateur de GitHub Actions fonctionne « au mieux ». Les 27 et 28 août
2026, le cron quotidien s'est réveillé onze puis douze heures plus tard — et
comme l'envoi avait entre-temps été relancé à la main, vingt-huit personnes ont
reçu l'édition deux fois.

Deux pièces répondent à ça, et il faut les deux :

| Pièce | Rôle |
|---|---|
| `tools/sent_log.py` | Journal des éditions parties. `main.py --now` s'y arrête si celle du jour est déjà envoyée. |
| `auth_server/send_watchdog.py` | Constate passé 08:30 UTC qu'aucune édition n'est partie, et relance le workflow. |

⚠️ **Le plafond de trois tentatives se compte chez GitHub**, pas en mémoire.
Railway redéploie à chaque commit — et chaque ouverture de la newsletter en
produit un, jusqu'à trente-six par jour. Un compteur interne repartirait à zéro
à chaque redémarrage, et « trois tentatives » ne serait une limite que jusqu'au
suivant.

⚠️ **Un refus de relance ne nomme pas sa cause.** Le 31 août 2026, le message
affirmait qu'il manquait la permission « Actions: read and write » ; le vrai
problème était que deux jetons coexistaient et que celui posé sur Railway
n'était pas celui dont on corrigeait les permissions. Pour trancher sans rien
envoyer, appeler l'endpoint de dispatch sur un workflow **inexistant** : `404`
signifie que la permission est là, `403` qu'elle manque.

⚠️ **La relance n'est pas un second cron.** Elle dépendrait du même
planificateur et serait retardée de la même façon. Elle vit sur l'hébergement
d'`auth_server`, allumé en continu — d'où la nécessité de conserver
`workflow_dispatch` dans `newsletter.yml`.

⚠️ **C'est le journal qui rend la relance sûre.** Sans lui, un veilleur qui
relance une édition déjà partie est une machine à doublons. Ne jamais activer
`WATCHDOG_ENABLED` sur un pipeline dont le garde-fou serait retiré.

| Variable | Où | Défaut |
|---|---|---|
| `WATCHDOG_ENABLED` | Railway | vide — éteint |
| `WATCHDOG_DEADLINE` | Railway | `08:30` (UTC) |

⚠️ **Heure UTC, sans passage à l'heure d'hiver.** En été, `07:15` donne 09:15 à
Paris ; la même valeur donnera 08:15 après le changement d'heure. Comme pour le
cron du workflow, c'est à décaler à la main fin octobre.

⚠️ **Rapprocher l'échéance de l'heure du cron rouvre une course.** Le journal
d'envoi n'est écrit qu'*après* l'envoi : un run encore en génération laisse
l'édition absente du journal, et le veilleur en lancerait un second. D'où la
vérification « un run est-il en cours ou en file d'attente ». Ne jamais la
retirer en rapprochant les deux horaires.
