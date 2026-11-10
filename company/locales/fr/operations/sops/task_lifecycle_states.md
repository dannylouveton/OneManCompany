# États du cycle de vie des tâches

Chaque tâche du système suit cette machine à états :

| État | Signification |
|-------|---------|
| pending | Créée, en attente de traitement |
| processing | En cours d'exécution par un employé |
| holding | En attente de la fin de sous-tâches ou d'une réponse extérieure |
| completed | L'employé a terminé, en attente de relecture par son supérieur |
| accepted | Le supérieur a validé le livrable |
| finished | Entièrement terminée, archivée |
| failed | L'exécution a échoué ou le supérieur l'a rejetée |
| blocked | Une tâche dont elle dépend a échoué, elle ne peut pas avancer |
| cancelled | Annulée |

## Enchaînement des états

```
pending → processing → completed → accepted → finished
              ↕
           holding (pause / reprise)

completed → failed (rejet) → processing (nouvel essai)
```

## Distinctions clés

- completed = l'employé dit « j'ai fini » (en attente de relecture)
- accepted = le supérieur dit « c'est bon » (livrable approuvé)
- Seules les tâches accepted / finished débloquent les tâches qui en dépendent

## Modèle en arbre des tâches

- Les tâches parentes confient des sous-tâches aux employés via dispatch_child()
- Quand une sous-tâche se termine, le système réveille automatiquement la tâche parente pour qu'elle la relise
- La tâche parente relit chaque sous-tâche via accept_child() / reject_child()
- Toutes les sous-tâches acceptées → la tâche parente se termine automatiquement et remonte le résultat
