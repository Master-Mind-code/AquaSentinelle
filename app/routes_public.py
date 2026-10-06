"""Pages publiques : état des zones, formulaire du relais (QR code), abonnement SMS, API ouverte."""
from __future__ import annotations

import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.db import transaction
from app.services import abonnes, pluviometre, points
from app.settings import reglages
from app.web import rendu, verifier_csrf
from src.canaux import canal

router = APIRouter()
TAILLE_MAX_PHOTO = 12 * 1024 * 1024
ID_POINT = re.compile(r"^[A-Z]{3}-\d{3}$")


def etat_zones(cx) -> list[dict]:
    return [dict(r._mapping) for r in cx.execute(text("""
        SELECT z.id, z.nom, z.region, z.type, ST_Y(z.centre) AS lat, ST_X(z.centre) AS lon,
               e.niveau AS niveau_annonce, s.niveau AS niveau_calcule, s.pluie_24h_mm, s.source, s.calcule_le
        FROM zone z
        LEFT JOIN etat_zone e ON e.zone_id = z.id
        LEFT JOIN LATERAL (SELECT niveau, pluie_24h_mm, source, calcule_le FROM score_risque
                           WHERE zone_id = z.id ORDER BY calcule_le DESC LIMIT 1) s ON true
        ORDER BY (z.region = 'District d''Abidjan') DESC, z.region, z.nom
    """))]


@router.get("/sante")
def sante():
    with transaction() as cx:
        cx.execute(text("SELECT 1"))
    return {"ok": True}


@router.get("/")
def accueil(request: Request):
    with transaction() as cx:
        zones = etat_zones(cx)
    return rendu(request, "accueil.html", zones=zones)


@router.get("/api/zones")
def api_zones():
    with transaction() as cx:
        return JSONResponse([{**z, "calcule_le": z["calcule_le"].isoformat() if z["calcule_le"] else None}
                             for z in etat_zones(cx)])


@router.get("/api/rivieres")
def api_rivieres():
    """Stations de rivière (cellules GloFAS), seuils de crue et pic de débit prévu sur 7 jours."""
    with transaction() as cx:
        rows = cx.execute(text("""
            SELECT r.zone_id, r.nom, z.nom AS ville, ST_Y(r.position) AS lat, ST_X(r.position) AS lon,
                   r.seuil_orange, r.seuil_rouge,
                   (SELECT max(debit_m3s) FROM mesure_debit m WHERE m.zone_id = r.zone_id AND m.prevision
                      AND m.jour BETWEEN current_date AND current_date + 7) AS pic_prevu
            FROM riviere r JOIN zone z ON z.id = r.zone_id ORDER BY r.nom
        """))
        return JSONResponse([dict(r._mapping) for r in rows])


@router.get("/api/points")
def api_points():
    """Statut public des points (sans photo : les photos restent réservées aux opérateurs)."""
    with transaction() as cx:
        rows = cx.execute(text("SELECT point_id, zone_id, lat, lon, classe, recu_le, perime, demo FROM statut_point"))
        return JSONResponse([{**dict(r._mapping), "recu_le": r.recu_le.isoformat() if r.recu_le else None}
                             for r in rows])


# --- Relais : le QR code peint ouvre /r/<identifiant> -------------------------------------------

def _point(cx, point_id: str):
    if not ID_POINT.match(point_id):
        raise HTTPException(404, "Point de contrôle inconnu")
    p = cx.execute(text("""
        SELECT p.id, p.description, p.demo, z.nom AS zone FROM point_controle p JOIN zone z ON z.id = p.zone_id
        WHERE p.id = :i AND p.actif
    """), {"i": point_id}).first()
    if p is None:
        raise HTTPException(404, "Point de contrôle inconnu")
    return p


@router.get("/r/{point_id}")
def formulaire_relais(request: Request, point_id: str):
    with transaction() as cx:
        p = _point(cx, point_id)
    return rendu(request, "relais.html", point=p, relais=request.session.get("relais"))


def _bool(v: str | None) -> bool | None:
    return {"oui": True, "non": False}.get(v or "")


@router.post("/r/{point_id}")
async def envoyer_relais(request: Request, point_id: str, csrf: str = Form(""), pseudo: str = Form(""),
                         telephone: str = Form(""), consentement: str = Form(""),
                         eau: str = Form(""), dechets: str = Form(""), avis: str = Form(""),
                         photo: UploadFile | None = File(None)):
    verifier_csrf(request, csrf)
    if consentement != "oui":
        raise HTTPException(400, "Merci d'accepter les conditions d'utilisation des photos.")
    donnees = await photo.read(TAILLE_MAX_PHOTO + 1) if photo and photo.filename else None
    if donnees is not None and len(donnees) > TAILLE_MAX_PHOTO:
        raise HTTPException(413, "Photo trop lourde (12 Mo maximum).")
    if not donnees and avis not in ("propre", "partiel", "bouche"):
        raise HTTPException(400, "Envoyez une photo ou indiquez l'état du caniveau.")

    def _enregistrer():
        with transaction() as cx:
            p = _point(cx, point_id)
            zone_id = cx.execute(text("SELECT zone_id FROM point_controle WHERE id = :i"), {"i": p.id}).scalar_one()
            r = points.trouver_ou_creer_relais(cx, pseudo.strip() or "anonyme", telephone.strip() or None,
                                               zone_id=zone_id, consentement=True)
            obs = points.enregistrer_observation(cx, p.id, r, donnees, _bool(eau), _bool(dechets),
                                                 avis if avis in ("propre", "partiel", "bouche") else None)
            return p, obs

    try:
        p, obs = await run_in_threadpool(_enregistrer)
    except ValueError as e:
        raise HTTPException(400, str(e))
    request.session["relais"] = {"pseudo": pseudo.strip()}
    return rendu(request, "relais_merci.html", point=p, obs=obs)


# --- Pluviomètre de quartier : relevé du matin par un relais ------------------------------------

@router.get("/pluviometre")
def page_pluviometre(request: Request):
    with transaction() as cx:
        zones = etat_zones(cx)
    return rendu(request, "pluviometre.html", zones=zones, relais=request.session.get("relais"), resultat=None)


@router.post("/pluviometre")
def envoyer_releve(request: Request, csrf: str = Form(""), zone_id: str = Form(...), pluie_mm: float = Form(...),
                   pseudo: str = Form(""), telephone: str = Form(""), consentement: str = Form("")):
    verifier_csrf(request, csrf)
    if consentement != "oui":
        raise HTTPException(400, "Merci d'accepter les conditions d'utilisation.")
    try:
        with transaction() as cx:
            r = points.trouver_ou_creer_relais(cx, pseudo.strip() or "anonyme", telephone.strip() or None,
                                               zone_id=zone_id, consentement=True)
            res = pluviometre.enregistrer_releve(cx, zone_id, r, pluie_mm)
            zones = etat_zones(cx)
    except ValueError as e:
        raise HTTPException(400, str(e))
    request.session["relais"] = {"pseudo": pseudo.strip()}
    return rendu(request, "pluviometre.html", zones=zones, relais=request.session["relais"], resultat=res,
                 pluie_mm=pluie_mm)


# --- Abonnement SMS (formulaire) et SMS entrants (mots-clés) -----------------------------------

@router.get("/abonnement")
def page_abonnement(request: Request, ok: str = ""):
    with transaction() as cx:
        zones = etat_zones(cx)
    return rendu(request, "abonnement.html", zones=zones, ok=ok)


@router.post("/abonnement")
def abonner(request: Request, csrf: str = Form(""), zone_id: str = Form(...), telephone: str = Form(...),
            consentement: str = Form(""), action: str = Form("abonner")):
    verifier_csrf(request, csrf)
    if not re.fullmatch(r"\+?[\d\s-]{8,16}", telephone.strip()):
        raise HTTPException(400, "Numéro de téléphone invalide.")
    with transaction() as cx:
        if action == "desabonner":
            abonnes.desabonner(cx, "sms", telephone, zone_id)
            return RedirectResponse("/abonnement?ok=desabonne", status_code=303)
        try:
            abonnes.abonner(cx, zone_id, "sms", telephone, consentement == "oui")
        except ValueError as e:
            raise HTTPException(400, str(e))
    return RedirectResponse("/abonnement?ok=abonne", status_code=303)


@router.post("/api/sms/entrant")
async def sms_entrant(request: Request):
    """Rappel d'Africa's Talking (SMS entrant) : champs « from » et « text »."""
    form = await request.form()
    numero, texte = str(form.get("from", "")), str(form.get("text", ""))
    if not numero:
        raise HTTPException(400, "champ from manquant")
    with transaction() as cx:
        reponse = abonnes.traiter_sms_entrant(cx, numero, texte)
    if reglages().sms_fournisseur:  # la réponse HTTP ne part pas en SMS : on l'envoie nous-mêmes
        try:
            await run_in_threadpool(canal("sms").envoyer, numero, reponse)
        except Exception:
            pass
    return PlainTextResponse(reponse)
