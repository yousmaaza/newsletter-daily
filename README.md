# Daily News Newsletter Agent

Un agent Claude qui cherche les meilleures actualités du jour, rédige une
newsletter HTML et l'envoie chaque matin à 8h par Gmail — puis mesure ce que
les lecteurs en font, en le leur disant.

## Le pipeline

```
        Brave Search API                    dépôt privé (abonnés)
              ↓                                      ↓
      search_today_news                     recipients.toml
              ↓                                      ↓
      ┌───────────────────────┐                      │
      │   Claude Agent Loop   │                      │
      │   (claude-sonnet-4-6) │                      │
      └───────────────────────┘                      │
              ↓                                      │
      déduplication TF-IDF                           │
              ↓                                      │
      validation Pydantic                            │
              ↓                                      ↓
      output/newsletter/DATE/data.json    rendu par destinataire
                                          (Jinja2 — pixel, clics et
                                           liens signés, individuels)
                                                     ↓
                                              Gmail API (OAuth2)
                                                     ↓
                                              27 emails distincts
                                                     ↓
                                      auth_server (Railway) collecte
                                      ouvertures · clics · réactions
                                                     ↓
                                              /board — public
```

## Démarrer

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env          # puis remplir — voir docs/SETUP.md

venv/bin/python scripts/check_apis.py            # les APIs répondent-elles ?
venv/bin/python scripts/fetch_subscriber_data.py # rapatrier la liste d'abonnés
venv/bin/python main.py --preview                # aperçu local, AUCUN envoi
```

## Commandes

```bash
venv/bin/python main.py --now                       # envoi aux abonnés
venv/bin/python main.py --preview [DATE]            # aperçu local, aucun envoi
venv/bin/python main.py --send-test moi@gmail.com   # réexpédition à une seule adresse
venv/bin/python main.py --with-notice               # + bloc transparence
venv/bin/python main.py                             # scheduler quotidien
venv/bin/python -m pytest tests/ -q                 # suite de tests
```

> ⚠️ `--preview` n'émet **aucune** URL de mesure, et `--send-test` ne lit
> **jamais** la liste d'abonnés. Ce sont les deux garde-fous à connaître avant
> de toucher au rendu. Voir [docs/TESTS.md](docs/TESTS.md).

## Ce qui est mesuré, et comment on s'y soustrait

Ouvertures, clics, réactions et avis, rattachés à un **identifiant tiré au
sort** — jamais à l'adresse, jamais à un hash de l'adresse. Chaque édition
peut annoncer ce qu'elle mesure dans un bloc transparence, avec un bouton
« Ne plus être mesuré » qui coupe l'observation **sans** désinscrire.

Les chiffres sont publiés sur `/board`, filtrés par liste blanche. La page
`/vie-privee` explique ce qui est collecté et n'a aucune dépendance — elle
tient debout même si le reste tombe.

→ [docs/MESURE.md](docs/MESURE.md)

## Où vivent les données

| Donnée | Où | Pourquoi |
|--------|-----|----------|
| Adresses des abonnés | dépôt privé `DATA_REPO` | ce dépôt-ci a vocation à devenir public |
| Ouvertures, clics, réactions | `data/*.csv`, ici | anonymes depuis la migration des identifiants |
| Table des identifiants | dépôt privé, commitée | sans elle, l'historique se fragmente |
| Historique agrégé | `data/dashboard.json` | recalculé par la CI après chaque envoi |

## Documentation

| Document | Pour quoi faire |
|----------|-----------------|
| [SETUP.md](docs/SETUP.md) | Installer et configurer, pas à pas |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Comment le pipeline est construit |
| [MESURE.md](docs/MESURE.md) | Suivi, identifiants, tableaux de bord, rétention |
| [ABONNES.md](docs/ABONNES.md) | Cycle de vie d'un abonné, dépôt privé, déploiement Railway |
| [TESTS.md](docs/TESTS.md) | Vérifier sans rien envoyer aux abonnés |
| [PROMPTS.md](docs/PROMPTS.md) | Modifier les prompts sans toucher au Python |

`CLAUDE.md` complète cet index : il ne réexplique pas le projet, il liste les
pièges — ce qui casse en silence, et pourquoi.

## Structure

```
newletter-ai/
├── main.py                  # CLI + scheduler
├── agent.py                 # boucle Claude tool_use
├── config.py                # AppConfig, PromptsConfig, NewsSettingsConfig
├── newsletter_template.html # template email (Jinja2)
│
├── tools/
│   ├── brave_search.py          # recherche d'actualités
│   ├── deduplicator.py          # déduplication TF-IDF
│   ├── newsletter_schema.py     # validation Pydantic
│   ├── newsletter_renderer.py   # rendu par destinataire, suivi en injection
│   ├── newsletter_stats.py      # agrégats du bloc transparence
│   ├── gmail_tool.py            # envoi (OAuth2, repli SMTP)
│   ├── interaction_helper.py    # URLs signées HMAC
│   ├── subscriber_ids.py        # identifiants opaques
│   └── topic_memory.py          # mémoire thématique inter-éditions
│
├── auth_server/             # Flask sur Railway
│   ├── app.py                   # pixel, click, react, unsubscribe, optout, inscription
│   ├── public_board.py          # filtre liste blanche de /board
│   ├── dashboard.py             # tableau de bord privé
│   ├── landing.html             # page d'inscription — poste dans le Google Form
│   └── vie_privee.html          # page publique, sans dépendance
│
├── config/
│   ├── prompts.toml             # prompts Claude
│   └── news_settings.toml       # thèmes, sources, déduplication
│
├── scripts/
│   ├── check_apis.py            # diagnostic avant envoi
│   ├── fetch_subscriber_data.py # rapatrie les abonnés du dépôt privé
│   ├── build_dashboard_data.py  # agrège l'historique
│   └── apply_retention.py       # applique les durées de conservation
│
├── tests/                   # 281 tests
└── .github/workflows/       # newsletter · retention · ci-validate
```

## Stack

| Composant | Technologie |
|-----------|-------------|
| Agent | Claude Sonnet 4.6 |
| Recherche | Brave Search REST API |
| Email | Gmail API v1 (OAuth2), repli SMTP |
| Template | Jinja2, rendu par destinataire |
| Déduplication | scikit-learn (TF-IDF) |
| Validation | Pydantic v2 |
| Liens signés | HMAC-SHA256 |
| Serveur | Flask + gunicorn (Railway) |
| Planification | GitHub Actions + APScheduler en local |
| Tests | pytest |
