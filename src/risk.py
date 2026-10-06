"""Score de risque par zone : règles transparentes, seuils lus en configuration."""
from __future__ import annotations

from dataclasses import dataclass

VERT, ORANGE, ROUGE = "vert", "orange", "rouge"


@dataclass
class Resultat:
    niveau: str
    pluie_24h_mm: float
    facteurs: list[str]


def niveau_pluie(pluie_24h_mm: float, seuils: dict) -> str:
    if pluie_24h_mm >= seuils["rouge"]:
        return ROUGE
    if pluie_24h_mm >= seuils["orange"]:
        return ORANGE
    return VERT


def score(pluie_24h_mm: float, seuils: dict, part_caniveaux_bouches: float | None = None,
          majoration: float = 0.15) -> Resultat:
    """Niveau de risque d'une zone.

    part_caniveaux_bouches : part (0 à 1) des points de contrôle récents classés « bouché ».
    Hypothèse de recherche (à tester) : des caniveaux bouchés en amont abaissent les seuils.
    Sans donnée de points de contrôle, on ne majore pas.
    """
    facteurs = [f"pluie 24 h : {pluie_24h_mm:.0f} mm"]
    s = dict(seuils)
    if part_caniveaux_bouches is not None and part_caniveaux_bouches > 0:
        k = 1 - majoration * min(part_caniveaux_bouches, 1.0)
        s = {n: v * k for n, v in s.items()}
        facteurs.append(f"caniveaux bouchés : {part_caniveaux_bouches:.0%} (seuils x{k:.2f})")
    return Resultat(niveau_pluie(pluie_24h_mm, s), pluie_24h_mm, facteurs)
