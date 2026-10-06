"""Exporte les photos étiquetées par DEUX personnes d'accord vers dataset/<classe>/ (S24 -> S25).

    python ia/exporter_jeu.py [--sortie dataset] [--photos-externes chemin/vers/dossier]

--photos-externes : dossier déjà rangé en sous-dossiers propre/ partiel/ bouche/ (photos prises hors application).
Les photos « inutilisable » et celles où les deux étiqueteurs divergent sont exclues.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import transaction  # noqa: E402
from app.settings import reglages  # noqa: E402

CLASSES = ("propre", "partiel", "bouche")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sortie", default=str(ROOT / "dataset"))
    p.add_argument("--photos-externes")
    a = p.parse_args()
    sortie = Path(a.sortie)
    for c in CLASSES:
        (sortie / c).mkdir(parents=True, exist_ok=True)

    with transaction() as cx:
        lignes = cx.execute(text("""
            SELECT o.id, o.photo_chemin, min(e.classe) AS classe FROM observation o
            JOIN etiquette e ON e.observation_id = o.id
            WHERE o.photo_chemin IS NOT NULL
            GROUP BY o.id, o.photo_chemin
            HAVING count(*) >= 2 AND count(DISTINCT e.classe) = 1 AND min(e.classe) <> 'inutilisable'
        """)).all()
    n = 0
    for l in lignes:
        src = reglages().dossier_photos / l.photo_chemin
        if src.exists():
            shutil.copy2(src, sortie / l.classe / f"obs{l.id}.jpg")
            n += 1
    print(f"{n} photo(s) de l'application exportée(s) (accord des deux étiqueteurs).")

    if a.photos_externes:
        ext = Path(a.photos_externes)
        for c in CLASSES:
            for f in (ext / c).glob("*"):
                if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    shutil.copy2(f, sortie / c / f"ext_{f.name}")
                    n += 1
    for c in CLASSES:
        print(f"  {c:8s} : {len(list((sortie / c).glob('*')))} photo(s)")
    print(f"Jeu prêt dans {sortie}. Suite : python ia/entrainer.py --donnees {sortie}")


if __name__ == "__main__":
    main()
