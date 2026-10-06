"""Remet la base de DÉMONSTRATION à zéro (par exemple avant la soutenance).

    python scripts/reinitialiser_demo.py --oui

1. Sauvegarde complète (pg_dump) dans data/sauvegardes/ : on peut toujours revenir en arrière avec
   docker exec -i aquasentinelle-ci-db-1 psql -U aqua -d aquasentinelle < data/sauvegardes/<fichier>.sql
2. Efface : alertes, envois, scores, états de zone, signalements, étiquettes, relais, relevés, abonnés,
   journal, pluies simulées et relevés de pluviomètre, photos.
   Efface aussi : signalements libres, demandes d'aide, capteurs et leurs mesures.
3. Garde : zones, comptes opérateurs, points, lieux sûrs, pluie et débits collectés, historique.
4. Donne aux points de démonstration quelques états fictifs (source « demo »), puis relance un cycle.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import transaction  # noqa: E402
from app.settings import reglages  # noqa: E402

ETATS_DEMO = {"ATT-001": "bouche", "ATT-002": "partiel", "YOP-001": "propre", "ABO-001": "partiel", "YOP-002": "propre"}
CONTENEUR = "aquasentinelle-ci-db-1"


def sauvegarder() -> Path:
    dossier = ROOT / "data" / "sauvegardes"
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"avant_reinitialisation_{datetime.now():%Y%m%d_%H%M%S}.sql"
    r = subprocess.run(["docker", "exec", CONTENEUR, "pg_dump", "-U", "aqua", "-d", "aquasentinelle", "--clean", "--if-exists"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise SystemExit(f"Sauvegarde impossible, rien n'a été effacé : {r.stderr.decode(errors='replace')[:300]}")
    f.write_bytes(r.stdout)
    return f


def main() -> None:
    if "--oui" not in sys.argv:
        raise SystemExit("Efface l'historique de la base de démonstration (après sauvegarde). Relancer avec --oui.")
    f = sauvegarder()
    print(f"Sauvegarde : {f.relative_to(ROOT)} ({f.stat().st_size // 1024} Ko)")
    with transaction() as cx:
        for table in ("envoi", "alerte", "score_risque", "etat_zone", "etiquette", "observation",
                      "releve_pluviometre", "abonne", "journal", "signalement", "demande_aide", "mesure_niveau", "capteur"):
            n = cx.execute(text(f"DELETE FROM {table}")).rowcount
            print(f"  {table:20s} {n} ligne(s) effacée(s)")
        cx.execute(text("DELETE FROM relais"))
        n = cx.execute(text("DELETE FROM mesure_pluie WHERE source IN ('simulation','pluviometre')")).rowcount
        print(f"  {'pluies simulées/relevés':20s} {n}")
        cx.execute(text("DELETE FROM point_controle WHERE description LIKE 'Test bout en bout%'"))
        for pid, classe in ETATS_DEMO.items():
            cx.execute(text("""
                INSERT INTO observation (point_id, source, classe, avis_relais, statut, motif, valide_par, valide_le)
                SELECT :p, 'demo', :c, :c, 'valide', 'donnée de démonstration (fictive)', 'demo', now()
                WHERE EXISTS (SELECT 1 FROM point_controle WHERE id = :p)
            """), {"p": pid, "c": classe})
        cx.execute(text("INSERT INTO journal (type, message) VALUES ('demo', 'base de démonstration réinitialisée')"))
    photos = reglages().dossier_photos
    if photos.exists():
        shutil.rmtree(photos)
    print(f"  photos effacées ({photos})")
    from app.cycle import cycle_complet
    bilan = cycle_complet(chirps=False)
    print("Cycle relancé :", {z: v.get("score", {}).get("niveau") for z, v in bilan["zones"].items()})


if __name__ == "__main__":
    main()
