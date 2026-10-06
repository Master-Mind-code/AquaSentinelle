"""Décision d'envoi d'une alerte : quand envoyer, quand se taire, quand attendre un humain.

Règles (version « r1 », à citer dans le rapport) :
- on n'envoie que sur CHANGEMENT de niveau (pas de répétition : la lassitude tue l'alerte) ;
- une hausse vers orange part automatiquement ;
- une hausse vers rouge attend la validation d'un opérateur (protection civile / mairie) ;
- une baisse après orange ou rouge envoie « retour à la normale » quand on revient au vert ;
- une baisse de rouge à orange n'envoie rien (on évite les messages contradictoires).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.risk import ORANGE, ROUGE, VERT

VERSION_REGLES = "r1"
_RANG = {VERT: 0, ORANGE: 1, ROUGE: 2}


@dataclass
class Decision:
    action: str          # "envoyer", "attendre_validation" ou "rien"
    niveau: str
    raison: str


def decider(niveau: str, niveau_precedent: str | None, validee_par: str | None = None) -> Decision:
    prec = niveau_precedent or VERT
    if niveau == prec:
        return Decision("rien", niveau, "niveau inchangé")
    if _RANG[niveau] > _RANG[prec]:
        if niveau == ROUGE and not validee_par:
            return Decision("attendre_validation", niveau, "alerte rouge : validation humaine requise")
        return Decision("envoyer", niveau, f"hausse {prec} -> {niveau}")
    if niveau == VERT:
        return Decision("envoyer", niveau, f"retour à la normale après {prec}")
    return Decision("rien", niveau, f"baisse {prec} -> {niveau} sans message")
