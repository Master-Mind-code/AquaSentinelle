"""Anti-abus (S13) : pas de message identique répété, plafond d'envois par abonné et par jour.

Le plafond ne s'applique pas au rouge : une alerte rouge validée doit toujours partir.
"""
from __future__ import annotations


def verdict(niveau: str, deja_envoye_meme_texte: bool, envois_du_jour: int, plafond: int) -> str:
    """'ok', 'bloque_doublon' ou 'bloque_plafond'."""
    if deja_envoye_meme_texte:
        return "bloque_doublon"
    if niveau != "rouge" and envois_du_jour >= plafond:
        return "bloque_plafond"
    return "ok"
