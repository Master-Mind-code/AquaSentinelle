from src.alertes import decider
from src.risk import ORANGE, ROUGE, VERT


def test_pas_de_repetition():
    assert decider(ORANGE, ORANGE).action == "rien"


def test_hausse_orange_automatique():
    assert decider(ORANGE, VERT).action == "envoyer"


def test_rouge_attend_un_humain():
    assert decider(ROUGE, ORANGE).action == "attendre_validation"
    assert decider(ROUGE, VERT, validee_par="ONPC-permanence").action == "envoyer"


def test_retour_a_la_normale():
    assert decider(VERT, ROUGE).action == "envoyer"
    assert decider(ORANGE, ROUGE).action == "rien"


def test_premier_passage_sans_historique():
    assert decider(VERT, None).action == "rien"
    assert decider(ORANGE, None).action == "envoyer"
