# AquaSentinelle CI — Système de Conception (Référence Master)

Établi et mis à niveau avec la compétence **ui-ux-pro-max** (« water monitoring iot environmental platform / public safety dashboard »).
Ce document est la Source Unique de Vérité (Master) pour l'ensemble de l'interface publique et de l'espace opérateur.

---

## 1. Direction Artistique & Style

- **Style Principal** : **Glassmorphism / Bento Box Grid**
  - Cartes modulaires Bento avec asymétrie structurée et hiérarchie visuelle claire.
  - Arrière-plans en verre dépoli (`backdrop-filter: blur(16px)` / `-webkit-backdrop-filter`), bordures subtiles (`rgba(255, 255, 255, 0.09)`) et lueurs ambiantes directionnelles.
  - Élévation douce au survol (`transform: translateY(-2px)` et intensification des bordures néon/cyan).
- **Ambiance** : **Dark Tech (#0B1120 / #0F172A)** avec accents d'état dynamiques haute visibilité.
- **Accents d'état dynamiques** :
  - **Cyan dynamique (`#38BDF8`)** : Accent principal, focus, liens, interactions clés (ratio de contraste > 8:1).
  - **Vert Sécurité (`#22C55E` / `#4ADE80`)** : Situation normale, niveau d'alerte vert, validation (ratio > 7:1).
  - **Orange Vigilance (`#FB923C`)** : Vigilance météo/crues, alertes modérées (ratio > 7:1).
  - **Rouge Urgence (`#EF4444` / `#F87171`)** : Alerte rouge, évacuation, danger critique (ratio > 5:1).

---

## 2. Variables & Tokens (CSS : `app/static/style.css`)

| Rôle | Token CSS | Valeur Hex / RGBA | Usage & Accessibilité |
|---|---|---|---|
| Fond principal | `--fond` | `#0B1120` | Fond global Dark Tech avec mesh radial |
| Surface sombre | `--nuit` | `#0F172A` | En-têtes, barres d'outils, modales |
| Verre / Carte Bento | `--carte` | `rgba(30, 41, 59, 0.68)` | Surfaces de cartes avec flou 16px |
| Bordure subtile | `--bord` | `rgba(255, 255, 255, 0.09)` | Séparateurs, délimitations de cartes |
| Bordure active | `--bord-accent` | `rgba(56, 189, 248, 0.40)` | Cartes en vedette, focus, états actifs |
| Texte principal | `--texte` | `#F8FAFC` | Texte lisible haute fidélité (ratio > 15:1) |
| Texte secondaire | `--ardoise` | `#CBD5E1` | Paragraphes, sous-titres (ratio > 10:1) |
| Texte d'aide | `--doux` | `#94A3B8` | Métadonnées, légendes (ratio > 5.5:1, conforme AA) |
| Accent Cyan | `--accent` | `#38BDF8` | Boutons primaires, liens, indicateurs vivants |
| Alerte Vert | `--vert` | `#22C55E` | Pastille et contour niveau Vert |
| Alerte Orange | `--orange` | `#FB923C` | Pastille et contour niveau Orange |
| Alerte Rouge | `--rouge` | `#EF4444` | Pastille, cartes en alerte rouge, bouton Urgence |
| Marque logo | `--marque` | `#EA580C` | Bandeau de Gouti et accentuation du logo |

---

## 3. Typographie

- **Police unique** : **Plus Jakarta Sans** (Google Fonts).
  - Poids utilisés : 400 (normal), 500 (moyen), 600 (semi-gras), 700 (gras), 800 (extra-gras).
  - Rendu numérique : `tabular-nums` pour tous les compteurs, tableaux de bord et indicateurs de débit/pluie.
- **Échelle typographique** :
  - **36 px / 700** : Grands indicateurs KPI (`.indicateur .valeur`).
  - **30-32 px / 700-800** : Titre principal de page (`h1`).
  - **22 px / 700** : Titre de section (`h2`).
  - **18 px / 600** : Titre de composant ou carte (`h3`).
  - **16 px / 400-500** : Corps de texte (base).
  - **14 px / 500** : Texte d'aide, badges et métadonnées secondaires (`.petit`, `.aide`).

---

## 4. Vérifications Qualité & Rigueur UX (Checklist ui-ux-pro-max)

1. **Contraste WCAG 2.1 AA/AAA** :
   - Tous les textes et icônes informatives dépassent le seuil obligatoire de 4.5:1 sur fond sombre (texte principal jusqu'à 15:1).
   - Aucun texte gris-sur-gris illisible.
2. **Zones Tactiles Ergonomiques (≥ 44×44 px)** :
   - Tous les boutons (`button`, `.bouton`), liens de navigation (`nav a`), champs de formulaire (`input`, `select`, `textarea`) et cases à cocher possèdent une zone d'interaction d'au moins 44 px de haut avec espacement adéquat.
3. **Zéro Émoji pour les Icônes** :
   - Utilisation exclusive des icônes vectorielles SVG Lucide (`app/static/icones.svg` via le macro Jinja `{{ icone(...) }}`).
   - Préservation stricte des rôles sémantiques (`aria-hidden="true"` si décoratif, libellé `aria-label` si action seule).
4. **Prise en charge de `prefers-reduced-motion`** :
   - Coupe immédiatement toutes les transitions, translations, lueurs pulsantes et animations de la mascotte Gouti lorsque l'utilisateur l'exige au niveau système.
5. **Disposition Bento Box Responsive** :
   - Points de rupture adaptatifs : 375 px (mobile), 768 px (tablette), 960 px (tiroir opérateur), 1220 px (desktop).
   - Zéro défilement horizontal parasite.
