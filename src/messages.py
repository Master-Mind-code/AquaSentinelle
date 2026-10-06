"""Messages d'alerte courts, par niveau. Les consignes sont des exemples : à valider avec la protection civile."""
from __future__ import annotations

MODELES = {
    "fr": {
        "orange": "ALERTE ORANGE - {zone}. Fortes pluies attendues. Videz les caniveaux devant chez vous, ne traversez pas l'eau, restez attentifs aux messages.",
        "rouge": "ALERTE ROUGE - {zone}. Risque d'inondation et de glissement de terrain. Quittez les bas-fonds et les pentes instables et rejoignez un point sûr. Appelez les secours en cas de danger.",
        "vert": "{zone} : retour a la normale.",
    },
    "fr_crue": {
        "orange": "ALERTE ORANGE - {zone}. Montee des eaux du fleuve attendue dans les prochains jours. Eloignez-vous des berges, mettez a l'abri documents, biens et animaux.",
        "rouge": "ALERTE ROUGE - {zone}. Crue importante du fleuve attendue. Quittez les zones basses proches du fleuve et suivez les consignes des autorites.",
        "vert": "{zone} : retour a la normale.",
    },
}


def message(niveau: str, zone: str, langue: str = "fr", crue: bool = False, lien: str = "") -> str:
    """lien : page de consignes, ajoutée aux alertes orange et rouge (pas au retour à la normale)."""
    texte = MODELES[f"{langue}_crue" if crue else langue][niveau].format(zone=zone)
    return f"{texte} Consignes : {lien}" if lien and niveau != "vert" else texte
