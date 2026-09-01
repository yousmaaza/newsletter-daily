---
description: Lit le backlog GitHub, groupe les US par problématique, développe la feature avec feature-dev, crée une branche, un document de test et une PR taguée.
argument-hint: Optionnel — filtre sur un label ou mot-clé (ex. "enhancement", "US-1")
---

# Backlog → Feature Development Pipeline

Tu orchestres un pipeline complet : lecture du backlog GitHub → groupement des User Stories → développement via `/feature-dev` → branche → document de test → Pull Request.

## Phase 0 — Initialisation

**Actions :**
1. Crée un todo avec toutes les phases.
2. Récupère le remote GitHub du repo :
   ```bash
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```
3. Note le owner/repo pour toutes les commandes `gh` suivantes.

---

## Phase 1 — Lecture du backlog GitHub

**Objectif :** Récupérer toutes les issues ouvertes du backlog.

**Actions :**
1. Liste toutes les issues ouvertes (limite 100) :
   ```bash
   gh issue list --state open --limit 100 --json number,title,labels,body,milestone,createdAt
   ```
   Si un filtre `$ARGUMENTS` est fourni, ajoute `--label "$ARGUMENTS"` ou filtre ensuite.

2. Affiche la liste complète à l'utilisateur sous forme de tableau :
   | # | Titre | Labels | Date |
   |---|-------|--------|------|

3. Si aucune issue n'est trouvée, informe l'utilisateur et arrête le pipeline.

---

## Phase 2 — Groupement des User Stories par problématique

**Objectif :** Identifier les groupes d'issues qui partagent la même problématique fonctionnelle.

**Actions :**
1. Analyse toutes les issues récupérées et identifie des **groupes thématiques** cohérents. Critères de regroupement :
   - Même préfixe d'épic (ex. `[US-1.x]`, `[US-2.x]`)
   - Même label partagé
   - Même domaine fonctionnel (détection doublons, mémoire thématique, auth, etc.)
   - Dépendances fonctionnelles entre issues (une US mentionne une autre)

2. Pour chaque groupe identifié, présente :
   ```
   Groupe A — <Titre de la problématique>
   ├── #15 [US-1.1] Détection des articles similaires
   ├── #16 [US-1.2] Logging des doublons détectés
   ├── #17 [US-1.3] Paramétrage du seuil via TOML
   └── #18 [US-1.4] Fusion intelligente des doublons
   Résumé : <2 phrases expliquant la problématique commune>
   Complexité estimée : Faible / Moyenne / Élevée
   ```

3. **Demande à l'utilisateur de choisir le groupe à développer** en indiquant la lettre ou le numéro du groupe.
4. **Attends la réponse avant de continuer.**

---

## Phase 3 — Chargement du contexte des issues sélectionnées

**Objectif :** Récupérer le détail complet de chaque issue du groupe choisi.

**Actions :**
1. Pour chaque issue du groupe sélectionné, récupère le détail complet :
   ```bash
   gh issue view <number> --json number,title,body,labels,comments,assignees,milestone
   ```

2. Extrait de chaque issue :
   - La description / critères d'acceptance
   - Les contraintes techniques mentionnées
   - Les dépendances avec d'autres issues

3. Construis un **résumé de la feature** en une phrase claire utilisable comme argument pour `feature-dev`.

4. Identifie le **nom de branche** selon le pattern :
   - `feature/us-<epic>-<slug-de-la-problematique>` (ex. `feature/us-1-deduplication`)
   - Utilise `echo <nom>` pour vérifier qu'il n'existe pas déjà :
     ```bash
     git branch --list "feature/*"
     ```

---

## Phase 4 — Création de la branche feature

**Objectif :** Créer une branche dédiée à la feature.

**Actions :**
1. Identifie la branche de base (généralement `main` ou la branche principale active) :
   ```bash
   git remote show origin | grep "HEAD branch"
   ```

2. Crée et checkout la branche feature :
   ```bash
   git checkout -b <nom-de-branche>
   ```

3. Confirme à l'utilisateur : "Branche `<nom-de-branche>` créée à partir de `<base>`."

---

## Phase 5 — Développement de la feature avec feature-dev

**Objectif :** Implémenter la feature en utilisant le workflow `/feature-dev`.

**Actions :**
1. Invoque le skill `feature-dev:feature-dev` avec comme arguments le résumé construit en Phase 3, enrichi des critères d'acceptance de toutes les issues du groupe.

   Format d'argument :
   ```
   <Résumé de la problématique>
   
   User Stories concernées :
   - #<N> : <titre> — <critères d'acceptance clés>
   - #<N> : <titre> — <critères d'acceptance clés>
   
   Contraintes :
   - <contrainte 1>
   - <contrainte 2>
   ```

2. Suis intégralement les 7 phases du workflow feature-dev (Discovery → Exploration → Clarification → Architecture → Implémentation → Review → Summary).

3. À la fin de chaque phase feature-dev, mets à jour ton todo principal.

---

## Phase 6 — Création du document de test

**Objectif :** Produire un guide de test manuel et automatisé pour la feature.

Les plans de test **ne sont plus un fichier par feature** : cinq `TEST_*.md`
avaient fini par se périmer en parallèle. Ce qui reste vrai après la livraison
va dans `docs/TESTS.md` ; le plan détaillé, lui, vit dans la PR, où il est lu
au moment de la revue puis archivé avec elle.

**Actions :**
1. Rédige le plan de test **dans la description de la PR**, avec la structure
   suivante :

```markdown
# Plan de test — <Titre de la problématique>

## Issues couvertes
- #<N> [<titre>](lien GitHub)
- ...

## Prérequis
- [ ] Branche `<nom-branche>` checkout localement
- [ ] Variables d'environnement configurées (`.env`)
- [ ] Dépendances installées (`pip install -r requirements.txt`)

## Scénarios de test manuels

### Scénario 1 — <Cas nominal>
**Objectif :** ...  
**Étapes :**
1. ...
2. ...  
**Résultat attendu :** ...

### Scénario 2 — <Cas limite>
...

### Scénario 3 — <Cas d'erreur>
...

## Tests automatisés
- Fichier(s) de test : `tests/test_<module>.py`
- Commande : `python -m pytest tests/test_<module>.py -v`
- Couverture minimale attendue : ...

## Critères d'acceptance (par issue)

### #<N> — <titre>
- [ ] Critère 1
- [ ] Critère 2

## Régressions à vérifier
- [ ] Le pipeline newsletter complet s'exécute sans erreur (`python main.py --now`)
- [ ] ...
```

2. Adapte le contenu en fonction de ce qui a réellement été implémenté en Phase 5.

---

## Phase 7 — Commit des changements

**Objectif :** Versionner proprement les changements.

**Actions :**
1. Stage tous les fichiers modifiés/créés :
   ```bash
   git add -A
   git status
   ```
2. Crée un commit descriptif :
   ```bash
   git commit -m "feat: <résumé feature>

   Closes #<N>, #<N>, #<N>
   
   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
   ```
3. Pousse la branche vers le remote :
   ```bash
   git push -u origin <nom-de-branche>
   ```

---

## Phase 8 — Création de la Pull Request

**Objectif :** Ouvrir une PR qui relie toutes les issues du groupe.

**Actions :**
1. Construis le body de la PR avec les issues liées en utilisant les mots-clés de fermeture automatique GitHub (`Closes #N`).

2. Crée la PR :
   ```bash
   gh pr create \
     --title "feat: <titre de la problématique>" \
     --base <branche-de-base> \
     --body "$(cat <<'EOF'
   ## Problématique

   <Description de la problématique adressée par ce groupe d'US>

   ## User Stories implémentées

   - Closes #<N> — <titre>
   - Closes #<N> — <titre>
   - Closes #<N> — <titre>

   ## Changements apportés

   <Liste des fichiers modifiés et nature des changements>

   ## Plan de test

   Voir la section « Plan de test » ci-dessus.

   ## Checklist

   - [ ] Tests manuels exécutés selon le plan ci-dessus
   - [ ] Pas de régression sur le pipeline principal (`pytest tests/ -q`)
   - [ ] Ce qui reste vrai après la livraison est reporté dans `docs/TESTS.md`
   - [ ] Documentation mise à jour si nécessaire

   🤖 Generated with [Claude Code](https://claude.ai/claude-code)
   EOF
   )"
   ```

3. Affiche l'URL de la PR créée.

4. (Optionnel) Ajoute les labels appropriés :
   ```bash
   gh pr edit <number> --add-label "enhancement"
   ```

---

## Phase 9 — Passage des issues en "In Review" sur le board

**Objectif :** Mettre à jour le statut des issues du groupe sur le project board GitHub.

**Prérequis :** Le token gh doit avoir le scope `project`. Si ce n'est pas le cas, demander à l'utilisateur de lancer :
```bash
gh auth refresh -s project
```

**Actions :**
1. Récupère le numéro du project board :
   ```bash
   gh project list --owner <owner> --format json --jq '.projects[] | [.number, .title] | @tsv'
   ```

2. Pour chaque issue du groupe, trouve son item ID dans le projet et passe son statut en "In Review" :
   ```bash
   # Récupérer l'ID du projet (number → id)
   PROJECT_ID=$(gh project list --owner <owner> --format json --jq '.projects[] | select(.number == <N>) | .id')

   # Lister les items du projet et trouver l'issue
   gh project item-list <project-number> --owner <owner> --format json \
     --jq '.items[] | select(.content.number == <issue-number>) | .id'

   # Récupérer l'ID du champ Status et l'option "In Review"
   gh project field-list <project-number> --owner <owner> --format json \
     --jq '.fields[] | select(.name == "Status") | {id: .id, options: .options}'

   # Mettre à jour le statut
   gh project item-edit \
     --project-id $PROJECT_ID \
     --id <item-id> \
     --field-id <status-field-id> \
     --single-select-option-id <in-review-option-id>
   ```

3. Répète pour chaque issue du groupe (sauf celles hors scope comme les US R&D Sprint 3+).

4. Confirme : "Issues #N, #N, #N passées en **In Review** sur le board."

5. Si le scope `project` est manquant, indique à l'utilisateur de relancer après `gh auth refresh -s project`.

---

## Phase 10 — Résumé final

**Objectif :** Confirmer ce qui a été accompli.

**Actions :**
1. Marque tous les todos comme terminés.
2. Affiche un récapitulatif :
   ```
   ✅ Pipeline backlog → feature terminé
   
   Branche     : <nom-de-branche>
   Issues      : #N, #N, #N (statut → In Review)
   PR          : <URL>
   Plan de test : dans la description de la PR
   ```
