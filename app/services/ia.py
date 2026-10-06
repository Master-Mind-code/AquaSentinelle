"""Classification d'une photo de caniveau : propre / partiel / bouché (S25, inférence).

Le modèle (ONNX) est produit par ia/entrainer.py. Tant qu'il n'existe pas, classer() renvoie (None, None)
et la classe retenue vient de l'avis du relais : le système fonctionne sans IA.
"""
from __future__ import annotations

import json
from functools import lru_cache

import cv2
import numpy as np

from app.settings import reglages

MOYENNE = np.array([0.485, 0.456, 0.406], dtype=np.float32)
ECART = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@lru_cache
def _session():
    chemin = reglages().modele_ia
    if not chemin.exists():
        return None
    import onnxruntime as ort
    etiquettes = json.loads(chemin.with_suffix(".labels.json").read_text(encoding="utf-8"))
    return ort.InferenceSession(str(chemin), providers=["CPUExecutionProvider"]), etiquettes


def disponible() -> bool:
    return _session() is not None


def pretraiter(jpeg: bytes, taille: int = 224) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    f = 256 / min(h, w)
    img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    y, x = (h - taille) // 2, (w - taille) // 2
    img = img[y:y + taille, x:x + taille].astype(np.float32) / 255.0
    return ((img - MOYENNE) / ECART).transpose(2, 0, 1)[None]


def classer(jpeg: bytes) -> tuple[str | None, float | None]:
    s = _session()
    if s is None:
        return None, None
    session, etiquettes = s
    logits = session.run(None, {session.get_inputs()[0].name: pretraiter(jpeg)})[0][0]
    p = np.exp(logits - logits.max())
    p /= p.sum()
    i = int(p.argmax())
    return etiquettes[i], float(p[i])
