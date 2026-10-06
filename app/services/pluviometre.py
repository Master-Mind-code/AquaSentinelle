"""Pluviomètres de quartier tenus par les relais : la 2e source observée qui manquait (CHIRPS peut rater
un orage entier, comme autour du 7 juillet 2023). Les relevés validés alimentent mesure_pluie (« pluviometre »)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.services.pluie import enregistrer
from app.settings import config_zones, reglages
from src.recoupement import decider_releve, fiabilite


def _consolider(cx: Connection, zone_id: str, jour: date) -> None:
    """La pluie « pluviomètre » du jour = le plus fort relevé validé (le pluviomètre le plus arrosé de la zone)."""
    mm = cx.execute(text("""
        SELECT max(pluie_mm) FROM releve_pluviometre WHERE zone_id = :z AND jour = :j AND statut = 'valide'
    """), {"z": zone_id, "j": jour}).scalar()
    if mm is None:
        cx.execute(text("DELETE FROM mesure_pluie WHERE zone_id = :z AND jour = :j AND source = 'pluviometre'"),
                   {"z": zone_id, "j": jour})
    else:
        enregistrer(cx, zone_id, "pluviometre", jour, mm)


def enregistrer_releve(cx: Connection, zone_id: str, relais, pluie_mm: float, jour: date | None = None) -> dict:
    jour = jour or date.today()
    if not 0 <= pluie_mm <= 400:
        raise ValueError("relevé hors limites (0 à 400 mm)")
    if not cx.execute(text("SELECT 1 FROM zone WHERE id = :z"), {"z": zone_id}).first():
        raise ValueError(f"zone inconnue : {zone_id}")
    relais_id = relais.id if relais is not None else None
    autres = [r[0] for r in cx.execute(text("""
        SELECT pluie_mm FROM releve_pluviometre
        WHERE zone_id = :z AND jour = :j AND statut <> 'rejete' AND relais_id IS DISTINCT FROM :r
    """), {"z": zone_id, "j": jour, "r": relais_id})]
    sans_effet = 0.5 * config_zones()["seuils_pluie_24h_mm"]["orange"]
    statut, motif = decider_releve(pluie_mm, relais.fiabilite if relais is not None else 0.0, autres,
                                   sans_effet, reglages().seuil_relais_fiable)
    rid = cx.execute(text("""
        INSERT INTO releve_pluviometre (zone_id, relais_id, jour, pluie_mm, statut, motif, valide_par)
        VALUES (:z, :r, :j, :mm, :st, :mo, CASE WHEN :st = 'valide' THEN 'automatique' END) RETURNING id
    """), {"z": zone_id, "r": relais_id, "j": jour, "mm": pluie_mm, "st": statut, "mo": motif}).scalar_one()
    # un relevé concordant valide aussi les relevés restés en attente qu'il confirme
    if statut == "valide" and motif.startswith("concorde"):
        cx.execute(text("""
            UPDATE releve_pluviometre SET statut = 'valide', valide_par = 'automatique', motif = 'confirmé par un 2e relevé'
            WHERE zone_id = :z AND jour = :j AND statut = 'a_valider' AND id <> :i
              AND abs(pluie_mm - :mm) <= greatest(10, 0.3 * greatest(pluie_mm, :mm))
        """), {"z": zone_id, "j": jour, "i": rid, "mm": pluie_mm})
    _consolider(cx, zone_id, jour)
    journaliser(cx, "pluviometre", f"{zone_id} {jour} : {pluie_mm} mm -> {statut} ({motif})")
    return {"id": rid, "statut": statut, "motif": motif}


def decider_releve_operateur(cx: Connection, releve_id: int, decision: str, operateur: str) -> None:
    if decision not in ("valide", "rejete"):
        raise ValueError("décision : valide ou rejete")
    r = cx.execute(text("SELECT * FROM releve_pluviometre WHERE id = :i"), {"i": releve_id}).one()
    cx.execute(text("UPDATE releve_pluviometre SET statut = :d, valide_par = :o, motif = :m WHERE id = :i"),
               {"d": decision, "o": operateur, "m": f"décision de {operateur}", "i": releve_id})
    if r.relais_id is not None and r.statut == "a_valider":
        col = "nb_confirmees" if decision == "valide" else "nb_rejetees"
        c = cx.execute(text(f"UPDATE relais SET {col} = {col} + 1 WHERE id = :r RETURNING nb_confirmees, nb_rejetees"),
                       {"r": r.relais_id}).one()
        cx.execute(text("UPDATE relais SET fiabilite = :f WHERE id = :r"),
                   {"f": fiabilite(c.nb_confirmees, c.nb_rejetees), "r": r.relais_id})
    _consolider(cx, r.zone_id, r.jour)
    journaliser(cx, "pluviometre", f"relevé {releve_id} : {decision} par {operateur}")
