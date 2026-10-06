"""Rejeu historique : compare deux sources de pluie et teste les seuils sur des événements connus.

Exemple :
    python scripts/replay.py --zone abidjan-centre --start 2024-06-01 --end 2024-06-30
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import rain_sources as rs  # noqa: E402
from src.evaluation import charger_evenements  # noqa: E402
from src.risk import niveau_pluie  # noqa: E402


def charger_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))


def rejouer(zone_id: str, start: date, end: date) -> tuple[pd.DataFrame, Path]:
    """Télécharge CHIRPS et Open-Meteo sur la période, classe chaque jour et enregistre le CSV."""
    cfg = charger_config()
    zone = next(z for z in cfg["zones"] if z["id"] == zone_id)
    seuils = cfg["seuils_pluie_24h_mm"]
    chirps = rs.chirps_series(zone["lat"], zone["lon"], start, end)
    om = rs.openmeteo_daily(zone["lat"], zone["lon"], start, end)
    prev = rs.openmeteo_previsions_passees(zone["lat"], zone["lon"], start, end)
    df = chirps.join(om, how="outer").join(prev, how="left")
    df.index.name = "date"
    df["niveau_chirps"] = [niveau_pluie(v, seuils) if pd.notna(v) else None for v in df["chirps_max_mm"]]
    df["niveau_openmeteo"] = [niveau_pluie(v, seuils) if pd.notna(v) else None for v in df["openmeteo_mm"]]

    out = ROOT / "data" / "results"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{zone_id}_{start.isoformat()}_{end.isoformat()}.csv"
    df.round(1).to_csv(f)
    return df, f


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--zone", default="abidjan-centre")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--top", type=int, default=5)
    a = p.parse_args()

    cfg = charger_config()
    zone = next(z for z in cfg["zones"] if z["id"] == a.zone)
    seuils = cfg["seuils_pluie_24h_mm"]
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    df, f = rejouer(a.zone, start, end)

    print(f"Zone : {zone['nom']} | {a.start} -> {a.end} | jours CHIRPS disponibles : {int(df['chirps_mm'].notna().sum())}/{len(df)}")
    print(f"\nJours les plus pluvieux (CHIRPS, max sur ~25 km) :")
    print(df.sort_values("chirps_max_mm", ascending=False).head(a.top)[["chirps_mm", "chirps_max_mm", "openmeteo_mm"]].round(1).to_string())
    for n in ("orange", "rouge"):
        c = int((df["chirps_max_mm"] >= seuils[n]).sum())
        o = int((df["openmeteo_mm"] >= seuils[n]).sum())
        print(f"Jours >= seuil {n} ({seuils[n]} mm) : CHIRPS={c} | Open-Meteo={o}")
    both = df.dropna(subset=["chirps_max_mm", "openmeteo_mm"])
    if len(both) > 3:
        print(f"Corrélation CHIRPS/Open-Meteo sur la période : {both['chirps_max_mm'].corr(both['openmeteo_mm']):.2f}")

    ev = charger_evenements()
    ev = ev[(ev["date"] >= pd.Timestamp(start)) & (ev["date"] <= pd.Timestamp(end))]
    if len(ev):
        print("\nÉvénements documentés dans la période :")
        for _, e in ev.iterrows():
            r = df.loc[e["date"]] if e["date"] in df.index else None
            if r is not None:
                print(f"  {e['date'].date()} : CHIRPS {r['chirps_max_mm']:.0f} mm ({r['niveau_chirps']}) | Open-Meteo {r['openmeteo_mm']:.0f} mm ({r['niveau_openmeteo']})")
    print(f"\nRésultats enregistrés : {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
