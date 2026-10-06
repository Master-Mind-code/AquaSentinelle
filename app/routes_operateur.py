"""Espace opérateur (S26-S30) : carte, validations, alertes, scores, points et QR, étiquetage, simulation."""
from __future__ import annotations

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.cycle import cycle_complet, traiter_zone
from app.db import journaliser, transaction
from app.securite import hacher_mot_de_passe, verifier_mot_de_passe
from app.services import alertes, curage, ia, pluie, pluviometre, points
from app.settings import reglages
from app.web import admin, noter_echec, noter_reussite, operateur, rendu, trop_d_echecs, verifier_csrf
from src.accord import interpretation, kappa_cohen, matrice_confusion

router = APIRouter()
CHEMIN_PHOTO = re.compile(r"^[A-Z]{3}-\d{3}/[0-9a-f]{32}\.jpg$")


# --- Connexion (S30) -----------------------------------------------------------------------------

@router.get("/connexion")
def page_connexion(request: Request, suite: str = "/operateur"):
    return rendu(request, "connexion.html", suite=suite if suite.startswith("/operateur") else "/operateur")


@router.post("/connexion")
def connexion(request: Request, csrf: str = Form(""), identifiant: str = Form(...), mot_de_passe: str = Form(...),
              suite: str = Form("/operateur")):
    verifier_csrf(request, csrf)
    ip = request.client.host if request.client else "?"
    if trop_d_echecs(ip):
        raise HTTPException(429, "Trop de tentatives. Réessayez dans 10 minutes.")
    with transaction() as cx:
        o = cx.execute(text("SELECT * FROM operateur WHERE identifiant = :i AND actif"), {"i": identifiant}).first()
        if o is None or not verifier_mot_de_passe(mot_de_passe, o.mot_de_passe_hash):
            noter_echec(ip)
            journaliser(cx, "connexion", f"échec pour « {identifiant[:40]} » depuis {ip}")
            return rendu(request, "connexion.html", suite=suite, erreur="Identifiant ou mot de passe incorrect.")
        journaliser(cx, "connexion", f"{o.identifiant} connecté depuis {ip}")
    noter_reussite(ip)
    request.session.clear()
    request.session["op"] = {"identifiant": o.identifiant, "nom": o.nom, "role": o.role}
    return RedirectResponse(suite if suite.startswith("/operateur") else "/operateur", status_code=303)


@router.post("/deconnexion")
def deconnexion(request: Request, csrf: str = Form("")):
    verifier_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# --- Carte (S26) ---------------------------------------------------------------------------------

@router.get("/operateur")
def carte(request: Request, op=Depends(operateur)):
    from app.routes_public import etat_zones
    rang = {"rouge": 0, "orange": 1, "vert": 2, None: 3}
    with transaction() as cx:
        zones = etat_zones(cx)
        a_curer = curage.points_a_curer(cx)
        derniere_collecte = cx.execute(text("SELECT max(le) FROM journal WHERE type = 'collecte'")).scalar()
        crues = cx.execute(text("""
            SELECT count(*) FROM riviere r WHERE r.seuil_orange IS NOT NULL AND
              (SELECT max(debit_m3s) FROM mesure_debit m WHERE m.zone_id = r.zone_id AND m.prevision
                 AND m.jour BETWEEN current_date AND current_date + 7) >= r.seuil_orange
        """)).scalar_one()
        points_suivis = cx.execute(text("SELECT count(*) FILTER (WHERE NOT perime), count(*) FROM statut_point")).one()
    for z in zones:
        z["niveau"] = z["niveau_annonce"] or z["niveau_calcule"]
    zones.sort(key=lambda z: (rang.get(z["niveau"], 3), z["nom"]))
    repartition = {n: sum(1 for z in zones if z["niveau"] == n) for n in ("rouge", "orange", "vert")}
    return rendu(request, "carte.html", zones=zones, repartition=repartition, a_curer=a_curer,
                 derniere_collecte=derniere_collecte, crues=crues, points_suivis=points_suivis)


@router.get("/operateur/api/points")
def api_points_operateur(op=Depends(operateur)):
    with transaction() as cx:
        rows = cx.execute(text("SELECT * FROM statut_point ORDER BY point_id"))
        return JSONResponse([{**dict(r._mapping), "recu_le": r.recu_le.isoformat() if r.recu_le else None,
                              "photo": f"/operateur/photos/{r.photo_chemin}" if r.photo_chemin else None}
                             for r in rows])


@router.get("/operateur/photos/{point_id}/{nom}")
def photo(point_id: str, nom: str, op=Depends(operateur)):
    chemin = f"{point_id}/{nom}"
    if not CHEMIN_PHOTO.match(chemin):
        raise HTTPException(404)
    f = reglages().dossier_photos / point_id / nom
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# --- Signalements des relais (S27) ---------------------------------------------------------------

@router.get("/operateur/signalements")
def signalements(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        obs = cx.execute(text("""
            SELECT o.*, r.pseudo, r.fiabilite, p.zone_id, p.demo FROM observation o
            JOIN point_controle p ON p.id = o.point_id LEFT JOIN relais r ON r.id = o.relais_id
            WHERE o.statut = 'a_valider' ORDER BY o.recu_le
        """)).all()
        recents = cx.execute(text("""
            SELECT o.id, o.point_id, o.classe, o.statut, o.motif, o.valide_par, o.recu_le, r.pseudo
            FROM observation o LEFT JOIN relais r ON r.id = o.relais_id
            WHERE o.statut <> 'a_valider' ORDER BY o.recu_le DESC LIMIT 30
        """)).all()
        libres = cx.execute(text("""
            SELECT s.*, ST_Y(s.position) AS lat, ST_X(s.position) AS lon, r.pseudo, r.fiabilite, z.nom AS zone
            FROM signalement s LEFT JOIN relais r ON r.id = s.relais_id LEFT JOIN zone z ON z.id = s.zone_id
            WHERE s.statut = 'a_valider' ORDER BY s.recu_le
        """)).all()
        releves = cx.execute(text("""
            SELECT v.*, z.nom, r.pseudo, r.fiabilite FROM releve_pluviometre v JOIN zone z ON z.id = v.zone_id
            LEFT JOIN relais r ON r.id = v.relais_id WHERE v.statut = 'a_valider' ORDER BY v.recu_le
        """)).all()
        relais = cx.execute(text("""
            SELECT pseudo, fiabilite, nb_observations, nb_confirmees, nb_rejetees FROM relais
            ORDER BY nb_observations DESC LIMIT 30
        """)).all()
    from app.services.signalements import TYPES as TYPES_SIGNALEMENT
    return rendu(request, "signalements.html", obs=obs, recents=recents, relais=relais, releves=releves,
                 libres=libres, types_signalement=TYPES_SIGNALEMENT)


@router.post("/operateur/signalements/{obs_id}")
def decider_signalement(request: Request, obs_id: int, csrf: str = Form(""), decision: str = Form(...),
                        classe: str = Form(""), op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        points.decider_observation(cx, obs_id, decision, op["identifiant"],
                                   classe if classe in ("propre", "partiel", "bouche") else None)
    return RedirectResponse("/operateur/signalements", status_code=303)


@router.post("/operateur/releves/{releve_id}")
def decider_releve(request: Request, releve_id: int, csrf: str = Form(""), decision: str = Form(...),
                   op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        pluviometre.decider_releve_operateur(cx, releve_id, decision, op["identifiant"])
    return RedirectResponse("/operateur/signalements", status_code=303)


# --- Alertes : validation des rouges (S28) et historique (S29) -----------------------------------

@router.get("/operateur/alertes")
def page_alertes(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        attente = cx.execute(text("""
            SELECT a.*, z.nom, s.pluie_24h_mm, s.entrees FROM alerte a JOIN zone z ON z.id = a.zone_id
            LEFT JOIN score_risque s ON s.id = a.score_id
            WHERE a.statut IN ('en_attente','escaladee') ORDER BY a.cree_le
        """)).all()
        historique = cx.execute(text("""
            SELECT a.*, z.nom,
              (SELECT count(*) FROM envoi e WHERE e.alerte_id = a.id AND e.statut = 'echec') AS echecs,
              (SELECT count(*) FROM envoi e WHERE e.alerte_id = a.id AND e.statut LIKE 'bloque%') AS bloques
            FROM alerte a JOIN zone z ON z.id = a.zone_id
            WHERE a.statut NOT IN ('en_attente','escaladee') ORDER BY a.cree_le DESC LIMIT 100
        """)).all()
        latence = cx.execute(text("""
            SELECT round(avg(latence_ms)) AS moy, max(latence_ms) AS maxi, count(*) AS n FROM alerte
            WHERE latence_ms IS NOT NULL AND validee_par IS NULL
        """)).one()
    return rendu(request, "alertes.html", attente=attente, historique=historique, latence=latence)


@router.post("/operateur/alertes/{alerte_id}")
def decider_alerte(request: Request, alerte_id: int, csrf: str = Form(""), decision: str = Form(...),
                   op=Depends(operateur)):
    verifier_csrf(request, csrf)
    with transaction() as cx:
        try:
            if decision == "valider":
                alertes.valider(cx, alerte_id, op["identifiant"])
            elif decision == "rejeter":
                alertes.rejeter(cx, alerte_id, op["identifiant"])
            else:
                raise HTTPException(400, "décision inconnue")
        except ValueError as e:
            raise HTTPException(409, str(e))
    return RedirectResponse("/operateur/alertes", status_code=303)


@router.get("/operateur/alertes/{alerte_id}/envois")
def envois(request: Request, alerte_id: int, op=Depends(operateur)):
    with transaction() as cx:
        a = cx.execute(text("SELECT a.*, z.nom FROM alerte a JOIN zone z ON z.id = a.zone_id WHERE a.id = :i"),
                       {"i": alerte_id}).first()
        if a is None:
            raise HTTPException(404)
        lignes = cx.execute(text("SELECT * FROM envoi WHERE alerte_id = :i ORDER BY le"), {"i": alerte_id}).all()
    return rendu(request, "envois.html", a=a, envois=lignes)


# --- Scores (S29) --------------------------------------------------------------------------------

@router.get("/operateur/scores")
def scores(request: Request, zone: str = "", op=Depends(operateur)):
    with transaction() as cx:
        zones = pluie.zones(cx)
        zone = zone or (zones[0]["id"] if zones else "")
        historique = cx.execute(text("""
            SELECT * FROM score_risque WHERE zone_id = :z ORDER BY calcule_le DESC LIMIT 60
        """), {"z": zone}).all()
        mesures = cx.execute(text("""
            SELECT jour, source, pluie_mm FROM mesure_pluie WHERE zone_id = :z AND jour > current_date - 45
            ORDER BY jour
        """), {"z": zone}).all()
        riviere = cx.execute(text("SELECT nom, seuil_orange, seuil_rouge FROM riviere WHERE zone_id = :z"), {"z": zone}).first()
        debits = cx.execute(text("""
            SELECT jour, debit_m3s FROM mesure_debit WHERE zone_id = :z AND prevision AND jour > current_date - 45
            ORDER BY jour
        """), {"z": zone}).all()
    serie = {}
    for m in mesures:
        serie.setdefault(m.source, []).append({"jour": m.jour.isoformat(), "mm": m.pluie_mm})
    return rendu(request, "scores.html", zones=zones, zone=zone, historique=historique, riviere=riviere,
                 debits=debits, serie=json.dumps(serie), json=json)


# --- Points de contrôle et QR (S18) --------------------------------------------------------------

@router.get("/operateur/points")
def page_points(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        pts = cx.execute(text("SELECT * FROM statut_point ORDER BY point_id")).all()
        zones = pluie.zones(cx)
    return rendu(request, "points.html", points=pts, zones=zones)


@router.post("/operateur/points")
def ajouter_point(request: Request, csrf: str = Form(""), zone_id: str = Form(...), lat: float = Form(...),
                  lon: float = Form(...), description: str = Form(""), op=Depends(operateur)):
    verifier_csrf(request, csrf)
    if not (4.0 < lat < 11.0 and -9.0 < lon < -2.0):
        raise HTTPException(400, "Coordonnées hors de Côte d'Ivoire.")
    with transaction() as cx:
        pid = points.creer_point(cx, zone_id, lat, lon, description[:300])
        journaliser(cx, "point", f"{pid} créé par {op['identifiant']}")
    return RedirectResponse("/operateur/points", status_code=303)


@router.get("/operateur/points/{point_id}/qr.png")
def qr(point_id: str, op=Depends(operateur)):
    if not re.fullmatch(r"[A-Z]{3}-\d{3}", point_id):
        raise HTTPException(404)
    return Response(points.qr_png(point_id), media_type="image/png")


@router.get("/operateur/planche-qr")
def planche_qr(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        pts = cx.execute(text("SELECT id, zone_id, description FROM point_controle WHERE actif ORDER BY id")).all()
    return rendu(request, "planche_qr.html", points=pts, url_point=points.url_point)


# --- Étiquetage à deux (S24) ---------------------------------------------------------------------

@router.get("/operateur/etiquetage")
def etiquetage(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        suivante = cx.execute(text("""
            SELECT o.id, o.photo_chemin, o.point_id FROM observation o
            WHERE o.photo_chemin IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM etiquette e WHERE e.observation_id = o.id AND e.etiqueteur = :moi)
              AND (SELECT count(*) FROM etiquette e WHERE e.observation_id = o.id) < 2
            ORDER BY (SELECT count(*) FROM etiquette e WHERE e.observation_id = o.id) DESC, o.id LIMIT 1
        """), {"moi": op["identifiant"]}).first()
        restantes = cx.execute(text("""
            SELECT count(*) FROM observation o WHERE o.photo_chemin IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM etiquette e WHERE e.observation_id = o.id AND e.etiqueteur = :moi)
        """), {"moi": op["identifiant"]}).scalar_one()
    return rendu(request, "etiquetage.html", obs=suivante, restantes=restantes)


@router.post("/operateur/etiquetage/{obs_id}")
def etiqueter(request: Request, obs_id: int, csrf: str = Form(""), classe: str = Form(...), op=Depends(operateur)):
    verifier_csrf(request, csrf)
    if classe not in ("propre", "partiel", "bouche", "inutilisable"):
        raise HTTPException(400, "classe inconnue")
    with transaction() as cx:
        cx.execute(text("""
            INSERT INTO etiquette (observation_id, etiqueteur, classe) VALUES (:o, :e, :c)
            ON CONFLICT (observation_id, etiqueteur) DO UPDATE SET classe = EXCLUDED.classe, le = now()
        """), {"o": obs_id, "e": op["identifiant"], "c": classe})
    return RedirectResponse("/operateur/etiquetage", status_code=303)


@router.get("/operateur/etiquetage/accord")
def accord(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        paires = [(r.a, r.b) for r in cx.execute(text("""
            SELECT e1.classe AS a, e2.classe AS b FROM etiquette e1
            JOIN etiquette e2 ON e2.observation_id = e1.observation_id AND e2.etiqueteur > e1.etiqueteur
        """))]
        par_classe = cx.execute(text("""
            SELECT e1.classe, count(*) AS n FROM etiquette e1
            JOIN etiquette e2 ON e2.observation_id = e1.observation_id AND e2.etiqueteur > e1.etiqueteur
            WHERE e1.classe = e2.classe GROUP BY e1.classe ORDER BY e1.classe
        """)).all()
        # l'IA comme « troisième annotateur » : comparée aux photos où les deux humains sont d'accord
        ia_vs_humains = [(r.humain, r.ia) for r in cx.execute(text("""
            SELECT min(e.classe) AS humain, o.classe_ia AS ia FROM etiquette e JOIN observation o ON o.id = e.observation_id
            WHERE o.ia_analyse_le IS NOT NULL
            GROUP BY o.id, o.classe_ia
            HAVING count(*) >= 2 AND count(DISTINCT e.classe) = 1 AND min(e.classe) <> 'inutilisable'
        """))]
    classes = ["propre", "partiel", "bouche", "inutilisable"]
    k = kappa_cohen(paires)
    classes_ia = ["propre", "partiel", "bouche", "aucune"]
    comparaison = [(h, i or "aucune") for h, i in ia_vs_humains]
    exactitude = sum(h == i for h, i in comparaison) / len(comparaison) if comparaison else None
    from app.services import ia_vision
    return rendu(request, "accord.html", n=len(paires), kappa=k, mot=interpretation(k), classes=classes,
                 matrice=matrice_confusion(paires, classes) if paires else None, par_classe=par_classe,
                 ia_disponible=ia.disponible(), vision_disponible=ia_vision.disponible(), modele_vision=ia_vision.MODELE,
                 n_ia=len(comparaison), exactitude_ia=exactitude, kappa_ia=kappa_cohen(comparaison),
                 matrice_ia=matrice_confusion(comparaison, classes_ia) if comparaison else None, classes_ia=classes_ia)


# --- Simulation et cycle manuel (démonstration) --------------------------------------------------

@router.get("/operateur/simulation")
def page_simulation(request: Request, op=Depends(operateur), bilan: str = ""):
    with transaction() as cx:
        zones = pluie.zones(cx)
        sims = cx.execute(text("SELECT zone_id, jour, pluie_mm FROM mesure_pluie WHERE source = 'simulation' "
                               "ORDER BY jour DESC, zone_id")).all()
    noms = {z["id"]: z["nom"] for z in zones}
    resultat = request.session.get("dernier_bilan") if bilan else None
    return rendu(request, "simulation.html", zones=zones, sims=sims, resultat=resultat, noms=noms)


@router.post("/operateur/simulation")
async def simuler(request: Request, csrf: str = Form(""), action: str = Form(...), zone_id: str = Form(""),
                  pluie_mm: float = Form(0), op=Depends(operateur)):
    verifier_csrf(request, csrf)
    if action == "pluie":
        if not 0 <= pluie_mm <= 500:
            raise HTTPException(400, "pluie entre 0 et 500 mm")
        with transaction() as cx:
            pluie.enregistrer(cx, zone_id, "simulation", date.today(), pluie_mm)
            journaliser(cx, "simulation", f"{op['identifiant']} simule {pluie_mm} mm sur {zone_id}")
        bilan = await run_in_threadpool(traiter_zone, zone_id)
    elif action == "effacer":
        with transaction() as cx:
            n = cx.execute(text("DELETE FROM mesure_pluie WHERE source = 'simulation'")).rowcount
            journaliser(cx, "simulation", f"{op['identifiant']} efface {n} pluie(s) simulée(s)")
        bilan = await run_in_threadpool(cycle_complet, False)
    elif action == "cycle":
        bilan = await run_in_threadpool(cycle_complet, True, False)
    else:
        raise HTTPException(400, "action inconnue")
    zones = bilan["zones"] if "zones" in bilan else {zone_id: bilan}
    request.session["dernier_bilan"] = [
        {"zone": z, "niveau": (v.get("score") or {}).get("niveau"), "valeur": (v.get("score") or {}).get("pluie_24h_mm"),
         "source": (v.get("score") or {}).get("source"), "action": (v.get("alerte") or {}).get("action", "rien"),
         "raison": (v.get("alerte") or {}).get("raison", v.get("erreur", ""))}
        for z, v in zones.items()]
    return RedirectResponse("/operateur/simulation?bilan=1", status_code=303)


# --- Journal, abonnés, opérateurs ----------------------------------------------------------------

@router.get("/operateur/journal")
def page_journal(request: Request, type: str = "", op=Depends(operateur)):
    with transaction() as cx:
        lignes = cx.execute(text("SELECT * FROM journal WHERE (:t = '' OR type = :t) ORDER BY le DESC LIMIT 300"),
                            {"t": type}).all()
        types = [r[0] for r in cx.execute(text("SELECT DISTINCT type FROM journal ORDER BY 1"))]
    return rendu(request, "journal.html", lignes=lignes, types=types, type=type)


@router.get("/operateur/abonnes")
def page_abonnes(request: Request, op=Depends(operateur)):
    with transaction() as cx:
        stats = cx.execute(text("""
            SELECT z.nom, a.canal, count(*) FILTER (WHERE a.actif) AS actifs,
                   count(*) FILTER (WHERE NOT a.actif) AS desabonnes
            FROM abonne a JOIN zone z ON z.id = a.zone_id GROUP BY z.nom, a.canal ORDER BY z.nom, a.canal
        """)).all()
    return rendu(request, "abonnes.html", stats=stats)


@router.get("/operateur/comptes")
def page_comptes(request: Request, op=Depends(admin)):
    with transaction() as cx:
        comptes = cx.execute(text("SELECT identifiant, nom, role, telegram_chat, actif FROM operateur ORDER BY identifiant")).all()
    return rendu(request, "comptes.html", comptes=comptes)


@router.post("/operateur/comptes")
def creer_compte(request: Request, csrf: str = Form(""), identifiant: str = Form(...), nom: str = Form(...),
                 mot_de_passe: str = Form(...), role: str = Form("operateur"), telegram_chat: str = Form(""),
                 op=Depends(admin)):
    verifier_csrf(request, csrf)
    if len(mot_de_passe) < 10:
        raise HTTPException(400, "Mot de passe : 10 caractères minimum.")
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", identifiant):
        raise HTTPException(400, "Identifiant : 3 à 40 caractères parmi a-z 0-9 . _ -")
    with transaction() as cx:
        cx.execute(text("""
            INSERT INTO operateur (identifiant, nom, mot_de_passe_hash, role, telegram_chat)
            VALUES (:i, :n, :h, :r, :t)
            ON CONFLICT (identifiant) DO UPDATE SET nom = EXCLUDED.nom, mot_de_passe_hash = EXCLUDED.mot_de_passe_hash,
              role = EXCLUDED.role, telegram_chat = EXCLUDED.telegram_chat, actif = true
        """), {"i": identifiant, "n": nom[:80], "h": hacher_mot_de_passe(mot_de_passe),
               "r": "admin" if role == "admin" else "operateur", "t": telegram_chat.strip() or None})
        journaliser(cx, "compte", f"{identifiant} créé ou modifié par {op['identifiant']}")
    return RedirectResponse("/operateur/comptes", status_code=303)
