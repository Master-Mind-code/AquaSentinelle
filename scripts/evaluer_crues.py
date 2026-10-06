"""GloFAS voit-il les crues documentées hors d'Abidjan ? (data/events_national.csv)

    python scripts/evaluer_crues.py

Pour chaque crue fluviale datée dans une ville équipée d'une station (config/zones.yaml, clé « riviere ») :
débit maximal de la réanalyse GloFAS entre J-5 et J+2, comparé à la crue annuelle (orange) et à la crue de 5 ans (rouge).
Fausses alertes : nombre d'épisodes par an au-dessus du seuil orange (jours consécutifs = un épisode).
Limite : on teste la réanalyse (le débit reconstitué), pas la prévision disponible à l'époque.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rain_sources import glofas_debit, seuils_de_crue  # noqa: E402


def main() -> None:
    zones = {z["id"]: z for z in yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))["zones"]
             if z.get("riviere")}
    ev = pd.read_csv(ROOT / "data" / "events_national.csv", sep=";", comment="#", header=None,
                     names=["date", "ville", "source", "note"], index_col=False)
    ev["date"] = pd.to_datetime(ev["date"], format="%Y-%m-%d")
    ev = ev[ev["ville"].isin(zones) & ev["note"].str.contains("crue", case=False)]

    detectes = total = 0
    print(f"{'date':10s} {'ville':13s} {'max J-5..J+2':>12s} {'annuel':>7s} {'5 ans':>7s}  verdict   (cours d'eau cité)")
    episodes = {}
    for zid in sorted(set(ev["ville"])):
        r = zones[zid]["riviere"]
        hist = glofas_debit(r["lat"], r["lon"], date(1984, 1, 1), date(2025, 12, 31))
        orange, rouge = seuils_de_crue(hist[hist.index.year <= 2025])
        depasse = hist >= orange
        debuts = depasse & ~depasse.shift(1, fill_value=False)
        episodes[zid] = (debuts.sum() / hist.index.year.nunique(), r["nom"])
        for _, e in ev[ev["ville"] == zid].iterrows():
            fen = hist.loc[e["date"] - timedelta(5): e["date"] + timedelta(2)]
            q = fen.max()
            niveau = "ROUGE" if q >= rouge else "orange" if q >= orange else "raté"
            total += 1
            detectes += niveau != "raté"
            incert = " (date incertaine)" if "incertaine" in e["note"] else ""
            cours = e["note"].split("(")[1].split(")")[0] if "(" in e["note"] else ""
            print(f"{e['date']:%Y-%m-%d} {zid:13s} {q:9.0f} m³/s {orange:7.0f} {rouge:7.0f}  {niveau:8s}  ({cours}){incert}")
    print(f"\nCrues détectées : {detectes}/{total}")
    print("Épisodes au-dessus du seuil orange (fausses alertes possibles, borne haute) :")
    for zid, (n, nom) in episodes.items():
        print(f"  {zones[zid]['nom']:13s} ({nom}) : {n:.1f} épisode(s) par an")


if __name__ == "__main__":
    main()
