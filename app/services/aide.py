"""Demandes d'aide d'urgence. NE REMPLACENT PAS le 180 : la page le dit d'abord.

La demande (position, situation) arrive dans l'espace opérateur et déclenche une notification immédiate ;
l'opérateur la relaie aux secours et met à jour son statut, que le demandeur suit avec son lien personnel.
"""
from __future__ import annotations

import secrets

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.securite import chiffrer
from app.services.alertes import notifier_operateurs
from app.services.signalements import zone_proche
from app.settings import reglages

SITUATIONS = {"eau_monte": "L'eau monte autour de nous", "bloque": "Personnes bloquées par l'eau",
              "blesse": "Personne blessée", "glissement": "Glissement de terrain ou effondrement",
              "autre": "Autre danger"}
STATUTS = {"recue": "Reçue par les opérateurs", "transmise": "Transmise aux secours", "traitee": "Prise en charge",
           "close": "Close"}


def creer(cx: Connection, situation: str, nb_personnes: int | None, description: str, lat: float | None,
          lon: float | None, precision_m: float | None, lieu_texte: str, contact: str | None) -> dict:
    if situation not in SITUATIONS:
        raise ValueError("situation inconnue")
    if lat is None and not (lieu_texte or "").strip():
        raise ValueError("indiquez votre position (GPS ou quartier et repère)")
    if lat is not None and not (4.0 < lat < 11.0 and -9.0 < lon < -2.0):
        raise ValueError("position hors de Côte d'Ivoire")
    jeton = secrets.token_urlsafe(9)
    zone = zone_proche(cx, lat, lon) if lat is not None else None
    if lat is None:
        position_sql = "NULL"
    else:
        position_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
    did = cx.execute(text(f"""
        INSERT INTO demande_aide (jeton, situation, nb_personnes, description, position, precision_m, lieu_texte,
                                  contact_chiffre, zone_id)
        VALUES (:j, :s, :n, :d, {position_sql}, :p, :l, :c, :z) RETURNING id
    """), {"j": jeton, "s": situation, "n": nb_personnes, "d": (description or "")[:500], "lat": lat, "lon": lon,
           "p": precision_m, "l": (lieu_texte or "")[:200], "c": chiffrer(contact) if contact else None,
           "z": zone}).scalar_one()
    ou = f"{lat:.5f}, {lon:.5f}" if lat is not None else lieu_texte
    notifier_operateurs(cx, f"DEMANDE D'AIDE n° {did} : {SITUATIONS[situation]}, {nb_personnes or '?'} personne(s), "
                        f"{ou}. {reglages().base_url}/operateur/aide")
    journaliser(cx, "aide", f"demande {did} : {situation} ({ou})")
    return {"id": did, "jeton": jeton}


def changer_statut(cx: Connection, did: int, statut: str, operateur: str, note: str = "") -> None:
    if statut not in STATUTS:
        raise ValueError("statut inconnu")
    n = cx.execute(text("""
        UPDATE demande_aide SET statut = :s, traite_par = :o, maj_le = now(),
               note = CASE WHEN :n = '' THEN note ELSE :n END WHERE id = :i
    """), {"s": statut, "o": operateur, "n": (note or "")[:500], "i": did}).rowcount
    if not n:
        raise ValueError("demande introuvable")
    journaliser(cx, "aide", f"demande {did} : {statut} par {operateur}")


def par_jeton(cx: Connection, jeton: str):
    return cx.execute(text("""
        SELECT id, situation, statut, recu_le, maj_le, note FROM demande_aide WHERE jeton = :j
    """), {"j": jeton}).first()
