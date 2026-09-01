#!/usr/bin/env python3
"""
Agrège l'historique d'engagement de la newsletter dans data/dashboard.json.

Ce fichier est la partie « lourde » du dashboard : 100+ éditions, ~900 titres,
assiduité des lecteurs, historique des runs CI. Il est régénéré par la CI après
chaque envoi. Les chiffres du jour, eux, sont lus en direct par auth_server
(voir auth_server/dashboard.py) — ils ne passent pas par ce fichier.

Usage :
    python scripts/build_dashboard_data.py [--output data/dashboard.json]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tomllib
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CONFIG_TOPICS = ["technologie", "science", "business", "monde", "santé"]


# ---------------------------------------------------------------------------
# Lecture des CSV d'interaction
# ---------------------------------------------------------------------------

def _rows(pattern: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted((ROOT / "data").glob(pattern)):
        with open(path, newline="", encoding="utf-8") as f:
            out.extend(csv.DictReader(f))
    return out


# ---------------------------------------------------------------------------
# Nombre de destinataires par édition
# ---------------------------------------------------------------------------

def _toml_versions(rel_path: str) -> list[tuple[str, dict]]:
    """Historique d'un TOML versionné, du plus ancien au plus récent.

    Renvoie [] si l'historique git est indisponible (checkout superficiel en CI).
    """
    try:
        log = subprocess.run(
            ["git", "log", "--format=%H|%aI", "--", rel_path],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if log.returncode != 0:
        return []

    versions: list[tuple[str, dict]] = []
    for line in log.stdout.strip().splitlines():
        sha, iso = line.split("|")
        blob = subprocess.run(["git", "show", f"{sha}:{rel_path}"],
                              capture_output=True, cwd=ROOT)
        if blob.returncode != 0:
            continue
        try:
            versions.append((iso, tomllib.loads(blob.stdout.decode("utf-8"))))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
    return sorted(versions, key=lambda t: t[0])


def _emails_at(versions, date: str, key: str) -> set[str]:
    cutoff = date + "T23:59:59Z"
    best = None
    for stamp, data in versions:
        if stamp <= cutoff:
            best = data
        else:
            break
    if best is None:
        best = versions[0][1] if versions else {}
    return {e.strip().lower() for e in best.get(key, {}).get("emails", []) if e.strip()}


def _current_active_count() -> int:
    def emails(path: Path, key: str) -> set[str]:
        if not path.exists():
            return set()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return {e.strip().lower() for e in data.get(key, {}).get("emails", []) if e.strip()}

    recipients = emails(ROOT / "config" / "recipients.toml", "recipients")
    unsubscribed = emails(ROOT / "config" / "unsubscribed.toml", "unsubscribed")
    return len(recipients - unsubscribed)


# ---------------------------------------------------------------------------
# Reconstitution des thèmes à partir des titres
#
# Le pipeline demande un `topic` au modèle (agent.py) mais data.json n'archive
# que rank + title : ce classement est une approximation, pas une mesure.
# Dès que le thème sera archivé, remplacer cette heuristique par la vraie valeur.
# ---------------------------------------------------------------------------

LEXICON = {
 "technologie": """ia intelligence-artificiel chatgpt openai anthropic claude gemini google appl microsoft
   meta amazon nvidia smartphone iphone android applicati logiciel algorithm puce processeur quantiq cyber
   pirat hacker piratag numeriq internet reseaux-sociaux tiktok twitter instagram snapchat robot drone tesla
   spacex startup tech ordinateur console jeu-video jeux-video streaming netflix spotify telephon 5g satellit
   crypto bitcoin blockchain voiture-electriq batteri semi-conducteur cloud serveur bug faille informatiq
   donnees-personnelles rgpd deepfake chatbot open-source silicon wifi bluetooth usb ecran casque vr""",
 "science": """recherch chercheu etude-scientifiq scientifiq espace nasa esa fusee mars lune astronom telescope
   planet galaxi astronaut fossil dinosaur archeolog decouvert physiq chimi biologi genom adn genetiq
   particul laboratoir experienc theorem mathemat neurosc paleonto meteorit asteroid orbit sonde
   antarctiq arctiq banquis glacier volcan seism eruption ocean-profond espece biodiversit""",
 "business": """bourse cac40 cac nasdaq dow-jones action marche marches economi entrepris pdg ceo benefic
   chiffre-affaires croissanc recession inflation taux-directeur bce fed banqu rachat fusion acquisition
   licenciement emploi chomage salair impot budget dett milliard million euro dollar investisseu fonds
   levee-de-fonds ipo introduction-en-bourse societe-general bnp lvmh total carrefour renault airbus boeing
   petrol gaz-naturel prix consommat commerc export import industri usine patronat syndicat greve-des
   trimestr resultat dividend capitalisation macro obligata immobilier assurance mutuell retrait pension
   pouvoir-achat facture tarif fiscal taxe douan""",
 "monde": """guerre conflit arme militair soldat frapp missil bombard ukrain russi poutin zelensky gaza israel
   palestin hamas hezbollah iran teheran chine pekin xi-jinping etats-unis washington trump biden harris
   europ bruxelles otan onu unesco diplomat sanction ambassad president election vote referendum parlement
   ministr gouvernement geopolit frontier refugi migrant coup-etat manifestation coree seoul pyongyang canada
   afriqu inde bresil mexiqu japon tokyo allemagne berlin royaume-uni londres italie espagne turquie erdogan
   syrie liban yemen soudan haiti venezuela cuba taiwan otage cessez-le-feu traite sommet g7 g20 brics
   assemblee senat elysee matignon macron""",
 "santé": """sante hopita medecin patient malad virus epidemi pandemi covid grippe vaccin cancer tumeur diabet
   alzheimer parkinson traitement medicament essai-cliniq oms sanitair soignant infirmi mortalit deces
   contamination symptom depistag nutrition obesit mental depression addiction tabac alcool sommeil ehpad
   secu securite-social ars pharmaci antibiotiq chirurgi greffe fertilit grossesse pediatr psychiatr
   autism handicap canicul-sante allergi""",
 "sport": """mbappe lloris deschamps bleus equipe-de-france mondial coupe-du-monde fifa uefa ligue1 ligue-1
   psg om olympique-lyonnais real-madrid barcelone champions-league football foot rugby tennis roland-garros
   wimbledon jo olympiq medaille athlet nba basket cyclism tour-de-france formule1 formule-1 f1 grand-prix
   match victoire defaite finale champion sacre podium buteur selectionneu joueur entraineur transfert stade
   supporter handball natation ski biathlon""",
 "société": """fait-divers meurtre crime proces justice tribunal condamn juge police gendarm enquete garde-a-vue
   prison detenu victime agression vol cambriolag incendi accident collision autoroute drame disparition
   ecole lycee college universit bac professeu eleve etudiant education harcelement religion laicit
   discrimination violence-conjugal feminicid manifestant syndicat greve transport sncf ratp greve-sncf
   logement loyer squat pauvret precarit associati benevol""",
 "environnement": """climat rechauffement carbone co2 emission pollution particule-fine plastique dechet recyclag
   biodiversit deforestation amazoni espece-menacee ours abeille pesticide glyphosate agricultur agriculteu
   vendange secheresse canicul inondation orage tempet tornade ouragan cyclone meteo meteo-france alerte-orange
   alerte-rouge incendie-de-foret feu-de-foret energie-renouvelabl eolien solair centrale-nucleaire
   energie-nucleaire dechet-nucleaire barrage eau potable transition-ecolog cop28 cop29 cop30 giec""",
}
LEXICON = {k: v.split() for k, v in LEXICON.items()}

# À score égal, le thème le plus spécifique l'emporte.
TOPIC_PRIORITY = ["sport", "santé", "environnement", "science",
                  "technologie", "business", "société", "monde"]


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def classify_title(title: str) -> str | None:
    text = _strip_accents(title)
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text)
    flat = text.replace("-", " ")

    scores = {}
    for topic, lexemes in LEXICON.items():
        hits = 0
        for lexeme in lexemes:
            if "-" in lexeme:
                hits += lexeme.replace("-", " ") in flat
            else:
                hits += any(w.startswith(lexeme) for w in words)
        scores[topic] = hits

    best = max(scores.values())
    if best == 0:
        return None
    winners = [t for t, s in scores.items() if s == best]
    return sorted(winners, key=TOPIC_PRIORITY.index)[0]


# ---------------------------------------------------------------------------
# Historique des runs GitHub Actions
# ---------------------------------------------------------------------------

def _fetch_runs(limit: int = 40) -> list[dict]:
    """Historique du workflow via l'API GitHub. Silencieux si indisponible."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    repo = os.getenv("GITHUB_REPOSITORY") or os.getenv("GITHUB_REPO") or ""
    if not token or not repo:
        return []
    try:
        import requests
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/actions/workflows/newsletter.yml/runs",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            params={"per_page": limit}, timeout=15,
        )
        resp.raise_for_status()
        return [
            {"date": r["created_at"][:10], "at": r["created_at"][11:16],
             "ok": r["conclusion"] == "success", "event": r["event"], "url": r["html_url"]}
            for r in resp.json().get("workflow_runs", [])
            if r["conclusion"] is not None
        ]
    except Exception as exc:  # noqa: BLE001 — l'historique CI est facultatif
        print(f"  runs CI indisponibles ({exc})", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def build_series(*, clicks: list[dict], opens: list[dict],
                 topics_by_date: list[tuple[str, str | None]]) -> dict:
    """
    Publie les mesures en gardant leur date, pour que le navigateur puisse les
    recalculer sur une période choisie.

    Le constructeur agrégeait tout sur l'historique complet : `by_rank` était
    un total unique, `loyalty` une liste de comptes. Les sources brutes
    portaient pourtant une date — c'est l'agrégation qui l'écrasait, et avec
    elle toute possibilité de filtrer.

    ⚠️ Un lecteur est désigné par un **indice**, jamais par son hash. Ces
    séries sont candidates à `/board`, et un hash stable y serait un
    identifiant — exactement ce que le projet a retiré de ses fichiers.
    """
    series_clics = []
    for r in clicks:
        try:
            rang = int(r["article_rank"])
        except (KeyError, ValueError, TypeError):
            # Une ligne abîmée ne doit pas priver le tableau de bord de tout
            # l'historique : on la saute, le reste passe.
            continue
        netloc = urlparse(r.get("target_url", "")).netloc.replace("www.", "")
        series_clics.append([r["send_date"], rang, netloc])

    # L'indice est attribué à la première apparition et ne bouge plus : sans
    # cela, un même lecteur compterait pour deux dans la fidélité recalculée.
    indices: dict[str, int] = {}
    par_date: dict[str, list[int]] = defaultdict(list)
    for r in opens:
        h = r["email_hash"]
        if h not in indices:
            indices[h] = len(indices)
        par_date[r["send_date"]].append(indices[h])

    themes: dict[str, Counter] = defaultdict(Counter)
    for date, topic in topics_by_date:
        themes[date][topic or "indéterminé"] += 1

    return {
        "clicks": series_clics,
        "opens": {d: sorted(set(v)) for d, v in sorted(par_date.items())},
        "topics": {d: dict(c) for d, c in sorted(themes.items())},
        "readers": len(indices),
    }


def build(previous: dict | None = None) -> dict:
    previous = previous or {}
    known_sent = {e["date"]: e["sent"] for e in previous.get("editions", []) if e.get("sent")}

    opens    = _rows("opens_*.csv")
    clicks   = _rows("clicks_*.csv")
    feedback = _rows("feedback_*.csv")
    reacts   = _rows("reactions_*.csv")

    rec_versions = _toml_versions("config/recipients.toml")
    uns_versions = _toml_versions("config/unsubscribed.toml")
    fallback_sent = _current_active_count()

    def sent_on(date: str) -> int:
        if date in known_sent:
            return known_sent[date]
        if rec_versions:
            return len(_emails_at(rec_versions, date, "recipients")
                       - _emails_at(uns_versions, date, "unsubscribed"))
        return fallback_sent

    dates = sorted({r["send_date"] for r in opens + clicks + feedback + reacts})
    editions = []
    for d in dates:
        o  = [r for r in opens    if r["send_date"] == d]
        c  = [r for r in clicks   if r["send_date"] == d]
        fb = [r for r in feedback if r["send_date"] == d]
        rc = [r for r in reacts   if r["send_date"] == d]
        editions.append({
            "date": d,
            "sent": sent_on(d),
            "opens": len({r["email_hash"] for r in o}),
            "clicks": len(c),
            "clickers": len({r["email_hash"] for r in c}),
            "like":    sum(1 for r in fb if r.get("global_reaction") == "like"),
            "meh":     sum(1 for r in fb if r.get("global_reaction") == "meh"),
            "dislike": sum(1 for r in fb if r.get("global_reaction") == "dislike"),
            "comments": [r["comment"] for r in fb if r.get("comment", "").strip()],
            "art_reactions": len(rc),
        })

    by_rank, by_domain = Counter(), Counter()
    for r in clicks:
        by_rank[int(r["article_rank"])] += 1
        netloc = urlparse(r["target_url"]).netloc.replace("www.", "")
        if netloc:
            by_domain[netloc] += 1

    by_hour = Counter(int(r["timestamp"][11:13]) for r in opens)

    per_reader = defaultdict(set)
    for r in opens:
        per_reader[r["email_hash"]].add(r["send_date"])
    loyalty = sorted((len(v) for v in per_reader.values()), reverse=True)

    unsub, reasons = [], Counter()
    reasons_path = ROOT / "data" / "unsubscribe_reasons.csv"
    if reasons_path.exists():
        with open(reasons_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                unsub.append({"date": r["timestamp"][:10], "reason": r["reasons"],
                              "text": r.get("free_text", "")})
                for part in r["reasons"].split(","):
                    if part.strip():
                        reasons[part.strip()] += 1

    # Thèmes
    topic_rows, monthly = [], defaultdict(Counter)
    topics_dated: list[tuple[str, str | None]] = []
    archive = sorted(glob.glob(str(ROOT / "output" / "newsletter" / "*" / "data.json")))
    archived_editions = len(archive)
    for path in archive:
        date = Path(path).parent.name
        # Une archive illisible — conflit git non résolu, écriture tronquée —
        # ne doit pas emporter tout le rebuild : l'édition est ignorée et
        # signalée, les autres restent comptées.
        try:
            with open(path, encoding="utf-8") as f:
                articles = json.load(f).get("articles", [])
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] archive ignorée — {path} : {exc}", file=sys.stderr)
            archived_editions -= 1
            continue
        for a in articles:
            # Si le pipeline archive un jour le thème, il fait autorité.
            topic = a.get("topic") or classify_title(a["title"])
            topic_rows.append(topic)
            topics_dated.append((date, topic))
            monthly[date[:7]][topic or "indéterminé"] += 1

    # Si l'API Actions est indisponible, on conserve l'historique déjà connu
    # plutôt que de le remplacer par une liste vide.
    runs = _fetch_runs() or previous.get("runs", [])

    topic_counts = Counter(t or "indéterminé" for t in topic_rows)
    months = []
    for m in sorted(monthly):
        total = sum(monthly[m].values())
        months.append({
            "m": m, "tot": total,
            "hors": sum(v for k, v in monthly[m].items()
                        if k not in CONFIG_TOPICS and k != "indéterminé"),
            "sport": monthly[m]["sport"],
        })

    # Séries datées : elles doublent les agrégats ci-dessous plutôt que de les
    # remplacer. Le tableau de bord actuel continue de lire les totaux ; le
    # nouveau recalcule sur la période choisie. Les deux doivent concorder —
    # tests/test_dashboard_series.py tient l'invariant.
    series = build_series(clicks=clicks, opens=opens, topics_by_date=topics_dated)

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": series,
        "editions": editions,
        "current_sent": fallback_sent,
        "by_rank": {str(k): v for k, v in sorted(by_rank.items())},
        "by_domain": dict(by_domain.most_common()),
        "by_hour": {str(h): by_hour.get(h, 0) for h in range(24)},
        "loyalty": loyalty,
        "unique_readers": len(per_reader),
        "unsub": unsub,
        "unsub_reasons": dict(reasons.most_common()),
        "runs": runs,
        "topics": {
            "config": CONFIG_TOPICS,
            "counts": dict(topic_counts.most_common()),
            "total": len(topic_rows),
            "editions": archived_editions,
            "monthly": months,
        },
        "totals": {
            "editions": len(dates),
            "opens": sum(e["opens"] for e in editions),
            "clicks": len(clicks),
            "feedback": len(feedback),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/dashboard.json")
    args = parser.parse_args()

    out_path = ROOT / args.output
    previous = None
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("dashboard.json existant illisible — reconstruction complète", file=sys.stderr)

    payload = build(previous)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")

    print(f"{args.output} — {len(payload['editions'])} éditions, "
          f"{payload['topics']['total']} articles, "
          f"{len(payload['runs'])} runs, {out_path.stat().st_size} octets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
