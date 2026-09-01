# Mesure d'audience

Ce que la newsletter observe de ses lecteurs, comment c'est stocké, ce qui est
publié, et comment un lecteur s'y soustrait.

Le principe qui gouverne tout le reste : **un lecteur n'est jamais désigné par
son adresse**, ni par quoi que ce soit qui s'y ramène. Ce qui est mesuré est
annoncé dans la newsletter, et refusable en un clic.

---

## 1. Ce qui est mesuré

Quatre signaux, tous déclenchés par le lecteur lui-même :

| Signal | Déclencheur | Fichier |
|--------|-------------|---------|
| Ouverture | chargement d'un pixel 1×1 | `data/opens_DATE.csv` |
| Clic | passage par `/click` avant redirection | `data/clicks_DATE.csv` |
| Réaction | bouton 👍 / 😐 / 👎 sous un article | `data/reactions_DATE.csv` |
| Avis global | formulaire `/feedback` en fin d'édition | `data/feedback_DATE.csv` |

À part, sans identifiant : `data/unsubscribe_reasons.csv` — les motifs de
départ, dont la colonne d'adresse a été retirée. Ce texte n'est rattaché à
personne.

Ces CSV vivent **dans ce dépôt** : ils sont anonymes depuis la migration des
identifiants. Les quatre fichiers qui portent des adresses vivent ailleurs
(voir [ABONNES.md](ABONNES.md)).

---

## 2. L'identifiant opaque

Chaque lecteur reçoit un identifiant **tiré au sort**, 32 caractères
hexadécimaux (`secrets.token_hex(16)`), rangé dans `config/subscriber_ids.toml`.

```python
# tools/interaction_helper.py
def _hash_email(email: str) -> str:
    """Le nom est conservé pour ses appelants ; la valeur n'a plus rien d'un hash."""
    return _subscriber_ids().get_or_create(email)
```

> ⚠️ **Avant le 26 août 2026, l'identifiant était `sha256(email)` non salé.**
> Avec `recipients.toml` en main, 23 des 26 identifiants se retournaient en
> quelques millisecondes. Un hash non salé d'une adresse email n'est pas un
> anonymat : c'est l'adresse, encodée. **Ne jamais revenir à un identifiant
> dérivé de l'adresse.**
>
> Migration de l'historique : `scripts/migrate_tracking_ids.py [--dry-run]`.
> `tests/test_legacy_hash_rejected.py` empêche la régression.

Deux conséquences pratiques :

- **La table doit être commitée.** Un nouvel abonné reçoit son identifiant
  pendant l'envoi, dans un runner éphémère. Sans renvoi de la table, il en
  recevrait un autre le lendemain et son historique se fragmenterait en
  silence, sans que rien ne le signale. La CI la renvoie vers le dépôt privé
  à chaque run, en `if: always()`.
- **Effacer quelqu'un se fait en une ligne.** Retirer son entrée de la table
  rend anonyme tout son historique, sans toucher à un seul CSV.

> ⚠️ `subscriber_ids.toml` est un fichier **séparé** de `recipients.toml`.
> `sync_recipients.gs::buildToml_()` reconstruit ce dernier entièrement à
> chaque inscription et n'y écrit que `emails` — un identifiant rangé là
> serait effacé au prochain inscrit.

---

## 3. Les liens signés

Tout lien personnalisé — pixel, clic, réaction, avis, désinscription, refus de
mesure — porte un jeton HMAC-SHA256 signé par `UNSUBSCRIBE_SECRET`.

| Lien | Ce que couvre le jeton | L'URL porte |
|------|------------------------|-------------|
| `/pixel` | `identifiant:date` | l'identifiant opaque |
| `/click` | `identifiant:date:rang` | l'identifiant opaque |
| `/react` | `identifiant:date:rang` | l'identifiant opaque |
| `/feedback` | `identifiant:date` | l'identifiant opaque |
| `/unsubscribe` | `email:date` | **l'adresse en clair** |
| `/tracking-optout` | `optout:email:date` | **l'adresse en clair** |

Deux familles, à ne pas confondre. Les liens de **mesure** ne portent que
l'identifiant opaque — c'est tout l'intérêt. Les liens d'**action sur
l'abonnement** portent l'adresse en clair, parce que le serveur doit savoir qui
retirer d'une liste d'adresses ; le HMAC garantit qu'un lien ne vaut que pour
son destinataire.

Le préfixe `optout:` rend le jeton de refus de mesure **non interchangeable**
avec celui de désinscription : présenter l'un à la route de l'autre échoue
(`tests/test_tracking_optout_url.py`).

> ⚠️ `UNSUBSCRIBE_SECRET` doit valoir **exactement** la même chose en local, en
> CI et sur Railway. Le serveur revérifie chaque jeton ; une valeur différente
> les rejette tous. **Sans ce secret, aucun de ces liens n'est rendu** — les
> emails partent alors sans lien de désinscription.

`/click` refuse par ailleurs toute cible non-HTTPS, pour ne pas servir de
redirecteur ouvert.

---

## 4. Le rendu par destinataire

`tools/newsletter_renderer.py::render_for_recipient()` prend la configuration
de suivi **en injection**, pas depuis `config` :

```python
render_for_recipient(data, email, date,
                     auth_server_url=..., secret=...,
                     transparency_notice=..., tracking_enabled=...)
```

Un rendu appelé sans `auth_server_url` ni `secret` ne contient donc **aucune
URL de mesure**. C'est ce qui rend `--preview` sûr par construction plutôt que
par précaution : il ne peut pas polluer les mesures, même lancé cent fois.

`tracking_enabled=False` retire le pixel et les redirections de clic, mais
**jamais** le lien de désinscription — celui-là est gouverné par
`server_configured`, pas par la mesure.

---

## 5. Le bloc transparence

Un encart en fin d'édition qui annonce au lecteur ce qui est mesuré, montre
les chiffres, et propose de s'y soustraire.

**Trois conditions cumulatives** pour qu'il s'affiche :

1. `SHOW_TRACKING_NOTICE` est vrai — variable de **dépôt** GitHub
   (Settings → Secrets and variables → Actions → onglet **Variables**), pas un
   secret : l'activation reste un geste délibéré et réversible depuis
   l'interface, sans toucher au code ;
2. le lecteur n'a pas refusé la mesure ;
3. tous les liens d'action et les chiffres existent.

La troisième est vérifiée par `_validated_transparency()`, qui supprime le bloc
entier si un lien manque — **jamais de bouton mort dans un encart qui parle de
confidentialité**. Le revers : la disparition est silencieuse.

> ⚠️ C'est exactement ainsi qu'une édition est partie sans le bloc le 27 août
> 2026 : `newsletter.yml` avait deux étapes d'envoi, les variables n'étaient
> câblées que dans l'une, et la newsletter est partie sans erreur ni log. Le
> workflow n'a plus qu'un seul chemin d'envoi depuis, et
> `tests/test_workflow_consistency.py` échoue si on le rescinde sans propager
> la configuration.

Les chiffres viennent de `tools/newsletter_stats.py`, qui ne lit que des
agrégats — jamais une ligne individuelle.

Pour tester la chaîne complète, `--with-notice` :

```bash
# Liens factices, aucun envoi
venv/bin/python main.py --preview 2026-08-25 --with-notice

# Liens RÉELS et cliquables — le seul moyen de tester comme un lecteur
venv/bin/python main.py --send-test moi@gmail.com 2026-08-25 --with-notice
```

Le second exige `AUTH_SERVER_URL`, `UNSUBSCRIBE_SECRET` et
`DASHBOARD_PUBLIC_URL` : il échoue en **nommant les manquants**, plutôt que
d'envoyer un email amputé du bouton.

---

## 6. Refuser la mesure

`GET /tracking-optout` — **distinct de la désinscription** : le lecteur garde
sa newsletter, seule l'observation s'arrête.

- Jeton HMAC préfixé `optout:`, non interchangeable
- Écrit dans `config/tracking_optout.toml`, **idempotent** : un re-clic
  n'écrit rien et ne crée pas de commit vide
- Relu par `config.TRACKING_OPTOUT`, appliqué dans `agent.py` via
  `tracking_enabled`

---

## 7. Les tableaux de bord

| Route | Accès | Indexable | Contenu |
|-------|-------|-----------|---------|
| `/dashboard` | `STATS_TOKEN` | non (`noindex`) | payload complet |
| `/board` | public | oui | payload filtré |
| `/stats/<date>` | `STATS_TOKEN` | non | une édition |
| `/vie-privee` | public | oui | page statique |

Deux sources, deux rythmes :

| Donnée | Origine | Fraîcheur |
|--------|---------|-----------|
| Édition du jour | CSV de `data/` relus via l'API GitHub | à chaque chargement, cache 45 s |
| Statut des envois | API GitHub Actions | cache 120 s |
| Historique | `data/dashboard.json` | recalculé par la CI après chaque envoi |

La page se rafraîchit seule toutes les 60 s, en pause quand l'onglet passe en
arrière-plan. `/dashboard/data` et `/board/data` renvoient le même payload en
JSON.

### Le filtre public est une liste blanche

`auth_server/public_board.py::PUBLIC_KEYS` énumère ce qui sort. **Toute clé
ajoutée à `build_dashboard_data.py` est exclue de `/board` tant qu'elle n'y est
pas ajoutée explicitement.** Ne jamais transformer ça en liste noire : l'oubli
y devient une fuite au lieu d'une absence.

Retirées volontairement : `runs` (révèle le compte et le dépôt GitHub), et les
champs privés de `unsub`.

> ⚠️ `DASHBOARD_PUBLIC_URL` doit pointer vers `/board`, **jamais** vers
> `/dashboard?token=…` — mettre ce jeton dans un email le diffuse à tous les
> abonnés, et un seul transfert suffit à le faire fuiter.

`/vie-privee` n'a **aucune dépendance** : ni jeton, ni GitHub, ni données. Une
page qui explique ce qui est collecté ne doit pas tomber avec l'infrastructure
qu'elle décrit. C'est la valeur à mettre dans `PRIVACY_URL`.

### Les thèmes sont reconstitués, pas mesurés

`agent.py` demande un `topic` au modèle, mais l'archive poussée dans
`output/newsletter/DATE/data.json` ne retient que `rank` et `title`. La
répartition par thème est donc **déduite des titres** par heuristique lexicale
(`classify_title` dans `scripts/build_dashboard_data.py`), avec environ 17 % de
titres non classés.

Archiver `topic` rendrait la mesure exacte — le script utilise déjà
`a.get("topic")` en priorité s'il est présent.

---

## 8. Rétention

```bash
venv/bin/python scripts/apply_retention.py --dry-run   # simulation
venv/bin/python scripts/apply_retention.py             # application
```

**Un seul seuil : 12 mois** (`MEASURE_RETENTION_DAYS = 365`). Il ne s'applique
qu'aux lignes portant un identifiant, et ce qu'il advient d'un texte libre
dépend donc du fichier où il se trouve :

| Fichier | Ce qui part à 12 mois | Ce qui reste |
|---------|------------------------|--------------|
| `opens_DATE.csv`, `clicks_DATE.csv`, `reactions_DATE.csv` | l'identifiant → `archived` | la ligne, donc le volume |
| `feedback_DATE.csv` | l'identifiant **et** le `comment` | la réaction globale |
| `unsubscribe_reasons.csv` | rien — fichier jamais réécrit | motifs **et** texte libre |

Les motifs de départ sont conservés indéfiniment **parce que** leur fichier ne
porte aucun identifiant : ce texte n'est lié à personne, et reste un retour
produit exploitable. C'est un invariant, pas un oubli — y réintroduire une
colonne d'adresse le rendrait nominatif *et* déclencherait l'effacement de son
texte.

Trois propriétés à préserver :

- **Aucune ligne n'est supprimée**, seulement désidentifiée. Les volumes
  publiés sur `/board` restent donc exacts après passage.
- **Idempotent** : un second passage ne change rien.
- **Atomique** : écriture dans un fichier temporaire, puis `replace`.

Le workflow `retention.yml` l'exécute le 1er de chaque mois à 04:00 UTC —
avant l'envoi de 05:00, pour ne jamais réécrire `data/` pendant qu'une
newsletter s'exécute. Sans cette exécution périodique, une politique de
rétention n'est qu'une promesse.

---

## Voir aussi

- [ABONNES.md](ABONNES.md) — inscription, désinscription, dépôt privé, déploiement Railway
- [TESTS.md](TESTS.md) — comment vérifier tout ce qui précède
- [ARCHITECTURE.md](ARCHITECTURE.md) — le pipeline, ses workflows et ses secrets

## Le jeton du tableau de bord vit dans un cookie

`/dashboard` et `/stats/<date>` s'ouvrent **une fois** avec `?token=…`. Le
serveur pose alors un cookie `stats_session` — `HttpOnly`, `SameSite=Lax`,
30 jours — et redirige vers une adresse sans jeton.

⚠️ **`Secure` dépend de `X-Forwarded-Proto`.** Railway termine TLS en amont :
le schéma vu par Flask est `http`. Sans lire cet en-tête, le cookie ne serait
jamais marqué `Secure` en production. `tests/test_dashboard_cookie.py` tient
les deux cas.

Pourquoi le sortir de l'URL :

- il apparaissait dans la barre d'adresse, l'historique, **les journaux du
  serveur**, et toute capture d'écran — il a fuité deux fois ;
- chaque lien interne était une occasion de le perdre. Un lien de période écrit
  `href="?range=7d"` remplaçait la chaîne de requête entière et emportait le
  jeton avec elle : la page devenait inaccessible au premier clic.

`?token=` reste accepté : c'est par lui qu'on ouvre une session, et les liens
déjà en circulation continuent de marcher.

⚠️ `/board` reste public et sans jeton — c'est la page que la newsletter
annonce à ses lecteurs, et elle ne doit jamais dépendre d'une session.

## `/stats/<date>` a fusionné dans le tableau de bord

Les deux pages disaient la même chose, dans deux styles différents et avec
chacune son authentification. Il n'en reste qu'une :

| Adresse | Ce qu'elle montre |
|---|---|
| `/dashboard` | vue d'ensemble, et l'édition la plus récente de la période |
| `/dashboard/<date>` | la même page, centrée sur cette édition |
| `/stats/<date>` | **redirige** vers `/dashboard/<date>` |

La redirection est conservée parce que des liens circulent — une page qui
disparaît sans rediriger est une page qui casse. Un vieux lien portant encore
`?token=` ouvre la session au passage, plutôt que de rediriger vers un refus.

⚠️ **Le détail d'une édition n'est pas public.** Il porte les réactions et les
commentaires article par article : `PUBLIC_KEYS` ne le laisse pas passer, et
`/board` masque la carte au lieu de l'afficher vide.

⚠️ **Un détail indisponible ne doit pas emporter la page.** `_detail_edition`
renvoie `None` en cas d'échec : le reste du tableau de bord n'en dépend pas, et
une vue d'ensemble amputée est plus utile qu'une erreur 502.
