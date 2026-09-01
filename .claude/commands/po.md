---
description: Lance le workflow Product Owner — lit le project board GitHub (#3), analyse le codebase, brainstorme de nouvelles User Stories pour améliorer la newsletter, les crée comme issues GitHub et les ajoute au board.
argument-hint: Optionnel — thème ou axe à prioriser (ex. "analytics", "multi-canal", "robustesse")
---

# Workflow PO — Newsletter AI

Lance l'agent Product Owner pour enrichir le backlog du projet.

## Contexte

- **Repo** : `yousmaaza/newletter-ai`
- **Project Board** : https://github.com/users/yousmaaza/projects/3
- **Filtre thématique** : $ARGUMENTS

## Instructions

Invoque l'agent `po-agent` (défini dans `.claude/agents/po-agent.md`) pour orchestrer le workflow complet en 7 phases :

1. Lire l'état actuel du project board #3
2. Lister toutes les issues existantes (éviter les doublons)
3. Analyser le codebase (`CLAUDE.md`, `agent.py`, `config/`, `docs/`)
4. Brainstormer 5–10 nouvelles User Stories — présenter un tableau et attendre confirmation
5. Créer les issues GitHub approuvées (format `[AXE-N.M] Titre`)
6. Ajouter chaque issue au project board
7. Afficher un rapport final avec les liens

Si `$ARGUMENTS` est fourni, oriente le brainstorming en priorité vers ce thème ou axe.

À la fin, rappelle à l'utilisateur qu'il peut lancer `/backlog-feature` pour implémenter les US créées.
