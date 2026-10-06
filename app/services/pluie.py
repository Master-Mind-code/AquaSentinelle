"""Collecte de la pluie (S4) : prévision multi-modèles chaque cycle, CHIRPS dès qu'il est publié.

Gestion des trous : à chaque cycle, on retente les jours CHIRPS manquants des 40 derniers jours.
CHIRPS est publié avec plusieurs semaines de retard : un jour absent n'est pas une erreur.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from src import rain_sources as rs

FENETRE_CHIRPS_JOURS = 40


def enregistrer(cx: Connection, zone_id: str, source: str, jour: date, mm: float) -> None:
    cx.execute(text("""
        INSERT INTO mesure_pluie (zone_id, source, jour, pluie_mm) VALUES (:z, :s, :j, :mm)
        ON CONFLICT (zone_id, source, jour) DO UPDATE SET pluie_mm = EXCLUDED.pluie_mm, recu_le = now()
    """), {"z": zone_id, "s": source, "j": jour, "mm": float(mm)})


def zones(cx: Connection) -> list[dict]:
    return [dict(r._mapping) for r in cx.execute(text(
        "SELECT id, nom, langue, telegram_chat, ST_Y(centre) AS lat, ST_X(centre) AS lon FROM zone ORDER BY id"))]


def collecter_prevision(cx: Connection, zone: dict) -> int:
    prev = rs.openmeteo_prevision_multimodele(zone["lat"], zone["lon"], days=2)
    n = 0
    for jour, mm in prev.dropna().items():
        enregistrer(cx, zone["id"], "prevision_max", jour.date(), mm)
        n += 1
    return n


def jours_chirps_manquants(cx: Connection, zone_id: str, aujourdhui: date) -> list[date]:
    debut = aujourdhui - timedelta(days=FENETRE_CHIRPS_JOURS)
    presents = {r[0] for r in cx.execute(text(
        "SELECT jour FROM mesure_pluie WHERE zone_id = :z AND source = 'chirps_max' AND jour >= :d"),
        {"z": zone_id, "d": debut})}
    return [debut + timedelta(n) for n in range(FENETRE_CHIRPS_JOURS) if debut + timedelta(n) not in presents]


def collecter_chirps(cx: Connection, zone: dict, aujourdhui: date) -> tuple[int, int]:
    """(jours ajoutés, jours encore absents)."""
    ajoutes = absents = 0
    for jour in jours_chirps_manquants(cx, zone["id"], aujourdhui):
        r = rs.chirps_point(jour, zone["lat"], zone["lon"])
        if r is None:
            absents += 1
            continue
        enregistrer(cx, zone["id"], "chirps_max", jour, r[1])
        ajoutes += 1
    return ajoutes, absents


def collecter_imerg(cx: Connection, zone: dict, aujourdhui: date, token: str) -> int:
    """IMERG Early (S3) pour hier et aujourd'hui. Stocké et affiché ; utilisé dans le score seulement
    si IMERG_DANS_SCORE=true (à activer après calibration avec scripts/evaluate.py)."""
    n = 0
    for jour in (aujourdhui - timedelta(1), aujourdhui):
        mm = rs.imerg_early_jour(jour, zone["lat"], zone["lon"], token)
        if mm is not None:
            enregistrer(cx, zone["id"], "imerg_early", jour, mm)
            n += 1
    return n


def collecter_debit(cx: Connection, zone_id: str) -> int:
    """Prévision GloFAS du débit (m³/s) sur 7 jours, à la station de rivière de la zone."""
    r = cx.execute(text("SELECT ST_Y(position) AS lat, ST_X(position) AS lon FROM riviere WHERE zone_id = :z"),
                   {"z": zone_id}).first()
    if r is None:
        return 0
    serie = rs.glofas_debit(r.lat, r.lon, forecast_days=7).dropna()
    for jour, q in serie.items():
        cx.execute(text("""
            INSERT INTO mesure_debit (zone_id, jour, prevision, debit_m3s) VALUES (:z, :j, true, :q)
            ON CONFLICT (zone_id, jour, prevision) DO UPDATE SET debit_m3s = EXCLUDED.debit_m3s, recu_le = now()
        """), {"z": zone_id, "j": jour.date(), "q": float(q)})
    return len(serie)


def collecter(cx: Connection, aujourdhui: date | None = None, chirps: bool = True) -> dict:
    from app.settings import reglages
    aujourdhui = aujourdhui or date.today()
    bilan = {}
    for z in zones(cx):
        b = {}
        if reglages().earthdata_token:
            try:
                b["imerg_jours"] = collecter_imerg(cx, z, aujourdhui, reglages().earthdata_token)
            except Exception as e:
                b["erreur_imerg"] = str(e)[:200]
                journaliser(cx, "erreur", f"IMERG {z['id']} : {e}")
        try:
            b["prevision_jours"] = collecter_prevision(cx, z)
        except Exception as e:  # réseau, API indisponible : on continue avec les autres zones
            b["erreur_prevision"] = str(e)[:200]
            journaliser(cx, "erreur", f"prévision {z['id']} : {e}")
        try:
            n = collecter_debit(cx, z["id"])
            if n:
                b["debit_jours"] = n
        except Exception as e:
            b["erreur_debit"] = str(e)[:200]
            journaliser(cx, "erreur", f"débit {z['id']} : {e}")
        if chirps:
            try:
                b["chirps_ajoutes"], b["chirps_absents"] = collecter_chirps(cx, z, aujourdhui)
            except Exception as e:
                b["erreur_chirps"] = str(e)[:200]
                journaliser(cx, "erreur", f"CHIRPS {z['id']} : {e}")
        bilan[z["id"]] = b
    journaliser(cx, "collecte", str(bilan))
    return bilan
