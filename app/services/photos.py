"""Préparation des photos des relais (S20) : redimensionnement, floutage des visages, suppression des métadonnées.

Le réencodage JPEG supprime les données EXIF (position GPS du téléphone, modèle, date).
Détection des visages : cascade de Haar d'OpenCV (simple, hors ligne). Elle rate des visages de profil :
le floutage réduit le risque, il ne le supprime pas.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

COTE_MAX = 1600


@lru_cache
def _detecteur():
    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def preparer(donnees: bytes) -> tuple[bytes, int]:
    """(JPEG nettoyé, nombre de visages floutés). Lève ValueError si ce n'est pas une image."""
    img = cv2.imdecode(np.frombuffer(donnees, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("fichier illisible : envoyer une photo JPEG ou PNG")
    h, w = img.shape[:2]
    if max(h, w) > COTE_MAX:
        f = COTE_MAX / max(h, w)
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    visages = _detecteur().detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    for (x, y, fw, fh) in visages:
        m = int(0.15 * fw)
        x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(img.shape[1], x + fw + m), min(img.shape[0], y + fh + m)
        zone = img[y0:y1, x0:x1]
        k = max(31, (min(zone.shape[:2]) // 2) | 1)
        img[y0:y1, x0:x1] = cv2.GaussianBlur(zone, (k, k), 0)
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("échec de l'encodage JPEG")
    return jpeg.tobytes(), len(visages)
