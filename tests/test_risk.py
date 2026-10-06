from src.risk import ORANGE, ROUGE, VERT, score

SEUILS = {"orange": 50, "rouge": 100}


def test_niveaux_de_base():
    assert score(10, SEUILS).niveau == VERT
    assert score(60, SEUILS).niveau == ORANGE
    assert score(120, SEUILS).niveau == ROUGE


def test_caniveaux_bouches_abaissent_les_seuils():
    assert score(46, SEUILS).niveau == VERT
    assert score(46, SEUILS, part_caniveaux_bouches=1.0).niveau == ORANGE


def test_sans_donnee_caniveaux_pas_de_majoration():
    assert score(46, SEUILS, part_caniveaux_bouches=None).niveau == VERT


def test_message_contient_la_zone():
    from src.messages import message
    assert "Yopougon" in message("rouge", "Yopougon")
    assert len(message("rouge", "Yopougon")) < 320
