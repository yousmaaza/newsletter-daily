Met à jour `docs/ARCHITECTURE.md` et `README.md` pour refléter l'état actuel du projet.

## Instructions

### Étape 1 — Lire l'état actuel du projet

Lis les fichiers suivants pour comprendre ce qui existe et ce qui a changé :
- `main.py` — CLI flags et fonctions disponibles
- `agent.py` — paramètres de run_agent()
- `config.py` — toutes les variables de configuration
- `tools/newsletter_renderer.py` — rendu HTML par destinataire, bloc transparence
- `tools/newsletter_stats.py` — agrégats affichés dans le bloc
- `scripts/check_apis.py` — script de vérification
- `.github/workflows/newsletter.yml` — workflow CI/CD
- `docs/ARCHITECTURE.md` — version actuelle à mettre à jour
- `README.md` — version actuelle à mettre à jour

### Étape 2 — Mettre à jour `docs/ARCHITECTURE.md`

Réécris le fichier pour documenter **toutes les fonctionnalités actuelles**, organisées en sections numérotées. Chaque section doit couvrir :
- Le fichier source concerné
- Le rôle de la fonctionnalité
- Le flux d'exécution (si pertinent)
- Les paramètres / variables clés

Sections obligatoires à inclure ou mettre à jour :
1. Agent Claude (boucle tool_use) — `agent.py`
2. Recherche d'actualités (Brave Search) — `tools/brave_search.py`
3. Newsletter HTML — `newsletter_template.html`
4. Envoi email (Gmail API) — `tools/gmail_tool.py`
5. Renouvellement automatique du token Gmail — `tools/auth_notifier.py`
6. CLI et modes d'exécution — `main.py`
7. Planification et CI/CD — GitHub Actions
8. Vérification des APIs — `scripts/check_apis.py`
9. Configuration — `config.py`

### Étape 3 — Mettre à jour `README.md`

Réécris les sections suivantes du README pour qu'elles reflètent l'état actuel :

**Section "Fonctionnement en un coup d'œil"** — schéma ASCII du pipeline : recherche → rédaction → rendu par destinataire → envoi

**Section "Utilisation / Commandes principales"** — liste exacte des commandes CLI actuelles :
```
--now
--preview [DATE]
--send-test EMAIL [DATE]
--with-notice
--data-file CHEMIN
(scheduler par défaut)
```

**Section "Variables d'environnement"** — tableau complet avec toutes les variables de config.py, groupées par catégorie (Core, Gmail, Mesure et transparence, Git, Scheduler)

**Section "GitHub Actions"** — chemin d'envoi unique : cron et déclenchement manuel partagent la même étape et le même bloc `env:`

Ne modifie pas les sections que tu ne connais pas (setup, architecture détaillée, etc.) sauf si elles sont clairement obsolètes.

### Étape 4 — Commiter les changements

Une fois les deux fichiers mis à jour, crée un commit :
```
docs: mise à jour ARCHITECTURE.md et README avec l'état actuel du projet
```