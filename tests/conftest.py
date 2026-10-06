"""Les tests utilisent une base SÉPARÉE (aquasentinelle_test) et un dossier de photos temporaire :
ils ne touchent jamais à la base de démonstration ni aux photos de l'application.

Attention : app.settings fige ses réglages à l'import. Rien de app/ ne doit être importé avant
d'avoir modifié l'environnement ci-dessous.
"""
import os
import tempfile
from pathlib import Path

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for ligne in _env.read_text(encoding="utf-8-sig").splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, val = ligne.split("=", 1)
            os.environ.setdefault(cle.strip(), val.strip())

_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://aqua:aqua@localhost:5434/aquasentinelle")
_base = _url.rpartition("/")[0]
os.environ["DATABASE_URL"] = f"{_base}/aquasentinelle_test"
os.environ["DOSSIER_PHOTOS"] = tempfile.mkdtemp(prefix="aqua_photos_test_")
os.environ["PLANIFICATEUR_ACTIF"] = "false"


def _creer_base_de_test() -> None:
    try:
        import psycopg
        conninfo = _base.replace("postgresql+psycopg://", "postgresql://") + "/postgres"
        with psycopg.connect(conninfo, autocommit=True, connect_timeout=5) as c:
            if not c.execute("SELECT 1 FROM pg_database WHERE datname = 'aquasentinelle_test'").fetchone():
                c.execute("CREATE DATABASE aquasentinelle_test")
    except Exception:
        pass  # base injoignable : les tests d'intégration seront ignorés


_creer_base_de_test()
