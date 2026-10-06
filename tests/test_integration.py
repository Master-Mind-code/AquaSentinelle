"""Tests avec la base PostGIS (docker compose up -d db). Ignorés si la base est injoignable.

Ils écrivent dans la base : zone « abobo », point ABO-001. À lancer sur une base de démonstration.
"""
import cv2
import numpy as np
import pytest
from sqlalchemy import text


def _base_disponible() -> bool:
    try:
        from app.db import transaction
        with transaction() as cx:
            cx.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _base_disponible(), reason="base PostGIS injoignable")


@pytest.fixture(scope="module", autouse=True)
def base():
    from app.initialisation import initialiser
    initialiser(demo=True)


def _photo() -> bytes:
    return cv2.imencode(".jpg", np.full((300, 400, 3), 128, np.uint8))[1].tobytes()


class FausseApi:
    def __init__(self):
        self.messages = []

    def __call__(self, methode, **p):
        if methode == "sendMessage":
            self.messages.append(p)
        return {}

    def telecharger(self, file_id):
        return _photo()


def test_bot_abonnement_et_signalement():
    from bot.telegram_bot import Bot
    from app.db import transaction
    api, chat = FausseApi(), 9876543210            # 10 chiffres : ne doit PAS devenir un numéro ivoirien
    bot = Bot(api)
    auteur = {"id": chat, "username": "relais_bot_test"}
    bot.traiter({"callback_query": {"id": "1", "from": auteur, "data": "ok:abobo", "message": {"chat": {"id": chat}}}})
    assert "Abonnement enregistré" in api.messages[-1]["text"]
    from app.securite import dechiffrer
    with transaction() as cx:
        c = cx.execute(text("SELECT contact_chiffre FROM abonne WHERE canal = 'telegram' AND actif "
                            "ORDER BY id DESC LIMIT 1")).scalar_one()
    assert dechiffrer(c) == str(chat)

    bot.traiter({"message": {"chat": {"id": chat}, "from": auteur, "text": "/start ABO-001"}})
    for data in ("consent:",):
        bot.traiter({"callback_query": {"id": "2", "from": auteur, "data": data, "message": {"chat": {"id": chat}}}})
    bot.traiter({"message": {"chat": {"id": chat}, "from": auteur, "photo": [{"file_id": "x"}]}})
    for data in ("eau:non", "dechets:oui", "avis:partiel"):
        bot.traiter({"callback_query": {"id": "3", "from": auteur, "data": data, "message": {"chat": {"id": chat}}}})
    assert "Merci" in api.messages[-1]["text"] and "Partiellement" in api.messages[-1]["text"]

    bot.traiter({"message": {"chat": {"id": chat}, "from": auteur, "text": "/desabonner"}})
    assert "Désabonné de 1" in api.messages[-1]["text"]


def test_sms_mots_cles():
    from app.db import transaction
    from app.services.abonnes import traiter_sms_entrant, zones_de
    with transaction() as cx:
        assert "Abonné" in traiter_sms_entrant(cx, "0701020304", "alerte abobo")
        assert zones_de(cx, "sms", "+225 07 01 02 03 04") == ["abobo"]
        assert "Zone inconnue" in traiter_sms_entrant(cx, "0701020304", "ALERTE paris")
        assert "désabonné" in traiter_sms_entrant(cx, "0701020304", "STOP")
        assert zones_de(cx, "sms", "0701020304") == []


def test_score_et_cycle_de_vie_alerte():
    from datetime import date
    from app.db import transaction
    from app.services import alertes, pluie, score
    with transaction() as cx:
        cx.execute(text("DELETE FROM mesure_pluie WHERE source = 'simulation' AND zone_id = 'abobo'"))
        cx.execute(text("UPDATE alerte SET statut = 'annulee' WHERE zone_id = 'abobo' AND statut IN ('en_attente','escaladee')"))
        cx.execute(text("INSERT INTO etat_zone (zone_id, niveau) VALUES ('abobo','vert') "
                        "ON CONFLICT (zone_id) DO UPDATE SET niveau = 'vert'"))
        pluie.enregistrer(cx, "abobo", "simulation", date.today(), 150)
        sc = score.calculer(cx, "abobo")
        assert sc["niveau"] == "rouge" and sc["entrees"]["lecture_retenue"] == "observee"
        r = alertes.traiter_score(cx, sc)
        assert r["action"] == "en_attente"
        assert alertes.traiter_score(cx, score.calculer(cx, "abobo"))["action"] == "deja_en_attente"
        # sans AUCUNE donnée de pluie (panne de collecte), on ne touche pas au rouge en attente
        cx.execute(text("DELETE FROM mesure_pluie WHERE zone_id = 'abobo' AND jour >= current_date - 1"))
        assert alertes.traiter_score(cx, score.calculer(cx, "abobo"))["action"] == "rien"
        # la pluie retombe avant validation : l'alerte en attente est annulée, rien n'est envoyé
        pluie.enregistrer(cx, "abobo", "prevision_max", date.today(), 5)
        sc = score.calculer(cx, "abobo")
        alertes.traiter_score(cx, sc)
        statut = cx.execute(text("SELECT statut FROM alerte WHERE id = :i"), {"i": r["alerte_id"]}).scalar_one()
        assert statut == "annulee"


def test_photo_nettoyee():
    from app.services.photos import preparer
    jpeg, visages = preparer(_photo())
    assert jpeg[:2] == b"\xff\xd8" and visages == 0
    with pytest.raises(ValueError):
        preparer(b"pas une image")


def test_pluviometres_recoupes_alimentent_le_score():
    from datetime import date
    from app.db import transaction
    from app.services import points, pluviometre, score
    with transaction() as cx:
        cx.execute(text("DELETE FROM mesure_pluie WHERE zone_id = 'yopougon' AND source IN ('pluviometre','simulation')"))
        cx.execute(text("DELETE FROM releve_pluviometre WHERE zone_id = 'yopougon' AND jour = :j"), {"j": date.today()})
        r1 = points.trouver_ou_creer_relais(cx, "pluvio-1", telegram_id="pluvio-test-1")
        r2 = points.trouver_ou_creer_relais(cx, "pluvio-2", telegram_id="pluvio-test-2")
        assert pluviometre.enregistrer_releve(cx, "yopougon", r1, 82)["statut"] == "a_valider"
        assert cx.execute(text("SELECT count(*) FROM mesure_pluie WHERE zone_id = 'yopougon' AND source = 'pluviometre' "
                               "AND jour = :j"), {"j": date.today()}).scalar_one() == 0
        assert pluviometre.enregistrer_releve(cx, "yopougon", r2, 76)["statut"] == "valide"
        mm = cx.execute(text("SELECT pluie_mm FROM mesure_pluie WHERE zone_id = 'yopougon' AND source = 'pluviometre' "
                             "AND jour = :j"), {"j": date.today()}).scalar_one()
        assert mm == 82                                   # le relevé en attente a été confirmé par le second
        sc = score.calculer(cx, "yopougon")
        assert sc["niveau"] == "orange" and sc["source"] == "pluviometre"
        cx.execute(text("DELETE FROM mesure_pluie WHERE zone_id = 'yopougon' AND source = 'pluviometre'"))
        cx.execute(text("DELETE FROM releve_pluviometre WHERE zone_id = 'yopougon' AND jour = :j"), {"j": date.today()})


def test_bot_releve_pluie_avec_accents():
    from bot.telegram_bot import Bot
    api = FausseApi()
    bot = Bot(api)
    auteur = {"id": 5550001, "username": "pluvio_bot"}
    bot.traiter({"message": {"chat": {"id": 5550001}, "from": auteur, "text": "/pluie 12,5 Attécoubé"}})
    assert "12 mm (attecoube) pris en compte" in api.messages[-1]["text"] or "13 mm (attecoube) pris en compte" in api.messages[-1]["text"]
    bot.traiter({"message": {"chat": {"id": 5550001}, "from": auteur, "text": "/pluie beaucoup"}})
    assert "Usage" in api.messages[-1]["text"]


def test_curage_preventif_une_fois_par_jour():
    from datetime import date
    from app.db import transaction
    from app.services import curage, pluie, points
    with transaction() as cx:
        # un point bouché validé à Anyama + 45 mm prévus aujourd'hui
        r = points.trouver_ou_creer_relais(cx, "curage-test", telegram_id="curage-test")
        cx.execute(text("UPDATE relais SET fiabilite = 0.9 WHERE id = :i"), {"i": r.id})
        r = points.trouver_ou_creer_relais(cx, "curage-test", telegram_id="curage-test")
        points.enregistrer_observation(cx, "ANY-001", r, None, True, True, "bouche")
        cx.execute(text("DELETE FROM journal WHERE type = 'curage' AND message LIKE 'anyama :%'"))
        pluie.enregistrer(cx, "anyama", "prevision_max", date.today(), 45)
        assert any(c["zone_id"] == "anyama" and "ANY-001" in c["points"] for c in curage.points_a_curer(cx))
        assert curage.notifier(cx) >= 1
        n_avant = cx.execute(text("SELECT count(*) FROM journal WHERE type = 'curage' AND message LIKE 'anyama :%'")).scalar_one()
        curage.notifier(cx)
        n_apres = cx.execute(text("SELECT count(*) FROM journal WHERE type = 'curage' AND message LIKE 'anyama :%'")).scalar_one()
        assert n_avant == n_apres == 1                      # pas de deuxième notification le même jour
        # remise en état : le point de démo redevient « jamais observé », la prévision réelle sera recollectée
        cx.execute(text("DELETE FROM observation WHERE point_id = 'ANY-001' AND relais_id = :i"), {"i": r.id})
        cx.execute(text("DELETE FROM mesure_pluie WHERE zone_id = 'anyama' AND source = 'prevision_max' AND jour = :j"),
                   {"j": date.today()})


def test_crue_de_fleuve_prevue():
    from datetime import date, timedelta
    from app.db import transaction
    from app.services import alertes, score
    with transaction() as cx:
        cx.execute(text("UPDATE riviere SET seuil_orange = 333, seuil_rouge = 595 WHERE zone_id = 'tiassale'"))
        cx.execute(text("DELETE FROM mesure_debit WHERE zone_id = 'tiassale'"))
        cx.execute(text("UPDATE alerte SET statut = 'annulee' WHERE zone_id = 'tiassale' AND statut IN ('en_attente','escaladee')"))
        cx.execute(text("INSERT INTO etat_zone (zone_id, niveau) VALUES ('tiassale','vert') "
                        "ON CONFLICT (zone_id) DO UPDATE SET niveau = 'vert'"))
        for i, q in enumerate((120, 210, 380, 450, 300)):      # pic de 450 m³/s dans 3 jours
            cx.execute(text("INSERT INTO mesure_debit (zone_id, jour, prevision, debit_m3s) VALUES ('tiassale', :j, true, :q)"),
                       {"j": date.today() + timedelta(i), "q": q})
        sc = score.calculer(cx, "tiassale")
        assert sc["niveau"] == "orange" and sc["entrees"]["lecture_retenue"] == "debit"
        assert sc["entrees"]["crue"]["debit_max_m3s"] == 450
        r = alertes.traiter_score(cx, sc)
        texte = cx.execute(text("SELECT texte FROM alerte WHERE id = :i"), {"i": r["alerte_id"]}).scalar_one()
        assert r["action"] == "envoyee" and "fleuve" in texte and "Tiassal" in texte



def test_signalements_libres_recoupes_a_300_m():
    from app.db import transaction
    from app.services import points, signalements
    with transaction() as cx:
        cx.execute(text("DELETE FROM signalement"))
        # la fiabilité monte à chaque confirmation : on repart de relais « neufs » à chaque lancement
        cx.execute(text("UPDATE relais SET fiabilite = 0.5, nb_confirmees = 0, nb_rejetees = 0 "
                        "WHERE telegram_id IN ('sig-test-1', 'sig-test-2')"))
        r1 = points.trouver_ou_creer_relais(cx, "sig-1", telegram_id="sig-test-1")
        r2 = points.trouver_ou_creer_relais(cx, "sig-2", telegram_id="sig-test-2")
        a = signalements.creer(cx, "route_inondee", 5.3400, -4.0300, 12, "boulevard coupé", None, r1)
        assert a["statut"] == "a_valider" and signalements.publics(cx) == []
        loin = signalements.creer(cx, "route_inondee", 5.3600, -4.0300, 12, "", None, r2)   # ~2,2 km
        assert loin["statut"] == "a_valider"
        pres = signalements.creer(cx, "route_inondee", 5.3410, -4.0305, 12, "", None, r2)  # ~120 m de a
        assert pres["statut"] == "valide"
        visibles = {s["id"] for s in signalements.publics(cx)}
        assert {a["id"], pres["id"]} <= visibles and loin["id"] not in visibles
        z = cx.execute(text("SELECT zone_id FROM signalement WHERE id = :i"), {"i": a["id"]}).scalar_one()
        assert z == "attecoube"


def test_demande_aide_et_suivi():
    import pytest
    from app.db import transaction
    from app.services import aide
    with transaction() as cx:
        d = aide.creer(cx, "bloque", 3, "toit", 5.3365, -4.0390, 20, "", "0700000009")
        suivi = aide.par_jeton(cx, d["jeton"])
        assert suivi.statut == "recue"
        aide.changer_statut(cx, d["id"], "transmise", "op-test", "Pompiers prévenus")
        suivi = aide.par_jeton(cx, d["jeton"])
        assert suivi.statut == "transmise" and suivi.note == "Pompiers prévenus"
        with pytest.raises(ValueError):
            aide.creer(cx, "bloque", 1, "", None, None, None, "", None)   # ni GPS ni repère
        sans_gps = aide.creer(cx, "blesse", 1, "", None, None, None, "Mossikro, derrière l'école", None)
        assert aide.par_jeton(cx, sans_gps["jeton"]).statut == "recue"


def test_capteur_cle_seuils_et_score():
    import pytest
    from app.db import transaction
    from app.services import capteurs, score
    with transaction() as cx:
        cx.execute(text("DELETE FROM mesure_niveau WHERE capteur_id = 'CAP-TEST-01'"))
        cle = capteurs.creer(cx, "CAP-TEST-01", "test", "anyama", 5.49, -4.05, 30, 60, simule=True)
        with pytest.raises(PermissionError):
            capteurs.recevoir(cx, "CAP-TEST-01", "mauvaise-cle", 70, 3.8)
        assert capteurs.recevoir(cx, "CAP-TEST-01", cle, 20, 3.8)["niveau"] == "vert"
        assert capteurs.recevoir(cx, "CAP-TEST-01", cle, 70, 3.8)["niveau"] == "rouge"
        sc = score.calculer(cx, "anyama")
        assert sc["niveau"] == "rouge" and sc["entrees"]["lecture_retenue"] == "capteur"
        cx.execute(text("UPDATE capteur SET actif = false WHERE id = 'CAP-TEST-01'"))



def test_second_regard_ia_en_arriere_plan():
    from app.db import transaction
    from app.services import ia_suivi, points
    with transaction() as cx:
        cx.execute(text("UPDATE observation SET ia_analyse_le = now() WHERE ia_analyse_le IS NULL"))   # isole le test
        r = points.trouver_ou_creer_relais(cx, "ia-test", telegram_id="ia-test")
        obs = points.enregistrer_observation(cx, "YOP-002", r, _photo(), False, False, "propre")
    assert obs["statut"] == "valide"                          # « propre » d'une seule source : accepté…
    faux = lambda jpeg: {"classe": "bouche", "obstruction_pct": 80, "confiance": 0.65, "est_caniveau": True,
                         "eau_stagnante": True, "dechets_visibles": True, "personne_visible": False,
                         "justification": "grille couverte de déchets", "modele": "faux-modele"}
    assert ia_suivi.traiter_en_attente(analyser=faux) == 1
    with transaction() as cx:
        o = cx.execute(text("SELECT statut, motif, classe_ia, obstruction_pct_ia, justification_ia FROM observation WHERE id = :i"),
                       {"i": obs["id"]}).one()
    assert o.statut == "a_valider" and "désaccord" in o.motif   # …mais l'IA le renvoie en vérification
    assert (o.classe_ia, o.obstruction_pct_ia) == ("bouche", 80)
    assert ia_suivi.traiter_en_attente(analyser=faux) == 0     # pas analysée deux fois
