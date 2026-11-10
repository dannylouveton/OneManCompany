# Référence du format des workflows

Les noms de champs (Flow ID, Owner, Goal…) restent en anglais : c'est ainsi que le système lit les workflows.

## En-tête

Chaque fichier de workflow doit commencer par un titre de niveau 1, suivi de ces champs :

- **Flow ID** *(obligatoire)* : identifiant unique en snake_case, ex. `project_retrospective`
- **Owner** *(obligatoire)* : le rôle responsable du workflow, ex. `HR`, `COO`
- **Collaborators** *(facultatif)* : les autres rôles impliqués à l'échelle du workflow
- **Trigger** *(facultatif)* : l'événement qui lance le workflow

## Phases

Chaque bloc `## Phase N: Title` définit une étape du workflow :

- **Goal** *(obligatoire)* : le résultat que cette phase doit atteindre
- **Responsible** *(obligatoire)* : qui exécute cette phase, ex. `HR`, `COO`, `Each participating employee`
- **Collaborators** *(facultatif)* : les rôles en soutien pour cette phase uniquement
- **Depends on** *(facultatif)* : les phases préalables, ex. `Phase 1` ou `Phase 1, Phase 2`
- **Steps** *(facultatif)* : sous-tâches numérotées ou à puces
- **Output** *(facultatif)* : livrable concret produit par cette phase

## Règles des champs

| Champ | Portée | Obligatoire |
|---|---|---|
| Flow ID | En-tête | Oui |
| Owner | En-tête | Oui |
| Collaborators | En-tête / Phase | Non |
| Trigger | En-tête | Non |
| Goal | Phase | Oui |
| Responsible | Phase | Oui |
| Depends on | Phase | Non |
| Steps | Phase | Non |
| Output | Phase | Non |

## Exemple

```markdown
# Workflow d'intégration

- **Flow ID**: onboarding
- **Owner**: HR
- **Trigger**: Arrivée d'une nouvelle recrue

---

## Phase 1: Préparer le poste de travail

- **Goal**: Le poste et les comptes sont prêts avant le premier jour
- **Responsible**: COO
- **Steps**:
  1. Configurer l'ordinateur et les accès
  2. Ajouter aux canaux de communication de l'entreprise
- **Output**: Liste de contrôle du poste prêt

## Phase 2: Accueil

- **Goal**: La recrue comprend la culture de l'entreprise et son rôle
- **Responsible**: HR
- **Depends on**: Phase 1
- **Steps**:
  1. Présenter le manuel de l'entreprise
  2. Présenter les membres de l'équipe
- **Output**: Confirmation d'intégration signée
```
