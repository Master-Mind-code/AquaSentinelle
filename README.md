# AquaSentinelle CI

Projet académique APP3 2026-27 (ESATIC, équipe AquaSentinelle) : alerte pluie par quartier et carnet de santé
des caniveaux (points de contrôle peints, photo cadrée, classification par IA). *Anticiper · Alerter · Protéger.*

## Couverture nationale

18 villes et communes (fichier `config/zones.yaml`, à compléter sans toucher au code) : le District d'Abidjan
(zone pilote, seuils calibrés) et 13 villes de l'intérieur et du littoral. Deux types de risque :

- **Inondation urbaine par pluie intense** : CHIRPS, pluviomètres des relais, prévisions de 5 modèles.
  Hors Abidjan, les seuils sont transposés selon le climat local (`scripts/transposer_seuils.py`, CHIRPS 2018-2023)
  et restent provisoires jusqu'à leur vérification sur les inondations documentées de chaque ville.
- **Crue de fleuve** (Bandama, Comoé, Sassandra, Bia, San-Pédro, Tarsca/Débao) : débit prévu à 7 jours par GloFAS
  (Copernicus, via Open-Meteo), comparé à la crue annuelle (orange, ~4 années sur 5) et à la crue de 5 ans (rouge), calculées sur 1984-2025 (`scripts/calibrer_rivieres.py`).
  Quelques jours d'avance, là où la pluie urbaine n'en donne que quelques heures. GloFAS est un modèle :
  les barrages (Kossou, Taabo, Buyo, Soubré) n'y sont que partiellement représentés.

Résultats de l'extension nationale (38 inondations datées hors Abidjan, `data/events_national.csv`) :

- **Crues de fleuve** (`scripts/evaluer_crues.py`) : 7 crues documentées sur 9 dépassent le seuil orange dans la
  réanalyse GloFAS, pour 0,6 à 1,3 épisode par an et par fleuve. Ratées : un petit affluent (Éholié) et les lâchers
  du barrage de Soubré, que le modèle ne représente pas. Seuil orange choisi sur ces 9 crues : à revoir.
- **Pluie observée** (`scripts/transposer_seuils.py`) : seuils x 0,6 à 1,04 selon le climat (CHIRPS 2018-2023) ;
  chaque ville a ainsi 5 à 7 jours d'alerte orange par an, comme Abidjan (avec les seuils d'Abidjan, l'intérieur
  n'en aurait eu qu'un). Inondations urbaines documentées : 5/9 détectées ; les ratées sont des orages d'une à deux
  heures (Bouaké, Man) et un « canal bouché » à Bouaké avec 0 mm : le cas que couvrent pluviomètres et caniveaux.
- **Pluie prévue** (`scripts/caler_previsions.py`) : seuils calés pour donner la même fréquence d'alerte qu'Abidjan
  (28 à 44 mm), car les modèles ne se comportent pas comme CHIRPS.

Ajouter une ville : une ligne dans `config/zones.yaml` (avec `riviere:` pour une ville au bord d'un fleuve),
puis `python scripts/calibrer_rivieres.py --chercher`, `python scripts/transposer_seuils.py`
et `python scripts/caler_previsions.py`.

## Démarrer (Docker)

    copy .env.example .env        # puis remplir APP_SECRET_KEY et ADMIN_MOT_DE_PASSE (voir le fichier)
    docker compose up -d --build  # base PostGIS (port 5434) + application sur http://localhost:8000
    docker compose exec app python -m app.initialisation --demo   # optionnel : 7 points de démonstration

- Page publique : http://localhost:8000 (niveaux par commune, inscription SMS)
- Espace opérateur : http://localhost:8000/connexion (identifiant et mot de passe : `ADMIN_*` dans `.env`)
- Bot Telegram : renseigner `TELEGRAM_TOKEN` puis `docker compose --profile telegram up -d`
- Documentation de l'API : http://localhost:8000/api/docs

**QR codes et téléphones** : les QR codes contiennent `BASE_URL`. `localhost` ne marche que sur le PC.
Pour la démonstration avec de vrais téléphones, mettre l'adresse du PC sur le Wi-Fi (ex. `http://192.168.1.20:8000`)
ou celle d'un serveur en ligne, puis redémarrer.

## Vérifier

    pip install -r requirements.txt -r requirements-app.txt
    pytest                                   # 33 tests (base séparée aquasentinelle_test) (les tests d'intégration exigent la base Docker)
    python scripts/verifier_bout_en_bout.py  # scénario complet sur le serveur qui tourne

Le scénario : 2 relais signalent un caniveau « bouché » (recoupement) → pluie simulée de 90 mm → alerte rouge
en attente (seuils abaissés de 15 %) → validation par l'opérateur → envoi → retour à la normale.

## Fonctionnalités

| N° | Fonction | Où |
|---|---|---|
| S1, S2, S5 | CHIRPS, Open-Meteo, prévisions passées de 5 modèles, rejeu, 15 événements documentés | `src/rain_sources.py`, `scripts/replay.py`, `data/events.csv` |
| S3 | IMERG Early (NASA), expérimental : stocké, hors du score tant qu'il n'est pas calibré | `EARTHDATA_TOKEN`, `IMERG_DANS_SCORE` |
| S4 | Planificateur : collecte, score, alertes, escalade chaque heure ; jours CHIRPS manquants retentés | `app/main.py`, `app/cycle.py` |
| S6, S8 | Score vert/orange/rouge, entrées et version des règles conservées | `app/services/score.py` |
| S7 | Caniveaux bouchés : seuils abaissés jusqu'à 15 % | idem |
| S9 | Calibration sur les événements | `scripts/evaluate.py` |
| S10 | Forêt aléatoire contre règles (résultat : la règle gagne, 8/11 contre 4/11) | `scripts/foret_aleatoire.py` |
| S11-S13 | Messages, validation humaine du rouge, escalade après 15 min, anti-doublon, plafond par jour | `app/services/alertes.py` |
| S14, S15 | Telegram ; SMS par Africa's Talking ou passerelle Android | `src/canaux.py`, `bot/telegram_bot.py` |
| S16 | Abonnés : consentement, STOP, numéros chiffrés ; SMS « ALERTE zone » | `app/services/abonnes.py` |
| S17 | Journal des envois et statuts de livraison | page Alertes → envois |
| S18 | Identifiants et QR codes, planche à imprimer pour le pochoir | page Points & QR |
| S19 | Parcours du relais : formulaire web (QR) ou bot Telegram | `/r/<point>` |
| S20 | Photo horodatée par le serveur, métadonnées supprimées, visages floutés | `app/services/photos.py` |
| S21, S22 | Fiabilité des relais (Laplace), recoupement de « bouché » | `src/recoupement.py` |
| S23 | Péremption à 30 jours (gris sur la carte) | vue `statut_point` |
| S24 | Étiquetage à deux, kappa de Cohen, matrice de confusion | page Étiquetage |
| S25 | MobileNetV3 : entraînement, test séparé, export ONNX, inférence dans l'application | `ia/` |
| S26-S30 | Carte Leaflet, validations, scores, historique, connexion sécurisée | espace opérateur |
| S31-S34 | PostGIS, API, Docker, tests, latence mesurée (cible < 60 s) | |
| S35 | Évaluation avec et sans caniveaux (exige une saison de relevés) | `scripts/evaluer_caniveaux.py` |
| + | Pluviomètres de quartier : relevé du matin (page `/pluviometre` ou `/pluie 45 attecoube`), recoupé au-delà de 35 mm | `app/services/pluviometre.py` |
| + | Curage préventif : pluie forte prévue + points bouchés → liste des points à curer avant la pluie | `app/services/curage.py` |

## Fonctions citoyennes (proposition du groupe)

| Besoin | Réponse | Où |
|---|---|---|
| Signaler route inondée, danger, caniveau, avec photo et position | Formulaire `/signaler` (GPS ou toucher la carte) ; validé si un 2e habitant confirme à moins de 300 m | `app/services/signalements.py` |
| Carte des zones à risque, inondées, lieux sûrs | Carte publique `/carte` : niveaux, signalements vérifiés (48 h), lieux sûrs, historique par ville | `app/routes_citoyen.py` |
| Sensibiliser, conseils avant et pendant | Page `/prevention` ; chaque alerte orange ou rouge y renvoie par un lien | `app/templates/prevention.html` |
| Aide d'urgence avec position | `/aide` : « Appeler le 180 » d'abord, puis envoi de la position aux opérateurs et page de suivi | `app/services/aide.py` |
| Capteurs de niveau d'eau | API `POST /api/capteurs/<id>/mesures` (clé par appareil), score, alerte de silence ; simulateur et programme ESP32 | `app/services/capteurs.py`, `firmware/` |

**La demande d'aide ne remplace pas le 180.** Sans convention avec l'ONPC ou les sapeurs-pompiers, personne ne
surveille les demandes en continu : la page le dit et renvoie d'abord vers l'appel.

**Position GPS sur téléphone** : les navigateurs ne la donnent qu'en HTTPS (ou sur localhost). Pour une démonstration
avec de vrais téléphones, publier le serveur en HTTPS (tunnel ou hébergement) ; à défaut, on touche la carte.

## Intelligence artificielle sur les photos

- **Gemma 4 (Ollama, local, sur la carte graphique du PC)** : « second regard » sur chaque photo de point de contrôle,
  en arrière-plan (~2 s par photo). Il estime le pourcentage d'obstruction, d'où une classe par seuils explicites
  (< 15 % propre, < 60 % partiel, sinon bouché), repère les photos hors sujet et les personnes visibles, et justifie en
  une phrase. **Il ne valide jamais seul** : il renvoie en vérification humaine une photo hors sujet ou un désaccord net
  avec le relais (`src/recoupement.py`, `reaction_avis_ia`). Premier essai sur 11 photos libres (Wikimedia) : 9/11 conformes,
  6/6 photos hors sujet reconnues ; à remesurer sur les photos de l'équipe (page Accord : IA contre étiquettes humaines).
- **MobileNet** (`ia/`) reste la cible en production : léger, entraîné sur les photos validées de l'équipe.
- Réglages : `IA_VISION_ACTIVE`, `OLLAMA_URL` (Docker : `http://host.docker.internal:11434`), `OLLAMA_MODELE_VISION`.

## Résultats d'évaluation

- Seuil orange 70 mm : 8 inondations sur 11 détectées, 2,8 jours d'alerte par mois en saison (`scripts/evaluate.py`).
- Forêt aléatoire : 4/11 contre 8/11 pour la règle à nombre d'alertes égal → règle conservée (`scripts/foret_aleatoire.py`).
- Humidité du sol (ERA5-Land) : +1 événement au mieux (9/11) pour +0,7 alerte/mois, avec un seuil ajusté sur ces
  mêmes événements ; le sol était sec avant le glissement de Mossikro 2025 → **non intégrée** au score,
  à réévaluer quand la liste d'événements grandira (`scripts/evaluer_sol.py`).

## Ce qui dépend de l'équipe

- **Photos réelles** de caniveaux (quelques centaines, zone pilote), puis :
  `python ia/exporter_jeu.py` et `python ia/entrainer.py` (`pip install -r ia/requirements-ia.txt`).
  Sans modèle, l'application fonctionne : la classe retenue est l'avis du relais.
- **Jetons** : `TELEGRAM_TOKEN` (@BotFather), `AT_API_KEY` (Africa's Talking, sandbox gratuit), `EARTHDATA_TOKEN`.
- **Zone pilote** (H1) : remplacer les points de démonstration par les vrais points peints.

## Sécurité

Contacts chiffrés (Fernet) et retrouvés par empreinte HMAC ; mots de passe scrypt ; sessions signées ;
jeton CSRF sur tous les formulaires ; limitation des tentatives de connexion ; photos réservées aux opérateurs.
Ne jamais versionner `.env`. Changer `APP_SECRET_KEY` rend illisibles les contacts déjà enregistrés.

## Données

CHIRPS : https://data.chc.ucsb.edu/products/CHIRPS-2.0/ · Open-Meteo : https://open-meteo.com (usage non commercial) ·
IMERG : https://gpm.nasa.gov · Fonds de carte : © contributeurs OpenStreetMap.
