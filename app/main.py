"""Application web : formulaire des relais, abonnements, tableau de bord des opérateurs, API JSON.

    uvicorn app.main:app --reload        (en local, avec la base Docker sur le port 5434)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from app import routes_citoyen, routes_operateur, routes_public, routes_terrain
from app.cycle import cycle_complet
from app.initialisation import initialiser
from app.settings import ROOT, reglages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("aquasentinelle")


async def _planificateur() -> None:
    """S4 : un cycle complet toutes les PLANIFICATEUR_MINUTES. Une erreur n'arrête pas la boucle."""
    while True:
        try:
            bilan = await run_in_threadpool(cycle_complet)
            log.info("cycle terminé : %s", {z: v.get("score", {}).get("niveau") for z, v in bilan["zones"].items()})
        except Exception:
            log.exception("échec du cycle")
        await asyncio.sleep(reglages().planificateur_minutes * 60)


async def _analyse_photos() -> None:
    """Second regard du modèle de vision (Ollama) sur les nouvelles photos, toutes les 15 s."""
    from app.services import ia_suivi, ia_vision
    while True:
        try:
            if await run_in_threadpool(ia_vision.disponible):
                n = await run_in_threadpool(ia_suivi.traiter_en_attente)
                if n:
                    log.info("IA vision : %s photo(s) analysée(s)", n)
        except Exception:
            log.exception("échec de l'analyse des photos")
        await asyncio.sleep(15)


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    await run_in_threadpool(initialiser)
    taches = []
    if reglages().planificateur_actif:
        taches.append(asyncio.create_task(_planificateur()))
    if reglages().ia_vision_active:
        taches.append(asyncio.create_task(_analyse_photos()))
    yield
    for t in taches:
        t.cancel()


app = FastAPI(title="AquaSentinelle CI", lifespan=cycle_de_vie, docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=reglages().secret_key, session_cookie="aqua_session",
                   max_age=8 * 3600, same_site="lax", https_only=reglages().base_url.startswith("https"))
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.include_router(routes_public.router)
app.include_router(routes_operateur.router)
app.include_router(routes_citoyen.router)
app.include_router(routes_terrain.router)


from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from fastapi.exception_handlers import http_exception_handler  # noqa: E402


@app.exception_handler(StarletteHTTPException)
async def erreur_lisible(request: Request, exc: StarletteHTTPException):
    """Les pages affichent l'erreur en clair ; l'API et les redirections gardent le comportement standard."""
    if request.url.path.startswith("/api/") or exc.status_code in (301, 302, 303, 307) or             "text/html" not in request.headers.get("accept", ""):
        return await http_exception_handler(request, exc)
    from app.web import rendu
    message = exc.detail if isinstance(exc.detail, str) else "Une erreur est survenue."
    if exc.status_code == 404:
        message = "Cette page n'existe pas ou n'existe plus."
    r = rendu(request, "erreur.html", code=exc.status_code, message=message,
              urgence=request.url.path.startswith(("/aide", "/signaler")))
    r.status_code = exc.status_code
    return r


from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.exception_handlers import request_validation_exception_handler  # noqa: E402


@app.exception_handler(RequestValidationError)
async def formulaire_incomplet(request: Request, exc: RequestValidationError):
    """Champ obligatoire absent ou mal rempli : page lisible plutôt que du JSON (sauf pour l'API)."""
    if request.url.path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
        return await request_validation_exception_handler(request, exc)
    from app.web import rendu
    r = rendu(request, "erreur.html", code=400, message="Formulaire incomplet : merci de remplir les champs demandés.",
              urgence=request.url.path.startswith(("/aide", "/signaler")))
    r.status_code = 400
    return r


@app.middleware("http")
async def entetes_securite(request: Request, call_next):
    r = await call_next(request)
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("X-Frame-Options", "DENY")
    # pas « same-origin » : les tuiles OpenStreetMap exigent un Referer (sinon 403 « Access blocked »)
    r.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return r
