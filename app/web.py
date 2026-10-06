"""Outils communs aux routes : gabarits, session opérateur, jeton CSRF, limitation des connexions."""
from __future__ import annotations

import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import text

from app.settings import ROOT, reglages

gabarits = Jinja2Templates(directory=ROOT / "app" / "templates")
NIVEAUX = {"vert": "Vert", "orange": "Orange", "rouge": "Rouge"}
CLASSES = {"propre": "Propre", "partiel": "Partiellement bouché", "bouche": "Bouché"}
STATUTS = {"envoyee": "Envoyée", "annulee": "Annulée (pluie retombée)", "rejetee": "Rejetée", "en_attente": "En attente",
           "escaladee": "Escaladée", "valide": "Validé", "rejete": "Rejeté", "a_valider": "À vérifier",
           "ok": "Livré", "echec": "Échec", "bloque_doublon": "Bloqué (doublon)", "bloque_plafond": "Bloqué (plafond du jour)"}
LECTURES = {"observee": "pluie observée", "prevision": "pluie prévue"}


def icone(nom: str, classe: str = "", titre: str = "") -> Markup:
    """Icône Lucide du sprite app/static/icones.svg. Décorative (aria-hidden) sauf si un titre est donné."""
    aria = f'role="img" aria-label="{escape(titre)}"' if titre else 'aria-hidden="true"'
    return Markup(f'<svg class="ic {escape(classe)}" {aria}><use href="/static/icones.svg#{escape(nom)}"></use></svg>')


gabarits.env.globals.update(NIVEAUX=NIVEAUX, CLASSES=CLASSES, STATUTS=STATUTS, LECTURES=LECTURES, icone=icone)


def duree(ms: int | None) -> str:
    """3108222 -> « 52 min » ; 98 -> « 98 ms »."""
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms} ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f} s"
    if s < 3600:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


gabarits.env.filters["duree"] = duree


def unite(source: str | None) -> str:
    """Unité de la valeur retenue par le score : débit (GloFAS), hauteur d'eau (capteur) ou pluie."""
    if source == "glofas":
        return "m³/s"
    if source and source.startswith("CAP"):
        return "cm"
    return "mm"


gabarits.env.globals["unite"] = unite


def compteurs_navigation() -> dict:
    """Pastilles de la barre latérale : ce qui attend une décision humaine."""
    from app.db import transaction
    with transaction() as cx:
        r = cx.execute(text("""
            SELECT (SELECT count(*) FROM alerte WHERE statut IN ('en_attente','escaladee')) AS alertes,
                   (SELECT count(*) FROM observation WHERE statut = 'a_valider')
                 + (SELECT count(*) FROM releve_pluviometre WHERE statut = 'a_valider')
                 + (SELECT count(*) FROM signalement WHERE statut = 'a_valider') AS signalements,
                   (SELECT count(*) FROM demande_aide WHERE statut IN ('recue','transmise')) AS aide
        """)).one()
    return {"alertes": r.alertes, "signalements": r.signalements, "aide": r.aide}


def jeton_csrf(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def verifier_csrf(request: Request, jeton: str) -> None:
    if not jeton or not secrets.compare_digest(jeton, request.session.get("csrf", "")):
        raise HTTPException(400, "Jeton de formulaire invalide : rechargez la page.")


def rendu(request: Request, gabarit: str, **ctx):
    op = request.session.get("op")
    ctx.update(request=request, csrf=jeton_csrf(request), op=op, chemin=request.url.path,
               base_url=reglages().base_url, bot=reglages().telegram_bot_nom,
               nav=compteurs_navigation() if op else {})
    return gabarits.TemplateResponse(request, gabarit, ctx)


def operateur(request: Request) -> dict:
    op = request.session.get("op")
    if not op:
        raise HTTPException(303, headers={"Location": f"/connexion?suite={request.url.path}"})
    return op


def admin(request: Request) -> dict:
    op = operateur(request)
    if op.get("role") != "admin":
        raise HTTPException(403, "Réservé aux administrateurs.")
    return op


_echecs: dict[str, list[float]] = defaultdict(list)


def trop_d_echecs(ip: str, fenetre: int = 600, maximum: int = 5) -> bool:
    _echecs[ip] = [t for t in _echecs[ip] if time.time() - t < fenetre]
    return len(_echecs[ip]) >= maximum


def noter_echec(ip: str) -> None:
    _echecs[ip].append(time.time())


_envois: dict[str, list[float]] = defaultdict(list)


def limite_atteinte(cle: str, maximum: int, fenetre_s: int) -> bool:
    """Compte un envoi pour « cle » et dit si la limite est dépassée (anti-abus des formulaires publics)."""
    _envois[cle] = [t for t in _envois[cle] if time.time() - t < fenetre_s]
    if len(_envois[cle]) >= maximum:
        return True
    _envois[cle].append(time.time())
    return False


def noter_reussite(ip: str) -> None:
    """Une connexion réussie efface les échecs passés : des fautes de frappe espacées ne bloquent pas un opérateur."""
    _echecs.pop(ip, None)
