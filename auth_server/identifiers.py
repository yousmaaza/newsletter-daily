"""
Reconnaissance des anciens identifiants réversibles, côté serveur.

Jusqu'au 26 août 2026, un lecteur était identifié par `sha256(email)` NON
SALÉ : avec la liste d'abonnés en main, l'identifiant se retournait par simple
comparaison. Les données ont été migrées vers des identifiants opaques.

Mais la migration ne pouvait pas fermer le robinet : **les éditions déjà
distribuées portent l'ancien identifiant dans leurs URL de pixel et de clic**,
et restent dans les boîtes des lecteurs pendant des mois. Chaque ouverture
d'une ancienne édition réintroduisait une donnée ré-identifiable — constaté le
26 août à 13:49, après la migration.

Le serveur refuse donc de les enregistrer. La ligne est conservée, pour que les
volumes publiés sur /board restent justes, mais elle devient anonyme.

La distinction est nette : les identifiants opaques font 32 caractères
hexadécimaux (`secrets.token_hex(16)`), les anciens hashs en font 64.
"""

import re

LEGACY_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

# Remplace un ancien identifiant : la mesure est comptée, la personne inconnue.
LEGACY_MARKER = "legacy"


def is_legacy_identifier(value: str) -> bool:
    """Vrai si la valeur a le format de l'ancien SHA-256 non salé."""
    return bool(value) and bool(LEGACY_PATTERN.match(value.strip()))


def normalise_identifier(value: str) -> str:
    """
    Identifiant à enregistrer.

    Un ancien hash devient `legacy` — la ligne compte toujours dans les
    volumes, mais ne désigne plus personne. Tout le reste passe inchangé.
    """
    cleaned = (value or "").strip()
    return LEGACY_MARKER if is_legacy_identifier(cleaned) else cleaned
