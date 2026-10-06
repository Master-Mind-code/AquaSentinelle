"""Vérification de bout en bout sur un serveur qui tourne (local ou Docker).

    python scripts/verifier_bout_en_bout.py [--url http://localhost:8000] [--zone attecoube]

Scénario : pages publiques -> connexion -> 2 relais signalent « bouché » (recoupement) -> pluie simulée
-> alerte rouge en attente -> validation -> envoi à un abonné « console » -> retour à la normale.
Ce script ÉCRIT dans la base (signalements, abonné de test, alertes) : à lancer sur une base de démonstration.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import requests
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, KO = "  ok  ", "  ÉCHEC"
echecs = 0


def verifier(cond: bool, quoi: str) -> None:
    global echecs
    print((OK if cond else KO), quoi)
    echecs += 0 if cond else 1


def csrf(s: requests.Session, url: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', s.get(url).text)
    return m.group(1) if m else ""


def photo_test() -> bytes:
    img = np.full((600, 800, 3), (120, 140, 150), np.uint8)
    cv2.rectangle(img, (200, 300), (600, 560), (40, 60, 70), -1)
    cv2.rectangle(img, (650, 80), (740, 170), (42, 116, 232), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--zone", default="attecoube")
    a = p.parse_args()
    u = a.url.rstrip("/")

    from app.settings import reglages
    r = reglages()

    print("Pages publiques")
    pub = requests.Session()
    for chemin in ("/sante", "/", "/abonnement", "/api/zones", "/api/points", "/connexion"):
        verifier(pub.get(u + chemin).status_code == 200, f"GET {chemin}")
    verifier(pub.get(u + "/operateur", allow_redirects=False).status_code in (303, 307), "/operateur protégé")
    verifier(pub.get(u + "/r/XXX-999").status_code == 404, "point inconnu -> 404")

    print("Connexion opérateur")
    op = requests.Session()
    jeton = csrf(op, u + "/connexion")
    rep = op.post(u + "/connexion", data={"csrf": jeton, "identifiant": r.admin_identifiant,
                                          "mot_de_passe": "mauvais-mot-de-passe", "suite": "/operateur"})
    verifier("incorrect" in rep.text, "mauvais mot de passe refusé")
    rep = op.post(u + "/connexion", data={"csrf": jeton, "identifiant": r.admin_identifiant,
                                          "mot_de_passe": r.admin_mot_de_passe, "suite": "/operateur"})
    verifier(rep.status_code == 200 and "Tableau de bord" in rep.text, "connexion administrateur")
    for chemin in ("/operateur/alertes", "/operateur/signalements", "/operateur/scores", "/operateur/points",
                   "/operateur/planche-qr", "/operateur/etiquetage", "/operateur/etiquetage/accord",
                   "/operateur/simulation", "/operateur/journal", "/operateur/abonnes", "/operateur/comptes",
                   "/operateur/api/points"):
        verifier(op.get(u + chemin).status_code == 200, f"GET {chemin}")
    qr = op.get(u + "/operateur/points/ATT-001/qr.png")
    verifier(qr.status_code == 200 and qr.content[:4] == b"\x89PNG", "QR code PNG")

    print("Préparation : point, abonné et relais neufs (le test est rejouable sur la même base)")
    import random
    import time
    from app.db import transaction
    from app.services import abonnes, points
    with transaction() as cx:
        cx.execute(text("UPDATE alerte SET statut = 'annulee' WHERE zone_id = :z AND statut IN ('en_attente','escaladee')"),
                   {"z": a.zone})
        point = points.creer_point(cx, a.zone, 5.3365, -4.0390, "Test bout en bout (à désactiver)", demo=True)
        abonnes.abonner(cx, a.zone, "console", f"test-console-{time.time_ns()}", consentement=True)
    verifier(True, f"point {point} et abonné console sur {a.zone}")

    print("Signalements de deux relais indépendants")
    for i, tel in enumerate([f"07{random.randrange(10**8):08d}" for _ in range(2)], 1):
        relais = requests.Session()
        jeton = csrf(relais, f"{u}/r/{point}")
        rep = relais.post(f"{u}/r/{point}", data={"csrf": jeton, "pseudo": f"relais-test-{i}", "telephone": tel,
                                                  "consentement": "oui", "eau": "oui", "dechets": "oui", "avis": "bouche"},
                          files={"photo": ("caniveau.jpg", photo_test(), "image/jpeg")})
        verifier(rep.status_code == 200 and "Merci" in rep.text, f"signalement relais {i}")
        attendu = "en attente" if i == 1 else "validé"
        verifier(attendu in rep.text, f"relais {i} : statut « {attendu} »")

    print("Pluie simulée -> alerte rouge -> validation")
    jeton = csrf(op, u + "/operateur/simulation")
    op.post(u + "/operateur/simulation", data={"csrf": jeton, "action": "effacer"})
    op.post(u + "/operateur/simulation", data={"csrf": jeton, "action": "pluie", "zone_id": a.zone, "pluie_mm": 120})
    page = op.get(u + "/operateur/alertes").text
    verifier("Valider et envoyer" in page, "120 mm -> rouge en attente de validation (rien n.est envoyé avant)")
    m = re.search(r'action="/operateur/alertes/(\d+)"', page)
    if m:
        rep = op.post(f"{u}/operateur/alertes/{m.group(1)}", data={"csrf": jeton, "decision": "valider"})
        verifier(rep.status_code == 200, "validation de l'alerte rouge")
        envois = op.get(f"{u}/operateur/alertes/{m.group(1)}/envois").text
        verifier(">Livré<" in envois, "envoi réussi à l'abonné console")
        rep = op.post(f"{u}/operateur/alertes/{m.group(1)}", data={"csrf": jeton, "decision": "valider"})
        verifier(rep.status_code == 409, "double validation refusée")

    print("Retour à la normale")
    op.post(u + "/operateur/simulation", data={"csrf": jeton, "action": "effacer"})
    hist = op.get(u + "/operateur/alertes").text
    verifier("retour" in hist.lower() or ">Vert<" in hist, "message de retour à la normale")

    print("Sécurité")
    verifier(op.post(u + "/operateur/simulation", data={"csrf": "faux", "action": "cycle"}).status_code == 400,
             "jeton CSRF invalide refusé")
    verifier(op.get(u + "/operateur/photos/../../.env").status_code == 404, "traversée de chemin refusée")

    # nettoyage : le point de test, signalé « bouché », abaisserait les seuils réels de la zone pendant 30 jours
    # nettoyage complet de ce que le test a créé : points, signalements, photos, relais (l'historique d'alertes reste)
    import shutil
    from app.settings import reglages as _r
    with transaction() as cx:
        tests = [p[0] for p in cx.execute(text("SELECT id FROM point_controle WHERE description LIKE 'Test bout en bout%'"))]
        cx.execute(text("DELETE FROM etiquette WHERE observation_id IN (SELECT id FROM observation WHERE point_id = ANY(:p))"), {"p": tests})
        cx.execute(text("DELETE FROM observation WHERE point_id = ANY(:p)"), {"p": tests})
        cx.execute(text("DELETE FROM point_controle WHERE id = ANY(:p)"), {"p": tests})
        cx.execute(text("DELETE FROM relais r WHERE pseudo LIKE 'relais-test-%' AND NOT EXISTS "
                        "(SELECT 1 FROM observation o WHERE o.relais_id = r.id)"))
        cx.execute(text("UPDATE abonne SET actif = false WHERE canal = 'console'"))
    for p in tests:
        shutil.rmtree(_r().dossier_photos / p, ignore_errors=True)

    print(f"\n{'TOUT EST OK' if not echecs else f'{echecs} ÉCHEC(S)'}")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
