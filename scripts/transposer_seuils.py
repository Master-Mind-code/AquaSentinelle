"""Transpose les seuils de pluie calibrés à Abidjan vers les autres villes, selon leur climat.

    python scripts/transposer_seuils.py [--debut 2018] [--fin 2023]     # écrit config/seuils_zones.yaml

Méthode : même source et même grandeur que les seuils (CHIRPS, maximum sur ~25 km). Pour chaque ville,
quantile 99 % des jours de pluie (≥ 1 mm) sur des années complètes. Seuils de la ville = seuils d'Abidjan
x (P99 ville / P99 Abidjan-centre), rapport borné entre 0,6 et 1,2.
(ERA5 a été écarté : sa maille d'Abidjan déborde sur la lagune et la mer et lisse les orages côtiers.)
Seuils PROVISOIRES hors Abidjan : à vérifier sur les inondations documentées de chaque ville.
Premier lancement : ~650 Ko par jour CHIRPS à télécharger, mis en cache (data/cache).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import rain_sources as rs  # noqa: E402

REFERENCE = "abidjan-centre"
SORTIE = ROOT / "config" / "seuils_zones.yaml"


def indices(lat: float, lon: float) -> tuple[int, int]:
    return int(round((rs.LAT0 - lat) / rs.RES)) - rs.Y0, int(round((lon - rs.LON0) / rs.RES)) - rs.X0


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--debut", type=int, default=2018)
    a.add_argument("--fin", type=int, default=2023)
    a = a.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))
    zones = {z["id"]: z for z in cfg["zones"]}
    jours = [date(a.debut, 1, 1) + timedelta(n) for n in range((date(a.fin, 12, 31) - date(a.debut, 1, 1)).days + 1)]

    series = {zid: [] for zid in zones}
    faits = 0

    def lire(jour):
        return jour, rs._chirps_grid(jour)

    with ThreadPoolExecutor(8) as ex:
        for jour, g in ex.map(lire, jours):
            faits += 1
            if faits % 200 == 0:
                print(f"  {faits}/{len(jours)} jours lus", flush=True)
            if g is None:
                continue
            for zid, z in zones.items():
                y, x = indices(z["lat"], z["lon"])
                series[zid].append(float(np.nanmax(g[y - 2:y + 3, x - 2:x + 3])))

    def p99(v):
        v = np.array(v)
        return float(np.quantile(v[v >= 1], 0.99))

    ref = p99(series[REFERENCE])
    n = len(series[REFERENCE])
    print(f"Référence {REFERENCE} : P99 = {ref:.1f} mm (CHIRPS max ~25 km, {n} jours, {a.debut}-{a.fin})")
    sortie = (yaml.safe_load(SORTIE.read_text(encoding="utf-8")) or {}) if SORTIE.exists() else {}
    for zid, z in zones.items():
        if z.get("region") == "District d'Abidjan":
            continue
        p = p99(series[zid])
        k = min(1.2, max(0.6, p / ref))
        sortie.setdefault(zid, {}).update({    # les seuils de PRÉVISION sont calés à part (caler_previsions.py)
            "facteur": round(k, 2), "p99_chirps_mm": round(p, 1),
            "seuils_pluie_24h_mm": {nv: round(v * k) for nv, v in cfg["seuils_pluie_24h_mm"].items()},
        })
        print(f"  {z['nom']:14s} P99 {p:5.1f} mm · facteur {k:.2f} · orange {sortie[zid]['seuils_pluie_24h_mm']['orange']:>3} mm"
              f" · rouge {sortie[zid]['seuils_pluie_24h_mm']['rouge']:>3} mm")
    entete = ("# Généré par scripts/transposer_seuils.py (pluie observée, CHIRPS) et scripts/caler_previsions.py\n"
              "# (pluie prévue : même fréquence d'alerte qu'Abidjan). NE PAS éditer à la main, relancer les scripts.\n"
              "# Seuils PROVISOIRES hors Abidjan. Les zones absentes utilisent les seuils d'Abidjan (config/zones.yaml).\n")
    SORTIE.write_text(entete + yaml.safe_dump(sortie, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"Écrit : {SORTIE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
