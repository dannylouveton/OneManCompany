/* OneManCompany — interface translations.
 *
 * English is the source language: keys are the English strings as they appear
 * in index.html / app.js. Text nodes and title / placeholder / aria-label
 * attributes are translated as they are added to the page, so most of the UI
 * is covered without touching app.js. Dynamic strings can use I18N.t('...').
 *
 * To add a language: add an entry to SUPPORTED and LOCALES and a dictionary
 * to DICTS (missing keys fall back to English).
 */
(function () {
  'use strict';

  const SUPPORTED = { en: 'English', fr: 'Français' };
  const LOCALES = { en: 'en-US', fr: 'fr-FR' };
  const STORAGE_KEY = 'omc.lang';

  const DICTS = {
    fr: {
      "Actions": "Actions",
      "Start onboarding": "Lancer la prise de poste",
      "Onboarding started": "Prise de poste lancée",
      "Launch onboarding mission": "Lancer la mission d'intégration",
      "Onboarding mission launched": "Mission d'intégration lancée",
      "My answers:": "Mes réponses :",
      "(no answer)": "(pas de réponse)",
      "Several choices possible": "Plusieurs choix possibles",
      "One choice": "Un seul choix",
      "Recommended": "Recommandé",
      "Other answer or note (optional)": "Autre réponse ou précision (facultatif)",
      "Answered": "Répondu",
      "Send answers": "Envoyer mes réponses",
      "Connect an MCP connector or an API key and choose which employees can use it": "Connectez un connecteur MCP ou une clé API et choisissez quels employés peuvent l'utiliser",
      "API key": "Clé API",
      "Employees never receive the key. They ask the server to make the call; it checks your rules, adds the key and returns the answer. Writes can wait for your approval": "Les employés ne reçoivent jamais la clé. Ils demandent au serveur de faire l'appel : il vérifie vos règles, ajoute la clé et renvoie la réponse. Les écritures peuvent attendre votre validation",
      "API address": "Adresse de l'API",
      "Paste the key here": "Collez la clé ici",
      "Key sent as": "Clé envoyée en",
      "Header": "En-tête",
      "Query parameter": "Paramètre d'URL",
      "Header or parameter name": "Nom de l'en-tête ou du paramètre",
      "Value format ({key} = the key)": "Format de la valeur ({key} = la clé)",
      "Documentation link (optional)": "Lien vers la documentation (facultatif)",
      "What it is for (optional)": "À quoi elle sert (facultatif)",
      "Reply to customers in Intercom": "Répondre aux clients dans Intercom",
      "The key is stored in the company secret store, never in the tool definition. By default employees can only read; you choose the allowed writes next": "La clé est enregistrée dans le coffre à secrets de l'entreprise, jamais dans la fiche de l'outil. Par défaut les employés peuvent seulement lire ; vous choisissez ensuite les écritures autorisées",
      "Name, API address and key are required": "Le nom, l'adresse de l'API et la clé sont obligatoires",
      "API key added": "Clé API ajoutée",
      "Key sent as query parameter": "Clé envoyée en paramètre d'URL",
      "Key sent in header": "Clé envoyée dans l'en-tête",
      "Current key": "Clé actuelle",
      "API documentation →": "Documentation de l'API →",
      "Employees never see the key: the server adds it to each call it allows": "Les employés ne voient jamais la clé : le serveur l'ajoute à chaque appel qu'il autorise",
      "Replace the key": "Remplacer la clé",
      "New API key": "Nouvelle clé API",
      "Replace key": "Remplacer la clé",
      "Key replaced": "Clé remplacée",
      "Waiting for your approval": "À valider",
      "Sent": "Envoyé",
      "Rejected": "Refusé",
      "Call failed": "L'appel a échoué",
      "Rules": "Règles",
      "Rules for this employee only. Changing them makes them personal": "Règles de cet employé uniquement. Les modifier les rend personnelles",
      "What they can do": "Ce qu'ils peuvent faire",
      "Reads (GET) are always allowed. Shared settings for every employee without personal rules": "Les lectures (GET) sont toujours autorisées. Réglages communs à tous les employés sans règles personnelles",
      "Writes (POST, PUT, PATCH, DELETE)": "Écritures (POST, PUT, PATCH, DELETE)",
      "Read only": "Lecture seule",
      "Only the writes listed below": "Seulement les écritures listées ci-dessous",
      "All writes": "Toutes les écritures",
      "Allowed writes (one per line, * = any segment)": "Écritures autorisées (une par ligne, * = n'importe quel segment)",
      "Ask me before each write": "Me demander avant chaque écriture",
      "Remove API key": "Retirer la clé API",
      "Recent calls": "Derniers appels",
      "No calls yet": "Aucun appel pour l'instant",
      "Remove this API key? It is deleted from the secret store and employees lose access": "Retirer cette clé API ? Elle est supprimée du coffre à secrets et les employés n'y ont plus accès",
      "allowed": "autorisé",
      "approval": "à valider",
      "approved": "validé",
      "rejected": "refusé",
      "denied": "bloqué",
      "Personalized": "Personnalisé",
      "Use shared settings": "Revenir aux réglages communs",
      "Actions for this employee only. Changing them makes them personal": "Actions de cet employé uniquement. Les modifier les rend personnelles",
      "Shared settings for every employee without personal actions. Unchecked actions are blocked, even without confirmation prompts": "Réglages communs à tous les employés sans actions personnelles. Les actions décochées sont bloquées, même sans demande de confirmation",
      "Add a tool": "Ajouter un outil",
      "Catalog": "Catalogue",
      "My Claude Code connectors": "Mes connecteurs Claude Code",
      "Other (URL or command)": "Autre (URL ou commande)",
      "Connect an MCP connector and choose which employees can use it": "Connectez un connecteur MCP et choisissez quels employés peuvent l'utiliser",
      "Installed": "Installé",
      "Install": "Installer",
      "Share with the team": "Partager avec l'équipe",
      "No MCP connectors found in your Claude Code configuration": "Aucun connecteur MCP trouvé dans votre configuration Claude Code",
      "My connector": "Mon connecteur",
      "URL, command or JSON": "URL, commande ou JSON",
      "Keys found in the command are stored in the company .env file, never in the tool definition": "Les clés présentes dans la commande sont enregistrées dans le fichier .env de l'entreprise, jamais dans la fiche de l'outil",
      "Connector installed": "Connecteur installé",
      "Name and URL or command are required": "Le nom et l'URL ou la commande sont obligatoires",
      "Testing": "Test en cours",
      "Save failed": "Échec de l'enregistrement",
      "Remove this connector? Employees will lose access to it": "Retirer ce connecteur ? Les employés n'y auront plus accès",
      "Connection": "Connexion",
      "Test connection": "Tester la connexion",
      "Who can use it": "Qui peut l'utiliser",
      "Allowed actions": "Actions autorisées",
      "Unchecked actions are blocked, even without confirmation prompts": "Les actions décochées sont bloquées, même sans demande de confirmation",
      "Test the connection to list its actions": "Testez la connexion pour afficher ses actions",
      "No employees": "Aucun employé",
      "No actions": "Aucune action",
      "Claude Code mode only": "Mode Claude Code uniquement",
      "Remove connector": "Retirer le connecteur",
      "Missing key": "Clé manquante",
      "MCP connector": "Connecteur MCP",
      "Stripe payments: customers, subscriptions, invoices, refunds": "Paiements Stripe : clients, abonnements, factures, remboursements",
      "Stripe API key (a restricted key is recommended)": "Clé API Stripe (clé restreinte conseillée)",
      "Intercom customer support (US workspace): conversations, contacts, articles, internal notes": "Support client Intercom (espace US) : conversations, contacts, articles, notes internes",
      "Intercom customer support (EU-hosted workspace): conversations, contacts, articles, internal notes": "Support client Intercom (espace hébergé en Europe) : conversations, contacts, articles, notes internes",
      "Intercom access token": "Jeton d'accès Intercom",
      "Intercom (EU)": "Intercom (Europe)",
      "GitHub repositories, issues and pull requests": "Dépôts, tickets et pull requests GitHub",
      "GitHub personal access token": "Jeton d'accès personnel GitHub",
      "Notion pages and databases shared with the integration": "Pages et bases Notion partagées avec l'intégration",
      "Notion integration secret": "Secret d'intégration Notion",
      "HubSpot CRM: contacts, companies, deals": "CRM HubSpot : contacts, entreprises, transactions",
      "HubSpot private app access token": "Jeton d'application privée HubSpot",
      "Founding": "Fondateur",
      "Junior": "Junior",
      "Mid": "Confirmé",
      "Senior": "Senior",
      "Operations": "Opérations",
      "Engineering": "Ingénierie",
      "Design": "Design",
      "Analytics": "Analyse",
      "Marketing": "Marketing",
      "General": "Général",
      "HR": "RH",
      "Sales": "Ventes",
      "Executive": "Direction",
      "CEO Office": "Bureau du CEO",
      "Department": "Service",
      "Role": "Rôle",
      "Level": "Niveau",
      "Core Principles": "Principes fondamentaux",
      "Labels": "Libellés",
      "Resolution": "Résolution",
      "Created by": "Créé par",
      "Fee": "Frais",
      "Actual": "Réel",
      "Connected": "Connecté",
      "Not connected": "Non connecté",
      "nodes": "nœuds",
      "messages": "messages",
      "participants": "participants",
      "tasks": "tâches",
      "notes": "notes",
      "0 selected": "0 sélectionné",
      "0 selected — click cards to select": "0 sélectionné — cliquez sur les cartes pour sélectionner",
      "1-on-1": "Entretien individuel",
      "1-on-1 Meeting": "Entretien individuel",
      "1-on-1 Notes": "Notes d'entretien",
      "3.25 Needs Improvement": "3.25 À améliorer",
      "3.5 Qualified": "3.5 Satisfaisant",
      "3.75 Excellent": "3.75 Excellent",
      "6 people": "6 personnes",
      "ACTIVITY LOG": "JOURNAL D'ACTIVITÉ",
      "API Connections": "Connexions API",
      "API Key": "Clé API",
      "e.g. OneManCompany官网": "ex. Site web de OneManCompany",
      "Abort this task? All related sub-tasks will be cancelled": "Annuler cette tâche ? Toutes les sous-tâches liées seront annulées",
      "Activate Product": "Activer le produit",
      "Active": "Actif",
      "Activity Log": "Journal d'activité",
      "Add": "Ajouter",
      "Add KR": "Ajouter un KR",
      "Add a new culture entry": "Ajouter une valeur de culture",
      "Agenda": "Ordre du jour",
      "Agent Family": "Famille d'agent",
      "Agent thinking": "L'agent réfléchit",
      "All": "Tout",
      "All Departments": "Tous les services",
      "All Levels": "Tous les niveaux",
      "All Priority": "Toutes priorités",
      "All Roles": "Tous les rôles",
      "All-Hands (CEO Address)": "Réunion générale (discours du CEO)",
      "Announcements": "Annonces",
      "Apply": "Appliquer",
      "Applying": "Application",
      "Approve": "Approuver",
      "Archive": "Archiver",
      "Are you sure you want to cancel this task": "Voulez-vous vraiment annuler cette tâche",
      "Are you sure you want to stop all running tasks in this iteration": "Voulez-vous vraiment arrêter toutes les tâches en cours de cette itération",
      "Are you sure you want to stop all tasks for all employees?\nThis will cancel ALL running tasks for ALL employees": "Voulez-vous vraiment arrêter toutes les tâches de tous les employés ?\nToutes les tâches en cours de TOUS les employés seront annulées",
      "Assign ID": "Attribuer un ID",
      "Assignee": "Responsable",
      "Attach file or image": "Joindre un fichier ou une image",
      "Attach file or image — sent with your next message": "Joindre un fichier ou une image — envoyé avec votre prochain message",
      "Auth": "Authentification",
      "Authorize": "Autoriser",
      "Authorize with Anthropic": "Autoriser avec Anthropic",
      "Available": "Disponible",
      "BACKGROUND TASKS": "TÂCHES DE FOND",
      "Back": "Retour",
      "Back to Candidates": "Retour aux candidats",
      "Back to list": "Retour à la liste",
      "Background Tasks": "Tâches de fond",
      "Backlog": "Backlog",
      "Blocked by dependency": "Bloqué par une dépendance",
      "Boss Online — Candidate Selection": "Boss Online — Sélection des candidats",
      "Both Client ID and Client Secret required": "Client ID et Client Secret requis",
      "Bump": "Incrémenter",
      "CANCEL": "ANNULER",
      "CEO": "CEO",
      "CEO (You)": "CEO (vous)",
      "CEO CONSOLE": "CONSOLE DU CEO",
      "CEO Report": "Rapport au CEO",
      "CEO message input": "Saisie du message du CEO",
      "COO Hiring Request": "Demande de recrutement du COO",
      "Cancel": "Annuler",
      "Cancel this task": "Annuler cette tâche",
      "Capacity": "Capacité",
      "Capacity (pts)": "Capacité (pts)",
      "Category": "Catégorie",
      "Chat": "Discussion",
      "Chat with EA": "Discuter avec l'EA",
      "Chief Executive Officer": "Directeur général",
      "Claude Session": "Session Claude",
      "Clear": "Effacer",
      "Clear all 1-on-1 history for this employee? This cannot be undone": "Effacer tout l'historique d'entretiens de cet employé ? Action irréversible",
      "Click here to open login page": "Cliquez ici pour ouvrir la page de connexion",
      "Click to edit": "Cliquer pour modifier",
      "Click to edit current value": "Cliquer pour modifier la valeur",
      "Click to open": "Cliquer pour ouvrir",
      "Click to rename": "Cliquer pour renommer",
      "Click to use suggested capacity": "Cliquer pour utiliser la capacité suggérée",
      "Client ID": "Client ID",
      "Client Secret": "Client Secret",
      "Close": "Fermer",
      "Code updated": "Code mis à jour",
      "Company Culture": "Culture d'entreprise",
      "Company Direction": "Cap de l'entreprise",
      "Company Rules — Workflows": "Règles de l'entreprise — Workflows",
      "Company default": "Valeur par défaut de l'entreprise",
      "Complete Review": "Terminer l'évaluation",
      "Config Warning": "Alerte de configuration",
      "Confirm": "Confirmer",
      "Continue Current Iteration": "Continuer l'itération en cours",
      "Copy Skills": "Copier les skills",
      "Cost": "Coût",
      "Cost & Budget": "Coûts et budget",
      "Could not load announcements": "Impossible de charger les annonces",
      "Create": "Créer",
      "Create Review": "Créer une évaluation",
      "DEFAULT": "PAR DÉFAUT",
      "DELETE": "SUPPRIMER",
      "DESIRED SKILLS": "COMPÉTENCES RECHERCHÉES",
      "Dashboard": "Tableau de bord",
      "Dates are required": "Les dates sont obligatoires",
      "Default Model": "Modèle par défaut",
      "Del": "Suppr.",
      "Delete": "Supprimer",
      "Delete Issue": "Supprimer le ticket",
      "Delete KR": "Supprimer le KR",
      "Delete failed": "Échec de la suppression",
      "Delete project and all data": "Supprimer le projet et toutes ses données",
      "Departed": "Parti",
      "Department": "Service",
      "Dept": "Service",
      "Dept Distribution": "Répartition par service",
      "Description": "Description",
      "Description (optional)": "Description (facultatif)",
      "Detail": "Détail",
      "Details": "Détails",
      "Different company defaults": "Valeurs par défaut différentes",
      "Disconnect": "Déconnecter",
      "Disconnect OAuth for this tool": "Déconnecter l'OAuth de cet outil",
      "Discussion (Open Floor)": "Discussion (tour de table)",
      "Dismiss": "Ignorer",
      "Dismiss Employee": "Licencier l'employé",
      "Display": "Affichage",
      "Do Not Disturb": "Ne pas déranger",
      "Do Not Disturb (ON)": "Ne pas déranger (activé)",
      "Documents": "Documents",
      "Done": "Terminé",
      "Download ZIP": "Télécharger le ZIP",
      "ERR": "ERR",
      "Edit": "Modifier",
      "Employee": "Employé",
      "Employee Details": "Fiche employé",
      "Empty": "Vide",
      "End": "Fin",
      "End Meeting": "Terminer la réunion",
      "Enter follow-up instructions": "Saisissez les instructions de suivi",
      "Enter model": "Saisir le modèle",
      "Enter owner employee ID (e.g. 00004)": "ID de l'employé responsable (ex. 00004)",
      "Equipment & Meeting Rooms": "Équipements et salles de réunion",
      "Error": "Erreur",
      "Ex-Employee Wall": "Mur des anciens",
      "Excellent": "Excellent",
      "Exchanging": "Échange en cours",
      "Execution Log": "Journal d'exécution",
      "Export": "Exporter",
      "Export SVG Screenshot": "Exporter une capture SVG",
      "FAIL": "ÉCHEC",
      "Failed to abort all tasks": "Impossible d'annuler toutes les tâches",
      "Failed to create product": "Impossible de créer le produit",
      "Failed to dismiss employee": "Impossible de licencier l'employé",
      "Failed to load": "Échec du chargement",
      "Failed to load chat": "Impossible de charger la discussion",
      "Failed to load culture": "Impossible de charger la culture",
      "Failed to load minutes": "Impossible de charger le compte rendu",
      "Failed to load template": "Impossible de charger le modèle",
      "Failed to load tools": "Impossible de charger les outils",
      "Failed to stop all cron jobs": "Impossible d'arrêter toutes les tâches planifiées",
      "Failed to stop cron job": "Impossible d'arrêter la tâche planifiée",
      "Feedback": "Retour",
      "Final Output": "Résultat final",
      "Follow-up Task": "Tâche de suivi",
      "For security reasons, only remote (self-hosted) employees support interview": "Pour des raisons de sécurité, seuls les employés distants (auto-hébergés) peuvent passer un entretien",
      "Force reload all data from disk": "Forcer le rechargement des données depuis le disque",
      "Get API key →": "Obtenir une clé API →",
      "Get credentials →": "Obtenir des identifiants →",
      "Goal": "Objectif",
      "Goal (optional)": "Objectif (facultatif)",
      "Grand Total": "Total général",
      "Hire": "Recruter",
      "Hiring": "Recrutement",
      "Hiring Fee": "Frais de recrutement",
      "History": "Historique",
      "Idle": "Inactif",
      "Import Product": "Importer un produit",
      "Import failed": "Échec de l'import",
      "Improvements": "Améliorations",
      "In Meeting": "En réunion",
      "In Progress": "En cours",
      "In Review": "En revue",
      "In Tokens": "Tokens entrants",
      "In meeting": "En réunion",
      "Interface & agents language": "Langue de l'interface et des agents",
      "Interval": "Intervalle",
      "Interview": "Entretien",
      "Issue deleted": "Ticket supprimé",
      "Issue title": "Titre du ticket",
      "JD — Job Description": "Fiche de poste",
      "KR deleted": "KR supprimé",
      "KR title": "Titre du KR",
      "Key Results": "Résultats clés",
      "LLM": "LLM",
      "LLM Model": "Modèle LLM",
      "Language": "Langue",
      "Level": "Niveau",
      "Link added": "Lien ajouté",
      "Link removed": "Lien supprimé",
      "Link task to product": "Lier la tâche au produit",
      "Links": "Liens",
      "Live Meeting Log": "Journal de réunion en direct",
      "Load failed": "Échec du chargement",
      "Loading": "Chargement",
      "Loading activity": "Chargement de l'activité",
      "Loading files": "Chargement des fichiers",
      "Loading kanban": "Chargement du kanban",
      "Loading minutes": "Chargement du compte rendu",
      "Loading models": "Chargement des modèles",
      "Loading roadmap": "Chargement de la feuille de route",
      "Loading settings": "Chargement des réglages",
      "Local": "Local",
      "Login": "Connexion",
      "Login successful": "Connexion réussie",
      "Major": "Majeur",
      "Match Reasoning": "Justification du choix",
      "Meeting": "Réunion",
      "Meeting Room": "Salle de réunion",
      "Meeting Type": "Type de réunion",
      "Milestoned Issues": "Tickets planifiés",
      "Minor": "Mineur",
      "Mode": "Mode",
      "Model": "Modèle",
      "NEW PRODUCT": "NOUVEAU PRODUIT",
      "Name": "Nom",
      "Needs Improvement": "À améliorer",
      "New": "Nouveau",
      "New Issue": "Nouveau ticket",
      "New Product": "Nouveau produit",
      "New Sprint": "Nouveau sprint",
      "New Template": "Nouveau modèle",
      "Nickname": "Surnom",
      "No 1-on-1 notes yet": "Pas encore de notes d'entretien",
      "No Product": "Aucun produit",
      "No Sprint": "Aucun sprint",
      "No active sessions": "Aucune session active",
      "No activity recorded yet": "Aucune activité pour l'instant",
      "No archived meetings": "Aucune réunion archivée",
      "No background tasks": "Aucune tâche de fond",
      "No cost data": "Aucune donnée de coût",
      "No culture entries yet. CEO can add above": "Aucune valeur pour l'instant. Le CEO peut en ajouter ci-dessus",
      "No data": "Aucune donnée",
      "No ex-employees": "Aucun ancien employé",
      "No info": "Aucune info",
      "No issues": "Aucun ticket",
      "No issues in DONE status to release": "Aucun ticket terminé à publier",
      "No iterations yet": "Aucune itération pour l'instant",
      "No key": "Aucune clé",
      "No links": "Aucun lien",
      "No log entries": "Aucune entrée de journal",
      "No logs": "Aucun journal",
      "No meeting logs": "Aucun journal de réunion",
      "No messages yet": "Aucun message pour l'instant",
      "No new announcements": "Aucune nouvelle annonce",
      "No participants": "Aucun participant",
      "No products or projects": "Aucun produit ni projet",
      "No project history": "Aucun historique de projet",
      "No project records": "Aucun dossier de projet",
      "No projects": "Aucun projet",
      "No projects linked to this product": "Aucun projet lié à ce produit",
      "No retrospective data for this project yet": "Pas encore de rétrospective pour ce projet",
      "No reviews yet": "Aucune évaluation pour l'instant",
      "No scheduled jobs": "Aucune tâche planifiée",
      "No system crons registered": "Aucune tâche système enregistrée",
      "No talents available": "Aucun talent disponible",
      "No tasks": "Aucune tâche",
      "No templates": "Aucun modèle",
      "No tools registered": "Aucun outil enregistré",
      "No work history": "Aucun historique de travail",
      "No work principles yet": "Pas encore de principes de travail",
      "None": "Aucun",
      "Not configured — credentials required": "Non configuré — identifiants requis",
      "Not found": "Introuvable",
      "Not set": "Non défini",
      "Notification": "Notification",
      "OFFLINE": "HORS LIGNE",
      "OK": "OK",
      "OKRs": "OKR",
      "ONBOARDING": "INTÉGRATION",
      "ONE MAN COMPANY": "ONE MAN COMPANY",
      "ONLINE": "EN LIGNE",
      "Objective": "Objectif",
      "Office floor plan": "Plan du bureau",
      "On-demand (no active sessions)": "À la demande (aucune session active)",
      "Onboarding": "Intégration",
      "One Man Company CEO Console": "Console du CEO One Man Company",
      "Or use API Key directly": "Ou utilisez directement une clé API",
      "Original": "Original",
      "Out Tokens": "Tokens sortants",
      "Output": "Résultat",
      "Overhead": "Frais généraux",
      "Overhead Tokens": "Tokens de fonctionnement",
      "Owner": "Responsable",
      "PIP": "Plan d'amélioration",
      "PLANNING": "PLANIFICATION",
      "PROBATION": "PÉRIODE D'ESSAI",
      "PRODUCTS": "PRODUITS",
      "Participants": "Participants",
      "Paste the code first": "Collez d'abord le code",
      "Paste the code from Anthropic": "Collez le code fourni par Anthropic",
      "Patch": "Correctif",
      "Perf": "Perf",
      "Performance Distribution": "Répartition des performances",
      "Perms": "Droits",
      "Personality": "Personnalité",
      "Planned": "Planifié",
      "Polish / Enrich": "Peaufiner / enrichir",
      "Preview": "Aperçu",
      "Product Detail": "Fiche produit",
      "Product detail": "Fiche produit",
      "Product goal / objective": "But / objectif du produit",
      "Product name is required": "Le nom du produit est obligatoire",
      "Product owner": "Responsable produit",
      "Products": "Produits",
      "Project": "Projet",
      "Project History": "Historique des projets",
      "Project Tokens": "Tokens du projet",
      "Project Wall — All Tasks": "Mur des projets — Toutes les tâches",
      "Projects": "Projets",
      "Provider": "Fournisseur",
      "Qualified": "Satisfaisant",
      "Queued": "En file d'attente",
      "REASON": "MOTIF",
      "RECRUIT PARTY (0)": "ÉQUIPE À RECRUTER (0)",
      "RECRUITING": "RECRUTEMENT",
      "ROLE": "RÔLE",
      "Ready": "Prêt",
      "Reconnecting": "Reconnexion",
      "Redirect URI": "URI de redirection",
      "Register Agent": "Enregistrer un agent",
      "Rehire": "Réembaucher",
      "Reject": "Refuser",
      "Release": "Publier",
      "Release Version": "Publier une version",
      "Released": "Publié",
      "Releases": "Versions",
      "Reload Data": "Recharger les données",
      "Reloading": "Rechargement",
      "Remote": "Distant",
      "Remove": "Retirer",
      "Remove link": "Retirer le lien",
      "Reopen": "Rouvrir",
      "Review completed": "Évaluation terminée",
      "Review created": "Évaluation créée",
      "Role": "Rôle",
      "Rooms": "Salles",
      "Running": "En cours",
      "Runs": "Exécutions",
      "SETTINGS": "RÉGLAGES",
      "STOP": "STOP",
      "STOPPING": "ARRÊT EN COURS",
      "Salary": "Salaire",
      "Save": "Enregistrer",
      "Save API key first": "Enregistrez d'abord la clé API",
      "Save Changes": "Enregistrer les modifications",
      "Saved": "Enregistré",
      "Saving": "Enregistrement",
      "Scheduled Jobs": "Tâches planifiées",
      "Search": "Rechercher",
      "Select": "Sélectionner",
      "Select Employee": "Choisir un employé",
      "Select Employee --": "Choisir un employé --",
      "Select a project to start": "Sélectionnez un projet pour commencer",
      "Select a task": "Sélectionnez une tâche",
      "Select a workflow to view": "Sélectionnez un workflow",
      "Select an iteration to view details": "Sélectionnez une itération pour voir le détail",
      "Select at least one issue": "Sélectionnez au moins un ticket",
      "Select issue": "Choisir un ticket",
      "Select model": "Choisir un modèle",
      "Select owner": "Choisir un responsable",
      "Self Evaluation": "Auto-évaluation",
      "Send": "Envoyer",
      "Send a message to this meeting": "Envoyer un message à cette réunion",
      "Sending": "Envoi",
      "Senior Reviews": "Évaluations des seniors",
      "Set": "Définir",
      "Set the company strategy / direction. This is injected into every employee's prompt": "Définissez la stratégie / le cap de l'entreprise. Il est injecté dans le prompt de chaque employé",
      "Settings": "Réglages",
      "Settings changes will trigger a server reload. Use when no tasks are running": "Modifier les réglages recharge le serveur. À faire quand aucune tâche ne tourne",
      "Setup Token (Recommended)": "Jeton d'abonnement (recommandé)",
      "Show more": "Afficher plus",
      "Simple task (Enter to submit)": "Tâche simple (Entrée pour envoyer)",
      "Skills": "Skills",
      "Sprint": "Sprint",
      "Sprint closed": "Sprint clôturé",
      "Sprint created": "Sprint créé",
      "Sprint deleted": "Sprint supprimé",
      "Sprint name": "Nom du sprint",
      "Sprint name is required": "Le nom du sprint est obligatoire",
      "Sprint started": "Sprint lancé",
      "Sprint updated": "Sprint mis à jour",
      "Sprints": "Sprints",
      "Staff Overview": "Vue d'ensemble de l'équipe",
      "Start": "Démarrer",
      "Start 1-on-1": "Démarrer l'entretien",
      "Start Meeting": "Démarrer la réunion",
      "Start Planning": "Démarrer la planification",
      "Status": "Statut",
      "Status unknown": "Statut inconnu",
      "Stop ALL scheduled jobs for this employee": "Arrêter TOUTES les tâches planifiées de cet employé",
      "Stop All": "Tout arrêter",
      "Stop All Tasks": "Arrêter toutes les tâches",
      "Stop this background task": "Arrêter cette tâche de fond",
      "Stopping": "Arrêt en cours",
      "Story pts": "Points",
      "Submit": "Valider",
      "Submitting": "Envoi",
      "Summary": "Résumé",
      "Switching": "Changement",
      "System Crons": "Tâches système",
      "TEAM ROSTER": "ÉQUIPE",
      "TOOL LIST": "OUTILS",
      "TRACE": "TRACE",
      "TRACE VIEWER": "VISIONNEUSE DE TRACES",
      "Talent Market": "Talent Market",
      "Talent Pool": "Vivier de talents",
      "Talent prefers": "Le talent préfère",
      "Target": "Cible",
      "Task Board": "Tableau des tâches",
      "Task Report": "Rapport de tâche",
      "Task Status": "Statut de la tâche",
      "Task Tree": "Arbre des tâches",
      "Team Roster": "Équipe",
      "Template cannot be empty": "Le modèle ne peut pas être vide",
      "Template filename (e.g. my_template.md)": "Nom du fichier modèle (ex. mon_modele.md)",
      "Test": "Tester",
      "Text Size": "Taille du texte",
      "Toggle project list": "Afficher/masquer les projets",
      "Tokens": "Tokens",
      "Tools": "Outils",
      "Trace": "Trace",
      "Type a message": "Écrivez un message",
      "Type message, / for commands (Enter to send)": "Écrivez un message, / pour les commandes (Entrée pour envoyer)",
      "USD": "USD",
      "Unassigned": "Non attribué",
      "Unit": "Unité",
      "Upload Avatar": "Changer l'avatar",
      "Use default --": "Valeur par défaut --",
      "Use default model --": "Modèle par défaut --",
      "Version History": "Historique des versions",
      "Waiting": "En attente",
      "Waiting for code": "En attente du code",
      "Waiting for tasks": "En attente de tâches",
      "Work History": "Historique de travail",
      "Work Principles": "Principes de travail",
      "Working": "Au travail",
      "YOU": "VOUS",
      "ZIP": "ZIP",
      "e.g. We focus on AI-driven creative tools for indie creators": "ex. Nous créons des outils créatifs IA pour les créateurs indépendants"
    },
  };

  function readStored() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }
  function writeStored(value) {
    try { localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* storage unavailable */ }
  }

  let lang = readStored();
  if (!SUPPORTED[lang]) lang = 'en';
  document.documentElement.lang = lang;
  const dict = DICTS[lang] || null;

  // Strings built with variables in app.js: [regex on the English text, French replacement]
  const PATTERNS = {
    fr: [
      [/^(.*\S) Details$/, '$1 — Fiche'],
      [/^Agent family switched to "(.*)"\. Active immediately\.$/, "Famille d'agent changée pour « $1 ». Effectif immédiatement."],
      [/^Connected — (\d+) actions available$/, 'Connecté — $1 actions disponibles'],
      [/^Connection failed: ([\s\S]*)$/, 'Échec de la connexion : $1'],
      [/^MCP connector "(.*)" imported from Claude Code\.$/, 'Connecteur MCP « $1 » repris de Claude Code.'],
      [/^MCP connector (.+)$/, 'Connecteur MCP $1'],
      [/^(.*?) \(([^()]*)\) Work Principles$/, 'Principes de travail — $1 ($2)'],
      [/^(\d+) nodes$/, '$1 nœuds'],
      [/^(\d+) tasks$/, '$1 tâches'],
      [/^(\d+) people$/, '$1 personnes'],
      [/^(\d+) session\(s\)$/, '$1 session(s)'],
      [/^\[(\d+) notes\]$/, '[$1 notes]'],
      [/^\((\d+) notes\)$/, '($1 notes)'],
      [/^(\d+) messages · (\d+) participants · (.*)$/, '$1 messages · $2 participants · $3'],
      [/^(\d+) issues? resolved$/, '$1 ticket(s) résolu(s)'],
      [/^(.*) \((\d+) issues\)$/, '$1 ($2 tickets)'],
      [/^v(\S+) \((\d+) issues\)$/, 'v$1 ($2 tickets)'],
      [/^(\d+)\/(\d+) SLOTS$/, '$1/$2 EMPLACEMENTS'],
      [/^\(suggested: (.*) pts\)$/, '(suggéré : $1 pts)'],
      [/^\.\.\. \((\d+) more lines\)$/, '... ($1 lignes de plus)'],
      [/^Acceptance Criteria \((\d+)\)$/, "Critères d'acceptation ($1)"],
      [/^Acceptance Result: (.*)$/, "Résultat de l'acceptation : $1"],
      [/^EA Review: (.*)$/, "Revue de l'EA : $1"],
      [/^Auto-confirm in (\d+)s$/, 'Confirmation automatique dans $1 s'],
      [/^Current quarter: (.*) tasks$/, 'Trimestre en cours : $1 tâches'],
      [/^Log \((\d+)\)$/, 'Journal ($1)'],
      [/^Team \((\d+)\)$/, 'Équipe ($1)'],
      [/^Timeline \((\d+) entries\):?$/, 'Chronologie ($1 entrées) :'],
      [/^Meeting Minutes: (.*)$/, 'Compte rendu : $1'],
      [/^Login with (.*)$/, 'Se connecter avec $1'],
      [/^RECRUIT PARTY \((\d+)\)$/, 'ÉQUIPE À RECRUTER ($1)'],
      [/^Released v(.*)$/, 'Version v$1 publiée'],
      [/^Sync (.*)$/, 'Synchro $1'],
      [/^Tokens: (.*) in \/ (.*) out$/, 'Tokens : $1 entrants / $2 sortants'],
      [/^Sessions \((\d+)\): (.*)$/, 'Sessions ($1) : $2'],
      [/^Select issues to include in release \((\d+) done\):?$/, 'Tickets à inclure dans la version ($1 terminés) :'],
      [/^(.*) Meeting$/, 'Réunion $1'],
      [/^Interview: (.*)$/, 'Entretien : $1'],
      [/^■ Stopped \((\d+)\)$/, '■ Arrêtées ($1)'],
      [/^(\d+) backend file\(s\) changed: (.*)$/, '$1 fichier(s) serveur modifié(s) : $2'],
      [/^Imported "(.*)" — (\d+) issues, (\d+) KRs$/, 'Import de « $1 » — $2 tickets, $3 KR'],
      [/^Delete (KR|issue|sprint|template|product|project) "(.*)"(?: and ALL its data)?\?(.*)$/, (m, kind, name, rest) =>
        `Supprimer ${({KR: 'le KR', issue: 'le ticket', sprint: 'le sprint', template: 'le modèle', product: 'le produit', project: 'le projet'})[kind]} « ${name} » ?` +
        (rest.includes('cannot be undone') ? ' Toutes ses données seront supprimées, action irréversible.' : '')],
      [/^Stop scheduled job "(.*)"\? Its pending tasks will also be cancelled\.$/, 'Arrêter la tâche planifiée « $1 » ? Ses tâches en attente seront aussi annulées.'],
      [/^Confirm rehire (.*)\? Will restart from Lv\.1\.$/, 'Réembaucher $1 ? Il repartira du niveau 1.'],
      [/^Are you sure you want to dismiss (.*)\?\nReason: ([\s\S]*)\n\nThis cannot be undone\.$/, 'Voulez-vous vraiment licencier $1 ?\nMotif : $2\n\nAction irréversible.'],
      [/^(Add link|Close|Create|Delete|Release|Remove link|Start|Update) failed: (.*)$/, (m, what, err) =>
        `${({'Add link': "Échec de l'ajout du lien", Close: 'Échec de la clôture', Create: 'Échec de la création', Delete: 'Échec de la suppression', Release: 'Échec de la publication', 'Remove link': 'Échec du retrait du lien', Start: 'Échec du démarrage', Update: 'Échec de la mise à jour'})[what]} : ${err}`],
      [/^Failed to (load activity|load kanban|load roadmap|send message|clear history): (.*)$/, (m, what, err) =>
        `${({'load activity': "Impossible de charger l'activité", 'load kanban': 'Impossible de charger le kanban', 'load roadmap': 'Impossible de charger la feuille de route', 'send message': "Impossible d'envoyer le message", 'clear history': "Impossible d'effacer l'historique"})[what]} : ${err}`],
      [/^(Failed|Error|Load failed|Cannot dismiss): (.*)$/, (m, what, err) =>
        `${({Failed: 'Échec', Error: 'Erreur', 'Load failed': 'Échec du chargement', 'Cannot dismiss': 'Licenciement impossible'})[what]} : ${err}`],
    ],
  };
  const patterns = PATTERNS[lang] || [];

  // Split "⚙ Settings:" into prefix "⚙ ", core "Settings", suffix ":"
  const PARTS_RE = /^([^A-Za-z0-9]*)([\s\S]*?)([\s:：….!?]*)$/;

  const has = (key) => Object.prototype.hasOwnProperty.call(dict, key);

  function lookupWord(text) {
    if (has(text)) return dict[text];
    const m = PARTS_RE.exec(text);
    if (!m || !m[2] || !has(m[2])) return null;
    return m[1] + dict[m[2]] + m[3];
  }

  function lookupPattern(text) {
    // Keep a leading icon/emoji out of the match ("🎓 1-on-1 Meeting")
    const lead = (text.match(/^[^A-Za-z0-9[(.■]*/) || [''])[0];
    const body = text.slice(lead.length);
    for (const [re, repl] of patterns) {
      if (re.test(body)) {
        // Translate known words captured by the pattern (e.g. a meeting type)
        const out = typeof repl === 'function'
          ? body.replace(re, repl)
          : body.replace(re, (...args) => repl.replace(/\$(\d)/g, (_, i) => {
              const v = args[Number(i)] ?? '';
              return lookupWord(v) ?? v;
            }));
        return lead + out;
      }
    }
    return null;
  }

  // "Status: active | Owner: COO" → translate each "Label: value" segment
  function lookupLabels(text) {
    if (!/:\s/.test(text)) return null;
    let changed = false;
    const out = text.split(' | ').map((seg) => {
      const m = /^(\s*[^:]{1,40}?)(\s*:\s*)([\s\S]*)$/.exec(seg);
      if (!m) return seg;
      const label = lookupWord(m[1].trim());
      const value = lookupWord(m[3].trim());
      if (label === null && value === null) return seg;
      changed = true;
      return (label ?? m[1].trim()) + ' : ' + (value ?? m[3]);
    }).join(' | ');
    return changed ? out : null;
  }

  function lookup(text) {
    if (!dict || !text) return null;
    return lookupWord(text) ?? lookupPattern(text) ?? lookupLabels(text);
  }

  /** Translate an English UI string; returns the input when no translation exists. */
  function t(text) {
    const out = lookup(text);
    return out === null ? text : out;
  }

  const ATTRS = ['title', 'placeholder', 'aria-label'];
  const SKIP_SELECTOR = 'script, style, textarea, code, pre, .xterm, [data-no-i18n], [contenteditable="true"]';

  function shouldSkip(el) {
    return !el || (el.closest && el.closest(SKIP_SELECTOR));
  }

  function translateText(node) {
    const value = node.nodeValue;
    if (!value || !/[A-Za-z]/.test(value)) return;
    if (shouldSkip(node.parentElement)) return;
    const out = lookup(value.trim());
    if (out === null) return;
    // Keep surrounding whitespace of the original node
    const lead = value.match(/^\s*/)[0];
    const trail = value.match(/\s*$/)[0];
    const next = lead + out + trail;
    if (next !== value) node.nodeValue = next;
  }

  function translateAttrs(el) {
    // Inputs and textareas keep their value untouched, but their placeholder
    // and title are UI text: only an explicit opt-out skips them.
    if (!el || (el.closest && el.closest('[data-no-i18n]'))) return;
    for (const attr of ATTRS) {
      const value = el.getAttribute(attr);
      if (!value) continue;
      const out = lookup(value.trim());
      if (out !== null && out !== value) el.setAttribute(attr, out);
    }
  }

  function translateTree(root) {
    if (!dict || !root) return;
    if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) {
      translateAttrs(root);
      root.querySelectorAll('[title], [placeholder], [aria-label]').forEach(translateAttrs);
      if (shouldSkip(root)) return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) translateText(node);
  }

  function observe() {
    if (!dict) return;
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach(translateTree);
        } else if (mutation.type === 'characterData') {
          translateText(mutation.target);
        } else if (mutation.type === 'attributes') {
          translateAttrs(mutation.target);
        }
      }
    });
    observer.observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRS,
    });
  }

  // Native dialogs used by app.js
  if (dict) {
    const nativeAlert = window.alert.bind(window);
    const nativeConfirm = window.confirm.bind(window);
    const nativePrompt = window.prompt.bind(window);
    window.alert = (msg) => nativeAlert(typeof msg === 'string' ? t(msg) : msg);
    window.confirm = (msg) => nativeConfirm(typeof msg === 'string' ? t(msg) : msg);
    window.prompt = (msg, def) => nativePrompt(typeof msg === 'string' ? t(msg) : msg, def);
  }

  async function fetchServerLanguage() {
    try {
      const res = await fetch('/api/settings/language');
      if (!res.ok) return null;
      const data = await res.json();
      return SUPPORTED[data.language] ? data.language : null;
    } catch (e) {
      return null;
    }
  }

  /** Change the company language (UI + AI employees) and reload the page. */
  async function setLanguage(next) {
    if (!SUPPORTED[next]) return;
    try {
      await fetch('/api/settings/language', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: next, rename_nicknames: true }),
      });
    } catch (e) {
      console.warn('[i18n] could not save language on the server', e);
    }
    writeStored(next);
    window.location.reload();
  }

  function mountSelector() {
    const select = document.getElementById('language-select');
    if (!select) return;
    select.innerHTML = '';
    for (const [code, label] of Object.entries(SUPPORTED)) {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = label;
      if (code === lang) opt.selected = true;
      select.appendChild(opt);
    }
    select.addEventListener('change', () => setLanguage(select.value));
  }

  function init() {
    translateTree(document.body);
    document.title = t(document.title);
    observe();
    mountSelector();
    // The server holds the company language; follow it when it differs.
    fetchServerLanguage().then((serverLang) => {
      if (serverLang && serverLang !== lang) {
        writeStored(serverLang);
        window.location.reload();
      }
    });
  }

  window.I18N = {
    t,
    lang: () => lang,
    locale: () => LOCALES[lang] || 'en-US',
    supported: SUPPORTED,
    setLanguage,
    translateTree,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
