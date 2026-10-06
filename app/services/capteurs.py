"""Capteurs de niveau d'eau (option IoT, I1-I10) : réception des mesures, seuils, détection du silence.

Chaque appareil s'authentifie par une clé d'API (en-tête X-Cle-API), dont seule l'empreinte est stockée.
L'heure de la mesure est celle du serveur (I7). Un capteur muet depuis plus d'une heure est signalé (I9) :
la disparition d'un capteur volé devient elle-même une donnée.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.services.alertes import notifier_operateurs
from src.risk import score

MINUTES_SILENCE = 60
MINUTES_VALIDITE = 60     # une mesure plus ancienne n'entre pas dans le score


def _empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


def creer(cx: Connection, capteur_id: str, nom: str, zone_id: str, lat: float, lon: float,
          seuil_orange_cm: float, seuil_rouge_cm: float, simule: bool = False) -> str:
    """Enregistre un capteur et renvoie sa clé d'API EN CLAIR (affichée une seule fois)."""
    if seuil_rouge_cm <= seuil_orange_cm:
        raise ValueError("le seuil rouge doit être au-dessus du seuil orange")
    cle = secrets.token_urlsafe(24)
    cx.execute(text("""
        INSERT INTO capteur (id, nom, zone_id, position, cle_hash, seuil_orange_cm, seuil_rouge_cm, simule)
        VALUES (:i, :n, :z, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :h, :o, :r, :s)
        ON CONFLICT (id) DO UPDATE SET nom = EXCLUDED.nom, zone_id = EXCLUDED.zone_id, position = EXCLUDED.position,
          cle_hash = EXCLUDED.cle_hash, seuil_orange_cm = EXCLUDED.seuil_orange_cm,
          seuil_rouge_cm = EXCLUDED.seuil_rouge_cm, simule = EXCLUDED.simule, actif = true
    """), {"i": capteur_id, "n": nom, "z": zone_id, "lat": lat, "lon": lon, "h": _empreinte(cle),
           "o": seuil_orange_cm, "r": seuil_rouge_cm, "s": simule})
    journaliser(cx, "capteur", f"{capteur_id} enregistré ({'simulé' if simule else 'physique'})")
    return cle


def recevoir(cx: Connection, capteur_id: str, cle: str, niveau_cm: float, batterie_v: float | None) -> dict:
    c = cx.execute(text("SELECT * FROM capteur WHERE id = :i AND actif"), {"i": capteur_id}).first()
    if c is None or not hmac.compare_digest(c.cle_hash, _empreinte(cle or "")):
        raise PermissionError("capteur inconnu ou clé invalide")
    if not -50 <= niveau_cm <= 2000:
        raise ValueError("niveau hors limites")
    cx.execute(text("INSERT INTO mesure_niveau (capteur_id, niveau_cm, batterie_v, le) VALUES (:i, :n, :b, clock_timestamp())"),
               {"i": capteur_id, "n": niveau_cm, "b": batterie_v})
    cx.execute(text("UPDATE capteur SET dernier_signal = clock_timestamp() WHERE id = :i"), {"i": capteur_id})
    niveau = score(niveau_cm, {"orange": c.seuil_orange_cm, "rouge": c.seuil_rouge_cm}).niveau
    return {"capteur": capteur_id, "niveau": niveau}


def lecture_zone(cx: Connection, zone_id: str):
    """Mesure récente la plus grave parmi les capteurs de la zone : (résultat de score, capteur) ou None."""
    lignes = cx.execute(text("""
        SELECT c.id, c.nom, c.seuil_orange_cm, c.seuil_rouge_cm, m.niveau_cm, m.le
        FROM capteur c JOIN LATERAL (SELECT niveau_cm, le FROM mesure_niveau WHERE capteur_id = c.id
                                     ORDER BY le DESC, id DESC LIMIT 1) m ON true
        WHERE c.zone_id = :z AND c.actif AND m.le > now() - make_interval(mins => :v)
    """), {"z": zone_id, "v": MINUTES_VALIDITE}).all()
    meilleur = None
    rang = {"vert": 0, "orange": 1, "rouge": 2}
    for l in lignes:
        r = score(l.niveau_cm, {"orange": l.seuil_orange_cm, "rouge": l.seuil_rouge_cm})
        r.facteurs = [f"capteur {l.id} : {l.niveau_cm:.0f} cm (orange {l.seuil_orange_cm:.0f}, rouge {l.seuil_rouge_cm:.0f})"]
        if meilleur is None or rang[r.niveau] > rang[meilleur[0].niveau]:
            meilleur = (r, l.id)
    return meilleur


def surveiller_silence(cx: Connection) -> int:
    """Capteurs muets depuis plus d'une heure : une notification par capteur et par jour."""
    muets = cx.execute(text("""
        SELECT id, nom, dernier_signal FROM capteur
        WHERE actif AND dernier_signal IS NOT NULL AND dernier_signal < now() - make_interval(mins => :m)
    """), {"m": MINUTES_SILENCE}).all()
    n = 0
    for c in muets:
        deja = cx.execute(text("""
            SELECT 1 FROM journal WHERE type = 'capteur' AND message LIKE :p AND le >= date_trunc('day', now())
        """), {"p": f"{c.id} muet%"}).first()
        if deja:
            continue
        notifier_operateurs(cx, f"CAPTEUR MUET : {c.id} ({c.nom}) sans signal depuis {c.dernier_signal:%d/%m %H:%M}. "
                                "Panne, batterie ou arrachement : vérifier sur place.")
        journaliser(cx, "capteur", f"{c.id} muet depuis {c.dernier_signal:%d/%m %H:%M}")
        n += 1
    return n
