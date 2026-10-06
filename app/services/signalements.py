"""Signalements libres géolocalisés par les habitants (route inondée, quartier inondé, danger, caniveau…).

Une inondation signalée s'affiche 48 h sur la carte publique ; un danger ou un caniveau, 7 jours.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.services import photos
from app.settings import reglages
from src.recoupement import decider_signalement, fiabilite

TYPES = {"route_inondee": "Route inondée", "zone_inondee": "Quartier inondé", "danger": "Endroit dangereux",
         "caniveau": "Caniveau bouché", "autre": "Autre"}
DUREE_HEURES = {"route_inondee": 48, "zone_inondee": 48, "danger": 168, "caniveau": 168, "autre": 72}
RAYON_RECOUPEMENT_M, FENETRE_RECOUPEMENT_H = 300, 6


def zone_proche(cx: Connection, lat: float, lon: float, max_km: float = 40) -> str | None:
    r = cx.execute(text("""
        SELECT id FROM zone
        WHERE ST_DWithin(centre::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :d)
        ORDER BY ST_Distance(centre::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) LIMIT 1
    """), {"lat": lat, "lon": lon, "d": max_km * 1000}).first()
    return r.id if r else None


def creer(cx: Connection, type_: str, lat: float, lon: float, precision_m: float | None, description: str,
          photo: bytes | None, relais) -> dict:
    if type_ not in TYPES:
        raise ValueError("type de signalement inconnu")
    if not (4.0 < lat < 11.0 and -9.0 < lon < -2.0):
        raise ValueError("position hors de Côte d'Ivoire")
    chemin = None
    if photo:
        jpeg, _ = photos.preparer(photo)
        dossier = reglages().dossier_photos / "signalements"
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = f"{uuid.uuid4().hex}.jpg"
        (dossier / chemin).write_bytes(jpeg)
    relais_id = relais.id if relais is not None else None
    voisins = cx.execute(text("""
        SELECT id FROM signalement
        WHERE type = :t AND statut <> 'rejete' AND recu_le > now() - make_interval(hours => :h)
          AND relais_id IS DISTINCT FROM :r
          AND ST_DWithin(position::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :m)
    """), {"t": type_, "h": FENETRE_RECOUPEMENT_H, "r": relais_id, "lat": lat, "lon": lon,
           "m": RAYON_RECOUPEMENT_M}).scalars().all()
    statut, motif = decider_signalement(relais.fiabilite if relais is not None else 0.0, len(voisins),
                                        reglages().seuil_relais_fiable)
    sid = cx.execute(text("""
        INSERT INTO signalement (type, description, position, precision_m, zone_id, photo_chemin, relais_id,
                                 expire_le, statut, motif, valide_par)
        VALUES (:t, :d, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :p, :z, :ph, :r,
                now() + make_interval(hours => :duree), :st, :mo, CASE WHEN :st = 'valide' THEN 'automatique' END)
        RETURNING id
    """), {"t": type_, "d": (description or "")[:500], "lat": lat, "lon": lon, "p": precision_m,
           "z": zone_proche(cx, lat, lon), "ph": chemin, "r": relais_id, "duree": DUREE_HEURES[type_],
           "st": statut, "mo": motif}).scalar_one()
    if statut == "valide" and voisins:  # le 2e témoin confirme aussi les signalements restés en attente
        for v in voisins:
            decider(cx, v, "valide", "automatique", "confirmé par un autre habitant à moins de 300 m")
    journaliser(cx, "signalement", f"{TYPES[type_]} ({lat:.5f}, {lon:.5f}) -> {statut} ({motif})")
    return {"id": sid, "statut": statut, "motif": motif}


def decider(cx: Connection, sid: int, decision: str, par: str, motif: str | None = None) -> None:
    if decision not in ("valide", "rejete", "resolu"):
        raise ValueError("décision : valide, rejete ou resolu")
    s = cx.execute(text("SELECT relais_id, statut FROM signalement WHERE id = :i"), {"i": sid}).one()
    cx.execute(text("UPDATE signalement SET statut = :d, valide_par = :p, motif = :m WHERE id = :i"),
               {"d": decision, "p": par, "m": motif or f"décision de {par}", "i": sid})
    if s.relais_id is not None and s.statut == "a_valider" and decision in ("valide", "rejete"):
        col = "nb_confirmees" if decision == "valide" else "nb_rejetees"
        c = cx.execute(text(f"UPDATE relais SET {col} = {col} + 1 WHERE id = :r RETURNING nb_confirmees, nb_rejetees"),
                       {"r": s.relais_id}).one()
        cx.execute(text("UPDATE relais SET fiabilite = :f WHERE id = :r"),
                   {"f": fiabilite(c.nb_confirmees, c.nb_rejetees), "r": s.relais_id})


def publics(cx: Connection) -> list[dict]:
    """Signalements validés et non expirés, pour la carte publique (sans photo ni auteur)."""
    return [dict(r._mapping) for r in cx.execute(text("""
        SELECT id, type, description, ST_Y(position) AS lat, ST_X(position) AS lon, recu_le, expire_le
        FROM signalement WHERE statut = 'valide' AND expire_le > now() ORDER BY recu_le DESC
    """))]
