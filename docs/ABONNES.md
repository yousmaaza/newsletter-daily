# Abonnés — cycle de vie, stockage et déploiement

Tout ce qui touche à une personne inscrite : comment elle arrive, comment elle
part, où son adresse est rangée, et comment déployer le serveur qui rend ce
départ possible.

---

## 1. Vue d'ensemble

Quatre acteurs, et **deux dépôts distincts** :

```
┌──────────────────┐  soumission  ┌────────────────────────┐
│  Google Form     │ ───────────→ │  Google Apps Script    │
│  (inscription)   │              │  sync_recipients.gs    │
└──────────────────┘              └───────────┬────────────┘
                                              │ API GitHub
                                              ↓
┌──────────────────┐              ┌────────────────────────┐
│  auth_server     │ ───────────→ │  DATA_REPO (PRIVÉ)     │
│  (Railway)       │  désinscrip. │  newsletter-data       │
│  /unsubscribe    │  refus mesure│  ├ recipients.toml     │
│  /tracking-optout│              │  ├ unsubscribed.toml   │
└──────────────────┘              │  ├ tracking_optout.toml│
         ↑                        │  └ subscriber_ids.toml │
         │ clic                   └───────────┬────────────┘
         │                                    │ fetch au démarrage
┌────────┴─────────┐              ┌───────────┴────────────┐
│  Email reçu      │ ←─────────── │  GitHub Actions        │
│                  │    envoi     │  newsletter.yml        │
└──────────────────┘              └────────────────────────┘
                                       │ push de la table
                                       └──→ DATA_REPO
```

> ⚠️ **Le dépôt applicatif (celui-ci) ne contient aucune adresse.** C'est ce qui
> lui permet de devenir public sans publier cinq mois d'historique de lecture
> nominatif.

---

## 2. Où vivent les données

### Les quatre fichiers du dépôt privé

Ils vivent dans **`DATA_REPO`** (`yousmaaza/newsletter-data`, privé), et sont
**gitignorés ici** — présents en local uniquement, le temps d'un envoi.

| Fichier | Écrit par | Lu par |
|---------|-----------|--------|
| `config/recipients.toml` | Apps Script (formulaire) | pipeline |
| `config/unsubscribed.toml` | `auth_server` `/unsubscribe` | pipeline, Apps Script |
| `config/tracking_optout.toml` | `auth_server` `/tracking-optout` | pipeline |
| `config/subscriber_ids.toml` | pipeline (nouvel abonné) | pipeline |

`data/*.csv` reste dans **ce** dépôt : ces fichiers sont anonymes depuis la
migration des identifiants (voir [MESURE.md](MESURE.md#2-lidentifiant-opaque)).

### Les rapatrier, les renvoyer

```bash
venv/bin/python scripts/fetch_subscriber_data.py   # avant tout envoi
venv/bin/python scripts/push_subscriber_ids.py     # après, pour la table d'ids
```

Les deux lisent `.env` en local, l'environnement en CI. En local, `.env` doit
donc contenir :

```
DATA_REPO=yousmaaza/newsletter-data
GIT_TOKEN=<PAT à portée fine, Contents RW sur LES DEUX dépôts>
```

En CI, ces deux commandes encadrent l'envoi :

| Étape | `if:` | Rôle |
|-------|-------|------|
| Récupérer les données d'abonnés | (toujours) | avant l'envoi |
| Send newsletter | (toujours) | — |
| Renvoyer la table d'identifiants | `always()` | même si l'envoi a échoué |

Le renvoi est en `always()` parce qu'un identifiant a pu être créé **avant**
l'échec : il doit remonter quand même, sinon la personne en recevra un autre
demain.

### Trois règles qui tiennent tout

**La récupération est tout ou rien.** Rien n'est écrit tant que les fichiers ne
sont pas tous récupérés et validés. Un `config/` à moitié écrit serait pire
qu'un échec net — l'envoi partirait à une liste tronquée sans que rien ne le
signale.

**Une liste de destinataires vide est traitée comme une erreur**, jamais comme
un état réel. Les trois autres fichiers peuvent légitimement être vides.

**Le renvoi refuse d'écraser par plus petit.** La table d'identifiants ne
devrait que grandir ; moins d'entrées signale une récupération ratée. Écraser
orphelinerait l'historique de mesure des lecteurs concernés. Rien n'est écrit
non plus si le contenu est identique — l'API GitHub crée un commit même à
contenu inchangé, et sans cette vérification chaque envoi en produirait un vide.

> ⚠️ **Sans récupération préalable, `config.GMAIL_TO` retombe sur la variable
> d'environnement `GMAIL_TO`.** En CI, l'étape de récupération fait échouer le
> job avant l'envoi. En local, **lance toujours le fetch d'abord** — sinon
> l'envoi part aux mauvaises adresses.

> ⚠️ **Le jeton GitHub doit avoir accès aux deux dépôts.** Un jeton qui ne voit
> que celui-ci fait lire des listes vides côté `auth_server`, ce qui a déjà
> réinscrit silencieusement des personnes désinscrites.

---

## 3. Inscription

Deux portes d'entrée, **un seul écrivain** : `sync_recipients.gs`. Mais elles
n'y arrivent pas par le même chemin.

```
Google Form (lien direct) ─→ Sheet ─→ onFormSubmit ─────┐
                                                        ├─→ syncRecipients()
landing page /inscription ─→ Sheet ─→ (rien) ───────────┘        │
                                          ▲                       ▼
                              déclencheur horaire /15 min    recipients.toml
```

> ⚠️ **Un POST direct vers `/formResponse` ne déclenche PAS `onFormSubmit`.**
> Vérifié le 27 août 2026 : la ligne apparaît bien dans la Sheet, mais le
> journal Apps Script ne montre **aucune exécution**, et l'adresse n'atteint
> jamais `recipients.toml`. Google enregistre la réponse sans considérer qu'un
> formulaire a été soumis.
>
> C'est pourquoi il faut **deux déclencheurs**. Sans le déclencheur horaire, la
> landing page collecte des adresses qui restent bloquées dans la Sheet — et,
> comme la page confirme sans preuve, personne ne s'en aperçoit.

La synchronisation relit la Sheet entière et n'écrit que s'il y a du nouveau :
la lancer sur une horloge est sans effet de bord, et deux déclencheurs qui se
croisent ne produisent pas de doublon. `tests/test_recipients_sync_entrypoints.py`
tient l'invariant qui rend ça possible — `syncRecipients()` ne doit jamais lire
l'événement de soumission.

Le délai est sans conséquence : la newsletter part une fois par jour à 8 h.

C'est ce montage qui permet à la page de ne rien savoir des abonnés : elle
n'écrit nulle part, elle ne lit pas `recipients.toml`, elle ne connaît pas
`DATA_REPO`. Voir [§8](#8-la-landing-page-inscription) pour le détail.

Le flux, quelle que soit la porte :

1. La personne remplit le **Google Form** (email, thèmes préférés)
2. Le déclencheur `onFormSubmit` s'exécute dans **Google Apps Script**
3. Le script lit tous les emails validés de la Google Sheet
4. Il récupère `recipients.toml` et `unsubscribed.toml` depuis **`newsletter-data`**
5. Il fusionne, déduplique et **filtre les désinscrits**
6. S'il y a du nouveau, il met à jour `recipients.toml` via l'API GitHub
7. Le commit est tagué `[skip ci]` — pas de newsletter déclenchée
8. La colonne **« Désinscrit »** du Sheet est mise à jour (`TRUE`/`FALSE`)

### Configurer Apps Script

**Deux déclencheurs**, tous deux nécessaires (⏱ *Déclencheurs* → *Ajouter*) :

| Fonction | Source | Couvre |
|----------|--------|--------|
| `onFormSubmit` | À l'envoi du formulaire | les inscriptions faites dans Google Forms |
| `syncRecipients` | Horaire, toutes les 15 min | celles venues de `/inscription` |

Configuration dans `sync_recipients.gs` :

```javascript
GITHUB_REPO: "newsletter-data",   // dépôt PRIVÉ dédié
```

> ⚠️ Le fichier de ce dépôt est une **copie de référence**. Le modifier ici ne
> change rien : il faut le **coller dans l'éditeur Apps Script** pour que le
> changement prenne effet.

> ⚠️ `sync_recipients.gs::buildToml_()` **reconstruit `recipients.toml`
> entièrement** à chaque inscription et n'y écrit que `emails`. C'est pourquoi
> les identifiants de mesure vivent dans un fichier séparé : rangés là, ils
> seraient effacés au prochain inscrit.

### Diagnostiquer une synchronisation

`testSync`, lancé manuellement depuis l'éditeur, doit afficher des compteurs
**non nuls** :

```
Emails déjà dans recipients.toml : 26     ← doit être > 0
Emails désinscrits : 6                    ← doit refléter la réalité
```

Des zéros signalent un jeton sans accès au dépôt de données. GitHub répond
alors 404 — indiscernable d'un fichier absent, c'est délibéré pour ne pas
révéler l'existence d'un dépôt privé — et la liste des désinscrits est lue
vide. La synchronisation **réinscrirait** les désabonnés.

`assertRepoReachable_` ferme ce trou en vérifiant l'accès **au dépôt** avant
toute lecture de fichier : un 404 sur le dépôt lui-même ne peut signifier
qu'une chose.

---

## 4. Désinscription

### Le flux

1. Chaque email contient un lien **« Se désabonner »** unique dans le pied de page
2. Le lien est signé : `token = HMAC-SHA256(UNSUBSCRIBE_SECRET, "email:date")`
3. Le clic appelle `GET /unsubscribe?email=…&date=…&token=…` sur Railway
4. Le serveur vérifie le jeton et la date (valide **90 jours**)
5. L'adresse est ajoutée à `unsubscribed.toml` **dans `DATA_REPO`**, avec son
   horodatage UTC
6. Une page de remerciement s'affiche, avec un formulaire de motif optionnel
7. Si un motif est soumis → `POST /unsubscribe` : la ligne part dans
   `data/unsubscribe_reasons.csv` (**ce** dépôt), et une notification est
   envoyée au propriétaire
8. Au prochain envoi, `config.py` exclut la personne

Un re-clic n'écrit rien et ne crée pas de commit vide.

### Le jeton

```
payload = f"{email.lower()}:{send_date}"      # ex : "jean@ex.fr:2026-04-01"
token   = HMAC-SHA256(UNSUBSCRIBE_SECRET, payload)
```

- Chaque destinataire reçoit un jeton **unique**, lié à son adresse et à la date
- Vérification en **temps constant** (`hmac.compare_digest`)
- Un jeton ne peut pas désinscrire quelqu'un d'autre

> Les liens de désinscription et de refus de mesure portent l'adresse **en
> clair** dans l'URL — c'est ce que signe le HMAC. Seuls les liens de **mesure**
> (pixel, clic, réaction, avis) utilisent l'identifiant opaque. Les deux
> mécanismes sont distincts : voir [MESURE.md](MESURE.md#3-les-liens-signés).

### Les formats

`unsubscribed.toml` — deux tableaux parallèles, `emails[i]` désinscrit à
`timestamps[i]` :

```toml
[unsubscribed]
emails     = ["jean@exemple.fr", "marie@exemple.fr"]
timestamps = ["2026-04-01T12:00:00Z", "2026-04-02T09:30:00Z"]
```

`data/unsubscribe_reasons.csv` — **sans colonne d'adresse** : ce texte n'est
rattaché à personne, et reste un retour produit exploitable.

```csv
"timestamp","send_date","reasons","free_text"
"2026-04-01T12:05:33","2026-04-01","too_frequent;irrelevant","Les sujets ne m'intéressent pas"
```

| Valeur | Label affiché |
|---|---|
| `too_frequent` | Trop d'emails |
| `irrelevant` | Contenu pas pertinent pour moi |
| `never_signed` | Je ne me souviens pas m'être inscrit(e) |
| `too_long` | Les emails sont trop longs |
| `other` | Autre raison (champ libre) |

### À ne pas confondre avec le refus de mesure

`GET /tracking-optout` est une **action distincte** : la personne garde sa
newsletter, seule l'observation s'arrête. Le jeton est préfixé `optout:`, donc
non interchangeable avec celui de désinscription.

> ⚠️ Couper la mesure ne retire **jamais** le lien de désinscription. C'est
> `server_configured` qui le gouverne, pas `measure`. Quelqu'un qui refuse
> d'être mesuré garde son droit de partir.

Détail dans [MESURE.md](MESURE.md#6-refuser-la-mesure).

---

## 5. Réinscription

Quand une personne désinscrite resoumet le formulaire :

1. `onFormSubmit` s'exécute normalement
2. Le script compare, pour chaque adresse désinscrite, l'horodatage de
   désinscription (`unsubscribed.toml`) et le dernier horodatage de soumission
   (colonne « Horodateur » du Sheet)
3. Si `soumission > désinscription` → réinscription détectée
4. L'adresse est retirée d'`unsubscribed.toml`
5. Une notification part vers le propriétaire
6. L'adresse revient dans `recipients.toml`, colonne « Désinscrit » à `FALSE`

```
30/03 14:17  Jean s'inscrit                → recipients.toml
01/04 12:00  Jean clique « Se désabonner » → unsubscribed.toml (12:00:00Z)
05/04 09:00  Jean resoumet le formulaire   → 05/04 09:00 > 01/04 12:00 ? OUI
                                           → retiré d'unsubscribed.toml
                                           → notification, puis réintégré
```

---

## 6. Filtrage à l'envoi

À chaque envoi, `config.py` charge les destinataires **en excluant les
désinscrits** :

```python
# config.py — _load_recipients()
unsubscribed = _load_unsubscribed()
filtered = [e for e in cleaned if e.lower() not in unsubscribed]
```

Double filet : même si `recipients.toml` contient encore une adresse
désinscrite (délai de synchronisation), elle est écartée à l'envoi.

---

## 7. Déployer l'`auth_server`

C'est ce serveur qui rend la désinscription possible. Sans lui, les liens ne
répondent pas — et sans `UNSUBSCRIBE_SECRET`, ils ne sont même pas rendus.

Hébergé sur **Railway**. Le déploiement se déclenche automatiquement à chaque
push sur la branche suivie ; compter une à deux minutes de build.

### Variables — projet → service `auth_server` → onglet **Variables**

| Variable | Valeur |
|----------|--------|
| `UNSUBSCRIBE_SECRET` | **exactement** la même qu'en CI et en local |
| `STATS_TOKEN` | protège `/dashboard` et `/stats/<date>` |
| `GITHUB_TOKEN` | PAT scope `repo`, **accès aux deux dépôts** |
| `GITHUB_REPO` | ce dépôt — écriture des CSV de mesure |
| `DATA_REPO` | dépôt privé — désinscriptions et refus de mesure |
| `GMAIL_FROM` | adresse expéditrice des notifications |
| `GMAIL_APP_PASSWORD` | envoi SMTP des notifications |
| `AUTH_SERVER_URL` | sa propre URL publique |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | renouvellement OAuth via `/auth` et `/callback` |

`PORT` est injecté par Railway — ne pas le définir.

> ⚠️ **Le pipeline ne tourne pas sur Railway.** Les variables Railway ne
> configurent que l'`auth_server` ; celles du pipeline vivent dans les GitHub
> Secrets (voir [ARCHITECTURE.md](ARCHITECTURE.md#7-planification-et-cicd)).
> Seul `UNSUBSCRIBE_SECRET` doit valoir la même chose des deux côtés — le
> serveur revérifie chaque jeton, une valeur différente les rejette tous.

### Vérifier un déploiement

```bash
curl -s "$AUTH_SERVER_URL/health"            # → {"status":"ok"}
curl -s "$AUTH_SERVER_URL/vie-privee" | head -5
```

`/vie-privee` est le meilleur test de fumée : la page n'a **aucune dépendance**
— ni jeton, ni GitHub, ni données. Si elle répond et que le reste échoue, le
problème est dans la configuration, pas dans le déploiement.

L'import du module de dashboard est tolérant aux pannes : si `dashboard.py`
échoue, `/pixel`, `/unsubscribe` et `/react` restent actives. Une régression
d'affichage ne doit pas emporter la collecte, ni le droit de partir.

### Après un changement d'URL ou de secret

Trois endroits à mettre à jour **ensemble**, sous peine de liens qui ne valident
plus : `.env` local, GitHub → Secrets, Railway → Variables.

Puis vérifier de bout en bout, avec un vrai bouton cliquable :

```bash
venv/bin/python main.py --send-test moi@gmail.com --with-notice
```

C'est le seul moyen de parcourir la chaîne complète comme un lecteur — voir
[TESTS.md](TESTS.md#tester-la-chaîne-de-refus-de-mesure-pour-de-vrai).

---

## 8. La landing page `/inscription`

Servie par l'`auth_server` depuis `auth_server/landing.html`. La route ne fait
que lire un fichier : aucune écriture, aucun secret, aucune dépendance à
GitHub.

### Ce qui est câblé

| | |
|---|---|
| Formulaire | « Inscription Daily News » |
| `action` | `.../forms/d/e/1FAIpQLSc8kX…zy4A/formResponse` |
| Champ email | `entry.259733735` |
| Champ piège | `name="site"` — bloqué en JavaScript, n'atteint jamais Google |

Ces valeurs sont **committées**. Le projet n'a qu'un déploiement et qu'un
formulaire, et l'identifiant est public — il figure dans l'URL du formulaire
comme dans la page servie. Le committer évite une étape de configuration au
déploiement, donc une occasion de servir la page muette.

> ⚠️ L'identifiant est celui des **réponses** (`/forms/d/e/1FAIpQLSc…`), pas
> celui de l'**édition** (`/forms/d/<autre-id>/edit`). Le second donne un 404
> que l'iframe avalerait sans rien dire. Ils se ressemblent, ils ne sont pas
> interchangeables.

Si ces valeurs redevenaient des placeholders, la route répondrait **503**
plutôt que de servir une page qui avalerait les inscriptions en silence.

### Ce que le montage coûte

- **La confirmation est optimiste.** Le seul échec plausible en pratique est un
  formulaire fermé ou supprimé, mais c'est un angle mort réel.
- **Pas de captcha.** Poster directement contourne le reCAPTCHA du formulaire.
  Le champ piège annule l'envoi quand il est rempli — tout en affichant la
  confirmation, pour ne pas apprendre au robot qu'il a été repéré. Ça arrête
  les robots élémentaires ; au-delà, c'est la Sheet qui se remplit.
- **Un `FORM_ID` erroné mais rempli ne déclenche pas le garde-fou.** Le 503 ne
  détecte que le placeholder. Après configuration, **soumettre une adresse de
  test et vérifier qu'elle apparaît dans la Sheet** — c'est la seule preuve.

### Ce que le montage évite

La déduplication, le filtrage des désinscrits et la détection de réinscription
restent **là où elles sont déjà testées**, dans `sync_recipients.gs`. Une route
qui écrirait elle-même dans `DATA_REPO` devrait les réimplémenter — et c'est
exactement ce genre de duplication qui a déjà réinscrit des gens en silence.

`tests/test_landing_page_route.py` tient l'invariant : le formulaire doit
poster vers Google Forms, et vers rien d'autre.

---

## Voir aussi

- [MESURE.md](MESURE.md) — identifiants opaques, refus de mesure, rétention
- [ARCHITECTURE.md](ARCHITECTURE.md) — le pipeline et son déploiement en CI
- [TESTS.md](TESTS.md) — tester la désinscription sans casser la liste
- [SETUP.md](SETUP.md) — installation complète du projet
