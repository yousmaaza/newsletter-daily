"""
Filtrage du tableau de bord par période.

La page montrait des moyennes depuis avril. Une moyenne sur cinq mois ne
montre aucune évolution : impossible d'y voir qu'une semaine décroche, ni de
comparer un mois au précédent.

L'agrégation se fait ici plutôt que dans le navigateur. Le coût est un
rechargement de page à chaque changement de période ; le gain est que chaque
règle est couverte par un test. Ce projet a appris à ses dépens que ce qui
n'est pas regardé n'est pas su — mieux vaut une page qui recharge et dont on
sait qu'elle dit vrai.

⚠️ `/dashboard` et `/board` partagent le même gabarit, mais `/board` reçoit un
payload **sans `series`** : la liste blanche de public_board.py les exclut,
parce que `series.opens` est une matrice lecteur × jour. Sans séries, il n'y a
rien à recalculer — le filtre s'efface et rend le payload intact, il n'échoue
jamais.
"""

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

# Nombre de jours couverts. None = tout l'historique.
RANGES: dict[str, int | None] = {
    "7d": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "all": None,
}

DEFAUT = "all"


def window_start(key: str, today: date | None = None) -> date | None:
    """Premier jour inclus dans la période. None si toute la période est prise."""
    jours = RANGES.get(key)
    if jours is None:
        return None
    return (today or date.today()) - timedelta(days=jours - 1)


def apply_range(payload: dict, key: str, today: date | None = None) -> dict:
    """
    Recalcule les agrégats sur la période demandée.

    Rend le payload inchangé si la période est inconnue, vaut « tout », ou si
    les séries datées sont absentes. Un paramètre d'URL trafiqué doit produire
    la page complète, jamais une page vide.
    """
    series = payload.get("series")
    if key not in RANGES or RANGES[key] is None or not series:
        return payload

    debut = window_start(key, today).isoformat()
    out = deepcopy(payload)
    out["range"] = {"key": key, "start": debut}

    # -- clics : rang et domaine ------------------------------------------
    clics = [c for c in series.get("clicks", []) if c[0] >= debut]
    out["by_rank"] = {str(k): v for k, v in sorted(Counter(r for _, r, _ in clics).items())}
    out["by_domain"] = dict(Counter(d for _, _, d in clics if d).most_common())

    # -- fidélité : nombre d'éditions ouvertes par lecteur -----------------
    #
    # Un lecteur absent de la période ne doit pas y figurer avec un zéro : la
    # distribution dirait alors qu'il y a plus de lecteurs tièdes qu'en réalité.
    par_lecteur: Counter = Counter()
    for jour, lecteurs in series.get("opens", {}).items():
        if jour >= debut:
            par_lecteur.update(lecteurs)
    out["loyalty"] = sorted(par_lecteur.values(), reverse=True)
    out["unique_readers"] = len(par_lecteur)

    # -- thèmes ------------------------------------------------------------
    themes: Counter = Counter()
    for jour, compte in series.get("topics", {}).items():
        if jour >= debut:
            themes.update(compte)
    out["topics"] = {**payload.get("topics", {}),
                     "counts": dict(themes.most_common()),
                     "total": sum(themes.values())}

    # -- listes datées : le filtre vaut pour toute la page ------------------
    #
    # Un filtre qui ne s'appliquerait qu'à une moitié de l'écran serait pire
    # qu'aucun filtre : on comparerait des chiffres de périodes différentes
    # sans que rien ne le signale.
    out["editions"] = [e for e in payload.get("editions", []) if e.get("date", "") >= debut]
    out["runs"] = [r for r in payload.get("runs", []) if r.get("date", "") >= debut]
    out["unsub"] = [u for u in payload.get("unsub", []) if u.get("date", "") >= debut]

    motifs: Counter = Counter()
    for u in out["unsub"]:
        for part in str(u.get("reason", "")).split(","):
            if part.strip():
                motifs[part.strip()] += 1
    out["unsub_reasons"] = dict(motifs.most_common())

    out["totals"] = {**payload.get("totals", {}),
                     "editions": len(out["editions"]),
                     "opens": sum(e.get("opens", 0) for e in out["editions"]),
                     "clicks": len(clics)}
    return out
