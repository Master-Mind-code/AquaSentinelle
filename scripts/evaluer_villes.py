"""Les seuils de pluie transposés détectent-ils les inondations urbaines documentées hors d'Abidjan ?

    python scripts/evaluer_villes.py

Pour chaque inondation par pluie (data/events_national.csv) dans une ville surveillée : pluie CHIRPS
(maximum sur ~25 km) de J-1 et J, comparée aux seuils de la ville (config/seuils_zones.yaml) ET à ceux
d'Abidjan, pour voir si la transposition aide. Les jours CHIRPS manquants sont téléchargés (cache).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import rain_sources as rs  # noqa: E402


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))
    zones = {z["id"]: z for z in cfg["zones"]}
    f = ROOT / "config" / "seuils_zones.yaml"
    transposes = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
    abidjan = cfg["seuils_pluie_24h_mm"]["orange"]
    ev = pd.read_csv(ROOT / "data" / "events_national.csv", sep=";", comment="#", header=None,
                     names=["date", "ville", "source", "note"], index_col=False)
    ev["date"] = pd.to_datetime(ev["date"], format="%Y-%m-%d")
    ev = ev[ev["ville"].isin(zones) & ev["note"].str.startswith("pluie")]

    print(f"{'date':10s} {'ville':13s} {'CHIRPS J-1/J':>13s} {'seuil ville':>11s} {'seuil Abidjan':>13s}")
    det_ville = det_abj = 0
    for _, e in ev.iterrows():
        z = zones[e["ville"]]
        vals = [rs.chirps_point((e["date"] - timedelta(d)).date(), z["lat"], z["lon"]) for d in (1, 0)]
        mm = max((v[1] for v in vals if v), default=float("nan"))
        s = transposes.get(e["ville"], {}).get("seuils_pluie_24h_mm", {}).get("orange", abidjan)
        det_ville += mm >= s
        det_abj += mm >= abidjan
        incert = " (date incertaine)" if "incertaine" in e["note"] else ""
        print(f"{e['date']:%Y-%m-%d} {e['ville']:13s} {mm:10.0f} mm {s:8d} {'✓' if mm >= s else '✗':>2s} "
              f"{abidjan:10d} {'✓' if mm >= abidjan else '✗':>2s}{incert}")
    print(f"\nDétectées (orange) : seuils de la ville {det_ville}/{len(ev)} · seuils d'Abidjan {det_abj}/{len(ev)}")
    print("Peu d'événements : indication seulement. Les fausses alertes se mesurent avec scripts/evaluate.py --zone <ville>.")


if __name__ == "__main__":
    main()
