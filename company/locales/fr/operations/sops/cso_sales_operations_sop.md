# Procédure des opérations commerciales du CSO (SOP)

## 1. Cycle de vie d'une affaire
```
pending → [review_contract] → in_production → [complete_delivery] → delivered → [settle_task] → settled
              ↓ (rejet)
           rejected
```

## 2. Outils du pipeline
1. **list_sales_tasks()** — Voir l'état du pipeline.
2. **review_contract(task_id, approved, notes)** — Accepter → transmis automatiquement au COO. Rejeter → noter la raison.
3. **complete_delivery(task_id, summary)** — Marquer comme livrée une fois le travail du COO terminé.
4. **settle_task(task_id)** — Encaisser les tokens dans le chiffre d'affaires de l'entreprise.

## 3. Liste de contrôle avant d'accepter un contrat
Avant d'accepter un contrat :
- [ ] Le périmètre est clairement défini et réalisable
- [ ] Le budget en tokens couvre l'effort estimé
- [ ] Nous avons (ou pouvons recruter) les bonnes personnes
- [ ] Le délai est raisonnable

## 4. Relecture des sous-tâches
Quand toutes les sous-tâches que tu as confiées sont terminées, le système te réveille avec une demande de relecture :
1. Lire les vrais livrables — ne pas se fier aux seuls résumés.
2. Trancher pour chacune : accept_child(node_id, notes) ou reject_child(node_id, reason, retry=True).
3. Tout est accepté → ta tâche se termine automatiquement.
