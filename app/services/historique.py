"""Inondations documentées (data/events.csv et data/events_national.csv), regroupées par zone surveillée."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from app.settings import ROOT, config_zones


@lru_cache
def par_zone() -> dict[str, dict]:
    zones = {z["id"] for z in config_zones()["zones"]}
    morceaux = []
    for f in ("events.csv", "events_national.csv"):
        chemin = ROOT / "data" / f
        if chemin.exists():
            morceaux.append(pd.read_csv(chemin, sep=";", comment="#", header=None, index_col=False,
                                        names=["date", "zone", "source", "note"]))
    if not morceaux:
        return {}
    ev = pd.concat(morceaux)
    ev = ev[ev["zone"].isin(zones)]
    sortie = {}
    for zone, g in ev.groupby("zone"):
        g = g.sort_values("date")
        sortie[zone] = {"nombre": len(g), "derniere": g["date"].iloc[-1],
                        "liste": [{"date": d, "note": str(n).split(" - ")[0][:120]} for d, n in zip(g["date"], g["note"])][-5:]}
    return sortie
