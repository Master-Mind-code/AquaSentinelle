"""Calcul du score d'une zone à partir de la base (S6, S7, S8).

Deux lectures, on garde la plus grave :
- pluie OBSERVÉE (CHIRPS, pluviomètre, simulation) d'hier ou d'aujourd'hui, seuils observés ;
- pluie PRÉVUE (max de 5 modèles) d'aujourd'hui ou demain, seuils de prévision.
Les caniveaux bouchés (points validés, non périmés) abaissent les seuils de 15 % au plus.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.settings import reglages, seuils_zone
from src.alertes import VERSION_REGLES
from src.risk import score

SOURCES_OBSERVEES = ("chirps_max", "pluviometre", "simulation")
_RANG = {"vert": 0, "orange": 1, "rouge": 2}


def part_caniveaux_bouches(cx: Connection, zone_id: str) -> tuple[float | None, int]:
    """(part de points « bouché » parmi les points à statut frais, nombre de points à statut frais)."""
    r = cx.execute(text("""
        SELECT count(*) FILTER (WHERE classe = 'bouche') AS bouches, count(*) AS frais
        FROM statut_point WHERE zone_id = :z AND NOT perime AND classe IS NOT NULL
    """), {"z": zone_id}).one()
    return (r.bouches / r.frais if r.frais else None), r.frais


def _max_pluie(cx: Connection, zone_id: str, sources: tuple[str, ...], jours: list[date]) -> tuple[float | None, str | None]:
    r = cx.execute(text("""
        SELECT pluie_mm, source FROM mesure_pluie
        WHERE zone_id = :z AND source = ANY(:s) AND jour = ANY(:j)
        ORDER BY pluie_mm DESC LIMIT 1
    """), {"z": zone_id, "s": list(sources), "j": jours}).first()
    return (float(r.pluie_mm), r.source) if r else (None, None)


def calculer(cx: Connection, zone_id: str, aujourdhui: date | None = None) -> dict:
    aujourdhui = aujourdhui or date.today()
    cfg = seuils_zone(zone_id)
    part, nb_frais = part_caniveaux_bouches(cx, zone_id)
    sources = SOURCES_OBSERVEES + (("imerg_early",) if reglages().imerg_dans_score else ())
    obs_mm, obs_src = _max_pluie(cx, zone_id, sources, [aujourdhui - timedelta(1), aujourdhui])
    prev_mm, _ = _max_pluie(cx, zone_id, ("prevision_max",), [aujourdhui, aujourdhui + timedelta(1)])

    lectures = []
    if obs_mm is not None:
        lectures.append(("observee", obs_src, score(obs_mm, cfg["seuils_pluie_24h_mm"], part)))
    if prev_mm is not None:
        lectures.append(("prevision", "prevision_max", score(prev_mm, cfg["seuils_prevision_24h_mm"], part)))
    crue = _crue_prevue(cx, zone_id, aujourdhui)
    if crue:
        lectures.append(("debit", "glofas", crue["resultat"]))
    from app.services.capteurs import lecture_zone
    capteur = lecture_zone(cx, zone_id)
    if capteur:
        lectures.append(("capteur", capteur[1], capteur[0]))
    if not lectures:
        return {"zone_id": zone_id, "niveau": None, "raison": "aucune donnée de pluie"}

    nature, source, res = max(lectures, key=lambda l: (_RANG[l[2].niveau], l[2].pluie_24h_mm))
    entrees = {
        "pluie_observee_mm": obs_mm, "source_observee": obs_src, "pluie_prevue_mm": prev_mm,
        "part_caniveaux_bouches": part, "points_a_statut_frais": nb_frais,
        "seuils_observes": cfg["seuils_pluie_24h_mm"], "seuils_prevision": cfg["seuils_prevision_24h_mm"],
        "lecture_retenue": nature, "facteurs": res.facteurs, "seuils_transposes": cfg["transposes"],
        "crue": {k: v for k, v in crue.items() if k != "resultat"} if crue else None,
    }
    row = cx.execute(text("""
        INSERT INTO score_risque (zone_id, niveau, pluie_24h_mm, source, entrees, version_regles, calcule_le)
        VALUES (:z, :n, :mm, :src, CAST(:e AS jsonb), :v, clock_timestamp()) RETURNING id, calcule_le
    """), {"z": zone_id, "n": res.niveau, "mm": res.pluie_24h_mm, "src": source,
           "e": json.dumps(entrees, ensure_ascii=False), "v": VERSION_REGLES}).one()
    return {"id": row.id, "calcule_le": row.calcule_le, "zone_id": zone_id, "niveau": res.niveau,
            "pluie_24h_mm": res.pluie_24h_mm, "source": source, "entrees": entrees}


def _crue_prevue(cx: Connection, zone_id: str, aujourdhui: date) -> dict | None:
    """Débit maximal prévu sur 7 jours à la station de la zone, comparé à la crue annuelle et à la crue de 5 ans.
    Les caniveaux ne jouent pas : une crue de fleuve ne dépend pas de l'état des caniveaux."""
    riv = cx.execute(text("SELECT nom, seuil_orange, seuil_rouge FROM riviere WHERE zone_id = :z AND seuil_orange IS NOT NULL"),
                     {"z": zone_id}).first()
    if riv is None:
        return None
    pic = cx.execute(text("""
        SELECT jour, debit_m3s FROM mesure_debit WHERE zone_id = :z AND prevision AND jour BETWEEN :d AND :f
        ORDER BY debit_m3s DESC LIMIT 1
    """), {"z": zone_id, "d": aujourdhui, "f": aujourdhui + timedelta(7)}).first()
    if pic is None:
        return None
    res = score(pic.debit_m3s, {"orange": riv.seuil_orange, "rouge": riv.seuil_rouge})
    res.facteurs = [f"{riv.nom} : {pic.debit_m3s:.0f} m³/s prévus le {pic.jour:%d/%m} "
                    f"(crue annuelle {riv.seuil_orange:.0f}, crue de 5 ans {riv.seuil_rouge:.0f})"]
    return {"riviere": riv.nom, "debit_max_m3s": round(pic.debit_m3s), "jour_pic": pic.jour.isoformat(),
            "seuil_orange": round(riv.seuil_orange), "seuil_rouge": round(riv.seuil_rouge), "resultat": res}
