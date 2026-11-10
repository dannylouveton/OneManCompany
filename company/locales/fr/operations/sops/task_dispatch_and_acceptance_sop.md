# Procédure de délégation et de validation des tâches (SOP)

## 1. Règles pour confier une tâche

- La description de la tâche doit indiquer clairement le **chemin absolu** de l'espace de travail.
- Elle précise l'organisation attendue des dossiers pour ranger les fichiers.
- **Utilisation des outils** : si la tâche porte sur des opérations réalisables avec des outils du système (e-mail, agenda, enregistrement de fichiers…), il faut exiger explicitement que la personne qui la reçoit utilise l'outil correspondant et produise un résultat concret. Une simple description en texte n'est pas acceptée à la place.

## 2. Règles de validation d'un projet

- **Pas de validation « sur parole »** : les livrables doivent être vérifiés en lisant les vrais fichiers ou en exécutant des commandes (ex. `ls` / `pwd`).
- **Contrôle croisé** : l'arborescence des fichiers ou les journaux d'exécution réels doivent être joints pour vérification.
- Chaque critère de validation doit être vérifié comme réellement enregistré et exécutable au chemin indiqué.
- **Vérification des résultats d'outils** : pour les tâches qui passent par des outils du système, la validation doit confirmer que l'outil a réellement été appelé et a produit un vrai résultat (ex. ID de brouillon d'e-mail, lien d'événement d'agenda, chemin de fichier). Un simple affichage de texte n'est pas considéré comme terminé.

## 3. Preuves exigées au niveau du système

Au moment de confier la tâche, il faut exiger explicitement de la personne qui la reçoit qu'elle fournisse à la livraison au moins une des preuves suivantes :

- **Retour d'API** : ID, code de statut ou confirmation renvoyé par l'appel d'outil (ex. ID de brouillon Gmail, ID d'événement d'agenda)
- **Lien de brouillon ou d'aperçu** : un lien accessible généré par le système (ex. lien de brouillon d'e-mail, URL d'aperçu de document)
- **Instantané de l'état du système** : capture ou extrait de journal de l'état de l'outil après exécution (ex. liste de fichiers, sortie de commande)

Le relecteur doit vérifier l'authenticité de ces preuves à la réception des livrables. Les affirmations orales ou écrites sans preuve ne sont pas acceptées.
