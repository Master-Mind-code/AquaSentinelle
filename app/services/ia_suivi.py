"""Analyse en arrière-plan des photos des points de contrôle par le modèle de vision (voir ia_vision.py).

Appelé toutes les 15 s par l'application. Le formulaire du relais répond tout de suite ; l'avis de l'IA arrive
quelques secondes plus tard. Trois tentatives au plus par photo (Ollama arrêté, délai dépassé…).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import journaliser, transaction
from app.services import ia, ia_vision
from app.settings import reglages
from src.recoupement import reaction_avis_ia

log = logging.getLogger("aquasentinelle.ia")
MAX_TENTATIVES = 3


def traiter_en_attente(limite: int = 5, analyser=None) -> int:
    """Analyse jusqu'à « limite » photos en attente. « analyser » est remplaçable (tests)."""
    analyser = analyser or ia_vision.analyser
    with transaction() as cx:
        a_faire = cx.execute(text("""
            SELECT id, photo_chemin FROM observation
            WHERE photo_chemin IS NOT NULL AND ia_analyse_le IS NULL AND ia_tentatives < :m
            ORDER BY recu_le LIMIT :l
        """), {"m": MAX_TENTATIVES, "l": limite}).all()
    n = 0
    for obs in a_faire:
        try:
            avis = analyser((reglages().dossier_photos / obs.photo_chemin).read_bytes())
        except Exception as e:
            with transaction() as cx:
                cx.execute(text("UPDATE observation SET ia_tentatives = ia_tentatives + 1 WHERE id = :i"), {"i": obs.id})
            log.warning("analyse IA de l'observation %s impossible : %s", obs.id, e)
            continue
        with transaction() as cx:
            enregistrer_avis(cx, obs.id, avis)
        n += 1
    return n


def enregistrer_avis(cx, obs_id: int, avis: dict) -> dict:
    o = cx.execute(text("SELECT statut, valide_par, classe, classe_ia FROM observation WHERE id = :i FOR UPDATE"),
                   {"i": obs_id}).one()
    statut, motif, classe = reaction_avis_ia(o.statut, o.valide_par, o.classe, avis)
    # MobileNet (entraîné sur nos photos) reste prioritaire s'il a déjà classé la photo
    mobilenet = o.classe_ia is not None and ia.disponible()
    cx.execute(text("""
        UPDATE observation SET modele_ia = :m, obstruction_pct_ia = :p, justification_ia = :j, est_caniveau_ia = :c,
               personne_visible_ia = :pv, ia_analyse_le = now(), ia_tentatives = ia_tentatives + 1,
               classe_ia = CASE WHEN :mobilenet THEN classe_ia ELSE :cia END,
               confiance_ia = CASE WHEN :mobilenet THEN confiance_ia ELSE :conf END,
               classe = :classe, statut = :statut,
               motif = COALESCE(:motif, motif),
               valide_par = CASE WHEN :statut = 'a_valider' THEN NULL ELSE valide_par END
        WHERE id = :i
    """), {"m": avis["modele"], "p": avis.get("obstruction_pct"), "j": avis["justification"], "c": avis["est_caniveau"],
           "pv": avis["personne_visible"], "mobilenet": mobilenet, "cia": avis["classe"], "conf": avis["confiance"],
           "classe": classe, "statut": statut, "motif": motif, "i": obs_id})
    if motif:
        journaliser(cx, "ia", f"observation {obs_id} : {motif}")
    return {"statut": statut, "motif": motif, "classe": classe}
