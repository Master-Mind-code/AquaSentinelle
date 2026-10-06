"""Évaluation des seuils sur les événements documentés : taux de détection et fausses alertes.

Règles de comptage (à citer dans le rapport) :
- un événement est DÉTECTÉ si au moins un jour d'alerte tombe dans [date - tolérance, date + tolérance] ;
- un jour d'alerte est une FAUSSE ALERTE si aucun événement documenté ne tombe à ± tolérance ;
- seuls les jours couverts par des données de pluie comptent ; les événements hors couverture sont signalés à part.

Limite : la liste d'événements est incomplète (inondations non médiatisées), donc le taux de fausses
alertes est SURESTIMÉ. C'est une borne haute, pas une mesure exacte.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
EVENTS = ROOT / "data" / "events.csv"


def charger_pluie(zone: str, dossier: Path = RESULTS) -> pd.DataFrame:
    """Assemble tous les rejeux enregistrés pour une zone (sorties de scripts/replay.py)."""
    fichiers = sorted(dossier.glob(f"{zone}_*.csv"))
    if not fichiers:
        raise FileNotFoundError(f"aucun rejeu pour la zone {zone} dans {dossier}")
    df = pd.concat(pd.read_csv(f, parse_dates=["date"]) for f in fichiers)
    return df.drop_duplicates("date", keep="last").set_index("date").sort_index()


def charger_evenements(fichier: Path = EVENTS) -> pd.DataFrame:
    """Événements documentés. Les lignes dont la note contient « incertaine » sont marquées."""
    ev = pd.read_csv(fichier, sep=";", comment="#", header=None, index_col=False,
                     names=["date", "zone", "source", "note"])
    # format strict : une ligne mal formée (ex. « ; » dans une note) doit échouer, pas décaler les colonnes
    ev["date"] = pd.to_datetime(ev["date"], format="%Y-%m-%d")
    ev["incertaine"] = ev["note"].fillna("").str.contains("incertaine", case=False)
    return ev


@dataclass
class Bilan:
    seuil: float
    evenements: int
    detectes: int
    jours_couverts: int
    jours_alerte: int
    fausses_alertes: int
    non_couverts: int

    @property
    def taux_detection(self) -> float:
        return self.detectes / self.evenements if self.evenements else float("nan")

    @property
    def taux_fausses_alertes(self) -> float:
        return self.fausses_alertes / self.jours_alerte if self.jours_alerte else 0.0

    @property
    def alertes_par_mois(self) -> float:
        return 30 * self.jours_alerte / self.jours_couverts if self.jours_couverts else float("nan")


def evaluer(pluie: pd.Series, dates_evenements: list[pd.Timestamp], seuil: float, tolerance: int = 1) -> Bilan:
    pluie = pluie.dropna()
    couverts = set(pluie.index)
    tol = pd.Timedelta(days=tolerance)
    ev_couverts = [d for d in dates_evenements if d in couverts]
    alertes = pluie.index[pluie >= seuil]
    detectes = sum(any(abs(a - d) <= tol for a in alertes) for d in ev_couverts)
    fausses = sum(not any(abs(a - d) <= tol for d in dates_evenements) for a in alertes)
    return Bilan(seuil, len(ev_couverts), detectes, len(couverts), len(alertes), fausses,
                 len(dates_evenements) - len(ev_couverts))


def balayage(pluie: pd.Series, dates_evenements: list[pd.Timestamp], seuils: list[float],
             tolerance: int = 1) -> pd.DataFrame:
    rows = []
    for s in seuils:
        b = evaluer(pluie, dates_evenements, s, tolerance)
        rows.append(dict(seuil_mm=s, detectes=f"{b.detectes}/{b.evenements}",
                         taux_detection=round(b.taux_detection, 2),
                         jours_alerte=b.jours_alerte, fausses_alertes=b.fausses_alertes,
                         taux_fausses_alertes=round(b.taux_fausses_alertes, 2),
                         alertes_par_mois=round(b.alertes_par_mois, 1)))
    return pd.DataFrame(rows)
