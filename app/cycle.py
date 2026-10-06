"""Un cycle complet : collecte de la pluie -> score par zone -> décision d'alerte -> escalade.

Lancé par le planificateur (toutes les PLANIFICATEUR_MINUTES), par un opérateur (bouton) ou en ligne de commande :
    python -m app.cycle [--sans-chirps]
"""
from __future__ import annotations

import sys
from datetime import date

from app.db import journaliser, transaction
from app.services import alertes, capteurs, curage, pluie, score


def traiter_zone(zone_id: str, aujourdhui: date | None = None) -> dict:
    """Score + décision pour une zone, dans sa propre transaction (une zone en échec ne bloque pas les autres)."""
    with transaction() as cx:
        sc = score.calculer(cx, zone_id, aujourdhui)
        if sc.get("niveau") is None:
            return {"score": sc}
        return {"score": {k: sc[k] for k in ("id", "niveau", "pluie_24h_mm", "source")},
                "alerte": alertes.traiter_score(cx, sc)}


def cycle_complet(collecte: bool = True, chirps: bool = True, aujourdhui: date | None = None) -> dict:
    bilan: dict = {}
    if collecte:
        with transaction() as cx:
            bilan["collecte"] = pluie.collecter(cx, aujourdhui, chirps=chirps)
    with transaction() as cx:
        zones = [z["id"] for z in pluie.zones(cx)]
    bilan["zones"] = {}
    for z in zones:
        try:
            bilan["zones"][z] = traiter_zone(z, aujourdhui)
        except Exception as e:
            bilan["zones"][z] = {"erreur": str(e)[:300]}
            with transaction() as cx:
                journaliser(cx, "erreur", f"cycle {z} : {e}")
    with transaction() as cx:
        bilan["escalades"] = alertes.escalader(cx)
        bilan["curages_notifies"] = curage.notifier(cx, aujourdhui)
        bilan["capteurs_muets"] = capteurs.surveiller_silence(cx)
    return bilan


if __name__ == "__main__":
    import json
    print(json.dumps(cycle_complet(chirps="--sans-chirps" not in sys.argv), default=str, ensure_ascii=False, indent=2))
