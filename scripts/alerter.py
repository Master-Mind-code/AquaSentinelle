"""Chaîne d'alerte : pluie -> score -> décision -> canal.

Rejeu (démo) : rejoue un mois passé jour par jour avec CHIRPS, sans rien envoyer pour de vrai :
    python scripts/alerter.py rejeu --zone abidjan-centre --du 2024-06-01 --au 2024-06-30
    python scripts/alerter.py rejeu ... --valide-par "permanence ONPC"   # simule la validation des rouges

Direct : prévision des prochaines 24 h pour toutes les zones (canal console par défaut), comparée
aux seuils de PRÉVISION (plus bas que les seuils observés, les modèles sous-estimant les orages) :
    python scripts/alerter.py direct
    python scripts/alerter.py direct --canal telegram     # nécessite TELEGRAM_TOKEN
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from replay import charger_config  # noqa: E402
from src import rain_sources as rs  # noqa: E402
from src.alertes import VERSION_REGLES, decider  # noqa: E402
from src.canaux import CanalConsole, canal  # noqa: E402
from src.evaluation import charger_pluie  # noqa: E402
from src.messages import message  # noqa: E402
from src.risk import score  # noqa: E402

ETAT = ROOT / "data" / "etat_alertes.json"


def traiter(zone: dict, pluie_mm: float, seuils: dict, etat: dict, envoi, valide_par: str | None,
            quand: str) -> None:
    r = score(pluie_mm, seuils)
    d = decider(r.niveau, etat.get(zone["id"]), valide_par)
    dest = zone.get("telegram_chat", zone["id"])
    if d.action == "envoyer":
        envoi.envoyer(dest, message(d.niveau, zone["nom"]), quand)
        etat[zone["id"]] = d.niveau
    elif d.action == "attendre_validation":
        print(f"{quand} [EN ATTENTE] {zone['nom']} : {d.raison} ({'; '.join(r.facteurs)})")
    else:
        etat[zone["id"]] = d.niveau


def rejeu(a, cfg) -> None:
    zone = next(z for z in cfg["zones"] if z["id"] == a.zone)
    pluie = charger_pluie(a.zone)[a.source].loc[a.du:a.au].dropna()
    etat: dict = {}
    envoi = CanalConsole(journal=False)
    print(f"Rejeu {zone['nom']} {a.du} -> {a.au} | source {a.source} | règles {VERSION_REGLES}\n")
    for jour, mm in pluie.items():
        traiter(zone, mm, cfg["seuils_pluie_24h_mm"], etat, envoi, a.valide_par, f"{jour:%Y-%m-%d}")


def direct(a, cfg) -> None:
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    envoi = canal(a.canal)
    for zone in cfg["zones"]:
        prev = rs.openmeteo_prevision_multimodele(zone["lat"], zone["lon"], days=2)
        mm = float(prev.max())  # jour le plus pluvieux entre aujourd'hui et demain
        print(f"{zone['nom']} : {mm:.1f} mm prévus (max de 5 modèles, aujourd'hui/demain)")
        traiter(zone, mm, cfg["seuils_prevision_24h_mm"], etat, envoi, a.valide_par, f"{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="mode", required=True)
    r = sp.add_parser("rejeu")
    r.add_argument("--zone", default="abidjan-centre")
    r.add_argument("--du", required=True)
    r.add_argument("--au", required=True)
    r.add_argument("--source", default="chirps_max_mm")
    r.add_argument("--valide-par")
    d = sp.add_parser("direct")
    d.add_argument("--canal", default="console", choices=["console", "telegram"])
    d.add_argument("--valide-par")
    a = p.parse_args()
    cfg = charger_config()
    (rejeu if a.mode == "rejeu" else direct)(a, cfg)


if __name__ == "__main__":
    main()
