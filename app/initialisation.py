"""Initialisation : schéma, zones (depuis config/zones.yaml), compte administrateur, historique de pluie.

    python -m app.initialisation            # schéma + zones + admin
    python -m app.initialisation --demo     # + points de démonstration (marqués « demo »)
"""
from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import appliquer_schema, transaction
from app.securite import hacher_mot_de_passe
from app.settings import ROOT, config_zones, reglages


def charger_zones(cx: Connection) -> int:
    zs = config_zones()["zones"]
    for z in zs:
        cx.execute(text("""
            INSERT INTO zone (id, nom, centre, telegram_chat, region, type)
            VALUES (:i, :n, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :tg, :reg, :typ)
            ON CONFLICT (id) DO UPDATE SET nom = EXCLUDED.nom, centre = EXCLUDED.centre, region = EXCLUDED.region,
                                           type = EXCLUDED.type,
                                           telegram_chat = COALESCE(EXCLUDED.telegram_chat, zone.telegram_chat)
        """), {"i": z["id"], "n": z["nom"], "lat": z["lat"], "lon": z["lon"], "tg": z.get("telegram_chat"),
               "reg": z.get("region"), "typ": z.get("type", "urbaine")})
        if z.get("riviere"):
            r = z["riviere"]
            cx.execute(text("""
                INSERT INTO riviere (zone_id, nom, position) VALUES (:z, :n, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                ON CONFLICT (zone_id) DO UPDATE SET nom = EXCLUDED.nom, position = EXCLUDED.position,
                  seuil_orange = CASE WHEN ST_Equals(riviere.position, EXCLUDED.position) THEN riviere.seuil_orange END,
                  seuil_rouge = CASE WHEN ST_Equals(riviere.position, EXCLUDED.position) THEN riviere.seuil_rouge END
            """), {"z": z["id"], "n": r["nom"], "lat": r["lat"], "lon": r["lon"]})
    return len(zs)


def creer_admin(cx: Connection) -> str:
    r = reglages()
    if cx.execute(text("SELECT 1 FROM operateur WHERE identifiant = :i"), {"i": r.admin_identifiant}).first():
        return "existant"
    if len(r.admin_mot_de_passe) < 10:
        raise RuntimeError("ADMIN_MOT_DE_PASSE absent ou trop court (10 caractères minimum) : voir .env")
    cx.execute(text("""
        INSERT INTO operateur (identifiant, nom, mot_de_passe_hash, role) VALUES (:i, 'Administrateur', :h, 'admin')
    """), {"i": r.admin_identifiant, "h": hacher_mot_de_passe(r.admin_mot_de_passe)})
    return "créé"


def importer_historique(cx: Connection) -> int:
    """Rejeux CHIRPS / Open-Meteo déjà calculés (data/results) -> mesure_pluie, pour les graphiques."""
    n = 0
    for f in sorted((ROOT / "data" / "results").glob("*_*-*-*_*.csv")):
        zone_id = f.name.split("_")[0]
        if not cx.execute(text("SELECT 1 FROM zone WHERE id = :z"), {"z": zone_id}).first():
            continue
        df = pd.read_csv(f, parse_dates=["date"])
        for col, source in (("chirps_max_mm", "chirps_max"), ("openmeteo_mm", "openmeteo")):
            for _, row in df.dropna(subset=[col]).iterrows():
                cx.execute(text("""
                    INSERT INTO mesure_pluie (zone_id, source, jour, pluie_mm) VALUES (:z, :s, :j, :mm)
                    ON CONFLICT (zone_id, source, jour) DO NOTHING
                """), {"z": zone_id, "s": source, "j": row["date"].date(), "mm": float(row[col])})
                n += 1
    return n


# Points de démonstration : positions approximatives, clairement marqués « demo » dans la base et la carte.
POINTS_DEMO = [
    ("ATT-001", "attecoube", 5.3365, -4.0390, "Démo : caniveau principal, Mossikro"),
    ("ATT-002", "attecoube", 5.3302, -4.0301, "Démo : regard, rue du marché"),
    ("ATT-003", "attecoube", 5.3401, -4.0262, "Démo : canal à ciel ouvert"),
    ("YOP-001", "yopougon", 5.3378, -4.0905, "Démo : caniveau, Micao"),
    ("YOP-002", "yopougon", 5.3290, -4.0810, "Démo : sortie de buse"),
    ("ABO-001", "abobo", 5.4190, -4.0200, "Démo : caniveau, gare"),
    ("ANY-001", "anyama", 5.4930, -4.0540, "Démo : fossé, derrière les rails"),
]


LIEUX_DEMO = [
    ("Démo : école primaire, site de regroupement", "regroupement", "attecoube", 5.3420, -4.0250, 400),
    ("Démo : mairie d'Attécoubé", "mairie", "attecoube", 5.3330, -4.0300, 150),
    ("Démo : centre de santé", "sante", "yopougon", 5.3400, -4.0750, 60),
    ("Démo : lycée, site de regroupement", "ecole", "abobo", 5.4250, -4.0150, 600),
]


def creer_lieux_demo(cx: Connection) -> int:
    n = 0
    for nom, type_, zone, lat, lon, cap in LIEUX_DEMO:
        if not cx.execute(text("SELECT 1 FROM lieu_sur WHERE nom = :n"), {"n": nom}).first():
            cx.execute(text("""
                INSERT INTO lieu_sur (nom, type, zone_id, position, capacite, demo)
                VALUES (:n, :t, :z, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :c, true)
            """), {"n": nom, "t": type_, "z": zone, "lat": lat, "lon": lon, "c": cap})
            n += 1
    return n


def creer_points_demo(cx: Connection) -> int:
    n = 0
    for pid, zone, lat, lon, desc in POINTS_DEMO:
        n += cx.execute(text("""
            INSERT INTO point_controle (id, zone_id, position, description, demo)
            VALUES (:i, :z, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :d, true)
            ON CONFLICT (id) DO NOTHING
        """), {"i": pid, "z": zone, "lat": lat, "lon": lon, "d": desc}).rowcount
    return n


def initialiser(demo: bool = False) -> dict:
    with transaction() as cx:
        appliquer_schema(cx)
        bilan = {"zones": charger_zones(cx), "admin": creer_admin(cx), "historique": importer_historique(cx)}
        if demo:
            bilan["points_demo"] = creer_points_demo(cx)
            bilan["lieux_demo"] = creer_lieux_demo(cx)
    return bilan


if __name__ == "__main__":
    print(initialiser(demo="--demo" in sys.argv))
