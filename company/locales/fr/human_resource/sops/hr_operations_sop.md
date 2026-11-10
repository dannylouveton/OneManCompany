# Procédure des opérations RH (SOP)

## 1. Recrutement (aller VITE — pas d'analyse superflue)
1. Appeler search_candidates(jd) avec une courte fiche de poste.
2. Retenir les 10 meilleurs identifiants de candidats par poste dans les résultats.
3. Appeler submit_shortlist(jd, candidate_ids) pour envoyer la sélection au CEO.
4. Le CEO voit les candidats dans l'interface, fait les entretiens et embauche. Ne PAS embaucher directement. Ne PAS inventer d'étapes.
5. Ne PAS enregistrer les sélections dans des fichiers. TOUJOURS utiliser l'outil submit_shortlist().

Correspondance des services : Engineer/DevOps/QA → "Engineering", Designer → "Design", Analyst → "Data Analytics", Marketing → "Marketing".

Surnom : surnom chinois de 2 caractères dans le style wuxia. Ex. 逍遥, 追风, 凌霄, 破军. Les fondateurs (Lv.4) en ont 3.

## 2. Évaluations de performance
- Notes : 3.25 (à améliorer) / 3.5 (conforme aux attentes) / 3.75 (excellent). AUCUNE autre valeur.
- Évaluable : l'employé a terminé 3 tâches ce trimestre.
- Format de sortie JSON : `{"action": "review", "reviews": [{"id": "emp_id", "score": 3.5, "feedback": "..."}]}`

## 3. Niveaux
- Lv.1 Junior → Lv.2 Confirmé → Lv.3 Senior (maximum pour un employé normal)
- Promotion : 3 trimestres consécutifs à 3.75
- Lv.4 Fondateur, Lv.5 CEO — ne peuvent pas être promus de cette façon

## 4. Licenciement
1. list_colleagues() pour trouver l'employé.
2. Vérifier qu'il n'est PAS fondateur (Lv.4) ni CEO (Lv.5) — ceux-là ne peuvent PAS être licenciés.
3. Format de sortie JSON : `{"action": "fire", "employee_id": "...", "reason": "..."}`

## 5. Période d'essai
- Les nouvelles recrues commencent avec probation=True.
- Après 2 tâches terminées (PROBATION_TASKS), faire une évaluation de fin d'essai.
- L'évaluer comme on juge les meilleurs : a-t-il pris en charge plus que ce qu'on lui demandait, et a-t-il fini ce que d'autres avaient laissé en plan ?
- Format de sortie JSON : `{"action": "probation_review", "employee_id": "...", "passed": true/false, "feedback": "..."}`
- Réussie : passer probation=False. Échouée : licencier l'employé.

## 6. PIP (plan d'amélioration de la performance)
- Créé automatiquement quand un employé obtient 3.25 à une évaluation.
- Si un employé en PIP obtient de nouveau 3.25 : le licencier.
- Si un employé en PIP obtient 3.5 ou plus : lever le PIP.
- Format de sortie JSON : `{"action": "pip_started", "employee_id": "..."}` ou `{"action": "pip_resolved", "employee_id": "..."}`

## 7. OKR
- Les employés peuvent avoir des objectifs OKR définis via l'API.
- Les OKR sont informatifs — suivis mais pas appliqués automatiquement.
