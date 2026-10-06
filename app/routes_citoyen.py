"""Pages citoyennes : consignes, signalement libre géolocalisé, carte publique, demande d'aide, capteurs (API)."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.db import transaction
from app.services import aide, capteurs, historique, points, signalements
from app.web import limite_atteinte, rendu, verifier_csrf

router = APIRouter()
TAILLE_MAX_PHOTO = 12 * 1024 * 1024


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _flottant(v: str) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


# --- Consignes et prévention ---------------------------------------------------------------------

@router.get("/prevention")
def prevention(request: Request):
    return rendu(request, "prevention.html")


# --- Carte publique ------------------------------------------------------------------------------

@router.get("/carte")
def carte_publique(request: Request):
    return rendu(request, "carte_publique.html", types=signalements.TYPES)


@router.get("/api/carte")
def api_carte():
    with transaction() as cx:
        lieux = [dict(r._mapping) for r in cx.execute(text("""
            SELECT id, nom, type, capacite, description, demo, ST_Y(position) AS lat, ST_X(position) AS lon
            FROM lieu_sur WHERE actif ORDER BY nom
        """))]
        sig = signalements.publics(cx)
        cap = [dict(r._mapping) for r in cx.execute(text("""
            SELECT c.id, c.nom, ST_Y(c.position) AS lat, ST_X(c.position) AS lon, c.seuil_orange_cm, c.seuil_rouge_cm,
                   c.simule, m.niveau_cm, m.le
            FROM capteur c LEFT JOIN LATERAL (SELECT niveau_cm, le FROM mesure_niveau WHERE capteur_id = c.id
                                              ORDER BY le DESC, id DESC LIMIT 1) m ON true
            WHERE c.actif
        """))]
    for s in sig:
        s["libelle"] = signalements.TYPES[s["type"]]
        s["recu_le"], s["expire_le"] = s["recu_le"].isoformat(), s["expire_le"].isoformat()
    for c in cap:
        c["le"] = c["le"].isoformat() if c["le"] else None
    return JSONResponse({"lieux": lieux, "signalements": sig, "capteurs": cap, "historique": historique.par_zone()})


# --- Signalement libre géolocalisé ---------------------------------------------------------------

@router.get("/signaler")
def page_signaler(request: Request):
    return rendu(request, "signaler.html", types=signalements.TYPES, relais=request.session.get("relais"))


@router.post("/signaler")
async def envoyer_signalement(request: Request, csrf: str = Form(""), type: str = Form(...), lat: str = Form(""),
                              lon: str = Form(""), precision: str = Form(""), description: str = Form(""),
                              pseudo: str = Form(""), telephone: str = Form(""), consentement: str = Form(""),
                              photo: UploadFile | None = File(None)):
    verifier_csrf(request, csrf)
    if limite_atteinte(f"signaler:{_ip(request)}", 10, 600):
        raise HTTPException(429, "Trop de signalements depuis cet appareil. Réessayez dans quelques minutes.")
    if consentement != "oui":
        raise HTTPException(400, "Merci d'accepter les conditions d'utilisation.")
    la, lo = _flottant(lat), _flottant(lon)
    if la is None or lo is None:
        raise HTTPException(400, "Position manquante : utilisez « Ma position » ou touchez la carte.")
    donnees = await photo.read(TAILLE_MAX_PHOTO + 1) if photo and photo.filename else None
    if donnees is not None and len(donnees) > TAILLE_MAX_PHOTO:
        raise HTTPException(413, "Photo trop lourde (12 Mo maximum).")

    def _enregistrer():
        with transaction() as cx:
            r = points.trouver_ou_creer_relais(cx, pseudo.strip() or "anonyme", telephone.strip() or None,
                                               consentement=True)
            return signalements.creer(cx, type, la, lo, _flottant(precision), description, donnees, r)

    try:
        res = await run_in_threadpool(_enregistrer)
    except ValueError as e:
        raise HTTPException(400, str(e))
    request.session["relais"] = {"pseudo": pseudo.strip()}
    return rendu(request, "signaler_merci.html", res=res, libelle=signalements.TYPES[type])


# --- Demande d'aide d'urgence --------------------------------------------------------------------

@router.get("/aide")
def page_aide(request: Request):
    return rendu(request, "aide.html", situations=aide.SITUATIONS)


@router.post("/aide")
def envoyer_aide(request: Request, csrf: str = Form(""), situation: str = Form(...), nb_personnes: str = Form(""),
                 description: str = Form(""), lat: str = Form(""), lon: str = Form(""), precision: str = Form(""),
                 lieu_texte: str = Form(""), telephone: str = Form("")):
    verifier_csrf(request, csrf)
    if limite_atteinte(f"aide:{_ip(request)}", 5, 600):
        raise HTTPException(429, "Trop de demandes depuis cet appareil. En cas de danger, appelez le 180.")
    try:
        nb = int(nb_personnes) if nb_personnes.strip() else None
        with transaction() as cx:
            res = aide.creer(cx, situation, nb, description, _flottant(lat), _flottant(lon), _flottant(precision),
                             lieu_texte, telephone.strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/aide/{res['jeton']}", status_code=303)


@router.get("/aide/{jeton}")
def suivi_aide(request: Request, jeton: str):
    with transaction() as cx:
        d = aide.par_jeton(cx, jeton)
    if d is None:
        raise HTTPException(404, "Demande introuvable")
    return rendu(request, "aide_suivi.html", d=d, situations=aide.SITUATIONS, statuts=aide.STATUTS)


# --- API des capteurs de niveau d'eau ------------------------------------------------------------

class Mesure(BaseModel):
    niveau_cm: float
    batterie_v: float | None = None


@router.post("/api/capteurs/{capteur_id}/mesures")
def recevoir_mesure(capteur_id: str, mesure: Mesure, x_cle_api: str = Header("")):
    try:
        with transaction() as cx:
            return capteurs.recevoir(cx, capteur_id, x_cle_api, mesure.niveau_cm, mesure.batterie_v)
    except PermissionError:
        raise HTTPException(401, "capteur inconnu ou clé invalide")
    except ValueError as e:
        raise HTTPException(422, str(e))
