# AquaSentinelle CI — Système de conception (référence Master)

Source unique de vérité pour le portail public et l'espace opérateur. Les valeurs vivent dans
`app/static/style.css` (jetons sur `:root`) ; ce document dit pourquoi elles sont ce qu'elles sont.

Version 2 (octobre 2026) : remplace la version « Dark Tech Glassmorphism / Bento ». Le verre, les lueurs, les ombres
au repos et les dégradés ont été retirés ; le site est passé sur fond clair, plus lisible en plein soleil sur un téléphone.

---

## 1. L'idée

**La couleur d'alerte est le produit.** Ce service ne produit qu'une chose : un niveau vert, orange ou rouge par ville.
La page d'accueil en fait des champs de couleur pleins :

- le premier écran prend la couleur de la situation nationale, ou celle de la ville choisie par le visiteur ;
- la goutte du logo (la forme de Gouti) sert de fenêtre sur une averse à Abidjan ;
- les chapitres suivants alternent papier, nuit et bleu d'eau ; le pied de page construit le nom en blocs
  dont les hauteurs dessinent une crue (montée rapide, décrue lente), « CI » aux couleurs du drapeau.

L'élément interactif : choisir sa ville (liste ou menu) colore tout l'écran à son niveau. La ville est mémorisée
dans le navigateur, et l'adresse `/?ville=<id>` fonctionne sans JavaScript.

### Pages intérieures

Chaque page publique s'ouvre sur un « chapitre » de couleur pleine (`<section class="tete">`) dont l'en-tête prend la
couleur, et porte un élément propre à son sujet. La couleur est fixée en tête de `index.html` (`champ_page`).

| Page | Champ | Élément propre |
|---|---|---|
| Carte (`/carte`) | nuit | Légende en grand avec les vrais symboles, carte pleine largeur |
| Signaler | ciel | Photo dans la goutte ; progression des étapes cochée au fil du formulaire |
| Consignes | eau, puis vert / orange / brume | Numéros d'urgence géants ; chapitres Avant (vert), Pendant (orange), Après |
| Alertes SMS | brume | Téléphone dessiné : aperçu du vrai SMS (`src/messages.py`) pour la commune choisie |
| Pluviomètre | nuit | Pluviomètre gradué qui se remplit avec la valeur saisie |
| Urgence (`/aide`) | rouge | Bouton d'appel 180 géant, placé juste sous le titre sur téléphone |
| Suivi d'une demande | rouge, vert une fois prise en charge | Étapes du traitement |
| Relais (`/r/<point>`) | nuit | Caniveau dessiné avec son repère orange et son QR code |
| Merci, erreur, connexion, guide | vert, brume, nuit, brume | Gouti, ou le formulaire en bonne place |

Vert, orange et rouge gardent toujours leur sens : niveau d'alerte, urgence (rouge), réussite (vert).

## 2. Couleurs

| Rôle | Jeton | Valeur | Usage |
|---|---|---|---|
| Encre | `--encre` | `#0B1120` | Texte courant, boutons, barre latérale, chapitres sombres |
| Papier | `--papier` | `#EFF3F7` | Fond des pages |
| Surface | `--surface` | `#FFFFFF` | Cartes, tableaux, formulaires (un pas de ton au-dessus du papier) |
| Surface 2 / 3 | `--surface-2`, `--surface-3` | `#E3E9F0`, `#D3DCE6` | Boutons légers, en-têtes de tableau, survols |
| Texte secondaire | `--texte-2` / `--doux` | `#334155` / `#4B5A6E` | Notes ; 6,4:1 sur le papier |
| Eau (marque) | `--ciel`, `--ciel-fonce` | `#0EA5E9`, `#0369A1` | Tuile d'action SMS, liens (5,5:1), lien actif opérateur |
| Marque | `--marque` | `#EA580C` | « CI » du logo, bandeau de Gouti |

**Niveaux d'alerte**, jamais utilisés comme décoration :

| Niveau | Champ plein | Encre sur le champ | Étiquette sur papier |
|---|---|---|---|
| Vert | `#22C55E` | nuit, 8,3:1 | `#DCFCE7` / `#14532D` |
| Orange (orange du drapeau) | `#F77F00` | nuit, 7,2:1 | `#FFEDD5` / `#7C2D12` |
| Rouge | `#C62828` | blanc, 5,6:1 | `#FEE2E2` / `#7F1D1D` |

Chaque étiquette de niveau porte aussi une forme (rond, triangle, octogone) : elle reste lisible sans la couleur.
Le champ de l'accueil est piloté par l'attribut `data-champ` du `body` (`vert`, `orange`, `rouge`, `gris`).

## 3. Typographie

Une seule famille : **Plus Jakarta Sans** (400, 600, 700, 800). Cinq tailles sur le portail :

| Jeton | Valeur | Usage |
|---|---|---|
| `--t-petit` | 15 px | Notes, légendes, crédits |
| corps | 18 px (portail), 16–17 px (opérateur) | Texte courant, boutons, champs |
| `--t-sous` / chapeau | 21–24 px | Phrase d'accroche, titres de panneau |
| `--t-titre` | clamp(34 px, 4,2vw, 60 px) | Titres de chapitre et de page |
| `--t-affiche` | clamp(44 px, 6,4vw, 108 px) | Titre du premier écran, noms des villes |

Titres en 800, interlettrage −0,03 à −0,045em, deux lignes au plus à toutes les largeurs. Pas de petites capitales
espacées, pas de sur-titre (« eyebrow ») au-dessus des titres du portail.

## 4. Formes, surfaces, verre et thèmes

- Un rayon de 4 px pour les cartes, champs et photos ; 28 px (`--rayon-verre`) pour les panneaux de verre.
- Boutons en forme de goutte : `--goutte: 4px 999px 999px 999px` (pointe en haut à gauche), hauteur 48 px minimum.
- **Colonne centrée** : `--largeur: 1280px` et `--gouttiere` (marge latérale) partagés par l'en-tête, les chapitres et le contenu.
- **Verre** (classes `.verre` et `.verre-champ`) réservé à ce qui flotte au-dessus d'autre chose : l'îlot de
  navigation au défilement, le menu mobile plein écran, la répartition des niveaux posée sur la photo de l'accueil,
  le panneau SMS sur la photo du Bandama, les couches posées sur la carte, les légendes des photos, la barre de
  progression des formulaires sur mobile, le guide de Gouti. Repli opaque sous `prefers-reduced-transparency`.
- **Deux thèmes**, `data-theme="light"` ou `"dark"` sur `<html>` : choix mémorisé (`localStorage` « aqua-theme »),
  sinon réglage du système ; appliqué dans le `<head>` avant le premier rendu. Bascule dans l'en-tête, le menu mobile
  et la barre latérale opérateur. Les jetons qui changent : papier, surfaces, textes, `--nuit`, `--plein`, `--saisie`,
  `--lien`, étiquettes de niveau. Vert, orange et rouge restent identiques (ils portent le niveau). En sombre, les
  tuiles de carte sont inversées.
- Aucun trait de séparation, sauf dans les tableaux et les champs de formulaire.

## 5. Images

Photos réelles du monde du sujet, sous licence libre, dans `app/static/img/` (WebP, 80 à 180 Ko). Crédits et
licences dans `app/static/img/credits.json` et en pied de l'accueil. Aucune n'est présentée comme une photo du projet.
Pas de vidéo : les visiteurs sont souvent sur données mobiles ; le mouvement de l'image du héros est un lent zoom CSS.

## 6. Mouvement

- Courbes : `--sortie: cubic-bezier(0.22, 1, 0.36, 1)`, `--ressort: cubic-bezier(0.32, 0.72, 0, 1)`.
- Geste signature : la photo de la goutte s'ouvre de bas en haut (l'eau qui monte), puis dérive lentement.
- Entrées au défilement posées par `app/static/app.js` (IntersectionObserver) : le contenu n'est masqué que si le
  script tourne. Retour visuel sur chaque bouton, lien et ligne de ville.
- Transform et opacity uniquement ; `prefers-reduced-motion` coupe tout déplacement.

## 7. Vérifications (ui-ux-pro-max et taste-skill)

1. Contraste AA partout (valeurs ci-dessus), texte courant à 16 px minimum.
2. Cibles tactiles ≥ 44 × 44 px ; menu du portail repliable sous 900 px.
3. Icônes Lucide du sprite `app/static/icones.svg`, jamais d'émoji ; `aria-hidden` si décoratives.
4. Contrôle automatique : `node <taste-skill>/scripts/lint.mjs app/static` et
   `node <taste-skill>/scripts/inspect.mjs "http://localhost:8000/?guide=0"` (le paramètre `guide=0` évite le guide de
   première visite). Une exception justifiée porte le commentaire `taste-skill-ignore`.
5. Points de rupture : 480 px (en-tête compact), 640 px, 900 px (portail), 960 px (tiroir opérateur).
