# Carte des zones à risque et des caniveaux d'Abidjan

Page autonome affichée dans un cadre par `/carte` (`app/templates/carte_publique.html`). Elle ne dépend ni de la base ni de l'API :
tout est lu dans ces fichiers (≈ 36 Mo, 363 fichiers, gardés une heure en cache par `app/main.py`).

- `index.html` : les deux onglets. `?integre=1` masque son titre (la page l'affiche déjà). `#caniveaux/KOU-001` ouvre un tronçon.
- `risque.html` : zones à risque (surface lissée, puis chaque bâtiment à partir du zoom 14). `caniveaux.html` : eau envoyée par chaque quartier.
- `analyse/`, `bati/`, `routes/`, `fond/`, `couches/`, `raster/`, `docs/` : données au format compact (zlib puis base64) et images WebP.
- Leaflet 1.9.4 est celui de l'application (`../leaflet/leaflet.js`).

Version 7 (15 novembre 2026), produite par M2 (géomatique) avec les scripts `etape20a` à `etape20d` et `etape18` à `etape19` du dossier
SIG_AquaSentinelle. Pour la mettre à jour, remplacer ce dossier par la nouvelle version publiée, puis :
remplacer l'adresse du script Leaflet de `risque.html` et `caniveaux.html` par `../leaflet/leaflet.js`, et garder le bloc `.integre` de `index.html`.
Sources : OpenStreetMap, Google Open Buildings, FABDEM, WorldPop.
