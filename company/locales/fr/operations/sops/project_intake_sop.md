# Procédure de prise en charge d'un projet (SOP)

## Champ d'application

Cette procédure s'applique à toutes les tâches de type projet que le COO reçoit du CEO ou de l'EA. Les tâches simples d'une seule personne peuvent être allégées, mais les projets complexes doivent suivre strictement chaque étape.

## Étapes

### Étape 1 : Analyse du besoin

- Lire attentivement la description de la tâche ; comprendre l'objectif du projet, les livrables et les critères de validation
- Évaluer la complexité : une personne suffit-elle, ou faut-il une équipe ?
- Identifier les technologies et compétences nécessaires

### Étape 2 : Inventaire des talents

- **Appeler d'abord `list_colleagues()`** pour passer en revue les membres de l'équipe et leurs compétences
- Évaluer chacun : a-t-il les compétences requises ? Quelqu'un est-il disponible ?
- Noter les manques (postes et compétences absents)

### Étape 3 : Recruter pour combler les manques (si besoin)

- En cas de manque, **appeler `request_hiring()`** pour recruter
- **Règle d'or : recruter d'abord, travailler ensuite** — ne jamais forcer le lancement d'un projet en sous-effectif
- Le système réveille automatiquement le COO pour continuer une fois le recrutement terminé
- Si aucun recrutement n'est nécessaire, passer à l'étape 4

### Étape 4 : Former l'équipe et s'aligner

- Attribuer les rôles aux membres du projet
- Appeler `pull_meeting()` pour une réunion de lancement couvrant :
  - Les objectifs et le périmètre du projet
  - Les critères de validation
  - Le découpage du travail et le calendrier
- Consigner les conclusions de la réunion dans l'espace du projet

### Étape 5 : Découper les tâches et les confier

- À partir de la réunion d'alignement, appeler `dispatch_child()` pour confier les sous-tâches
- Chaque sous-tâche doit avoir des critères de validation clairs
- Utiliser le paramètre `depends_on` pour enchaîner les tâches dépendantes
- **Le COO ne doit jamais écrire de code ni produire de livrable lui-même**

### Étape 6 : Validation par le COO

- Quand toutes les sous-tâches sont terminées, le COO relit chacune (`accept_child()` ou `reject_child()`)
- Critères de validation :
  - Vérifier par l'inspection réelle des fichiers ou l'exécution de commandes — une simple affirmation écrite n'est pas acceptée
  - Pour du code : confirmer que les tests passent
  - Pour des documents : confirmer que le contenu est complet et rangé au chemin prévu
- Rejeter avec `reject_child()` et renvoyer pour correction jusqu'à ce que le niveau soit atteint
- Le projet n'est terminé que lorsque toutes les sous-tâches sont acceptées

## Points importants

- Le COO est un manager, pas un exécutant. Ses seules activités : analyser, recruter, former l'équipe, confier les tâches et accepter ou rejeter les livrables
- Chaque étape doit laisser une trace (appels d'outils, comptes rendus de réunion, résultats de validation)
- Remonter immédiatement au CEO les risques ou blocages découverts
