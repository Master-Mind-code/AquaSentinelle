"""S10 : une forêt aléatoire fait-elle mieux que les règles ? Gardée seulement si oui.

    python scripts/foret_aleatoire.py [--zone abidjan-centre] [--seuil 70]

Validation croisée « un mois laissé de côté » : un même épisode de pluie ne peut pas être à la fois
dans l'entraînement et dans le test. Variables : pluie du jour (CHIRPS max et maille centrale),
pluie cumulée sur 3 et 5 jours (sols saturés, glissements), Open-Meteo.
Comparaison au même nombre de jours d'alerte que la règle, pour une comparaison équitable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation import charger_evenements, charger_pluie, evaluer  # noqa: E402


def variables(pluie: pd.DataFrame) -> pd.DataFrame:
    p = pluie.asfreq("D")
    v = pd.DataFrame(index=p.index)
    v["chirps_max"] = p["chirps_max_mm"]
    v["chirps"] = p["chirps_mm"]
    v["cumul_3j"] = p["chirps_max_mm"].rolling(3, min_periods=1).sum()
    v["cumul_5j"] = p["chirps_max_mm"].rolling(5, min_periods=1).sum()
    v["openmeteo"] = p["openmeteo_mm"]
    return v.dropna(subset=["chirps_max"]).fillna(0)


def cibles(index: pd.DatetimeIndex, dates: list[pd.Timestamp], tol: int = 1) -> np.ndarray:
    return np.array([any(abs((j - d).days) <= tol for d in dates) for j in index], dtype=int)


def main() -> None:
    from sklearn.ensemble import RandomForestClassifier

    a = argparse.ArgumentParser()
    a.add_argument("--zone", default="abidjan-centre")
    a.add_argument("--seuil", type=float, default=70)
    a = a.parse_args()

    ev = charger_evenements()
    dates = sorted(set(ev.loc[~ev["incertaine"], "date"]))
    X = variables(charger_pluie(a.zone))
    y = cibles(X.index, dates)
    mois = X.index.to_period("M")
    print(f"{len(X)} jours, {y.sum()} jours « événement » (± 1 j), {mois.nunique()} mois, {len(dates)} événements\n")

    regle = X["chirps_max"]
    b_regle = evaluer(regle, dates, a.seuil)
    proba = pd.Series(0.0, index=X.index)
    importances = []
    for m in mois.unique():
        test = mois == m
        if y[~test].sum() == 0:
            continue
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced", random_state=0)
        rf.fit(X[~test], y[~test])
        proba[test] = rf.predict_proba(X[test])[:, 1]
        importances.append(rf.feature_importances_)

    # même budget d'alertes que la règle : on garde les N jours les plus probables
    n_alertes = b_regle.jours_alerte
    seuil_rf = np.sort(proba.values)[-n_alertes] if n_alertes else 1.1
    b_rf = evaluer(proba, dates, seuil_rf)

    print(f"{'Méthode':42s} {'détectés':>9s} {'jours alerte':>13s} {'alertes/mois':>13s}")
    for nom, b in ((f"Règle : CHIRPS max ≥ {a.seuil:.0f} mm", b_regle), ("Forêt aléatoire (même nb d'alertes)", b_rf)):
        print(f"{nom:42s} {b.detectes:>4d} / {b.evenements:<3d} {b.jours_alerte:>13d} {b.alertes_par_mois:>13.1f}")
    imp = np.mean(importances, axis=0)
    print("\nImportance des variables :", ", ".join(f"{c} {v:.2f}" for c, v in sorted(zip(X.columns, imp), key=lambda t: -t[1])))
    gagne = b_rf.detectes > b_regle.detectes
    print("\nVerdict :", "la forêt détecte plus d'événements à budget égal : à approfondir."
          if gagne else "la forêt ne fait pas mieux que la règle : on garde la règle (plus simple, explicable).")
    print("Prudence : ~11 événements, l'écart d'un seul événement n'est pas significatif.")


if __name__ == "__main__":
    main()
