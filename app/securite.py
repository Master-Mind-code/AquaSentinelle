"""Chiffrement des contacts, empreintes, mots de passe.

- Contacts (numéros, identifiants Telegram) : chiffrés (Fernet, AES-128 + HMAC), jamais en clair en base.
- Empreinte : HMAC-SHA256 du contact normalisé, pour retrouver un abonné sans déchiffrer.
- Mots de passe : scrypt salé.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from app.settings import reglages


def _fernet() -> Fernet:
    cle = hashlib.sha256(("fernet:" + reglages().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(cle))


def normaliser_contact(contact: str, telephone: bool = True) -> str:
    """Numéros : chiffres seulement, préfixe 225 ajouté aux numéros ivoiriens à 10 chiffres.

    telephone=False pour un identifiant Telegram : il ne doit surtout pas recevoir de préfixe.
    """
    c = contact.strip()
    if telephone and c.lstrip("+").replace(" ", "").replace("-", "").isdigit():
        c = "".join(ch for ch in c if ch.isdigit())
        if len(c) == 10:
            c = "225" + c
        return "+" + c
    return c


def chiffrer(contact: str, telephone: bool = True) -> bytes:
    return _fernet().encrypt(normaliser_contact(contact, telephone).encode())


def dechiffrer(donnee: bytes) -> str:
    return _fernet().decrypt(bytes(donnee)).decode()


def empreinte(contact: str, telephone: bool = True) -> str:
    cle = hashlib.sha256(("hmac:" + reglages().secret_key).encode()).digest()
    return hmac.new(cle, normaliser_contact(contact, telephone).encode(), hashlib.sha256).hexdigest()


def hacher_mot_de_passe(mdp: str) -> str:
    sel = secrets.token_bytes(16)
    h = hashlib.scrypt(mdp.encode(), salt=sel, n=2**14, r=8, p=1)
    return f"scrypt${sel.hex()}${h.hex()}"


def verifier_mot_de_passe(mdp: str, stocke: str) -> bool:
    try:
        _, sel, h = stocke.split("$")
    except ValueError:
        return False
    calc = hashlib.scrypt(mdp.encode(), salt=bytes.fromhex(sel), n=2**14, r=8, p=1)
    return hmac.compare_digest(calc.hex(), h)
