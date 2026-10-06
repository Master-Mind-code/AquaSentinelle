from src.accord import interpretation, kappa_cohen, matrice_confusion
from src.anti_abus import verdict
from src.recoupement import classe_retenue, decider_statut, fiabilite


def test_classe_retenue_ia_sure_puis_avis_relais():
    assert classe_retenue("bouche", 0.9, "propre") == "bouche"
    assert classe_retenue("bouche", 0.5, "propre") == "propre"
    assert classe_retenue(None, None, None) is None


def test_bouche_exige_relais_fiable_ou_deuxieme_source():
    assert decider_statut("bouche", 0.5, 0)[0] == "a_valider"
    assert decider_statut("bouche", 0.85, 0)[0] == "valide"
    assert decider_statut("bouche", 0.5, 1)[0] == "valide"
    assert decider_statut("propre", 0.1, 0)[0] == "valide"
    assert decider_statut(None, 0.9, 3)[0] == "a_valider"


def test_fiabilite_laplace():
    assert fiabilite(0, 0) == 0.5
    assert fiabilite(8, 0) == 0.9
    assert fiabilite(0, 8) == 0.1


def test_kappa():
    assert kappa_cohen([("a", "a"), ("b", "b"), ("a", "a"), ("b", "b")]) == 1.0
    assert kappa_cohen([("a", "a")]) is None
    k = kappa_cohen([("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")])
    assert abs(k) < 1e-9 and interpretation(k) == "nul ou négatif"
    assert matrice_confusion([("a", "b")], ["a", "b"]) == [[0, 1], [0, 0]]


def test_anti_abus_le_rouge_passe_le_plafond_pas_le_doublon():
    assert verdict("orange", False, 5, 5) == "bloque_plafond"
    assert verdict("rouge", False, 9, 5) == "ok"
    assert verdict("rouge", True, 0, 5) == "bloque_doublon"


def test_identifiant_telegram_jamais_prefixe(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 64)
    from app.securite import normaliser_contact
    assert normaliser_contact("07 08 09 10 11") == "+2250708091011"
    assert normaliser_contact("1234567890", telephone=False) == "1234567890"


def test_releve_pluviometre():
    from src.recoupement import decider_releve
    assert decider_releve(12, 0.5, [])[0] == "valide"            # trop faible pour déclencher quoi que ce soit
    assert decider_releve(80, 0.5, [])[0] == "a_valider"         # forte pluie d'un relais non vérifié
    assert decider_releve(80, 0.85, [])[0] == "valide"           # relais fiable
    assert decider_releve(80, 0.5, [72])[0] == "valide"          # concorde avec un autre relevé
    assert decider_releve(80, 0.5, [20])[0] == "a_valider"       # discordant


def test_signalement_libre_et_lien_des_alertes():
    from src.recoupement import decider_signalement
    from src.messages import message
    assert decider_signalement(0.5, 0)[0] == "a_valider"
    assert decider_signalement(0.5, 1)[0] == "valide"
    assert decider_signalement(0.9, 0)[0] == "valide"
    rouge = message("rouge", "Attécoubé", lien="https://aqua.ci/prevention")
    assert rouge.endswith("Consignes : https://aqua.ci/prevention") and len(rouge) < 320
    assert "Consignes" not in message("vert", "Attécoubé", lien="https://aqua.ci/prevention")


def test_avis_ia_renvoie_en_verification_sans_jamais_valider():
    from src.recoupement import reaction_avis_ia
    bouche = {"est_caniveau": True, "classe": "bouche"}
    # désaccord franc avec une validation automatique -> vérification humaine
    assert reaction_avis_ia("valide", "automatique", "propre", bouche)[0] == "a_valider"
    # désaccord léger -> rien ne change
    assert reaction_avis_ia("valide", "automatique", "partiel", bouche)[0] == "valide"
    # photo hors sujet -> vérification
    assert reaction_avis_ia("valide", "automatique", "propre", {"est_caniveau": False, "classe": None})[0] == "a_valider"
    # pas de classe : l'IA propose, mais n'auto-valide pas
    assert reaction_avis_ia("a_valider", None, None, bouche) == ("a_valider", "classe proposée par l'IA (bouche), à confirmer", "bouche")
    # une décision d'opérateur n'est jamais remise en cause
    assert reaction_avis_ia("valide", "admin", "propre", bouche)[0] == "valide"
