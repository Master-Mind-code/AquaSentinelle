"""Points de contrôle et observations des relais (S18-S23)."""
from __future__ import annotations

import io
import uuid

import qrcode
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.securite import chiffrer, empreinte
from app.services import ia, photos
from app.settings import reglages
from src.recoupement import classe_retenue, decider_statut, fiabilite

FENETRE_RECOUPEMENT_HEURES = 72


def url_point(point_id: str) -> str:
    return f"{reglages().base_url}/r/{point_id}"


def qr_png(point_id: str, taille_case: int = 12) -> bytes:
    """QR code du point (S18) : correction d'erreur élevée (H), il reste lisible si la peinture s'abîme."""
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=taille_case, border=2)
    q.add_data(url_point(point_id))
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def prochain_identifiant(cx: Connection, zone_id: str) -> str:
    prefixe = zone_id[:3].upper()
    n = cx.execute(text("SELECT count(*) FROM point_controle WHERE id LIKE :p"), {"p": f"{prefixe}-%"}).scalar_one()
    return f"{prefixe}-{n + 1:03d}"


def creer_point(cx: Connection, zone_id: str, lat: float, lon: float, description: str = "",
                point_id: str | None = None, demo: bool = False) -> str:
    point_id = point_id or prochain_identifiant(cx, zone_id)
    cx.execute(text("""
        INSERT INTO point_controle (id, zone_id, position, description, demo)
        VALUES (:i, :z, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :d, :demo)
    """), {"i": point_id, "z": zone_id, "lat": lat, "lon": lon, "d": description, "demo": demo})
    return point_id


def trouver_ou_creer_relais(cx: Connection, pseudo: str, contact: str | None = None,
                            telegram_id: str | None = None, zone_id: str | None = None,
                            consentement: bool = False):
    if telegram_id:
        r = cx.execute(text("SELECT * FROM relais WHERE telegram_id = :t"), {"t": telegram_id}).first()
        if r:
            return r
    if contact:
        r = cx.execute(text("SELECT * FROM relais WHERE contact_empreinte = :e"), {"e": empreinte(contact)}).first()
        if r:
            return r
    return cx.execute(text("""
        INSERT INTO relais (zone_id, pseudo, contact_chiffre, contact_empreinte, telegram_id, consentement)
        VALUES (:z, :p, :c, :e, :t, :cons) RETURNING *
    """), {"z": zone_id, "p": pseudo[:60] or "anonyme", "c": chiffrer(contact) if contact else None,
           "e": empreinte(contact) if contact else None, "t": telegram_id, "cons": consentement}).one()


def _autres_sources_bouche(cx: Connection, point_id: str, relais_id: int | None) -> list[int]:
    return [r.id for r in cx.execute(text("""
        SELECT id FROM observation
        WHERE point_id = :p AND classe = 'bouche' AND statut <> 'rejete'
          AND recu_le > now() - make_interval(hours => :h)
          AND relais_id IS DISTINCT FROM :r
    """), {"p": point_id, "h": FENETRE_RECOUPEMENT_HEURES, "r": relais_id})]


def enregistrer_observation(cx: Connection, point_id: str, relais, photo: bytes | None,
                            eau_stagnante: bool | None, dechets_visibles: bool | None,
                            avis_relais: str | None, source: str = "relais") -> dict:
    point = cx.execute(text("SELECT id, zone_id FROM point_controle WHERE id = :p AND actif"), {"p": point_id}).first()
    if point is None:
        raise ValueError(f"point de contrôle inconnu : {point_id}")
    chemin, visages, classe_ia, confiance = None, 0, None, None
    if photo:
        jpeg, visages = photos.preparer(photo)
        dossier = reglages().dossier_photos / point_id
        dossier.mkdir(parents=True, exist_ok=True)
        nom = f"{uuid.uuid4().hex}.jpg"
        (dossier / nom).write_bytes(jpeg)
        chemin = f"{point_id}/{nom}"
        classe_ia, confiance = ia.classer(jpeg)

    classe = classe_retenue(classe_ia, confiance, avis_relais, reglages().seuil_confiance_ia)
    relais_id = relais.id if relais is not None else None
    autres = _autres_sources_bouche(cx, point_id, relais_id) if classe == "bouche" else []
    statut, motif = decider_statut(classe, relais.fiabilite if relais is not None else 0.0, len(autres),
                                   reglages().seuil_relais_fiable)
    oid = cx.execute(text("""
        INSERT INTO observation (point_id, relais_id, source, photo_chemin, eau_stagnante, dechets_visibles,
                                 avis_relais, classe_ia, confiance_ia, classe, statut, motif,
                                 valide_par, valide_le)
        VALUES (:p, :r, :src, :ph, :eau, :dech, :avis, :cia, :conf, :cl, :st, :mo,
                CASE WHEN :st = 'valide' THEN 'automatique' END, CASE WHEN :st = 'valide' THEN now() END)
        RETURNING id, recu_le
    """), {"p": point_id, "r": relais_id, "src": source, "ph": chemin, "eau": eau_stagnante,
           "dech": dechets_visibles, "avis": avis_relais, "cia": classe_ia, "conf": confiance,
           "cl": classe, "st": statut, "mo": motif}).one()
    if relais_id is not None:
        cx.execute(text("UPDATE relais SET nb_observations = nb_observations + 1 WHERE id = :r"), {"r": relais_id})
    # le recoupement valide aussi les signalements « bouché » restés en attente sur ce point
    if statut == "valide" and classe == "bouche" and autres:
        for autre in autres:
            _decider(cx, autre, "valide", "automatique", "recoupé par une deuxième source indépendante")
        if relais_id is not None:  # confirmé par une autre source : compte pour la fiabilité
            r = cx.execute(text("UPDATE relais SET nb_confirmees = nb_confirmees + 1 WHERE id = :r "
                                "RETURNING nb_confirmees, nb_rejetees"), {"r": relais_id}).one()
            cx.execute(text("UPDATE relais SET fiabilite = :f WHERE id = :r"),
                       {"f": fiabilite(r.nb_confirmees, r.nb_rejetees), "r": relais_id})
    journaliser(cx, "observation", f"{point_id} : {classe or '?'} -> {statut} ({motif}), {visages} visage(s) flouté(s)")
    return {"id": oid.id, "recu_le": oid.recu_le, "classe": classe, "classe_ia": classe_ia,
            "confiance_ia": confiance, "statut": statut, "motif": motif, "visages_floutes": visages}


def _decider(cx: Connection, obs_id: int, decision: str, par: str, motif: str, classe: str | None = None) -> None:
    o = cx.execute(text("SELECT id, relais_id, statut FROM observation WHERE id = :i"), {"i": obs_id}).one()
    cx.execute(text("""
        UPDATE observation SET statut = :d, valide_par = :par, valide_le = now(), motif = :m,
               classe = COALESCE(:cl, classe)
        WHERE id = :i
    """), {"d": decision, "par": par, "m": motif, "cl": classe, "i": obs_id})
    if o.relais_id is not None and o.statut == "a_valider":
        col = "nb_confirmees" if decision == "valide" else "nb_rejetees"
        r = cx.execute(text(f"UPDATE relais SET {col} = {col} + 1 WHERE id = :r RETURNING nb_confirmees, nb_rejetees"),
                       {"r": o.relais_id}).one()
        cx.execute(text("UPDATE relais SET fiabilite = :f WHERE id = :r"),
                   {"f": fiabilite(r.nb_confirmees, r.nb_rejetees), "r": o.relais_id})


def decider_observation(cx: Connection, obs_id: int, decision: str, operateur: str, classe: str | None = None) -> None:
    """Validation par un opérateur (S27). Met à jour la fiabilité du relais (S21)."""
    if decision not in ("valide", "rejete"):
        raise ValueError("décision : valide ou rejete")
    _decider(cx, obs_id, decision, operateur, f"décision de {operateur}", classe)
    journaliser(cx, "observation", f"observation {obs_id} : {decision} par {operateur}")
