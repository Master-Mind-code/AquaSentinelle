"""S35 : les caniveaux bouchés améliorent-ils l'alerte ? Évaluation AVEC et SANS la variable « caniveaux ».

    python scripts/evaluer_caniveaux.py [--majoration 0.15]

Pour chaque zone et chaque jour où la base contient une pluie observée (CHIRPS) ET un état de caniveaux
connu ce jour-là (dernière observation validée de chaque point, de moins de 30 jours à cette date),
on calcule le niveau avec et sans majoration et on compare aux événements de data/events.csv.
Il faut une saison de relevés de terrain pour conclure : le script le dit quand les données manquent.
Un résultat nul (« pas de différence ») est un résultat valable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import transaction  # noqa: E402
from app.settings import config_zones  # noqa: E402
from src.evaluation import charger_evenements  # noqa: E402
from src.risk import ORANGE, ROUGE, score  # noqa: E402


def jours_avec_caniveaux(cx) -> pd.DataFrame:
    return pd.DataFrame(cx.execute(text("""
        SELECT m.zone_id, m.jour, m.pluie_mm,
          (SELECT avg((o.classe = 'bouche')::int) FROM point_controle p
           JOIN LATERAL (SELECT classe, recu_le FROM observation
                         WHERE point_id = p.id AND statut = 'valide' AND recu_le < m.jour + 1
                         ORDER BY recu_le DESC LIMIT 1) o ON true
           WHERE p.zone_id = m.zone_id AND o.recu_le > m.jour - 30) AS part_bouches
        FROM mesure_pluie m WHERE m.source = 'chirps_max'
    """)).mappings().all())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--majoration", type=float, default=0.15)
    a = p.parse_args()
    seuils = config_zones()["seuils_pluie_24h_mm"]
    with transaction() as cx:
        df = jours_avec_caniveaux(cx)
    if df.empty or df["part_bouches"].notna().sum() == 0:
        print("Données insuffisantes : aucun jour ne réunit une pluie CHIRPS et un état de caniveaux validé.")
        print("Il faut des relevés de terrain réguliers pendant une saison des pluies (étapes 3 et 4), puis relancer.")
        return
    df = df.dropna(subset=["part_bouches"])
    ev = charger_evenements()
    ev = ev[~ev["incertaine"]]

    def evenement(zone: str, jour) -> bool:
        j = pd.Timestamp(jour)
        return any(abs((j - d).days) <= 1 and (z == zone or z == "abidjan-centre") for d, z in zip(ev["date"], ev["zone"]))

    lignes = []
    for _, r in df.iterrows():
        sans = score(r.pluie_mm, seuils).niveau
        avec = score(r.pluie_mm, seuils, r.part_bouches, a.majoration).niveau
        lignes.append({"evenement": evenement(r.zone_id, r.jour), "sans": sans in (ORANGE, ROUGE),
                       "avec": avec in (ORANGE, ROUGE), "rouge_sans": sans == ROUGE, "rouge_avec": avec == ROUGE})
    t = pd.DataFrame(lignes)
    print(f"{len(t)} jours-zones évaluables, {int(t['evenement'].sum())} avec événement documenté\n")
    for nom in ("sans", "avec"):
        d = t[nom]
        print(f"{nom.upper():5s} caniveaux : événements détectés {int((d & t.evenement).sum())}/{int(t.evenement.sum())}"
              f" · jours d'alerte {int(d.sum())} · fausses alertes {int((d & ~t.evenement).sum())}")
    print("\nConclure seulement avec assez d'événements ; un écart d'un ou deux n'est pas significatif.")


if __name__ == "__main__":
    main()
