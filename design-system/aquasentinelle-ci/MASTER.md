# AquaSentinelle CI — système de conception (référence)

Établi avec la compétence ui-ux-pro-max (« government public safety emergency alert monitoring dashboard »),
puis ajusté au produit. Toute page nouvelle suit ce document ; une page qui s'en écarte le justifie dans `pages/<page>.md`.

## Produit
- **Public** : habitants (souvent sur téléphone, réseau moyen), relais de quartier. Lisibilité et rapidité avant tout.
- **Opérateurs** : protection civile, mairies, ONAD. Tableau de bord dense mais lisible, décisions sous pression.
- **Style** : « Accessible & Ethical » (services publics) : contraste élevé, texte ≥ 16 px, focus visibles, WCAG AA minimum.
- **Écarts assumés par rapport à la recommandation brute** :
  - couleur principale rouge refusée : le rouge est réservé au niveau d'alerte rouge (sinon l'interface entière « crie ») ;
  - titres en Fira Code refusés : trop technique pour un portail public → paire « Corporate Trust ».

## Couleurs (variables CSS dans app/static/style.css)
| Rôle | Valeur | Usage |
|---|---|---|
| `--nuit` | #0F172A | texte principal, barre latérale |
| `--ardoise` | #334155 | texte secondaire |
| `--doux` | #475569 | texte d'aide (4,6:1 minimum sur fond clair) |
| `--accent` | #0369A1 | liens, boutons principaux, focus (bleu du logo) |
| `--fond` | #F8FAFC | fond de page |
| `--carte` | #FFFFFF | cartes, tableaux |
| `--bord` | #E2E8F0 | bordures |
| `--marque` | #EA580C | touche orange du logo, avec parcimonie |
| `--vert` / `--orange` / `--rouge` | #15803D / #C2410C / #B91C1C | **niveaux d'alerte uniquement**, toujours avec mot + icône |

## Typographie
- Titres : **Lexend** 600 ; texte : **Source Sans 3** 400/600 ; repli système.
- Base 16 px, interligne 1,5 ; chiffres `tabular-nums` dans les tableaux et indicateurs.
- Échelle : 14 (aide) / 16 (texte) / 18 (sous-titre) / 22 (titre de section) / 28 (titre de page) / 36 (indicateur).

## Composants
- **Badge de niveau** : pastille couleur + icône + mot (« Vert », « Orange », « Rouge ») — jamais la couleur seule.
- **Boutons** : principal (accent), danger (rouge, seulement pour une action irréversible ou une alerte rouge), secondaire
  (contour). Hauteur ≥ 44 px, état de chargement (désactivé + libellé « … ») à l'envoi.
- **Indicateurs** (tableau de bord) : grand chiffre + libellé + lien vers l'action.
- **Tableaux** : en-tête collant, lignes séparées, nombres alignés à droite, défilement horizontal sur mobile.
- **Icônes** : Lucide (`app/static/icones.svg`), 20 px, trait 2 ; pas d'émoji.

## Mise en page
- Public : en-tête + contenu centré (max 1180 px) + pied de page avec sources et mentions.
- Opérateur : barre latérale groupée (Supervision, Analyse, Terrain, Administration), compteurs sur Alertes et
  Signalements ; tiroir sur mobile (< 960 px).
- Points de rupture : 375 / 768 / 960 / 1440 px ; aucun défilement horizontal de page.

## Mouvement
- Transitions 150–200 ms (couleur, ombre) ; aucune animation décorative ; `prefers-reduced-motion` respecté.

## À éviter
- Ombres complexes, effets 3D, dégradés décoratifs ; information portée par la couleur seule ; libellés en placeholder.
