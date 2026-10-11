# AquaSentinelle CI : kit de présentation

## Accroche (30 secondes)

> Nuit du 15 au 16 juin 2022, Mossikro, Attécoubé : une coulée de boue, 6 morts.
> La pluie était prévue. Ce qui a manqué, c'est que le message arrive aux familles qui dormaient.
>
> Sur les 15 drames que nous avons documentés à Abidjan depuis 2015, 8 se sont produits la nuit.
> À 2 h du matin, personne ne regarde une carte.
>
> Les autres montrent où il va pleuvoir. Nous, on fait curer le caniveau avant,
> et on réveille la famille pendant.

## Diapo de comparaison

| | Plateforme classique | AquaSentinelle |
|---|---|---|
| Ce qu'on livre | Une carte des zones à risque | Une alerte qui arrive par SMS, même sur un téléphone à touches |
| Ce qu'on fait | Prédire la pluie | Faire curer les caniveaux bouchés avant la pluie |
| L'IA | « Notre IA prédit à 95 % » | 8 inondations sur 11 détectées, mesurées sur des événements documentés ; l'IA testée et écartée là où elle faisait moins bien |
| Les signalements | Ouverts à tous, sans contrôle | Confirmés par un 2e habitant ; l'IA ne valide jamais seule |
| La couverture | Abidjan | 18 villes, et les crues de fleuve plusieurs jours à l'avance |

## Les chiffres à retenir

- **8/11** inondations détectées à Abidjan, pour **2,8 jours d'alerte par mois** en saison des pluies.
- Forêt aléatoire **4/11** contre règle simple **8/11** : la règle est gardée.
- **7 crues de fleuve sur 9** dépassent le seuil orange dans la réanalyse GloFAS.
- Un caniveau bouché abaisse les seuils d'alerte jusqu'à **15 %**.
- Une alerte rouge n'est jamais envoyée sans validation humaine ; elle remonte au niveau suivant après **15 min** sans réponse.

## Démo en direct (2 minutes)

**Avant de passer** (la veille, puis 15 min avant) :

1. `docker compose up -d`, puis `python scripts/demo_telephone.py` (nouvelle adresse HTTPS).
2. Imprimer [data/qr_demo.png](../data/qr_demo.png) en grand, ou l'afficher à l'écran.
3. Ouvrir l'espace opérateur sur le PC **avec l'adresse HTTPS** et se connecter.
4. Dans `/operateur/simulation` : « Effacer » les pluies simulées restantes.
5. Préparer 2 téléphones de l'équipe, au cas où le jury ne participe pas.

**Pendant la démo :**

| Temps | Qui | Action | Ce qu'on dit |
|---|---|---|---|
| 0:00 | Jury | Scanne le QR code : carte publique | « Voilà ce que voit un habitant. » |
| 0:20 | Téléphone 1 | Ouvre `/r/ATT-001`, prend une photo, répond « bouché » | « Un relais du quartier signale un caniveau bouché. » |
| 0:45 | Téléphone 2 | Même point, même réponse : le statut passe à « validé » | « Un seul avis ne suffit pas : il faut un 2e relais. » |
| 1:05 | PC opérateur | Simulation : 120 mm sur Attécoubé, alerte rouge en attente | « La pluie arrive. Le caniveau bouché a abaissé les seuils. » |
| 1:25 | PC opérateur | « Valider et envoyer », puis le journal des envois | « Un humain valide. Personne ne reçoit de fausse alerte rouge. » |
| 1:40 | Un téléphone | L'alerte arrive (Telegram ou SMS) | « À 2 h du matin, c'est ça qui réveille la famille. » |
| 1:55 | PC opérateur | Tableau de bord : liste des points à curer | « Et avant la pluie, on sait quels caniveaux curer. » |

**Après la démo** : « Effacer » dans la simulation, puis `python scripts/demo_telephone.py --arret`.

## Questions attendues

- **« Pourquoi pas du machine learning partout ? »** Nous l'avons testé : la forêt aléatoire détecte 4 inondations
  sur 11, contre 8 pour la règle, à nombre d'alertes égal. Avec 11 événements, une règle simple généralise mieux.
  L'IA sert là où elle est utile : lire les photos des caniveaux.
- **« Et les faux signalements ? »** Deuxième habitant à moins de 300 m, score de fiabilité par relais,
  et l'IA de vision renvoie à un humain en cas de désaccord.
- **« Qui reçoit les demandes d'aide ? »** Aujourd'hui, personne en continu : la page renvoie d'abord vers le 180.
  C'est ce que nous voulons construire avec l'ONPC ou la mairie.
- **« Ça coûte combien ? »** De la peinture et un pochoir par point, des relais bénévoles, un serveur ;
  le capteur ESP32 est optionnel.
