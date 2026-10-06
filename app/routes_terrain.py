"""Espace opérateur, volet terrain : demandes d'aide, signalements libres, lieux sûrs, capteurs."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import text

from app.db import journaliser, transaction
from app.services import aide, capteurs, pluie, signalements
from app.services.signalements import zone_proche
from app.settings import reglages
from app.web import admin, operateur, rendu, verifier_csrf

router = APIRouter()
TYPES_LIEUX = {"regroupement": "Site de regroupement", "ecole": "École", "mairie": "Mairie", "sante": "Centre de santé",
               "lieu_de_culte": "Lieu de culte", "autre": "Autre"}


def _coordonnees(lat: float, lon: float) -> None:
    if not (4.0 < lat < 11.0 and -9.0 < lon < -2.0):
        raise HTTPException(400, "Coordonnées hors de Côte d'Ivoire.")


# --- Demandes d'aide ---------------------------------------------------------------------------

@router.get("/operateur/aide")
def page_aide(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        demandes = cx.execute(text("""
            SELECT d.*, ST_Y(d.position) AS lat, ST_X(d.position) AS lon, z.nom AS zone
            FROM demande_aide d LEFT JOIN zone z ON z.id = d.zone_id
            ORDER BY (d.statut IN ('recue','transmise')) DESC, d.recu_le DESC LIMIT 100
        """)).all()
    return rendu(request, "op_aide.html", demandes=demandes, situations=aide.SITUATIONS, statuts=aide.STATUTS)


@router.post("/operateur/aide/{did}")
def statut_aide(request: Request, did: int, csrf: str = Form(""), statut: str = Form(...), note: str = Form(""),
                op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        try:
            aide.changer_statut(cx, did, statut, op["identifiant"], note)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return RedirectResponse("/operateur/aide", status_code=303)


# --- Signalements libres -------------------------------------------------------------------------

@router.post("/operateur/signalements-libres/{sid}")
def decider_signalement(request: Request, sid: int, csrf: str = Form(""), decision: str = Form(...),
                        op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        signalements.decider(cx, sid, decision, op["identifiant"])
        journaliser(cx, "signalement", f"signalement {sid} : {decision} par {op['identifiant']}")
    return RedirectResponse("/operateur/signalements", status_code=303)


@router.get("/operateur/photos-signalements/{nom}")
def photo_signalement(nom: str, op=Depends(operateur)):
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", nom):
        raise HTTPException(404)
    f = reglages().dossier_photos / "signalements" / nom
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# --- Lieux sûrs ----------------------------------------------------------------------------------

@router.get("/operateur/lieux")
def page_lieux(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        lieux = cx.execute(text("""
            SELECT l.*, ST_Y(l.position) AS lat, ST_X(l.position) AS lon, z.nom AS zone
            FROM lieu_sur l LEFT JOIN zone z ON z.id = l.zone_id ORDER BY l.actif DESC, z.nom, l.nom
        """)).all()
    return rendu(request, "op_lieux.html", lieux=lieux, types=TYPES_LIEUX)


@router.post("/operateur/lieux")
def ajouter_lieu(request: Request, csrf: str = Form(""), nom: str = Form(...), type: str = Form(...),
                 lat: float = Form(...), lon: float = Form(...), capacite: str = Form(""), description: str = Form(""),
                 op=Depends(operateur)):
    verifier_csrf(request, csrf)
    _coordonnees(lat, lon)
    if type not in TYPES_LIEUX:
        raise HTTPException(400, "type de lieu inconnu")
    with transaction() as cx:
        cx.execute(text("""
            INSERT INTO lieu_sur (nom, type, zone_id, position, capacite, description)
            VALUES (:n, :t, :z, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :c, :d)
        """), {"n": nom[:120], "t": type, "z": zone_proche(cx, lat, lon), "lat": lat, "lon": lon,
               "c": int(capacite) if capacite.strip().isdigit() else None, "d": description[:300]})
        journaliser(cx, "lieu", f"lieu sûr « {nom[:60]} » ajouté par {op['identifiant']}")
    return RedirectResponse("/operateur/lieux", status_code=303)


@router.post("/operateur/lieux/{lid}/basculer")
def basculer_lieu(request: Request, lid: int, csrf: str = Form(""), op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        cx.execute(text("UPDATE lieu_sur SET actif = NOT actif WHERE id = :i"), {"i": lid})
    return RedirectResponse("/operateur/lieux", status_code=303)


# --- Capteurs ------------------------------------------------------------------------------------

def _liste_capteurs(cx):
    return cx.execute(text("""
        SELECT c.*, ST_Y(c.position) AS lat, ST_X(c.position) AS lon, z.nom AS zone, m.niveau_cm, m.le, m.batterie_v,
               (c.dernier_signal IS NOT NULL AND c.dernier_signal < now() - make_interval(mins => 60)) AS muet
        FROM capteur c JOIN zone z ON z.id = c.zone_id
        LEFT JOIN LATERAL (SELECT niveau_cm, le, batterie_v FROM mesure_niveau WHERE capteur_id = c.id
                           ORDER BY le DESC, id DESC LIMIT 1) m ON true
        ORDER BY c.actif DESC, c.id
    """)).all()


@router.get("/operateur/capteurs")
def page_capteurs(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        return rendu(request, "op_capteurs.html", capteurs=_liste_capteurs(cx), zones=pluie.zones(cx), cle=None)


@router.post("/operateur/capteurs")
def ajouter_capteur(request: Request, csrf: str = Form(""), capteur_id: str = Form(...), nom: str = Form(...),
                    zone_id: str = Form(...), lat: float = Form(...), lon: float = Form(...),
                    seuil_orange_cm: float = Form(...), seuil_rouge_cm: float = Form(...), simule: str = Form(""),
                    op=Depends(admin)):
    verifier_csrf(request, csrf)
    _coordonnees(lat, lon)
    capteur_id = capteur_id.strip().upper()
    if not re.fullmatch(r"CAP-[A-Z0-9-]{2,20}", capteur_id):
        raise HTTPException(400, "Identifiant : CAP- suivi de lettres, chiffres ou tirets (ex. CAP-ATT-01).")
    with transaction() as cx:
        try:
            cle = capteurs.creer(cx, capteur_id, nom[:80], zone_id, lat, lon, seuil_orange_cm, seuil_rouge_cm, simule == "oui")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return rendu(request, "op_capteurs.html", capteurs=_liste_capteurs(cx), zones=pluie.zones(cx),
                     cle={"id": capteur_id, "valeur": cle})


@router.post("/operateur/capteurs/{cid}/basculer")
def basculer_capteur(request: Request, cid: str, csrf: str = Form(""), op=Depends(admin)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        cx.execute(text("UPDATE capteur SET actif = NOT actif WHERE id = :i"), {"i": cid})
    return RedirectResponse("/operateur/capteurs", status_code=303)
