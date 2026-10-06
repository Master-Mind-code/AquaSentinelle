"""Cale les seuils de pluie PRÉVUE de chaque ville sur la même fréquence d'alerte qu'Abidjan.

    python scripts/caler_previsions.py        # met à jour seuils_prevision_24h_mm dans config/seuils_zones.yaml

Les modèles de prévision ne se comportent pas comme CHIRPS : on ne peut pas réutiliser le facteur CHIRPS.
Méthode : prévisions passées (max de 5 modèles, Open-Meteo, 2022-2025). À Abidjan, le seuil orange calibré
(30 mm) donne N jours d'alerte par an. Pour chaque ville, on prend le seuil qui donne le même N (même rareté).
Idem pour le rouge. Les prévisions passées sont mises en cache (data/cache).
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rain_sources import MODELES_PREVISION, OPEN_METEO_HIST_FORECAST  # noqa: E402

CACHE = ROOT / "data" / "cache"
DEBUT, FIN = date(2022, 1, 1), date(2025, 12, 31)
SORTIE = ROOT / "config" / "seuils_zones.yaml"


def previsions_passees(lat: float, lon: float) -> pd.Series:
    f = CACHE / f"prevmax_{lat:.3f}_{lon:.3f}_{DEBUT}_{FIN}.csv"
    if f.exists():
        return pd.read_csv(f, parse_dates=["date"]).set_index("date")["mm"]
    for essai in range(6):
        r = requests.get(OPEN_METEO_HIST_FORECAST, params=dict(
            latitude=lat, longitude=lon, start_date=DEBUT.isoformat(), end_date=FIN.isoformat(),
            daily="precipitation_sum", timezone="Africa/Abidjan", models=",".join(MODELES_PREVISION)), timeout=180)
        if r.status_code != 429:
            break
        time.sleep(30 * (essai + 1))
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({m: d.get(f"precipitation_sum_{m}") for m in MODELES_PREVISION}, index=pd.to_datetime(d["time"]), dtype="float")
    s = df.max(axis=1).rename("mm").dropna()
    CACHE.mkdir(parents=True, exist_ok=True)
    s.rename_axis("date").to_csv(f)
    return s


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))
    zones = {z["id"]: z for z in cfg["zones"]}
    ref_cfg = cfg["seuils_prevision_24h_mm"]
    ref = previsions_passees(zones["abidjan-centre"]["lat"], zones["abidjan-centre"]["lon"])
    ans = len(ref) / 365.25
    freq = {n: (ref >= s).sum() / ans for n, s in ref_cfg.items()}
    print(f"Abidjan : orange {ref_cfg['orange']} mm -> {freq['orange']:.1f} j/an · rouge {ref_cfg['rouge']} mm -> {freq['rouge']:.1f} j/an")
    sortie = yaml.safe_load(SORTIE.read_text(encoding="utf-8")) if SORTIE.exists() else {}
    for zid, z in zones.items():
        if z.get("region") == "District d'Abidjan":
            continue
        p = previsions_passees(z["lat"], z["lon"])
        a = len(p) / 365.25
        seuils = {}
        for n, f in freq.items():
            k = max(1, int(round(f * a)))                   # même nombre de jours d'alerte que le seuil d'Abidjan
            seuils[n] = int(round(float(np.sort(p.values)[-k])))
        seuils["rouge"] = max(seuils["rouge"], seuils["orange"] + 5)
        sortie.setdefault(zid, {})["seuils_prevision_24h_mm"] = seuils
        print(f"  {z['nom']:14s} orange {seuils['orange']:3d} mm · rouge {seuils['rouge']:3d} mm"
              f" (facteur CHIRPS aurait donné {sortie[zid].get('seuils_pluie_24h_mm', {}).get('orange', '?')} / 70 x 30)")
        time.sleep(2)
    entete = ("# Généré par scripts/transposer_seuils.py (pluie observée, CHIRPS) et scripts/caler_previsions.py\n"
              "# (pluie prévue : même fréquence d'alerte qu'Abidjan). NE PAS éditer à la main, relancer les scripts.\n"
              "# Seuils PROVISOIRES hors Abidjan. Les zones absentes utilisent les seuils d'Abidjan (config/zones.yaml).\n")
    SORTIE.write_text(entete + yaml.safe_dump(sortie, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"Écrit : {SORTIE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
