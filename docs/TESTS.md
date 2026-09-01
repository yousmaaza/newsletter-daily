# Tester la newsletter

Quatre niveaux, du plus sûr au plus proche du réel. Le principe : **rien ne
doit jamais partir aux abonnés par accident**, et rien ne doit polluer les
mesures.

| Niveau | Réseau | Envoi | Coût | Pollue les mesures |
|--------|--------|-------|------|--------------------|
| `pytest` | non | non | — | non |
| `--preview` | non | non | — | non |
| `--send-test` | oui | 1 adresse | — | non |
| `ci-validate` | oui | 1 adresse | selon la source | non |

---

## 1. Suite automatisée

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest tests/ -q
```

Ce que la suite garde sous surveillance — chaque fichier existe parce que
quelque chose a cassé un jour :

| Test | Ce qu'il empêche de revenir |
|------|------------------------------|
| `test_legacy_hash_rejected` | Un identifiant dérivé de l'adresse (voir [MESURE.md](MESURE.md#2-lidentifiant-opaque)) |
| `test_workflow_consistency` | Un chemin d'envoi scindé sans propager la configuration |
| `test_send_targeting` | Un envoi à la liste d'abonnés alors qu'un override était demandé |
| `test_preview` | Une URL de mesure dans un aperçu local |
| `test_notice_requirements` | Un bloc transparence rendu avec un lien mort |
| `test_transparency_block` / `_stats` | Un bloc qui ment sur ses chiffres |
| `test_optout_honoured` | Un lecteur mesuré après avoir refusé |
| `test_optout_no_empty_commit` | Un re-clic qui crée un commit vide |
| `test_unsubscribe_no_empty_commit` | Idem côté désinscription |
| `test_public_board` / `_route` | Une clé privée servie sur `/board` |
| `test_privacy_page_route` | Une page vie privée qui dépend de l'infrastructure |
| `test_retention` | Une purge non idempotente ou destructrice |
| `test_unsubscribe_reasons_privacy` | Une adresse dans le fichier des motifs |
| `test_data_repo_routing` | Une lecture d'abonnés dans le mauvais dépôt |
| `test_open_rate_sanity` | Un taux d'ouverture supérieur à 100 % |

Le rendu vit dans `tools/newsletter_renderer.py`, extrait de la closure
d'`agent.py` précisément pour être testable : `render_for_recipient()` prend la
configuration de suivi en **injection**, donc un rendu sans `auth_server_url`
ni `secret` ne contient aucune URL de mesure.

---

## 2. Aperçu local — `--preview`

```bash
venv/bin/python main.py --preview                  # édition du jour
venv/bin/python main.py --preview 2026-08-25       # une date précise
venv/bin/python main.py --preview 2026-08-25 --with-notice
```

Écrit `output/preview/DATE.html` (dossier gitignoré). **Aucun réseau, aucun
envoi**, et surtout aucun pixel ni lien de redirection : relançable autant de
fois qu'on veut sans fausser une seule statistique.

Avec `--with-notice`, le bloc transparence est rendu avec des **liens
factices** — bon pour juger la mise en forme, inutile pour tester la chaîne.

---

## 3. Réexpédition ciblée — `--send-test`

```bash
venv/bin/python main.py --send-test moi@gmail.com                 # édition du jour
venv/bin/python main.py --send-test moi@gmail.com 2026-08-25      # une date précise
venv/bin/python main.py --now --send-test moi@gmail.com           # pipeline complet, 1 destinataire
```

Passe par `recipients_override` : **la liste d'abonnés n'est jamais lue**. Un
override vide lève une `ValueError` au lieu de retomber sur les abonnés
(`tools/gmail_tool.py::resolve_recipients`).

### Tester la chaîne de refus de mesure pour de vrai

```bash
venv/bin/python main.py --send-test moi@gmail.com 2026-08-25 --with-notice
```

Ici les liens sont **réels**. Le bouton « Ne plus être mesuré » reçu dans
l'email fonctionne vraiment — c'est le seul moyen de parcourir la chaîne
complète comme un lecteur. La commande exige `AUTH_SERVER_URL`,
`UNSUBSCRIBE_SECRET` et `DASHBOARD_PUBLIC_URL`, et **échoue en nommant les
manquants** plutôt que d'envoyer un email amputé du bouton.

> Après le test, retire-toi de `config/tracking_optout.toml` — sinon tes
> propres éditions ne sont plus mesurées.

### Sans consommer de crédits

```bash
venv/bin/python main.py --send-test moi@gmail.com \
  --data-file tests/fixtures/newsletter_sample.json --with-notice
```

`--data-file` compose depuis une édition figée au lieu de chercher
`output/newsletter/DATE/data.json`. Le rendu, le bloc, les liens et la mise en
forme sont validés sans lancer l'agent, donc sans appel à Anthropic ni Brave.

---

## 4. Validation en CI — `ci-validate.yml`

Envoie une édition à la seule adresse `CI_TEST_EMAIL`. Deux sources, choisies
au déclenchement manuel :

| Source | Coût | Ce que ça valide |
|--------|------|------------------|
| `reference` (défaut) | **aucun** | template, bloc, liens, mise en forme |
| `generation` | crédits Anthropic + quota Brave | sélection et rédaction des articles |

Un push ou une PR utilise `reference` : la génération n'est lancée que sur
demande explicite.

> ⚠️ Le workflow **écrase `config/recipients.toml`** pour n'y laisser que
> l'adresse de test. **Ne jamais reproduire ce geste en local** : un oubli
> détruit la liste d'abonnés.

---

## Vérifier les APIs avant un envoi

```bash
venv/bin/python scripts/check_apis.py
```

Anthropic, Brave, le jeton Gmail local (avec tentative de rafraîchissement) et
la liste de destinataires. Sortie en code 1 dès qu'une vérification échoue.

Il signale aussi le cas où la liste vient de `GMAIL_TO` faute de
`recipients.toml` rapatrié — un envoi partirait alors aux mauvaises adresses.

---

## Vérifications manuelles

Ce que la suite automatisée ne couvre pas et qui demande un œil ou un
navigateur.

### Rendu de l'email

- Ouvrir `output/preview/DATE.html` dans un navigateur **et** dans un vrai
  client mail : styles inline, pas de JavaScript
- Trois boutons 👍 / 😐 / 👎 par article, uniquement si
  `article.reaction_like_url` est défini
- Les liens sources passent par `/click`, pas directement vers l'article
- Sans `AUTH_SERVER_URL` : newsletter normale, sans bouton de réaction et avec
  des liens sources directs

### Chaîne d'interaction

Avec un `auth_server` local (`cd auth_server && python app.py`) :

| À vérifier | Attendu |
|------------|---------|
| Clic sur une réaction | Page de confirmation, une ligne dans `data/reactions_DATE.csv` |
| Deuxième clic, autre réaction | « Réaction mise à jour », toujours **une seule** ligne |
| Jeton modifié à la main | Page d'erreur, **rien** d'écrit |
| Clic sur un lien source | 302 vers la cible, une ligne dans `clicks_DATE.csv` |
| Cible non-HTTPS forcée | Refus — pas de redirecteur ouvert |
| Appel du pixel deux fois | Une seule ligne dans `opens_DATE.csv` (idempotent) |
| Jeton de désinscription sur `/tracking-optout` | Refusé — les deux ne sont pas interchangeables |

### Déduplication et mémoire thématique

- `news_settings.dedup_enabled = false` → comportement nominal inchangé
- Seuil hors plage → erreur claire au chargement, pas un défaut silencieux
- Deuxième run du jour → l'historique des thèmes est pris en compte dans le
  prompt (`venv/bin/python -c "from tools.topic_memory import get_recent_topics; print(get_recent_topics())"`)

### Validation Pydantic

- `rank` en chaîne (`"1"`) → coercé en entier
- `articles` renvoyé comme chaîne JSON → absorbé par le validateur
- Champ obligatoire manquant → l'erreur repart à Claude, qui corrige, sans
  crash du pipeline
- `data.json` corrompu → `ERROR data.json invalide`, code 1

---

## Voir aussi

- [MESURE.md](MESURE.md) — ce qui est mesuré et pourquoi c'est testé ainsi
- [ARCHITECTURE.md](ARCHITECTURE.md) — le pipeline dans son ensemble
- [ABONNES.md](ABONNES.md) — le dépôt privé, à rapatrier avant tout test réel
