"""Accord entre deux étiqueteurs (kappa de Cohen) et matrice de confusion."""
from __future__ import annotations

from collections import Counter


def matrice_confusion(paires: list[tuple[str, str]], classes: list[str]) -> list[list[int]]:
    idx = {c: i for i, c in enumerate(classes)}
    m = [[0] * len(classes) for _ in classes]
    for a, b in paires:
        m[idx[a]][idx[b]] += 1
    return m


def kappa_cohen(paires: list[tuple[str, str]]) -> float | None:
    """1 = accord parfait, 0 = pas mieux que le hasard. None si moins de 2 paires."""
    n = len(paires)
    if n < 2:
        return None
    po = sum(a == b for a, b in paires) / n
    ca, cb = Counter(a for a, _ in paires), Counter(b for _, b in paires)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / n**2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def interpretation(k: float | None) -> str:
    """Échelle de Landis et Koch (1977)."""
    if k is None:
        return "pas assez de paires"
    for borne, mot in ((0.8, "quasi parfait"), (0.6, "fort"), (0.4, "modéré"), (0.2, "faible"), (0.0, "très faible")):
        if k > borne:
            return mot
    return "nul ou négatif"
