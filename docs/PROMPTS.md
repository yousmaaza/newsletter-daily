# Gestion des prompts — `config/prompts.toml`

Tous les prompts du projet sont centralisés dans `config/prompts.toml`.
Modifier ce fichier suffit — aucune retouche du code Python n'est nécessaire.

---

## Structure du fichier

```
config/prompts.toml
└── [newsletter]
    ├── system_prompt         → instructions de l'agent journaliste Claude
    └── initial_message       → message de démarrage du pipeline newsletter
```

---

## Section `[newsletter]`

### `system_prompt`

Instructions données à Claude au démarrage de chaque session. Définit le rôle, les règles de
rédaction (titre ≤ 10 mots, flash une phrase, niveaux de hype, etc.) et la langue.

```toml
[newsletter]
system_prompt = """
Tu es un agent journaliste...
"""
```

### `initial_message`

Premier message utilisateur envoyé à Claude pour déclencher le pipeline. Contient la variable
`{today}` remplacée dynamiquement par la date du jour.

```toml
[newsletter]
initial_message = "Génère et envoie la newsletter quotidienne pour le {today}."
```

---

## Workflow pour itérer

### Vérifier ce que le modèle recevra

```bash
venv/bin/python -c "from config import prompts; print(prompts.system_prompt)"
venv/bin/python -c "from config import prompts; print(prompts.initial_message)"
```

### Tester un prompt modifié sans consommer de crédits

Le rendu de la newsletter est indépendant de la génération : pour valider un
gabarit ou un bloc sans relancer l'agent, composer depuis une édition figée.

```bash
venv/bin/python main.py --send-test moi@gmail.com \
  --data-file tests/fixtures/newsletter_sample.json --with-notice
```

### Vérifier que le TOML est valide

```bash
venv/bin/python -c "import tomllib; tomllib.load(open('config/prompts.toml','rb')); print('OK')"
```

---

## Chargement dans le code

Les prompts sont exposés via la classe `PromptsConfig` dans `config.py` :

```python
from config import prompts

prompts.system_prompt         # str — system prompt de l'agent Claude
prompts.initial_message       # str — message initial (contient {today})
```

En cas de fichier manquant ou de syntaxe invalide, une erreur claire est levée au démarrage
(fail-fast) avec le chemin exact du fichier en cause.
