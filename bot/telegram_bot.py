"""Bot Telegram (S14, S16, S19) : abonnement par zone, désabonnement, niveaux, parcours du relais.

    python -m bot.telegram_bot          (TELEGRAM_TOKEN dans .env)

Parcours du relais : le lien https://t.me/<bot>?start=ATT-023 (ou /signaler ATT-023) ouvre le point,
puis consentement -> photo -> eau stagnante ? -> déchets ? -> état du caniveau -> enregistrement.
Interrogation longue (long polling) : pas besoin d'adresse publique ni de certificat.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

import requests
from sqlalchemy import text

from app.db import transaction
from app.services import abonnes, pluviometre, points
from app.settings import reglages

log = logging.getLogger("bot")
ID_POINT = re.compile(r"^[A-Za-z]{3}-\d{3}$")
NIVEAU = {"vert": "🟢 Vert", "orange": "🟠 Orange", "rouge": "🔴 Rouge"}
CLASSES = {"propre": "Propre", "partiel": "Partiellement bouché", "bouche": "Bouché"}


class ApiTelegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.fichiers = f"https://api.telegram.org/file/bot{token}"

    def __call__(self, methode: str, **params):
        r = requests.post(f"{self.base}/{methode}", json=params, timeout=70)
        donnees = r.json()
        if not donnees.get("ok"):
            raise RuntimeError(f"{methode} : {donnees.get('description')}")
        return donnees["result"]

    def telecharger(self, file_id: str) -> bytes:
        chemin = self("getFile", file_id=file_id)["file_path"]
        return requests.get(f"{self.fichiers}/{chemin}", timeout=60).content


def sans_accents(mot: str) -> str:
    """« Attécoubé » -> « attecoube » (identifiant de zone)."""
    return unicodedata.normalize("NFKD", mot).encode("ascii", "ignore").decode().lower()


def clavier(*lignes: list[tuple[str, str]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in ligne] for ligne in lignes]}


class Bot:
    """Logique du bot, indépendante du transport (l'API est injectée : testable sans réseau)."""

    def __init__(self, api):
        self.api = api
        self.parcours: dict[int, dict] = {}   # chat_id -> état du signalement en cours

    def dire(self, chat_id: int, texte: str, **extra) -> None:
        self.api("sendMessage", chat_id=chat_id, text=texte, **extra)

    # --- aiguillage -------------------------------------------------------------------------------
    def traiter(self, maj: dict) -> None:
        if "callback_query" in maj:
            cq = maj["callback_query"]
            self.api("answerCallbackQuery", callback_query_id=cq["id"])
            self.rappel(cq["message"]["chat"]["id"], cq["from"], cq.get("data", ""))
        elif "message" in maj:
            m = maj["message"]
            chat_id, auteur = m["chat"]["id"], m.get("from", {})
            if "photo" in m:
                self.photo(chat_id, m["photo"][-1]["file_id"])
            elif "text" in m:
                self.commande(chat_id, auteur, m["text"].strip())

    def commande(self, chat_id: int, auteur: dict, texte: str) -> None:
        cmd, _, arg = texte.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/signaler") and ID_POINT.match(arg.strip()):
            return self.debut_signalement(chat_id, arg.strip().upper())
        if cmd in ("/start", "/aide"):
            return self.dire(chat_id, "AquaSentinelle CI : alertes inondation par commune.\n"
                                      "/abonner : recevoir les alertes d'une commune\n"
                                      "/niveaux : niveau actuel de chaque commune\n"
                                      "/desabonner : ne plus rien recevoir\n"
                                      "/signaler ATT-023 : signaler l'état d'un caniveau (relais)\n"
                                      "/pluie 45 attecoube : relevé du pluviomètre en mm (relais)")
        if cmd == "/abonner":
            with transaction() as cx:
                zones = cx.execute(text("SELECT id, nom FROM zone ORDER BY nom")).all()
            return self.dire(chat_id, "Choisissez votre commune :",
                             reply_markup=clavier(*[[(z.nom, f"zone:{z.id}")] for z in zones]))
        if cmd == "/desabonner":
            with transaction() as cx:
                n = abonnes.desabonner(cx, "telegram", str(chat_id))
            return self.dire(chat_id, f"Désabonné de {n} commune(s). /abonner pour revenir.")
        if cmd == "/niveaux":
            with transaction() as cx:
                lignes = cx.execute(text("""
                    SELECT z.nom, coalesce(e.niveau, 'vert') AS niveau FROM zone z
                    LEFT JOIN etat_zone e ON e.zone_id = z.id ORDER BY z.nom
                """)).all()
            return self.dire(chat_id, "\n".join(f"{NIVEAU[l.niveau]} · {l.nom}" for l in lignes))
        if cmd == "/pluie":
            return self.releve_pluie(chat_id, auteur, arg)
        if self.parcours.get(chat_id, {}).get("etape") == "photo":
            return self.dire(chat_id, "J'attends une photo cadrée sur le repère peint (bouton trombone ou appareil photo).")
        self.dire(chat_id, "Commande inconnue. /aide pour la liste.")

    # --- abonnement -----------------------------------------------------------------------------
    def rappel(self, chat_id: int, auteur: dict, data: str) -> None:
        cle, _, val = data.partition(":")
        if cle == "zone":
            return self.dire(chat_id, "Vous recevrez au plus quelques messages par jour, seulement quand le niveau change. "
                                      "Votre identifiant Telegram est chiffré et ne sert qu'à cela (loi 2013-450).",
                             reply_markup=clavier([("J'accepte", f"ok:{val}"), ("Annuler", "annuler:")]))
        if cle == "ok":
            with transaction() as cx:
                try:
                    abonnes.abonner(cx, val, "telegram", str(chat_id), consentement=True)
                except ValueError as e:
                    return self.dire(chat_id, str(e))
            return self.dire(chat_id, "Abonnement enregistré. /desabonner pour arrêter à tout moment.")
        if cle == "annuler":
            self.parcours.pop(chat_id, None)
            return self.dire(chat_id, "Annulé.")
        # --- parcours du relais ---
        etat = self.parcours.get(chat_id)
        if etat is None:
            return self.dire(chat_id, "Signalement expiré : rescannez le QR code du point.")
        if cle == "consent":
            etat["etape"] = "photo"
            return self.dire(chat_id, "Envoyez maintenant une photo cadrée sur le repère peint (bande + carré orange).")
        if cle in ("eau", "dechets"):
            etat[cle] = val == "oui"
            if cle == "eau":
                return self.dire(chat_id, "Des déchets sont-ils visibles dans le caniveau ?",
                                 reply_markup=clavier([("Oui", "dechets:oui"), ("Non", "dechets:non")]))
            return self.dire(chat_id, "Selon vous, le caniveau est :",
                             reply_markup=clavier(*[[(v, f"avis:{k}")] for k, v in CLASSES.items()]))
        if cle == "avis" and val in CLASSES:
            return self.terminer(chat_id, auteur, val)

    def releve_pluie(self, chat_id: int, auteur: dict, arg: str) -> None:
        """/pluie <mm> [zone] : relevé du pluviomètre de quartier (zone facultative si le relais en a une)."""
        mots = arg.replace(",", ".").split()
        try:
            mm = float(mots[0])
        except (IndexError, ValueError):
            return self.dire(chat_id, "Usage : /pluie 45 attecoube (millimètres lus ce matin, puis la commune).")
        pseudo = auteur.get("username") or auteur.get("first_name") or "relais"
        try:
            with transaction() as cx:
                r = points.trouver_ou_creer_relais(cx, pseudo, telegram_id=str(auteur.get("id", chat_id)), consentement=True)
                zone = sans_accents(mots[1]) if len(mots) > 1 else r.zone_id
                if not zone:
                    return self.dire(chat_id, "Précisez la commune : /pluie 45 attecoube")
                if r.zone_id is None:
                    cx.execute(text("UPDATE relais SET zone_id = :z WHERE id = :i"), {"z": zone, "i": r.id})
                res = pluviometre.enregistrer_releve(cx, zone, r, mm)
        except ValueError as e:
            return self.dire(chat_id, f"Relevé refusé : {e}")
        etat = "pris en compte" if res["statut"] == "valide" else "en attente de vérification"
        self.dire(chat_id, f"Relevé de {mm:.0f} mm ({zone}) {etat}. Merci !")

    # --- parcours du relais ------------------------------------------------------------------------
    def debut_signalement(self, chat_id: int, point_id: str) -> None:
        with transaction() as cx:
            p = cx.execute(text("SELECT p.id, z.nom FROM point_controle p JOIN zone z ON z.id = p.zone_id "
                                "WHERE p.id = :i AND p.actif"), {"i": point_id}).first()
        if p is None:
            return self.dire(chat_id, f"Point {point_id} inconnu.")
        self.parcours[chat_id] = {"point": p.id, "etape": "consentement", "debut": time.time()}
        self.dire(chat_id, f"Point {p.id} · {p.nom}.\nLa photo servira uniquement à suivre l'état des caniveaux ; "
                           "les visages sont floutés automatiquement.",
                  reply_markup=clavier([("J'accepte", "consent:"), ("Annuler", "annuler:")]))

    def photo(self, chat_id: int, file_id: str) -> None:
        etat = self.parcours.get(chat_id)
        if not etat or etat.get("etape") != "photo":
            return self.dire(chat_id, "Pour signaler un caniveau, scannez d'abord le QR code peint sur le point.")
        etat["photo"] = self.api.telecharger(file_id)
        etat["etape"] = "questions"
        self.dire(chat_id, "De l'eau stagne-t-elle ?", reply_markup=clavier([("Oui", "eau:oui"), ("Non", "eau:non")]))

    def terminer(self, chat_id: int, auteur: dict, avis: str) -> None:
        etat = self.parcours.pop(chat_id)
        pseudo = auteur.get("username") or auteur.get("first_name") or "relais"
        try:
            with transaction() as cx:
                r = points.trouver_ou_creer_relais(cx, pseudo, telegram_id=str(auteur.get("id", chat_id)), consentement=True)
                obs = points.enregistrer_observation(cx, etat["point"], r, etat.get("photo"), etat.get("eau"),
                                                     etat.get("dechets"), avis)
        except ValueError as e:
            return self.dire(chat_id, f"Signalement refusé : {e}")
        statut = "validé" if obs["statut"] == "valide" else "en attente de vérification"
        self.dire(chat_id, f"Merci ! Point {etat['point']} : {CLASSES.get(obs['classe'], 'à déterminer')}, {statut}."
                           + (f"\n{obs['visages_floutes']} visage(s) flouté(s)." if obs["visages_floutes"] else ""))


def boucle(bot: Bot, api: ApiTelegram) -> None:
    decalage = 0
    while True:
        try:
            for maj in api("getUpdates", offset=decalage, timeout=50):
                decalage = maj["update_id"] + 1
                try:
                    bot.traiter(maj)
                except Exception:
                    log.exception("échec du traitement de %s", maj.get("update_id"))
        except Exception:
            log.exception("getUpdates")
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    jeton = reglages().telegram_token
    if not jeton:
        raise SystemExit("TELEGRAM_TOKEN absent : créer un bot avec @BotFather et le mettre dans .env")
    api = ApiTelegram(jeton)
    moi = api("getMe")
    log.info("bot @%s démarré", moi["username"])
    api("setMyCommands", commands=[
        {"command": "abonner", "description": "Recevoir les alertes d'une commune"},
        {"command": "niveaux", "description": "Niveau actuel par commune"},
        {"command": "desabonner", "description": "Ne plus recevoir d'alertes"},
        {"command": "signaler", "description": "Signaler un caniveau : /signaler ATT-023"},
        {"command": "pluie", "description": "Relevé du pluviomètre : /pluie 45 attecoube"},
        {"command": "aide", "description": "Aide"},
    ])
    boucle(Bot(api), api)
