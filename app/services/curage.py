"""Alerte de curage préventive : une forte pluie est PRÉVUE et des caniveaux de la zone sont signalés bouchés.

On prévient les opérateurs (mairie, ONAD) AVANT la pluie, avec la liste des points à curer en priorité.
Une seule notification par zone et par jour (le journal sert de mémoire).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.services.alertes import notifier_operateurs
from app.settings import config_zones, reglages


def points_a_curer(cx: Connection, aujourdhui: date | None = None) -> list[dict]:
    """Zones où la pluie prévue atteint le seuil orange de prévision ET où des points sont bouchés (non périmés)."""
    aujourdhui = aujourdhui or date.today()
    seuil = config_zones()["seuils_prevision_24h_mm"]["orange"]
    return [dict(r._mapping) for r in cx.execute(text("""
        SELECT z.id AS zone_id, z.nom, p.prevu_mm,
               array_agg(s.point_id ORDER BY s.recu_le) AS points, min(s.recu_le) AS depuis
        FROM zone z
        JOIN LATERAL (SELECT max(pluie_mm) AS prevu_mm FROM mesure_pluie
                      WHERE zone_id = z.id AND source = 'prevision_max' AND jour = ANY(:j)) p ON true
        JOIN statut_point s ON s.zone_id = z.id AND s.classe = 'bouche' AND NOT s.perime
        WHERE p.prevu_mm >= :seuil
        GROUP BY z.id, z.nom, p.prevu_mm ORDER BY p.prevu_mm DESC
    """), {"j": [aujourdhui, aujourdhui + timedelta(1)], "seuil": seuil})]


def notifier(cx: Connection, aujourdhui: date | None = None) -> int:
    n = 0
    for c in points_a_curer(cx, aujourdhui):
        deja = cx.execute(text("""
            SELECT 1 FROM journal WHERE type = 'curage' AND message LIKE :z AND le >= date_trunc('day', now())
        """), {"z": f"{c['zone_id']} :%"}).first()
        if deja:
            continue
        texte = (f"CURAGE PRIORITAIRE avant la pluie : {c['nom']}, {c['prevu_mm']:.0f} mm prévus. "
                 f"Points bouchés : {', '.join(c['points'])}. {reglages().base_url}/operateur")
        notifier_operateurs(cx, texte)
        journaliser(cx, "curage", f"{c['zone_id']} : {texte}")
        n += 1
    return n
