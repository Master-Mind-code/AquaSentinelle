import pandas as pd

from src.evaluation import evaluer

JOURS = pd.date_range("2024-06-01", "2024-06-10")
#                      1   2   3   4   5    6   7   8   9  10
PLUIE = pd.Series([0, 60, 0, 0, 0, 120, 0, 0, 55, 0], index=JOURS, dtype=float)


def test_detection_avec_tolerance():
    # événement le 7 : la pluie du 6 le détecte avec une tolérance d'un jour
    b = evaluer(PLUIE, [pd.Timestamp("2024-06-07")], seuil=50, tolerance=1)
    assert (b.detectes, b.evenements) == (1, 1)
    # les alertes du 2 et du 9 ne correspondent à aucun événement
    assert (b.jours_alerte, b.fausses_alertes) == (3, 2)


def test_evenement_manque():
    b = evaluer(PLUIE, [pd.Timestamp("2024-06-04")], seuil=100, tolerance=1)
    assert b.detectes == 0 and b.taux_fausses_alertes == 1.0


def test_evenement_hors_couverture_compte_a_part():
    b = evaluer(PLUIE, [pd.Timestamp("2023-06-01")], seuil=50)
    assert b.evenements == 0 and b.non_couverts == 1
