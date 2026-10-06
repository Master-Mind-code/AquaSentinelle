"""Analyse d'une photo par un grand modèle de vision local (Ollama, par défaut Gemma 4) : « second regard ».

Rôle : il ne valide JAMAIS seul (un modèle de vision peut se tromper avec assurance). Il sert à :
- donner une classe et une justification lisible aux opérateurs ;
- détecter une photo hors sujet ou un désaccord net avec le relais (le signalement repasse en vérification) ;
- servir de « troisième annotateur » mesurable face aux étiquettes humaines (page Accord entre étiqueteurs).
La cible en production reste MobileNet (léger), entraîné sur les photos validées.
"""
from __future__ import annotations

import base64
import json
import os
import time

import cv2
import numpy as np
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODELE = os.environ.get("OLLAMA_MODELE_VISION", "gemma4:e4b")
CONFIANCE = {"faible": 0.4, "moyenne": 0.65, "elevee": 0.85}
SEUIL_PARTIEL, SEUIL_BOUCHE = 15, 60      # % d'obstruction : à recaler sur les photos étiquetées par l'équipe

SCHEMA = {
    "type": "object",
    "properties": {
        "est_caniveau": {"type": "boolean"},
        "obstruction_pct": {"type": "integer", "minimum": 0, "maximum": 100},
        "classe": {"type": "string", "enum": ["propre", "partiel", "bouche", "indetermine"]},
        "confiance": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
        "eau_stagnante": {"type": "boolean"},
        "dechets_visibles": {"type": "boolean"},
        "personne_visible": {"type": "boolean"},
        "justification": {"type": "string"},
    },
    "required": ["est_caniveau", "obstruction_pct", "classe", "confiance", "eau_stagnante", "dechets_visibles", "personne_visible", "justification"],
}

CONSIGNE = """Tu es un agent technique chargé du suivi des caniveaux et canaux d'évacuation des eaux de pluie en Côte d'Ivoire.
Analyse la photo et réponds uniquement en JSON.
- est_caniveau : la photo montre-t-elle un caniveau, un canal, un fossé, une grille ou un regard d'évacuation des eaux ?
  (faux pour un document, un texte, une personne seule, un paysage sans ouvrage d'évacuation)
- obstruction_pct : part (0 à 100) de la section du caniveau ou de la grille bloquée par des déchets, du sable, de la
  boue, de la végétation ou de l'eau stagnante. 0 = entièrement dégagé, 100 = entièrement bouché. Sois précis : une
  grille couverte de bouteilles et de sachets dépasse 70 ; un canal à l'eau claire qui coule est sous 10.
- classe : « propre » si l'eau peut circuler librement ; « partiel » si des déchets, du sable ou de la végétation gênent
  une partie de l'écoulement ; « bouche » si l'écoulement est bloqué ou presque (déchets, boue, eau stagnante qui ne
  s'écoule pas) ; « indetermine » si ce n'est pas un caniveau ou si on ne peut pas juger.
- confiance : ta certitude sur la classe.
- justification : une phrase courte en français (moins de 25 mots) décrivant ce que tu vois."""


def _preparer(jpeg: bytes, cote: int = 768) -> str:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("image illisible")
    h, w = img.shape[:2]
    if max(h, w) > cote:
        f = cote / max(h, w)
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    return base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()).decode()


def disponible(timeout: float = 3) -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        return r.ok and any(m["name"] == MODELE for m in r.json().get("models", []))
    except requests.RequestException:
        return False


def analyser(jpeg: bytes, timeout: float = 180) -> dict:
    """Résultat normalisé : classe (ou None), confiance (0-1), drapeaux, justification, durée, modèle."""
    debut = time.time()
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=timeout, json={
        "model": MODELE, "stream": False, "think": False, "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": CONSIGNE, "images": [_preparer(jpeg)]}],
    })
    r.raise_for_status()
    brut = json.loads(r.json()["message"]["content"])
    # la classe est déduite du pourcentage par une règle explicite et réglable (le modèle hésite à trancher)
    pct = int(brut.get("obstruction_pct", 0))
    classe = None if not brut["est_caniveau"] else "propre" if pct < SEUIL_PARTIEL else "partiel" if pct < SEUIL_BOUCHE else "bouche"
    return {
        "classe": classe, "obstruction_pct": pct, "classe_modele": brut["classe"],
        "confiance": CONFIANCE.get(brut["confiance"], 0.4), "est_caniveau": brut["est_caniveau"],
        "eau_stagnante": brut["eau_stagnante"], "dechets_visibles": brut["dechets_visibles"],
        "personne_visible": brut["personne_visible"], "justification": brut["justification"][:300],
        "duree_s": round(time.time() - debut, 1), "modele": MODELE,
    }
