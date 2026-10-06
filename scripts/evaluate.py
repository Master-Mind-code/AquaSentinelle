"""Évalue les seuils de pluie sur les événements documentés (data/events.csv).

Exemples :
    python scripts/evaluate.py                     # utilise les rejeux déjà enregistrés
    python scripts/evaluate.py --fetch             # télécharge d'abord les mois des événements non couverts
    python scripts/evaluate.py --sans-incertains   # ignore les événements dont la date est incertaine
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.evaluation import RESULTS, balayage, charger_evenements, charger_pluie  # noqa: E402

COLONNES = {
    "chirps_max_mm": "CHIRPS, maximum sur ~25 km",
    "chirps_mm": "CHIRPS, maille centrale",
    "openmeteo_mm": "Open-Meteo (réanalyse)",
    "prevision_max_mm": "Prévision courte échéance, max de 5 modèles",
}


def mois_manquants(zone: str, dates) -> list[tuple[date, date]]:
    try:
        couverts = set(charger_pluie(zone).dropna(subset=["chirps_mm"]).index)
    except FileNotFoundError:
        couverts = set()
    mois = sorted({(d.year, d.month) for d in dates if d not in couverts})
    return [(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])) for y, m in mois]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--zone", default="abidjan-centre", help="série de pluie utilisée (échelle district)")
    p.add_argument("--tolerance", type=int, default=1, help="décalage toléré en jours")
    p.add_argument("--fetch", action="store_true", help="rejouer les mois des événements non couverts")
    p.add_argument("--sans-incertains", action="store_true")
    a = p.parse_args()

    ev = charger_evenements()
    if a.sans_incertains:
        ev = ev[~ev["incertaine"]]
    dates = sorted(set(ev["date"]))

    if a.fetch:
        from replay import rejouer
        for debut, fin in mois_manquants(a.zone, dates):
            print(f"Rejeu {debut:%Y-%m} ...", flush=True)
            rejouer(a.zone, debut, fin)

    pluie = charger_pluie(a.zone)
    print(f"Événements retenus : {len(dates)} | jours de pluie disponibles : {len(pluie)} "
          f"| tolérance ± {a.tolerance} j\n")

    seuils = list(range(30, 160, 10))
    sorties = []
    for col, libelle in COLONNES.items():
        if col not in pluie or pluie[col].isna().all():
            print(f"== {libelle} : pas de données (relancer les rejeux) ==\n")
            continue
        t = balayage(pluie[col], dates, seuils, a.tolerance)
        print(f"== {libelle} ==")
        print(t.to_string(index=False), "\n")
        sorties.append(t.assign(source=col))

    nc = [d.date() for d in dates if d not in set(pluie["chirps_mm"].dropna().index)]
    if nc:
        print(f"Événements sans données de pluie ({len(nc)}) : {', '.join(map(str, nc))}"
              " -> relancer avec --fetch")
    f = RESULTS / f"evaluation_{a.zone}.csv"
    pd.concat(sorties).to_csv(f, index=False)
    print(f"\nTableau complet : {f.relative_to(ROOT)}")
    print("Rappel : la liste d'événements est incomplète, le taux de fausses alertes est une borne haute.")


if __name__ == "__main__":
    main()
