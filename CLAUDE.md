# CLAUDE.md — newletter-ai

Ce fichier ne réexplique pas le projet : il liste **ce qui casse en silence**.
Pour comprendre le fonctionnement, voir l'index de [README.md](README.md).

## Environnement

- **Python** : `venv/bin/python` (pas `python3` ni `.venv/`)
- **Run main** : `venv/bin/python main.py [--now] [--preview [DATE]] [--send-test EMAIL [DATE]]`
- **Tests** : `venv/bin/python -m pytest tests/ -q`
- **Profil git perso** : toujours lancer `git-perso` avant de committer/pusher

## Où lire quoi

| Sujet | Document |
|-------|----------|
| Le pipeline, les workflows, les secrets GitHub | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Suivi, identifiants, `/board`, rétention | [docs/MESURE.md](docs/MESURE.md) |
| Abonnés, dépôt privé, déploiement Railway | [docs/ABONNES.md](docs/ABONNES.md) |
| Tester sans rien envoyer | [docs/TESTS.md](docs/TESTS.md) |
| Modifier les prompts | [docs/PROMPTS.md](docs/PROMPTS.md) |

---

# Les pièges

## Ne jamais détruire la liste d'abonnés

- ⚠️ `ci-validate.yml` **écrase `config/recipients.toml`** pour n'y laisser que
  l'adresse de test. Ne **jamais** reproduire ce geste en local : un oubli
  détruit la liste.
- ⚠️ Sans `fetch_subscriber_data.py` préalable, `config.GMAIL_TO` retombe sur la
  variable d'environnement `GMAIL_TO`. En CI l'étape de récupération fait
  échouer le job avant l'envoi ; en local, **lance toujours le fetch d'abord**.
- La récupération est **tout ou rien** et échoue bruyamment : une liste vide est
  traitée comme une erreur, jamais comme un état réel.

## Ne jamais dériver un identifiant de l'adresse

Avant le 26 août 2026, l'identifiant de mesure était `sha256(email)` **non
salé** : avec `recipients.toml` en main, 23 des 26 identifiants se retournaient
en quelques millisecondes. Un hash non salé d'une adresse, c'est l'adresse.

`tests/test_legacy_hash_rejected.py` empêche le retour en arrière.

## `config/subscriber_ids.toml` doit être renvoyé au dépôt privé

Un nouvel abonné reçoit son identifiant **pendant l'envoi**, dans un runner
éphémère. Sans renvoi, il en reçoit un autre le lendemain et son historique de
lecture se fragmente en silence, sans que rien ne le signale.

⚠️ Fichier **séparé de `recipients.toml`** : `sync_recipients.gs::buildToml_()`
reconstruit ce dernier entièrement à chaque inscription et n'y écrit que
`emails` — un identifiant rangé là serait effacé au prochain inscrit.

## `UNSUBSCRIBE_SECRET` : une seule valeur, trois endroits

Local, CI et Railway. Le serveur revérifie chaque jeton HMAC ; une valeur
différente les rejette tous. **Sans ce secret, aucun pixel ni lien de
désinscription n'est rendu du tout** — les emails partent amputés, sans erreur.

## Le jeton GitHub doit voir les deux dépôts

Un jeton qui ne voit que celui-ci fait lire des listes d'abonnés vides côté
`auth_server`, ce qui a déjà réinscrit silencieusement des personnes
désinscrites.

## `DASHBOARD_PUBLIC_URL` pointe vers `/board`, jamais `/dashboard?token=…`

Mettre le `STATS_TOKEN` dans un email le diffuse à tous les abonnés, et un seul
transfert suffit à le faire fuiter.

## Le filtre de `/board` est une liste blanche

`auth_server/public_board.py::PUBLIC_KEYS`. Toute clé ajoutée à
`build_dashboard_data.py` est exclue tant qu'elle n'y figure pas explicitement.
**Ne jamais transformer ça en liste noire** : l'oubli y devient une fuite au
lieu d'une absence.

## Le bloc transparence disparaît sans prévenir

`_validated_transparency()` supprime le bloc entier si un lien d'action ou un
chiffre manque — jamais de bouton mort dans un encart qui parle de vie privée.
Le revers : la disparition est silencieuse.

C'est ainsi qu'une édition est partie sans le bloc le 27 août 2026 :
`newsletter.yml` avait deux étapes d'envoi et les variables n'étaient câblées
que dans l'une. Le workflow n'a plus qu'un chemin d'envoi, et
`tests/test_workflow_consistency.py` échoue si on le rescinde sans propager la
configuration.

⚠️ Le pipeline tourne dans **GitHub Actions**, pas sur Railway : les variables
Railway ne configurent que l'`auth_server`.

## Couper la mesure ne retire jamais le lien de désinscription

C'est `server_configured` qui le gouverne, pas `measure`. Un lecteur qui refuse
d'être mesuré garde son droit de partir.

## `/vie-privee` ne doit dépendre de rien

Ni jeton, ni GitHub, ni données. Une page qui explique ce qui est collecté ne
doit pas tomber avec l'infrastructure qu'elle décrit.

## `output/newsletter/<date>/data.json` est écrit deux fois

`agent.py` en écrit une version complète en local et pousse une version allégée
(`rank` + `title`) via l'API GitHub. Le chemin étant suivi par git, les deux
divergent dès qu'un second envoi a lieu le même jour — d'où le
`git checkout -- output/newsletter` avant le pull dans `newsletter.yml`, sans
lequel `--autostash` laisse des marqueurs de conflit dans le fichier.

## Les thèmes du dashboard sont déduits, pas mesurés

`agent.py` demande un `topic` au modèle, mais l'archive poussée ne retient que
`rank` + `title`. La répartition vient d'une heuristique lexicale
(`classify_title`), avec ~17 % de titres non classés. Archiver `topic` rendrait
la mesure exacte — le script utilise déjà `a.get("topic")` en priorité.

## Le texte libre n'a pas de durée à lui

`apply_retention.py` n'a **qu'un seul seuil** : 12 mois
(`MEASURE_RETENTION_DAYS = 365`). La purge à 3 mois que ce fichier a annoncée
un temps n'a jamais existé dans le code.

Ce qui décide du sort d'un texte, c'est la présence d'un identifiant dans son
fichier — pas son ancienneté propre :

| Fichier | Colonne | Sort |
|---------|---------|------|
| `data/feedback_DATE.csv` | `comment` | effacé à 12 mois, **en même temps** que l'identifiant |
| `data/unsubscribe_reasons.csv` | `free_text` | **conservé** — le fichier n'est jamais réécrit |

⚠️ Les motifs de départ survivent **parce que** leur fichier ne porte aucun
identifiant. Y réintroduire une colonne d'adresse ferait deux dégâts d'un
coup : le fichier redeviendrait nominatif, et son texte commencerait à
s'effacer. `tests/test_unsubscribe_reasons_privacy.py` et `test_retention.py`
tiennent l'invariant.

## `count` est un nombre d'articles PAR thème

`news_settings.count` est passé à `search_news()` comme `count_per_topic` : avec
5 thèmes, `count = 4` demande 20 articles bruts, pas 4. `newsletter_count`, lui,
est le nombre d'articles retenus dans l'édition finale.

L'interface Streamlit retirée le 27 août 2026 présentait ce champ comme un
« nombre total réparti entre les thèmes » — le porter à 10 depuis l'UI aurait
demandé 50 articles. Elle effaçait aussi `newsletter_count` à chaque
sauvegarde. Le fichier s'édite à la main.

## Deux déclencheurs Apps Script, pas un

Un POST direct vers `/formResponse` — c'est ce que fait `/inscription` — crée
une ligne dans la Sheet mais **ne déclenche pas `onFormSubmit`**. Vérifié le
27 août 2026 : ligne présente, aucune exécution au journal, adresse absente de
`recipients.toml`.

D'où le déclencheur **horaire** sur `syncRecipients()`, qui refait le même
travail sans événement. Le retirer ferait disparaître toutes les inscriptions
venues de la landing page — dans la Sheet, mais jamais dans la liste, et sans
que rien ne le signale puisque la page confirme sans preuve.

⚠️ Ne jamais faire lire `e.values` ou `e.namedValues` à `syncRecipients()` :
chaque exécution horaire planterait. `tests/test_recipients_sync_entrypoints.py`
tient l'invariant.

## La landing page confirme sans preuve

`/inscription` poste dans le Google Form. Google ne renvoie pas d'en-tête
CORS : la réponse part dans une iframe cachée et le navigateur ne peut pas la
lire. La page remercie donc **sans savoir** si l'inscription a été enregistrée.

D'où le garde-fou dans `app.py::landing_page` : si `FORM_ID` redevenait un
placeholder dans `landing.html`, la route répondrait **503** au lieu de servir
une page qui avalerait les adresses en silence. Ne jamais le retirer « parce
que la page a l'air de marcher ».

⚠️ Deux identifiants se ressemblent dans les URL Google Forms : celui de
l'**édition** (`/forms/d/<id>/edit`) et celui des **réponses**
(`/forms/d/e/1FAIpQLSc…/viewform`). Seul le second marche dans `action=` ; le
premier donne un 404 que l'iframe avale.

⚠️ Le 503 ne détecte que le **placeholder**. Un `FORM_ID` erroné mais rempli
passe le garde-fou et retombe dans le même silence : après configuration,
soumettre une adresse de test et vérifier qu'elle arrive dans la Sheet.

⚠️ Poster directement contourne aussi le reCAPTCHA. Le champ piège
(`name="site"`, classe `hp`) annule l'envoi tout en affichant la confirmation
— ne pas « simplifier » en affichant une erreur, ça apprendrait au robot
qu'il a été repéré.

## Gmail `invalid_grant` en local mais pas en CI

Après un re-auth via l'email de notification, `auth_server` met à jour le secret
GitHub `GMAIL_TOKEN_JSON`. Le fichier local `~/.gmail-mcp/token.json` ne l'est
pas — d'où le crash local seul.

```bash
venv/bin/python scripts/reauth_local.py
```

## `sync_recipients.gs` doit être recollé dans Apps Script

Le fichier de ce dépôt est une **copie de référence**. Le modifier ici ne
change rien tant qu'il n'est pas collé dans l'éditeur Apps Script.

---

# Commandes utiles

```bash
venv/bin/python scripts/check_apis.py                 # avant un envoi
venv/bin/python scripts/fetch_subscriber_data.py      # rapatrier les abonnés
venv/bin/python main.py --preview 2026-08-25          # aperçu, aucun envoi
venv/bin/python main.py --send-test moi@gmail.com     # une seule adresse
venv/bin/python main.py --now                         # envoi aux abonnés
venv/bin/python -m pytest tests/ -q                   # 281 tests
venv/bin/python scripts/apply_retention.py --dry-run  # simulation de purge
venv/bin/python scripts/build_dashboard_data.py       # régénère data/dashboard.json
```
