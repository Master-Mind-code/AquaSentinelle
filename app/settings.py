"""Réglages lus dans l'environnement (fichier .env en local, variables Docker en conteneur).

Aucun secret n'est écrit dans le code : voir .env.example.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _charger_env(fichier: Path = ROOT / ".env") -> None:
    """Lecteur minimal de .env (clé=valeur), sans écraser les variables déjà définies."""
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, val = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


_charger_env()


def _bool(nom: str, defaut: bool) -> bool:
    return os.environ.get(nom, str(defaut)).lower() in ("1", "true", "oui", "yes")


class Reglages:
    database_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://aqua:aqua@localhost:5434/aquasentinelle")
    secret_key = os.environ.get("APP_SECRET_KEY", "")
    base_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

    admin_identifiant = os.environ.get("ADMIN_IDENTIFIANT", "admin")
    admin_mot_de_passe = os.environ.get("ADMIN_MOT_DE_PASSE", "")

    planificateur_actif = _bool("PLANIFICATEUR_ACTIF", True)
    planificateur_minutes = int(os.environ.get("PLANIFICATEUR_MINUTES", "60"))
    escalade_minutes = int(os.environ.get("ESCALADE_MINUTES", "15"))
    anti_doublon_heures = int(os.environ.get("ANTI_DOUBLON_HEURES", "6"))
    plafond_envois_jour = int(os.environ.get("PLAFOND_ENVOIS_JOUR", "5"))
    peremption_jours = int(os.environ.get("PEREMPTION_JOURS", "30"))
    seuil_relais_fiable = float(os.environ.get("SEUIL_RELAIS_FIABLE", "0.8"))
    seuil_confiance_ia = float(os.environ.get("SEUIL_CONFIANCE_IA", "0.7"))

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_bot_nom = os.environ.get("TELEGRAM_BOT_NOM", "")
    sms_fournisseur = os.environ.get("SMS_FOURNISSEUR", "")          # africastalking | passerelle | vide
    at_username = os.environ.get("AT_USERNAME", "sandbox")
    at_api_key = os.environ.get("AT_API_KEY", "")
    at_sender_id = os.environ.get("AT_SENDER_ID", "")
    passerelle_url = os.environ.get("SMS_PASSERELLE_URL", "")        # ex. http://192.168.1.20:8080/message
    passerelle_identifiant = os.environ.get("SMS_PASSERELLE_IDENTIFIANT", "")
    passerelle_mot_de_passe = os.environ.get("SMS_PASSERELLE_MOT_DE_PASSE", "")

    ia_vision_active = _bool("IA_VISION_ACTIVE", True)
    earthdata_token = os.environ.get("EARTHDATA_TOKEN", "")
    imerg_dans_score = _bool("IMERG_DANS_SCORE", False)

    dossier_photos = Path(os.environ.get("DOSSIER_PHOTOS", ROOT / "data" / "photos"))
    modele_ia = Path(os.environ.get("MODELE_IA", ROOT / "models" / "caniveaux.onnx"))


@lru_cache
def reglages() -> Reglages:
    r = Reglages()
    if not r.secret_key or len(r.secret_key) < 32:
        raise RuntimeError("APP_SECRET_KEY absente ou trop courte (32 caractères minimum) : voir .env.example")
    return r


@lru_cache
def config_zones() -> dict:
    return yaml.safe_load((ROOT / "config" / "zones.yaml").read_text(encoding="utf-8"))


def seuils_zone(zone_id: str) -> dict:
    """Seuils de pluie d'une zone : ceux de config/seuils_zones.yaml (transposés) sinon ceux d'Abidjan."""
    cfg = config_zones()
    propre = _seuils_transposes().get(zone_id, {})
    return {"seuils_pluie_24h_mm": propre.get("seuils_pluie_24h_mm", cfg["seuils_pluie_24h_mm"]),
            "seuils_prevision_24h_mm": propre.get("seuils_prevision_24h_mm", cfg["seuils_prevision_24h_mm"]),
            "transposes": bool(propre)}


@lru_cache
def _seuils_transposes() -> dict:
    f = ROOT / "config" / "seuils_zones.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}
