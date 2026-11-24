# T17 — Import PostGIS de la livraison v0 de M2

## Périmètre réalisé

La livraison finale de M2 est importée depuis la branche `carte-risques-v7` du dépôt AquaSentinelle, figée au commit `5f3f1720c7271750af6134b71a45018a40d59106` (17 novembre 2026). Ce choix rend l’import reproductible même si la branche évolue ensuite.

La livraison n’est pas un GeoPackage : les objets de la maquette sont distribués en GeoJSON et en fichiers compacts propres à cette carte (`AQG2` pour couches et carreaux, `AQB2` pour bâtiments), compressés puis encodés en base64. Le script reprend le décodeur de la page `risque.html`, puis charge les géométries dans PostGIS en EPSG:4326.

## Schéma et résultat

Le schéma ajoute `t17_couche` pour le registre des couches, leurs sources et leur dictionnaire, et `t17_entite` pour les géométries et attributs. Les attributs d’origine sont préservés en JSONB; les couches sont distinguées entre cœur de la carte et second plan. Les index GiST (géométrie), GIN (attributs) et B-tree (couche/commune) sont créés. Les 13 limites de commune sont également chargées dans `zone.contour`.

| Couche importée | Entités | Catégorie |
|---|---:|---|
| Empreintes de bâtiments avec attributs de risque | 958 210 | Cœur |
| Grille de risque à 100 m | 53 600 | Cœur |
| Grille de risque à 250 m | 11 613 | Cœur |
| Classes de pente et HAND | 50 784 | Cœur |
| Zones de débordement | 23 041 | Cœur |
| Bassins versants | 442 | Cœur |
| Cours d’eau modélisés | 826 | Cœur |
| Cours d’eau nommés OSM | 63 | Cœur |
| Limites des communes | 13 | Cœur |
| Repères de quartiers | 501 | Cœur |
| Sites constatés | 22 | Cœur |
| Caniveaux de la maquette | 562 | Second plan |

Les attributs des couches compactes sont traduits à partir des accès utilisés par la maquette. Pour les bâtiments, cela inclut le niveau de risque, la cause, la population estimée, la pente, la hauteur au-dessus du cours d’eau, le bassin amont, la hauteur du bâtiment, l’altitude et les indicateurs de débordement/construction. Une valeur brute dont la signification n’est pas exposée par la maquette est conservée sans interprétation.

## Contrôles et limites constatées

- Les 13 géométries de communes sont présentes et valides; la requête PostGIS `ST_Intersects` trouve des bâtiments dans chacune d’elles. Le critère spatial de T17 est ainsi exécuté.
- 416 géométries d’analyse compactes présentaient des auto-intersections. Elles ont été normalisées avec `ST_MakeValid`; après correction, aucune géométrie invalide ne reste dans les entités importées.
- 32 enregistrements de l’analyse de pente/HAND ne contiennent pas d’anneau extérieur polygonal exploitable (moins de trois sommets distincts) et sont écartés. Les fichiers source intacts restent archivés localement pour traçabilité.
- Le contrôle des limites révèle des recouvrements surfaciques entre certaines communes livrées : Abobo/Anyama environ 36,1 km², Bingerville/Cocody environ 3,0 km² et Bingerville/Koumassi environ 0,057 km². Les résultats de croisement par commune peuvent donc compter certains bâtiments dans plusieurs communes. M2 doit confirmer/corriger ces limites avant de présenter des totaux exclusifs par commune.
- Les sites constatés sont 22 repères issus de la maquette, pas une base exhaustive d’événements historiques. Les champs visibles identifient parfois une provenance générale (par ex. ONPC 2025), mais la livraison n’apporte pas partout une date ni un lien de source détaillé.
- La grille et les attributs de la maquette donnent des estimations modélisées; ils ne constituent pas à eux seuls une validation scientifique. Les seuils, facteurs et étiquettes de risque doivent être vérifiés avec M2/M3 avant leur usage en alerte.
- Le manifeste inclut toutes les 333 ressources de `couches/`, `analyse/` et `bati/` utiles à la livraison, soit environ 30,1 MB, avec leurs empreintes Git. Les ressources cartographiques de fond et raster servant uniquement à l’affichage ne sont pas importées dans les tables d’entités.

## Reproduction

Depuis la racine du dépôt :

```powershell
python scripts/importer_t17.py --preparer
# Démarrer PostGIS selon l’environnement du projet, puis :
python scripts/importer_t17.py --importer
python scripts/importer_t17.py --verifier
```

`--preparer` télécharge le commit épinglé et compare l’empreinte de chaque fichier avec l’arbre GitHub. `--importer` remplace le contenu T17 précédent et importe les couches. `--reprendre` conserve les couches complètes et recharge celles qui sont absentes ou partielles. `--verifier` affiche les effectifs et vérifie les intersections spatiales bâtiments/communes.

Données brutes locales (ignorées par Git) : `dataset/t17_m2_v0/`. Manifeste de provenance : `dataset/t17_m2_v0/source_manifest.json`.

## Sources

- Dépôt : <https://github.com/Master-Mind-code/AquaSentinelle>
- Branche épinglée : <https://github.com/Master-Mind-code/AquaSentinelle/tree/carte-risques-v7/app/static/carte>
- Contrat de données compact et champs consultés : `app/static/carte/risque.html` dans le commit épinglé.
- Répartition des tâches : T17 (M4), dépend de T57 (livraison v0 de M2), avec critère « requête spatiale test réussie ».
