"""Règles de vérification des signalements (sans base de données, donc testables).

- Classe retenue : celle de l'IA si elle est assez sûre d'elle, sinon l'avis du relais.
- « bouché » n'est validé que par un relais fiable ou par une deuxième source indépendante.
- « propre » et « partiel » sont acceptés sur une source : ils ne peuvent pas abaisser les seuils.
- Fiabilité d'un relais : estimateur de Laplace, (confirmées + 1) / (décisions + 2), 0,5 au départ.
"""
from __future__ import annotations

CLASSES = ("propre", "partiel", "bouche")


def classe_retenue(classe_ia: str | None, confiance_ia: float | None, avis_relais: str | None,
                   seuil_confiance: float = 0.7) -> str | None:
    if classe_ia in CLASSES and confiance_ia is not None and confiance_ia >= seuil_confiance:
        return classe_ia
    if avis_relais in CLASSES:
        return avis_relais
    return classe_ia if classe_ia in CLASSES else None


def decider_statut(classe: str | None, fiabilite_relais: float, autres_sources_bouche: int,
                   seuil_fiable: float = 0.8) -> tuple[str, str]:
    """(statut, motif). autres_sources_bouche : observations « bouché » récentes d'AUTRES sources sur ce point."""
    if classe is None:
        return "a_valider", "aucune classe : ni avis du relais ni IA assez sûre"
    if classe != "bouche":
        return "valide", "classe non critique, source unique acceptée"
    if fiabilite_relais >= seuil_fiable:
        return "valide", f"relais fiable ({fiabilite_relais:.2f})"
    if autres_sources_bouche >= 1:
        return "valide", "recoupé par une deuxième source indépendante"
    return "a_valider", "« bouché » non recoupé : validation d'un opérateur ou d'une 2e source requise"


def fiabilite(confirmees: int, rejetees: int) -> float:
    return (confirmees + 1) / (confirmees + rejetees + 2)


def decider_releve(pluie_mm: float, fiabilite_relais: float, autres_releves_mm: list[float],
                   seuil_sans_effet: float = 35.0, seuil_fiable: float = 0.8) -> tuple[str, str]:
    """Relevé de pluviomètre d'un relais. Un relevé faux pourrait déclencher une alerte orange automatique :
    au-dessus de seuil_sans_effet (moitié du seuil orange), il faut un relais fiable, un 2e relevé concordant
    du même jour dans la zone (écart ≤ 30 % ou ≤ 10 mm), ou un opérateur."""
    if pluie_mm < seuil_sans_effet:
        return "valide", "valeur trop faible pour déclencher une alerte"
    if fiabilite_relais >= seuil_fiable:
        return "valide", f"relais fiable ({fiabilite_relais:.2f})"
    if any(abs(a - pluie_mm) <= max(10.0, 0.3 * max(a, pluie_mm)) for a in autres_releves_mm):
        return "valide", "concorde avec un autre relevé du jour dans la zone"
    return "a_valider", "forte pluie non recoupée : validation d'un opérateur ou d'un 2e relevé requise"


_ORDRE = {"propre": 0, "partiel": 1, "bouche": 2}


def reaction_avis_ia(statut: str, valide_par: str | None, classe: str | None, ia: dict) -> tuple[str, str | None, str | None]:
    """Que faire d'une observation après le « second regard » du modèle de vision ?

    Règle : l'IA peut RENVOYER en vérification humaine, jamais valider seule.
    - photo qui ne montre pas un caniveau -> vérification (photo hors sujet ou abus) ;
    - désaccord franc avec la classe retenue (propre contre bouché) -> vérification ;
    - aucune classe retenue (relais sans avis) -> l'IA propose sa classe, qui reste à confirmer.
    Une décision prise par un opérateur n'est jamais remise en cause. Renvoie (statut, motif ou None, classe).
    """
    automatique = valide_par in (None, "automatique")
    if not automatique:
        return statut, None, classe
    if not ia.get("est_caniveau", True):
        return "a_valider", "photo hors sujet selon l'IA : vérification requise", classe
    proposee = ia.get("classe")
    if classe is None and proposee:
        return "a_valider", f"classe proposée par l'IA ({proposee}), à confirmer", proposee
    if classe and proposee and abs(_ORDRE[classe] - _ORDRE[proposee]) == 2:
        return "a_valider", f"désaccord net entre le relais ({classe}) et l'IA ({proposee}) : vérification requise", classe
    return statut, None, classe


def decider_signalement(fiabilite_relais: float, voisins_independants: int,
                        seuil_fiable: float = 0.8) -> tuple[str, str]:
    """Signalement libre géolocalisé (route inondée, danger…). voisins_independants : signalements du même type,
    à moins de 300 m et de 6 h, venant d'autres personnes. Une fausse inondation sur la carte publique ferait
    fuir des habitants pour rien : sans recoupement ni relais fiable, un opérateur décide."""
    if fiabilite_relais >= seuil_fiable:
        return "valide", f"relais fiable ({fiabilite_relais:.2f})"
    if voisins_independants >= 1:
        return "valide", "confirmé par un autre habitant à moins de 300 m"
    return "a_valider", "signalement isolé : vérification d'un opérateur ou d'un 2e témoin requise"
