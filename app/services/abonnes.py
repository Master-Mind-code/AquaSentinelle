"""Abonnés (S16) : consentement explicite, désabonnement à tout moment, contacts chiffrés."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.securite import chiffrer, empreinte

CANAUX = ("telegram", "sms", "console")


def abonner(cx: Connection, zone_id: str, canal: str, contact: str, consentement: bool, langue: str = "fr") -> int:
    if not consentement:
        raise ValueError("le consentement est obligatoire (loi 2013-450)")
    if canal not in CANAUX:
        raise ValueError(f"canal inconnu : {canal}")
    if not cx.execute(text("SELECT 1 FROM zone WHERE id = :z"), {"z": zone_id}).first():
        raise ValueError(f"zone inconnue : {zone_id}")
    tel = canal == "sms"
    aid = cx.execute(text("""
        INSERT INTO abonne (zone_id, contact_chiffre, contact_empreinte, canal, langue, consentement_le)
        VALUES (:z, :c, :e, :canal, :l, now())
        ON CONFLICT (zone_id, canal, contact_empreinte)
        DO UPDATE SET actif = true, desabonne_le = NULL, consentement_le = now()
        RETURNING id
    """), {"z": zone_id, "c": chiffrer(contact, tel), "e": empreinte(contact, tel), "canal": canal,
           "l": langue}).scalar_one()
    journaliser(cx, "abonnement", f"abonné {aid} : {zone_id} par {canal}")
    return aid


def desabonner(cx: Connection, canal: str, contact: str, zone_id: str | None = None) -> int:
    n = cx.execute(text(f"""
        UPDATE abonne SET actif = false, desabonne_le = now()
        WHERE canal = :canal AND contact_empreinte = :e AND actif {"AND zone_id = :z" if zone_id else ""}
    """), {"canal": canal, "e": empreinte(contact, canal == "sms"), "z": zone_id}).rowcount
    journaliser(cx, "abonnement", f"désabonnement {canal} : {n} abonnement(s)")
    return n


def zones_de(cx: Connection, canal: str, contact: str) -> list[str]:
    return [r.zone_id for r in cx.execute(text(
        "SELECT zone_id FROM abonne WHERE canal = :c AND contact_empreinte = :e AND actif ORDER BY zone_id"),
        {"c": canal, "e": empreinte(contact, canal == "sms")})]


def traiter_sms_entrant(cx: Connection, numero: str, texte: str) -> str:
    """Mots-clés SMS : « ALERTE <zone> » pour s'abonner, « STOP » pour tout arrêter. Renvoie la réponse."""
    mots = texte.strip().split()
    if not mots:
        return "Envoyez ALERTE suivi du nom de votre zone, ou STOP."
    cle = mots[0].upper()
    if cle in ("STOP", "ARRET", "ARRÊT"):
        n = desabonner(cx, "sms", numero)
        return f"Vous êtes désabonné ({n} zone(s)). Merci."
    if cle == "ALERTE" and len(mots) > 1:
        zone_id = mots[1].lower()
        try:
            abonner(cx, zone_id, "sms", numero, consentement=True)  # l'envoi du mot-clé vaut consentement
        except ValueError:
            zones = ", ".join(r.id for r in cx.execute(text("SELECT id FROM zone ORDER BY id")))
            return f"Zone inconnue. Zones : {zones}"
        return f"Abonné aux alertes {zone_id}. Envoyez STOP pour arrêter."
    return "Envoyez ALERTE suivi du nom de votre zone, ou STOP."
