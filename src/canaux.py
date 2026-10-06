"""Canaux d'envoi. Le canal « console » n'envoie rien : il journalise (démonstration, tests, rejeu).

Telegram : créer un bot avec @BotFather, puis définir la variable d'environnement TELEGRAM_TOKEN.
Le token ne doit JAMAIS être écrit dans le code ni dans un fichier versionné.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import requests

JOURNAL = Path(__file__).resolve().parent.parent / "data" / "envois.log"


class CanalConsole:
    nom = "console"

    def __init__(self, journal: bool = True):
        self.journal = journal  # False en rejeu : on ne mélange pas simulation et envois réels

    def envoyer(self, destinataire: str, texte: str, quand: str | None = None) -> bool:
        ligne = f"{quand or f'{datetime.now():%Y-%m-%d %H:%M:%S}'} [{self.nom}] -> {destinataire} : {texte}"
        print(ligne)
        if self.journal:
            JOURNAL.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL.open("a", encoding="utf-8") as f:
                f.write(ligne + "\n")
        return True


class CanalTelegram:
    nom = "telegram"

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_TOKEN")
        if not self.token:
            raise RuntimeError("TELEGRAM_TOKEN absent : créer un bot via @BotFather et définir la variable.")

    def envoyer(self, destinataire: str, texte: str, quand: str | None = None) -> bool:
        """destinataire : chat_id d'un abonné ou d'un canal (ex. -100123..., @aquasentinelle_attecoube)."""
        r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          json={"chat_id": destinataire, "text": texte}, timeout=30)
        return r.ok and r.json().get("ok", False)


class CanalSMSAfricasTalking:
    """SMS via Africa's Talking. AT_USERNAME=sandbox pour le bac à sable (aucun SMS réel envoyé)."""
    nom = "sms"

    def __init__(self):
        self.username = os.environ.get("AT_USERNAME", "sandbox")
        self.api_key = os.environ.get("AT_API_KEY")
        self.sender = os.environ.get("AT_SENDER_ID") or None
        if not self.api_key:
            raise RuntimeError("AT_API_KEY absente : créer un compte sur africastalking.com (sandbox gratuit).")
        hote = "api.sandbox.africastalking.com" if self.username == "sandbox" else "api.africastalking.com"
        self.url = f"https://{hote}/version1/messaging"

    def envoyer(self, destinataire: str, texte: str, quand: str | None = None) -> bool:
        donnees = {"username": self.username, "to": destinataire, "message": texte}
        if self.sender:
            donnees["from"] = self.sender
        r = requests.post(self.url, data=donnees, timeout=30,
                          headers={"apiKey": self.api_key, "Accept": "application/json"})
        if not r.ok:
            return False
        dest = r.json().get("SMSMessageData", {}).get("Recipients", [])
        return bool(dest) and dest[0].get("status") in ("Success", "Sent", "Queued")


class CanalSMSPasserelle:
    """SMS via un téléphone Android servant de passerelle (application « SMS Gateway for Android »)."""
    nom = "sms"

    def __init__(self):
        self.url = os.environ.get("SMS_PASSERELLE_URL")
        if not self.url:
            raise RuntimeError("SMS_PASSERELLE_URL absente (ex. http://192.168.1.20:8080/message).")
        self.auth = (os.environ.get("SMS_PASSERELLE_IDENTIFIANT", ""), os.environ.get("SMS_PASSERELLE_MOT_DE_PASSE", ""))

    def envoyer(self, destinataire: str, texte: str, quand: str | None = None) -> bool:
        r = requests.post(self.url, json={"message": texte, "phoneNumbers": [destinataire]},
                          auth=self.auth if self.auth[0] else None, timeout=30)
        return r.ok


def canal(nom: str):
    if nom == "sms":
        fournisseur = os.environ.get("SMS_FOURNISSEUR", "")
        if fournisseur == "africastalking":
            return CanalSMSAfricasTalking()
        if fournisseur == "passerelle":
            return CanalSMSPasserelle()
        raise RuntimeError("SMS_FOURNISSEUR doit valoir « africastalking » ou « passerelle ».")
    return {"console": CanalConsole, "telegram": CanalTelegram}[nom]()
