"""
Contrat entre le filtre public et dashboard.html.

Ce test existe parce que le filtre a cassé la page en production : il retirait
`runs`, que le gabarit consomme via `D.runs.slice()`. Une clé absente y lève une
TypeError qui laisse le tableau de bord entièrement blanc.

Il relit le gabarit à chaque exécution : ajouter un `D.nouvelle_cle` sans
l'autoriser dans le filtre fait échouer ce test au lieu de casser la page.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auth_server"))

from auth_server.public_board import public_payload

TEMPLATE = Path(__file__).resolve().parent.parent / "auth_server" / "dashboard.html"

# Un payload complet et représentatif de ce que sert le dashboard privé.
FULL = {
    "generated": "2026-08-25T19:18:30+00:00",
    "editions": [{"date": "2026-08-25", "sent": 25, "opens": 17, "clicks": 5}],
    "current_sent": 25,
    "unique_readers": 26,
    "by_rank": {"1": 12},
    "by_domain": {"lefigaro.fr": 9},
    "by_hour": {"06": 14},
    "loyalty": [100, 99],
    "unsub": [{"date": "2026-04-01", "reason": "too_long", "text": "privé"}],
    "unsub_reasons": {"too_long": 2},
    "topics": {"monde": 31},
    "totals": {"opens": 1706, "clicks": 168},
    "live": True,
    "runs": [{"date": "2026-08-25", "url": "https://github.com/u/r/actions/runs/1"}],
}


# Clés que le gabarit lit DÉLIBÉRÉMENT de façon facultative.
#
# Le filtre de période n'existe que sur /dashboard : /board reçoit un payload
# sans `series` (la matrice lecteur × jour n'a pas à être publique) ni `range`.
# Le gabarit s'en accommode et masque le sélecteur au lieu de le rendre mort.
#
# ⚠️ Une exemption n'est PAS un laissez-passer : le test ci-dessous vérifie que
# chaque lecture de ces clés est effectivement gardée. Retirer la garde fait
# échouer, exactement comme une clé oubliée.
OPTIONAL_KEYS = {
    "series",   # présence testée par `if (!D.series) return;`
    "range",    # toujours lue derrière `D.range && …` ou `D.range ? … : …`
    "edition",  # `if (!E) { carte.hidden = true; return; }`
}

# ⚠️ `edition` n'est volontairement PAS publique : elle porte les réactions et
# les commentaires article par article. /board masque la carte au lieu de la
# rendre vide.


def keys_used_by_the_page() -> set[str]:
    """Toutes les clés `D.xxx` lues par le JavaScript du gabarit."""
    return set(re.findall(r"\bD\.([a-zA-Z_][a-zA-Z0-9_]*)", TEMPLATE.read_text(encoding="utf-8")))


def test_every_key_the_page_reads_is_present_in_the_public_payload():
    missing = keys_used_by_the_page() - set(public_payload(FULL)) - OPTIONAL_KEYS

    assert not missing, (
        f"dashboard.html lit {sorted(missing)} — absent du payload public. "
        f"La page rendra blanc. Autoriser ces clés dans PUBLIC_KEYS, ou les "
        f"neutraliser comme runs/live/unsub."
    )


def test_no_array_loses_entries_between_private_and_public():
    """
    Le filtre expurge des champs, il ne supprime jamais d'entrées. La page
    indexe dans ces tableaux et divise par leur longueur : en retirer une
    entrée fausse les taux, les vider plante le rendu.
    """
    public = public_payload(FULL)
    shrunk = {
        key: (len(FULL[key]), len(public[key]))
        for key, value in FULL.items()
        if isinstance(value, list) and key in public and len(public[key]) != len(value)
    }

    assert not shrunk, f"tableaux amputés (source, public) : {shrunk}"


def test_the_page_reads_at_least_the_keys_we_know_about():
    """Garde-fou : si l'extraction ne trouve plus rien, le test ci-dessus devient vide."""
    used = keys_used_by_the_page()

    assert {"runs", "live", "unsub", "editions", "totals"} <= used


def test_the_redacted_keys_keep_their_entries():
    """
    Vider un tableau casse la page autant qu'une clé absente : elle fait
    `runs[runs.length-1].ok` et divise par `runs.length`.
    """
    result = public_payload(FULL)

    assert len(result["runs"]) == 1
    assert len(result["unsub"]) == 1


def test_the_redacted_keys_carry_no_private_content():
    result = public_payload(FULL)

    assert "github.com" not in str(result)
    assert "privé" not in str(result)


def test_les_cles_facultatives_sont_toutes_lues_derriere_une_garde():
    """
    L'exemption ne vaut que tant que la garde existe. Sans ce test, ajouter une
    clé à OPTIONAL_KEYS suffirait à faire taire le contrat — et la page
    publique redeviendrait blanche sans que rien ne l'annonce.
    """
    src = TEMPLATE.read_text(encoding="utf-8")
    gardes = {
        "series": "if (!D.series) return;",
        "range": "D.range &&",
        "edition": "if (!E) { carte.hidden = true; return; }",
    }
    for cle in OPTIONAL_KEYS:
        assert cle in gardes, f"{cle} exemptée sans garde déclarée"
        assert gardes[cle] in src, (
            f"D.{cle} est exemptée du contrat public, mais sa garde "
            f"({gardes[cle]!r}) a disparu du gabarit : la page publique "
            f"redeviendra blanche."
        )
