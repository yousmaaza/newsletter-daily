"""
Détail d'une édition : ouvertures, clics et réactions, article par article.

Ce calcul vivait dans le corps de la route /stats. Il en est extrait pour être
partagé avec /dashboard — tant qu'il restait là, il n'était ni réutilisable ni
testable sans réseau.

Les accès à GitHub restent chez l'appelant : cette fonction ne voit que des
lignes déjà chargées, ce qui la rend vérifiable ligne à ligne.
"""

# Pondération des signaux. Un clic vaut davantage qu'un pouce levé au repos :
# il demande de quitter l'email. Un « mitigé » compte quand même — c'est un
# lecteur qui a pris la peine de répondre.
POIDS_CLIC = 2
POIDS_LIKE = 3
POIDS_MEH = 1


def build_detail(*, send_date: str, sent: int, opens: list[dict],
                 reactions: list[dict], clicks: list[dict],
                 feedbacks: list[dict], articles: list[dict]) -> dict:
    """Agrège une édition. Aucun accès réseau, aucune dépendance à Flask."""
    def uniques(rows: list[dict]) -> int:
        return len({r.get("email_hash") for r in rows if r.get("email_hash")})

    def compte(rows: list[dict], champ: str, valeur: str) -> int:
        return sum(1 for r in rows if r.get(champ) == valeur)

    titres = {a["rank"]: a.get("title") or f"Article #{a['rank']}" for a in articles}

    # Un rang qui porte un signal sans figurer dans l'archive apparaît quand
    # même : l'archive a déjà manqué, et perdre un clic serait pire que
    # d'afficher un titre générique.
    rangs = sorted(
        {int(r["article_rank"]) for r in list(reactions) + list(clicks)
         if str(r.get("article_rank", "")).strip().isdigit()}
        | set(titres)
    )

    par_article = []
    for rang in rangs:
        cle = str(rang)
        c = [x for x in clicks if str(x.get("article_rank")) == cle]
        r = [x for x in reactions if str(x.get("article_rank")) == cle]
        likes = compte(r, "reaction", "like")
        mehs = compte(r, "reaction", "meh")
        dislikes = compte(r, "reaction", "dislike")
        score = round(
            (len(c) * POIDS_CLIC + likes * POIDS_LIKE + mehs * POIDS_MEH)
            / max(sent, 1) * 100, 1
        )
        par_article.append({
            "rank": rang,
            "title": titres.get(rang, f"Article #{rang}"),
            "clicks": len(c),
            "likes": likes, "mehs": mehs, "dislikes": dislikes,
            "score": score,
        })

    # Score décroissant, puis rang croissant : sans le second critère, l'ordre
    # des articles sans signal dépendrait de l'implémentation du tri.
    par_article.sort(key=lambda a: (-a["score"], a["rank"]))

    return {
        "date": send_date,
        "sent": sent,
        "opens": uniques(opens),
        "clickers": uniques(clicks),
        "reactors": uniques(feedbacks),
        "global": {
            "like": compte(feedbacks, "global_reaction", "like"),
            "meh": compte(feedbacks, "global_reaction", "meh"),
            "dislike": compte(feedbacks, "global_reaction", "dislike"),
        },
        "comments": [f["comment"].strip() for f in feedbacks
                     if (f.get("comment") or "").strip()],
        "articles": par_article,
    }
