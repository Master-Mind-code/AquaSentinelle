"""Simule un capteur de niveau d'eau qui envoie ses mesures à l'API, comme le ferait un ESP32.

    python scripts/simuler_capteur.py CAP-ATT-01 <clé> [--url http://localhost:8000] [--intervalle 5]

Scénario : l'eau monte de 5 cm à ~75 cm (crue éclair), puis redescend. Le capteur passe en orange puis en rouge
selon ses seuils ; lancer ensuite un cycle (page Simulation) pour voir le score de la zone réagir.
"""
from __future__ import annotations

import argparse
import math
import time

import requests


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("capteur")
    p.add_argument("cle")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--intervalle", type=float, default=5, help="secondes entre deux mesures")
    p.add_argument("--points", type=int, default=16)
    a = p.parse_args()
    for i in range(a.points):
        niveau = 5 + 70 * math.sin(math.pi * i / (a.points - 1))       # montée puis décrue
        batterie = 3.9 - 0.01 * i
        r = requests.post(f"{a.url}/api/capteurs/{a.capteur}/mesures", timeout=15,
                          headers={"X-Cle-API": a.cle}, json={"niveau_cm": round(niveau, 1), "batterie_v": round(batterie, 2)})
        etat = r.json().get("niveau", r.text[:80]) if r.ok else f"refusé ({r.status_code})"
        print(f"{i + 1:2d}/{a.points} · {niveau:5.1f} cm · {etat}")
        if not r.ok:
            break
        time.sleep(a.intervalle)


if __name__ == "__main__":
    main()
