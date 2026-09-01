"""
Tableau de bord public — filtrage du payload du dashboard privé.

La newsletter promet à ses lecteurs qu'ils peuvent suivre les chiffres. Cette
route sert donc les mêmes agrégats que `/dashboard`, sans jeton.

Le filtrage est une **liste blanche** et non une liste noire : toute clé ajoutée
plus tard à `scripts/build_dashboard_data.py` est exclue tant qu'elle n'a pas été
explicitement autorisée ici. La confidentialité ne repose ainsi jamais sur le fait
que personne n'enrichira le payload.
"""

# Clés servies publiquement. N'ajouter une entrée qu'après avoir vérifié qu'elle
# ne contient que des agrégats — aucun email_hash, aucune adresse, aucun détail
# par lecteur.
PUBLIC_KEYS: tuple[str, ...] = (
    "generated",       # horodatage de génération
    "editions",        # une ligne par édition : date, ouvertures, cliqueurs
    "current_sent",    # nombre de destinataires de la dernière édition
    "unique_readers",  # compteur de lecteurs distincts
    "by_rank",         # clics par position dans la newsletter
    "by_domain",       # clics par domaine de source
    "by_hour",         # ouvertures par heure
    "loyalty",         # distribution anonyme du nombre d'ouvertures par lecteur
    "unsub_reasons",   # motifs de désinscription, agrégés
    "topics",          # répartition des thèmes couverts
    "totals",          # totaux ouvertures / clics
)

# Champs expurgés de chaque entrée, par clé.
#
# On retire des CHAMPS, jamais les entrées elles-mêmes : dashboard.html indexe
# dans ces tableaux (`runs[runs.length-1].ok`) et divise par leur longueur.
# Un tableau vidé casse la page aussi sûrement qu'une clé absente.
PRIVATE_FIELDS: dict[str, tuple[str, ...]] = {
    # `url` pointe vers github.com/<compte>/<dépôt> — la page ne lit que ok et date
    "runs": ("url",),
    # `text` est le commentaire libre écrit en se désabonnant : il appartient
    # à son auteur. La page ne lit que la longueur du tableau et les motifs.
    "unsub": ("text", "email", "email_hash"),
}

# Champs qui doivent rester présents mais VIDES : la page les parcourt
# (`e.comments.map(...)`), donc les supprimer la planterait, mais leur contenu
# ne doit pas être publié.
EMPTIED_FIELDS: dict[str, tuple[str, ...]] = {
    # Ce qu'un lecteur écrit en bas d'édition s'adresse à l'auteur de la
    # newsletter, pas au public. Sur une trentaine de lecteurs, une phrase
    # reconnaissable suffit à identifier celui qui l'a écrite.
    "editions": ("comments",),
}


def _redact(
    entries,
    private_fields: tuple[str, ...] = (),
    emptied_fields: tuple[str, ...] = (),
) -> list[dict]:
    """
    Conserve chaque entrée, en retirant les champs privés et en vidant ceux
    que la page parcourt mais dont le contenu ne doit pas sortir.
    """
    if not isinstance(entries, list):
        return []
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict):
            cleaned.append({})
            continue
        kept = {k: v for k, v in entry.items() if k not in private_fields}
        for field in emptied_fields:
            if field in kept:
                kept[field] = []
        cleaned.append(kept)
    return cleaned


def public_payload(payload: dict) -> dict:
    """
    Ne conserve que les clés explicitement autorisées, puis neutralise celles
    dont `dashboard.html` a besoin pour fonctionner mais qui ne doivent pas
    être publiées telles quelles.

    `runs` et `unsub` sont **expurgés champ par champ, jamais vidés** : la page
    fait `D.runs.slice()`, `runs[runs.length-1].ok` et divise par `runs.length`.
    Une clé absente comme un tableau vide y lèvent une TypeError qui laisse le
    tableau de bord entièrement blanc.
    """
    public = {key: payload[key] for key in PUBLIC_KEYS if key in payload}

    # Nécessaires au rendu, servis sans leurs champs privés
    public["runs"] = _redact(payload.get("runs", []), PRIVATE_FIELDS["runs"])
    public["unsub"] = _redact(payload.get("unsub", []), PRIVATE_FIELDS["unsub"])
    if "editions" in public:
        public["editions"] = _redact(
            public["editions"], emptied_fields=EMPTIED_FIELDS["editions"]
        )
    # live : le board public est mis en cache 300 s, pas d'auto-rafraîchissement
    public["live"] = False

    return public
