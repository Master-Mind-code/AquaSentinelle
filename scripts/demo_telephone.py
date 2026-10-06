"""Prépare la démonstration sur téléphones : adresse HTTPS publique temporaire + QR code d'accès.

    python scripts/demo_telephone.py           # démarre le tunnel, met BASE_URL à jour, affiche le QR code
    python scripts/demo_telephone.py --arret   # ferme le tunnel et revient à http://localhost:8000

Pourquoi HTTPS : les téléphones ne donnent leur position GPS qu'à un site en HTTPS.
L'adresse (https://….trycloudflare.com) change à chaque lancement : imprimer la planche de QR codes des points
APRÈS avoir lancé ce script. Tant que le tunnel tourne, le site est joignable depuis internet : l'arrêter après.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
LOCAL = "http://localhost:8000"


def docker(*args: str, capture: bool = True) -> str:
    r = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=capture, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"docker compose {' '.join(args)} a échoué :\n{r.stderr}")
    return (r.stdout or "") + (r.stderr or "")


def fixer_base_url(url: str) -> None:
    texte = ENV.read_text(encoding="utf-8")
    texte = re.sub(r"(?m)^BASE_URL=.*$", f"BASE_URL={url}", texte) if re.search(r"(?m)^BASE_URL=", texte) \
        else texte + f"\nBASE_URL={url}\n"
    ENV.write_text(texte, encoding="utf-8")
    docker("up", "-d", "--force-recreate", "app")      # l'application relit .env
    for _ in range(60):
        try:
            import urllib.request
            urllib.request.urlopen(f"{LOCAL}/sante", timeout=3)
            return
        except Exception:
            time.sleep(2)
    raise SystemExit("l'application ne répond pas après redémarrage")


def arret() -> None:
    docker("--profile", "demo", "stop", "tunnel")
    docker("--profile", "demo", "rm", "-f", "tunnel")
    fixer_base_url(LOCAL)
    print(f"Tunnel fermé. Le site n'est plus joignable depuis internet. BASE_URL = {LOCAL}")


def demarrer() -> None:
    print("Démarrage du tunnel HTTPS…")
    docker("--profile", "demo", "up", "-d", "--force-recreate", "tunnel")
    url = None
    for _ in range(45):
        trouve = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", docker("--profile", "demo", "logs", "tunnel"))
        if trouve:
            url = trouve[-1]
            break
        time.sleep(2)
    if not url:
        raise SystemExit("Pas d'adresse reçue de Cloudflare (connexion internet ?). Voir : docker compose logs tunnel")
    print(f"Adresse publique : {url}\nMise à jour de BASE_URL et redémarrage de l'application…")
    fixer_base_url(url)
    # le tunnel met parfois quelques secondes à router les premières requêtes
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{url}/sante", timeout=10)
            break
        except Exception:
            time.sleep(3)
    else:
        print("ATTENTION : l'adresse ne répond pas encore depuis internet ; réessayer dans une minute.")
    image = ROOT / "data" / "qr_demo.png"
    qrcode.make(url).save(image)
    q = qrcode.QRCode(border=1)
    q.add_data(url)
    q.print_ascii(invert=True)
    print(f"""
Scannez ce QR code avec les téléphones (image aussi enregistrée : {image.relative_to(ROOT)}).
  Public          : {url}
  Signaler        : {url}/signaler        Aide d'urgence : {url}/aide
  Point de contrôle (exemple) : {url}/r/ATT-001
  Opérateurs      : {url}/connexion  (sur le PC aussi : utilisez cette adresse HTTPS, pas localhost)

À faire maintenant : imprimer la planche de QR codes des points (elle contient cette nouvelle adresse).
Après la démonstration : python scripts/demo_telephone.py --arret""")


if __name__ == "__main__":
    arret() if "--arret" in sys.argv else demarrer()
