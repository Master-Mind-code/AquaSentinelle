"""Le sol saturé aide-t-il à détecter les inondations et glissements que la pluie du jour rate ?

    python scripts/evaluer_sol.py [--zone abidjan-centre]

Compare, à budget d'alertes comparable, la règle actuelle (CHIRPS max ≥ 70 mm) à deux règles « 2e chance » :
  A. pluie du jour ≥ P ET humidité du sol (ERA5-Land, 0-7 cm, veille) ≥ S
  B. pluie du jour ≥ P ET pluie cumulée sur 3 jours ≥ C
Une règle n'est retenue que si elle détecte PLUS d'événements sans trop d'alertes en plus.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation import RESULTS, charger_evenements, charger_pluie, evaluer  # noqa: E402

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def humidite_sol(lat: float, lon: float, debut: str, fin: str) -> pd.Series:
    r = requests.get(ARCHIVE, params=dict(latitude=lat, longitude=lon, start_date=debut, end_date=fin,
                                          hourly="soil_moisture_0_to_7cm", timezone="Africa/Abidjan"), timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    s = pd.Series(h["soil_moisture_0_to_7cm"], index=pd.to_datetime(h["time"]), dtype="float")
    return s.resample("D").mean()


def charger_sol(zone: str, pluie: pd.DataFrame) -> pd.Series:
    cache = RESULTS / f"sol_{zone}.csv"
    if cache.exists():
        s = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["sol_m3m3"]
        if set(pluie.index) <= set(s.index):
            return s
    import yaml
    z = next(z for z in yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))["zones"]
             if z["id"] == zone)
    morceaux = []
    for mois in sorted({d.to_period("M") for d in pluie.index}):
        debut, fin = mois.start_time - pd.Timedelta(days=1), mois.end_time
        morceaux.append(humidite_sol(z["lat"], z["lon"], debut.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")))
    s = pd.concat(morceaux)
    s = s[~s.index.duplicated()].rename("sol_m3m3")
    s.rename_axis("date").to_csv(cache)
    return s


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--zone", default="abidjan-centre")
    a = a.parse_args()
    ev = charger_evenements()
    dates = sorted(set(ev.loc[~ev["incertaine"], "date"]))
    pluie = charger_pluie(a.zone)
    sol = charger_sol(a.zone, pluie)
    df = pluie[["chirps_max_mm"]].join(sol.rename("sol"), how="left")
    df["sol_veille"] = df["sol"].shift(1)                       # l'état du sol AVANT la pluie du jour
    df["cumul_3j"] = df["chirps_max_mm"].rolling(3, min_periods=1).sum()

    print("Humidité du sol (m³/m³) la veille des événements :")
    for d in dates:
        if d in df.index:
            r = df.loc[d]
            print(f"  {d.date()} : pluie {r.chirps_max_mm:5.0f} mm · sol veille {r.sol_veille:.3f} · cumul 3 j {r.cumul_3j:5.0f} mm")
    print(f"  (médiane tous jours : sol {df['sol_veille'].median():.3f})\n")

    base = evaluer(df["chirps_max_mm"], dates, 70)
    print(f"{'Règle':58s} {'détectés':>9s} {'alertes/mois':>13s}")
    print(f"{'Actuelle : pluie ≥ 70 mm':58s} {base.detectes:>4d} / {base.evenements:<3d} {base.alertes_par_mois:>13.1f}")
    meilleures = []
    for p in (30, 35, 40, 50):
        for s in (0.38, 0.40, 0.42, 0.44):
            signal = ((df["chirps_max_mm"] >= 70) | ((df["chirps_max_mm"] >= p) & (df["sol_veille"] >= s))).astype(float)
            meilleures.append((f"A : ≥ 70 mm, ou ≥ {p} mm et sol ≥ {s:.2f}", evaluer(signal, dates, 1)))
        for c in (60, 80, 100):
            signal = ((df["chirps_max_mm"] >= 70) | ((df["chirps_max_mm"] >= p) & (df["cumul_3j"] >= c))).astype(float)
            meilleures.append((f"B : ≥ 70 mm, ou ≥ {p} mm et cumul 3 j ≥ {c} mm", evaluer(signal, dates, 1)))
    # on montre les règles qui gagnent au moins un événement, triées par alertes ajoutées
    gains = sorted([m for m in meilleures if m[1].detectes > base.detectes],
                   key=lambda m: (-m[1].detectes, m[1].alertes_par_mois))
    for nom, b in gains[:8]:
        print(f"{nom:58s} {b.detectes:>4d} / {b.evenements:<3d} {b.alertes_par_mois:>13.1f}")
    if not gains:
        print("Aucune règle « 2e chance » ne détecte plus d'événements : on n'ajoute rien au score.")


if __name__ == "__main__":
    main()
