-- AquaSentinelle CI : schéma PostgreSQL + PostGIS (v3).
-- Idempotent : rejoué à chaque démarrage de l'API, il ne détruit rien.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS zone (
  id            text PRIMARY KEY,
  nom           text NOT NULL,
  contour       geometry(MultiPolygon, 4326),
  centre        geometry(Point, 4326) NOT NULL,
  langue        text NOT NULL DEFAULT 'fr',
  telegram_chat text                               -- canal public de la zone (optionnel)
);

-- Point de contrôle : identifiant peint + QR, position fixe connue
CREATE TABLE IF NOT EXISTS point_controle (
  id            text PRIMARY KEY,                -- ex. ATT-023
  zone_id       text NOT NULL REFERENCES zone(id),
  position      geometry(Point, 4326) NOT NULL,
  description   text,                            -- repère peint, accès, tronçon
  actif         boolean NOT NULL DEFAULT true,
  demo          boolean NOT NULL DEFAULT false,  -- point fictif de démonstration
  cree_le       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relais (
  id              serial PRIMARY KEY,
  zone_id         text REFERENCES zone(id),
  pseudo          text NOT NULL,
  contact_chiffre bytea,                          -- jamais en clair
  contact_empreinte text UNIQUE,                  -- HMAC du contact, pour retrouver un relais sans déchiffrer
  telegram_id     text UNIQUE,
  fiabilite       real NOT NULL DEFAULT 0.5,      -- 0 à 1, mise à jour par recoupement
  nb_observations integer NOT NULL DEFAULT 0,
  nb_confirmees   integer NOT NULL DEFAULT 0,
  nb_rejetees     integer NOT NULL DEFAULT 0,
  consentement    boolean NOT NULL DEFAULT false,
  cree_le         timestamptz NOT NULL DEFAULT now()
);

-- Observation : une photo cadrée sur le repère + 2 ou 3 réponses
CREATE TABLE IF NOT EXISTS observation (
  id               bigserial PRIMARY KEY,
  point_id         text NOT NULL REFERENCES point_controle(id),
  relais_id        integer REFERENCES relais(id),
  source           text NOT NULL DEFAULT 'relais' CHECK (source IN ('relais','operateur','capteur','demo')),
  recu_le          timestamptz NOT NULL DEFAULT now(),  -- horodatage du SERVEUR
  photo_chemin     text,
  eau_stagnante    boolean,
  dechets_visibles boolean,
  avis_relais      text CHECK (avis_relais IN ('propre','partiel','bouche')),
  classe_ia        text CHECK (classe_ia IN ('propre','partiel','bouche')),
  confiance_ia     real,
  classe           text CHECK (classe IN ('propre','partiel','bouche')),  -- classe retenue
  statut           text NOT NULL DEFAULT 'a_valider'
                   CHECK (statut IN ('a_valider','valide','rejete')),
  motif            text,                                 -- pourquoi validé / rejeté
  valide_par       text,
  valide_le        timestamptz
);
CREATE INDEX IF NOT EXISTS observation_point_idx ON observation (point_id, recu_le DESC);

-- Second regard d'un modèle de vision (Ollama, Gemma 4) sur les photos des points de contrôle
ALTER TABLE observation ADD COLUMN IF NOT EXISTS modele_ia text;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS obstruction_pct_ia integer;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS justification_ia text;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS est_caniveau_ia boolean;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS personne_visible_ia boolean;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS ia_analyse_le timestamptz;
ALTER TABLE observation ADD COLUMN IF NOT EXISTS ia_tentatives integer NOT NULL DEFAULT 0;

-- Étiquetage à deux personnes pour constituer le jeu de photos (S24)
CREATE TABLE IF NOT EXISTS etiquette (
  observation_id bigint NOT NULL REFERENCES observation(id),
  etiqueteur     text NOT NULL,
  classe         text NOT NULL CHECK (classe IN ('propre','partiel','bouche','inutilisable')),
  le             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (observation_id, etiqueteur)
);

CREATE TABLE IF NOT EXISTS mesure_pluie (
  id          bigserial PRIMARY KEY,
  zone_id     text NOT NULL REFERENCES zone(id),
  source      text NOT NULL,                      -- chirps_max, openmeteo, prevision_max, simulation...
  jour        date NOT NULL,
  pluie_mm    real NOT NULL,
  recu_le     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (zone_id, source, jour)
);

-- Relevés des pluviomètres de quartier tenus par les relais (pluviomètre gradué, relevé le matin)
CREATE TABLE IF NOT EXISTS releve_pluviometre (
  id          bigserial PRIMARY KEY,
  zone_id     text NOT NULL REFERENCES zone(id),
  relais_id   integer REFERENCES relais(id),
  jour        date NOT NULL,                      -- jour du relevé (pluie des 24 h précédentes)
  pluie_mm    real NOT NULL CHECK (pluie_mm >= 0 AND pluie_mm <= 400),
  recu_le     timestamptz NOT NULL DEFAULT now(),
  statut      text NOT NULL DEFAULT 'a_valider' CHECK (statut IN ('a_valider','valide','rejete')),
  motif       text,
  valide_par  text
);
CREATE INDEX IF NOT EXISTS releve_zone_jour_idx ON releve_pluviometre (zone_id, jour);

-- Crues de fleuves : une station virtuelle par zone fluviale (cellule GloFAS), seuils issus de 40 ans de débits
CREATE TABLE IF NOT EXISTS riviere (
  zone_id       text PRIMARY KEY REFERENCES zone(id),
  nom           text NOT NULL,
  position      geometry(Point, 4326) NOT NULL,
  seuil_orange  real,                               -- crue annuelle : quantile 20 pour cent des maxima annuels (m³/s), pas de signe pourcent ici (lu comme paramètre)
  seuil_rouge   real,                               -- crue de période de retour 5 ans (m³/s)
  calibre_le    timestamptz
);

-- Débit journalier (m³/s) : prévision GloFAS (prevision = true) ou réanalyse (false)
CREATE TABLE IF NOT EXISTS mesure_debit (
  zone_id     text NOT NULL REFERENCES zone(id),
  jour        date NOT NULL,
  prevision   boolean NOT NULL,
  debit_m3s   real NOT NULL,
  recu_le     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (zone_id, jour, prevision)
);

ALTER TABLE zone ADD COLUMN IF NOT EXISTS region text;
ALTER TABLE zone ADD COLUMN IF NOT EXISTS type text NOT NULL DEFAULT 'urbaine';

-- Signalement libre d'un habitant, n'importe où : route inondée, endroit dangereux, caniveau hors point peint
CREATE TABLE IF NOT EXISTS signalement (
  id            bigserial PRIMARY KEY,
  type          text NOT NULL CHECK (type IN ('route_inondee','zone_inondee','danger','caniveau','autre')),
  description   text,
  position      geometry(Point, 4326) NOT NULL,
  precision_m   real,                               -- précision GPS annoncée par le téléphone
  zone_id       text REFERENCES zone(id),           -- zone la plus proche (calculée)
  photo_chemin  text,
  relais_id     integer REFERENCES relais(id),
  recu_le       timestamptz NOT NULL DEFAULT now(),
  expire_le     timestamptz NOT NULL,               -- une inondation signalée n'est plus affichée après 48 h
  statut        text NOT NULL DEFAULT 'a_valider' CHECK (statut IN ('a_valider','valide','rejete','resolu')),
  motif         text,
  valide_par    text
);
CREATE INDEX IF NOT EXISTS signalement_position_idx ON signalement USING gist (position);

-- Lieux sûrs : sites de regroupement, écoles, mairies… saisis par les opérateurs
CREATE TABLE IF NOT EXISTS lieu_sur (
  id          serial PRIMARY KEY,
  nom         text NOT NULL,
  type        text NOT NULL CHECK (type IN ('regroupement','ecole','mairie','sante','lieu_de_culte','autre')),
  zone_id     text REFERENCES zone(id),
  position    geometry(Point, 4326) NOT NULL,
  capacite    integer,
  description text,
  demo        boolean NOT NULL DEFAULT false,
  actif       boolean NOT NULL DEFAULT true,
  cree_le     timestamptz NOT NULL DEFAULT now()
);

-- Demande d'aide d'urgence : NE REMPLACE PAS le 180. Transmise aux opérateurs qui la relaient aux secours.
CREATE TABLE IF NOT EXISTS demande_aide (
  id            bigserial PRIMARY KEY,
  jeton         text UNIQUE NOT NULL,               -- permet au demandeur de suivre sa demande sans compte
  situation     text NOT NULL CHECK (situation IN ('eau_monte','bloque','blesse','glissement','autre')),
  nb_personnes  integer,
  description   text,
  position      geometry(Point, 4326),
  precision_m   real,
  lieu_texte    text,                               -- si pas de GPS : quartier, repère
  contact_chiffre bytea,
  zone_id       text REFERENCES zone(id),
  recu_le       timestamptz NOT NULL DEFAULT now(),
  statut        text NOT NULL DEFAULT 'recue' CHECK (statut IN ('recue','transmise','traitee','close')),
  traite_par    text,
  note          text,
  maj_le        timestamptz NOT NULL DEFAULT now()
);

-- Capteurs de niveau d'eau (option IoT) : une clé d'API par appareil, l'heure est celle du serveur
CREATE TABLE IF NOT EXISTS capteur (
  id            text PRIMARY KEY,                   -- ex. CAP-ATT-01
  nom           text NOT NULL,
  zone_id       text NOT NULL REFERENCES zone(id),
  position      geometry(Point, 4326) NOT NULL,
  cle_hash      text NOT NULL,
  seuil_orange_cm real NOT NULL,
  seuil_rouge_cm  real NOT NULL,
  simule        boolean NOT NULL DEFAULT false,
  actif         boolean NOT NULL DEFAULT true,
  dernier_signal timestamptz,
  cree_le       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mesure_niveau (
  id          bigserial PRIMARY KEY,
  capteur_id  text NOT NULL REFERENCES capteur(id),
  le          timestamptz NOT NULL DEFAULT now(),
  niveau_cm   real NOT NULL,
  batterie_v  real
);
CREATE INDEX IF NOT EXISTS mesure_niveau_idx ON mesure_niveau (capteur_id, le DESC);

CREATE TABLE IF NOT EXISTS score_risque (
  id          bigserial PRIMARY KEY,
  zone_id     text NOT NULL REFERENCES zone(id),
  calcule_le  timestamptz NOT NULL DEFAULT now(),
  niveau      text NOT NULL CHECK (niveau IN ('vert','orange','rouge')),
  pluie_24h_mm real NOT NULL,
  source      text NOT NULL DEFAULT 'prevision',
  entrees     jsonb NOT NULL,                     -- explicabilité
  version_regles text NOT NULL
);
CREATE INDEX IF NOT EXISTS score_zone_idx ON score_risque (zone_id, calcule_le DESC);

-- Dernier niveau annoncé par zone (mémoire de la règle « envoyer seulement sur changement »)
CREATE TABLE IF NOT EXISTS etat_zone (
  zone_id     text PRIMARY KEY REFERENCES zone(id),
  niveau      text NOT NULL CHECK (niveau IN ('vert','orange','rouge')),
  maj_le      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS abonne (
  id          serial PRIMARY KEY,
  zone_id     text NOT NULL REFERENCES zone(id),
  contact_chiffre bytea NOT NULL,
  contact_empreinte text NOT NULL,
  canal       text NOT NULL CHECK (canal IN ('telegram','sms','whatsapp','voix','console')),
  langue      text NOT NULL DEFAULT 'fr',
  consentement_le timestamptz NOT NULL,
  actif       boolean NOT NULL DEFAULT true,
  desabonne_le timestamptz,
  UNIQUE (zone_id, canal, contact_empreinte)
);

CREATE TABLE IF NOT EXISTS alerte (
  id          bigserial PRIMARY KEY,
  zone_id     text NOT NULL REFERENCES zone(id),
  score_id    bigint REFERENCES score_risque(id),
  niveau      text NOT NULL,
  texte       text NOT NULL,
  statut      text NOT NULL DEFAULT 'envoyee'
              CHECK (statut IN ('en_attente','escaladee','envoyee','rejetee','annulee')),
  cree_le     timestamptz NOT NULL DEFAULT now(),
  validee_par text,                               -- obligatoire avant tout envoi rouge
  validee_le  timestamptz,
  escaladee_le timestamptz,
  envoyee_le  timestamptz,
  nb_destinataires integer,
  latence_ms  integer                             -- du calcul du score au dernier envoi réussi
);

-- Journal de chaque envoi, avec son statut de livraison (S17)
CREATE TABLE IF NOT EXISTS envoi (
  id          bigserial PRIMARY KEY,
  alerte_id   bigint NOT NULL REFERENCES alerte(id),
  abonne_id   integer REFERENCES abonne(id),
  canal       text NOT NULL,
  statut      text NOT NULL CHECK (statut IN ('ok','echec','bloque_doublon','bloque_plafond')),
  detail      text,
  le          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operateur (
  id          serial PRIMARY KEY,
  identifiant text UNIQUE NOT NULL,
  nom         text NOT NULL,
  mot_de_passe_hash text NOT NULL,
  role        text NOT NULL DEFAULT 'operateur' CHECK (role IN ('admin','operateur')),
  telegram_chat text,                             -- pour l'escalade des alertes rouges
  actif       boolean NOT NULL DEFAULT true,
  cree_le     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journal (
  id    bigserial PRIMARY KEY,
  le    timestamptz NOT NULL DEFAULT now(),
  type  text NOT NULL,                            -- collecte, score, alerte, escalade, erreur...
  message text NOT NULL
);

-- Statut courant d'un point : dernière observation validée ; périmé après 30 jours
CREATE OR REPLACE VIEW statut_point AS
SELECT p.id AS point_id, p.zone_id, p.demo,
       ST_Y(p.position) AS lat, ST_X(p.position) AS lon, p.description,
       o.classe, o.recu_le, o.photo_chemin,
       CASE WHEN o.recu_le IS NULL THEN true
            ELSE (now() - o.recu_le) > interval '30 days' END AS perime
FROM point_controle p
LEFT JOIN LATERAL (
  SELECT classe, recu_le, photo_chemin FROM observation
  WHERE point_id = p.id AND statut = 'valide'
  ORDER BY recu_le DESC LIMIT 1
) o ON true
WHERE p.actif;
