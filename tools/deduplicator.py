"""Déduplication sémantique des articles collectés par similarité TF-IDF."""

import json
import logging
from datetime import date
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent / "logs"


def deduplicate_newsletter_articles(articles: list[dict], threshold: float = 0.60) -> list[dict]:
    """
    Déduplication post-Claude sur les articles synthétisés (Format B : rank/title/flash/sources).
    Double vérification :
    1. URL partagée : deux items citent exactement la même URL source → doublon certain
    2. TF-IDF sur title+flash : similarité sémantique du contenu généré par Claude
    Réassigne les ranks après filtrage pour conserver une numérotation continue.
    """
    if len(articles) < 2:
        return articles

    to_remove: set[int] = set()

    # Passe 1 — URLs partagées entre items (même URL source = même événement)
    url_to_first: dict[str, int] = {}
    for i, art in enumerate(articles):
        for src in art.get("sources", []):
            url = src.get("url", "")
            if not url:
                continue
            if url in url_to_first:
                first = url_to_first[url]
                if i not in to_remove:
                    logger.info(
                        f"Doublon URL post-Claude : '{art['title']}' partage {url} "
                        f"avec '{articles[first]['title']}' → supprimé"
                    )
                    to_remove.add(i)
            else:
                url_to_first[url] = i

    # Passe 2 — Similarité TF-IDF sur title+flash
    remaining = [i for i in range(len(articles)) if i not in to_remove]
    if len(remaining) >= 2:
        texts = [
            f"{articles[i]['title']} {articles[i].get('flash', '')}"
            for i in remaining
        ]
        vectorizer = TfidfVectorizer(strip_accents="unicode", min_df=1)
        tfidf_matrix = vectorizer.fit_transform(texts)
        sim_matrix = cosine_similarity(tfidf_matrix)

        for ri, i in enumerate(remaining):
            if i in to_remove:
                continue
            for rj, j in enumerate(remaining):
                if rj <= ri or j in to_remove:
                    continue
                score = float(sim_matrix[ri, rj])
                if score >= threshold:
                    desc_i = articles[i].get("flash", "")
                    desc_j = articles[j].get("flash", "")
                    keep, drop = (i, j) if len(desc_i) >= len(desc_j) else (j, i)
                    to_remove.add(drop)
                    logger.info(
                        f"Doublon TF-IDF post-Claude (score={score:.2f}) : "
                        f"'{articles[drop]['title']}' supprimé"
                    )

    result = [a for i, a in enumerate(articles) if i not in to_remove]
    # Réassigner les ranks pour garder une numérotation continue
    for new_rank, art in enumerate(result, start=1):
        art["rank"] = new_rank

    if to_remove:
        logger.info(f"Dédup post-Claude : {len(to_remove)} doublon(s) supprimé(s) → {len(result)} articles")
    else:
        logger.info("Dédup post-Claude : 0 doublon détecté")

    return result


def deduplicate_articles(articles: list[dict], threshold: float) -> list[dict]:
    """
    Filtre les articles doublon par similarité TF-IDF sur title + description.
    En cas de doublon, conserve l'article avec la description la plus longue.
    Écrit le rapport dans logs/dedup_YYYY-MM-DD.json (écrase si plusieurs runs/jour).

    Note : algorithme greedy single-pass — des paires transitives impliquant un
    article déjà supprimé peuvent être manquées. Acceptable pour un corpus ≤ 50 articles.
    """
    if len(articles) < 2:
        _write_log(total=len(articles), removed=0, pairs=[])
        return articles

    texts = [f"{a['title']} {a.get('description', '')} {a.get('source', '')}" for a in articles]
    vectorizer = TfidfVectorizer(strip_accents="unicode", min_df=1)
    tfidf_matrix = vectorizer.fit_transform(texts)
    sim_matrix = cosine_similarity(tfidf_matrix)

    to_remove: set[int] = set()
    pairs: list[dict] = []

    for i in range(len(articles)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(articles)):
            if j in to_remove:
                continue
            score = float(sim_matrix[i, j])
            # Seuil abaissé de 30% pour deux articles du même domaine
            same_domain = articles[i].get("source") == articles[j].get("source")
            effective_threshold = threshold * 0.7 if same_domain else threshold
            if score >= effective_threshold:
                desc_i = articles[i].get("description", "")
                desc_j = articles[j].get("description", "")
                keep, drop = (i, j) if len(desc_i) >= len(desc_j) else (j, i)
                to_remove.add(drop)
                pairs.append({
                    "article_a": articles[i]["title"],
                    "article_b": articles[j]["title"],
                    "score": round(score, 4),
                    "kept": articles[keep]["title"],
                })

    deduplicated = [a for idx, a in enumerate(articles) if idx not in to_remove]
    _write_log(total=len(articles), removed=len(to_remove), pairs=pairs)
    return deduplicated


def _write_log(total: int, removed: int, pairs: list[dict]) -> None:
    if removed == 0:
        logger.info(f"Déduplication : 0 doublon détecté sur {total} articles collectés")
    else:
        logger.info(
            f"Déduplication : {removed} doublon(s) supprimé(s) sur {total} articles "
            f"→ {total - removed} conservé(s)"
        )

    today_str = date.today().strftime("%Y-%m-%d")
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGS_DIR / f"dedup_{today_str}.json"
    log_data = {
        "date": today_str,
        "total_articles": total,
        "duplicates_removed": removed,
        "articles_kept": total - removed,
        "pairs": pairs,
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Log déduplication : {log_path}")
