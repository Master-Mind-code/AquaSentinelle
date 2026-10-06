"""Seuils de crue de chaque station de rivière, à partir de 40 ans de débits GloFAS (1984 à l'an dernier).

    python scripts/calibrer_rivieres.py            # calcule et enregistre dans la base
    python scripts/calibrer_rivieres.py --chercher # cherche aussi la cellule du fleuve autour de chaque ville

Orange = crue annuelle (quantile 20 % des maxima annuels, ~4 années sur 5), rouge = crue de 5 ans (rare).
GloFAS est un MODÈLE hydrologique : les barrages (Kossou, Taabo, Buyo, Soubré) ne sont que partiellement
représentés. À confronter aux crues documentées et, si possible, aux stations de la Direction de l'Hydraulique.
"""
from __future__ import annotations

import statistics
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import transaction  # noqa: E402
from app.initialisation import initialiser  # noqa: E402
from app.settings import config_zones  # noqa: E402
from src.rain_sources import OPEN_METEO_FLOOD, glofas_debit, seuils_de_crue  # noqa: E402


def cellule_du_fleuve(lat: float, lon: float, rayon: int = 3, pas: float = 0.05) -> tuple[float, float, float]:
    """Cellule de plus fort débit moyen autour du point (le lit du fleuve), (lat, lon, débit moyen)."""
    pts = [(round(lat + i * pas, 3), round(lon + j * pas, 3)) for i in range(-rayon, rayon + 1) for j in range(-rayon, rayon + 1)]
    r = requests.get(OPEN_METEO_FLOOD, params=dict(
        latitude=",".join(str(p[0]) for p in pts), longitude=",".join(str(p[1]) for p in pts),
        daily="river_discharge", start_date="2020-01-01", end_date="2024-12-31"), timeout=180)
    r.raise_for_status()
    best = max(((statistics.mean([v for v in d["daily"]["river_discharge"] if v is not None] or [0]),
                 d["latitude"], d["longitude"]) for d in r.json()))
    return best[1], best[2], best[0]


def main() -> None:
    initialiser()
    for z in config_zones()["zones"]:
        if not z.get("riviere"):
            continue
        riv = z["riviere"]
        if "--chercher" in sys.argv:
            la, lo, m = cellule_du_fleuve(z["lat"], z["lon"])
            print(f"{z['nom']:14s} cellule du fleuve : ({la}, {lo}), débit moyen {m:.0f} m³/s (config : {riv['lat']}, {riv['lon']})")
        hist = glofas_debit(riv["lat"], riv["lon"], date(1984, 1, 1), date(date.today().year - 1, 12, 31))
        orange, rouge = seuils_de_crue(hist)
        with transaction() as cx:
            cx.execute(text("UPDATE riviere SET seuil_orange = :o, seuil_rouge = :r, calibre_le = now() WHERE zone_id = :z"),
                       {"o": orange, "r": rouge, "z": z["id"]})
        print(f"{z['nom']:14s} {riv['nom']:28s} {hist.index[0].year}-{hist.index[-1].year} · moyenne {hist.mean():7.0f} m³/s"
              f" · orange (crue annuelle) {orange:7.0f} · rouge (5 ans) {rouge:7.0f} m³/s")


if __name__ == "__main__":
    main()
