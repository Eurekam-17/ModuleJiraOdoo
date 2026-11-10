# CLAUDE.md — Synchronisation Jira → Odoo (Eurekam)

> Spécification de travail pour Claude Code. Projet : modules Odoo 18 qui recopient dans Odoo,
> en lecture seule, les tickets Jira du développement Drugcam, pour les tableaux de bord et pour
> relier les tickets d'assistance aux corrections logicielles.
> Rédigée le 10 novembre 2026 pour Loïc TAMARELLE (Président, Eurekam). Première cible : la base **sandbox**.

---

## 1. Contexte et objectif

Eurekam développe Drugcam, un logiciel de contrôle par vision des préparations de chimiothérapie en
pharmacie hospitalière. **Drugcam n'est pas un dispositif médical** : ne jamais l'écrire ainsi, ni dans
le code, ni dans les libellés, ni dans la documentation.

Aujourd'hui :
- le développement est suivi dans **Jira Cloud** (`eurekam.atlassian.net`), projets **DA** (Drugcam
  Assist), **DC** (Drugcam Control) et **DP** (idées / projets à arbitrer) ;
- l'assistance client est suivie dans **Odoo 18 Entreprise** (application Assistance, modèle
  `helpdesk.ticket`). Un champ propriété « Ticket Jira » existe sur les tickets, mais il n'est rempli
  que sur 5 tickets et ne donne pas le statut du correctif ;
- les tableaux de bord de direction sont des tableaux de bord Odoo (`spreadsheet.dashboard`) : ils ne
  lisent que des données Odoo.

**Objectif :** copier régulièrement dans Odoo les tickets, versions et sprints Jira (sens unique
Jira → Odoo), pour :
1. construire dans Odoo un tableau de bord « Suivi des développements » (hors périmètre de ce module :
   il sera construit ensuite à partir des données synchronisées) ;
2. afficher sur chaque ticket d'assistance l'état du ticket Jira lié (statut, version cible, date de
   livraison), et mesurer le délai entre la demande client et la livraison du correctif.

## 2. Règles non négociables

1. **Lecture seule côté Jira.** Le module n'écrit jamais dans Jira : pas de création, pas de commentaire,
   pas de transition, pas de modification de version. Utiliser uniquement des requêtes `GET` (et `POST`
   sur l'endpoint de recherche, qui est une lecture). Drugcam est un outil de management de la qualité :
   les éléments de traçabilité Jira ne doivent jamais être modifiés par l'intégration.
2. **Ne jamais supprimer** d'enregistrement Odoo. Un ticket disparu de Jira est archivé (`active = False`).
3. **Données minimales (RGPD et règle interne).**
   - Ne pas stocker la description, les commentaires ni les pièces jointes : ils peuvent contenir des
     données patient ou des secrets techniques.
   - Ne pas stocker l'assigné ni le rapporteur nominativement : pas d'indicateur par personne nommée.
     Seul le booléen `is_assigned` est autorisé.
   - Le titre (`summary`) est stocké, car il est nécessaire pour la lecture.
4. **Secrets hors du code.** Le jeton d'API Atlassian est saisi dans les paramètres Odoo, visible
   seulement des administrateurs système. Ne jamais l'écrire dans le dépôt, les logs ou les tests.
5. **Sandbox d'abord.** Tout développement et toute recette se font sur `eurekam-sandbox.odoo.com`.
   Rien n'est installé en production (`eurekam.odoo.com`) sans validation écrite de Loïc.
6. **Libellés en français** dans l'interface (champs, menus, messages), code et commentaires en anglais.

## 3. Environnement

| Élément | Valeur |
|---|---|
| Odoo | 18.0 Entreprise, hébergé sur **Odoo.sh** (à confirmer par le prestataire Odoo d'Eurekam ; un module Python personnalisé est impossible sur Odoo Online) |
| Bases | production `eurekam.odoo.com` (UUID `96e026e0-4de0-11e8-ae51-020000fbd37d`) ; sandbox `eurekam-sandbox.odoo.com` (rechargée souvent : **vérifier l'UUID** via `ir.config_parameter` `database.uuid` avant toute action) ; la base recette `eurekam-recette.odoo.com` est une autre base, à ne pas confondre |
| Jira | Jira Cloud `https://eurekam.atlassian.net`, cloudId `7d6e6a02-ca13-460a-86c0-940d5c14c43b` |
| Projets Jira | `DA` (id 10006, board 6), `DC` (id 10007, board 7), `DP` |
| Python | 3.12 (Odoo 18) ; bibliothèque `requests` (déjà présente dans Odoo) |

**Point de vigilance Odoo 18 :** dans les vues, les expressions `invisible=`, `readonly=` et
`required=` ne tolèrent plus que des champs déclarés dans la vue. Déclarer chaque champ utilisé, au
besoin avec `invisible="1"`.

## 4. Architecture : deux modules

L'application Assistance (`helpdesk`) fait partie d'Odoo Entreprise : elle n'existe pas dans l'image
Docker communautaire. Pour pouvoir tester l'essentiel en local, le code est séparé en deux :

```
addons/
├── eurekam_jira_sync/          # cœur : dépend de base, mail — testable en local (Odoo Community 18)
└── eurekam_jira_helpdesk/      # pont Assistance : dépend de eurekam_jira_sync + helpdesk — testé sur sandbox
```

### 4.1 `eurekam_jira_sync`

```
eurekam_jira_sync/
├── __manifest__.py             # version "18.0.1.0.0", license "LGPL-3", depends ["base", "mail"]
├── models/
│   ├── jira_client.py          # client HTTP (pur Python, sans ORM) : auth, pagination, 429/5xx
│   ├── jira_project.py         # jira.project
│   ├── jira_version.py         # jira.version
│   ├── jira_sprint.py          # jira.sprint
│   ├── jira_issue.py           # jira.issue
│   ├── jira_sync_log.py        # jira.sync.log
│   ├── jira_sync_service.py    # orchestrateur (AbstractModel jira.sync.service)
│   └── res_config_settings.py  # paramètres
├── data/ir_cron.xml            # synchronisation incrémentale + réconciliation hebdomadaire
├── security/
│   ├── security.xml            # groupes « Jira : lecteur » et « Jira : administrateur »
│   └── ir.model.access.csv
├── views/                      # listes, formulaires, recherche, pivot, graphe, menus, paramètres
└── tests/
    ├── fixtures/               # réponses JSON Jira anonymisées (aucune donnée réelle)
    ├── test_client.py
    ├── test_sync.py
    └── test_rules.py
```

### 4.2 `eurekam_jira_helpdesk`

- Ajoute à `helpdesk.ticket` :
  - `jira_key` (Char, indexé) ;
  - `jira_issue_id` (Many2one `jira.issue`, calculé à partir de `jira_key`, stocké) ;
  - des champs liés stockés pour les tableaux de bord : statut, catégorie de statut, version cible,
    date de résolution.
- Ajoute à `jira.issue` le One2many inverse `helpdesk_ticket_ids` et un compteur.
- Ajoute au formulaire du ticket d'assistance un bloc « Développement » : clé cliquable vers Jira,
  statut, version cible, date de livraison.
- Fournit une **migration** des valeurs du champ propriété « Ticket Jira » (clé de propriété
  `f4ebc7ff7e3532f8` dans `helpdesk.ticket.properties`) vers `jira_key` :
  - forme : une méthode `action_migrate_jira_property()` appelable depuis les paramètres, plus un
    `post_init_hook` ;
  - idempotente : elle ne remplace pas une valeur déjà saisie ;
  - elle normalise la saisie (majuscules, espaces retirés, URL → clé) et signale les valeurs illisibles
    dans le journal.

## 5. Modèle de données

### `jira.project`
`key` (Char, unique), `jira_id` (Char), `name`, `sync_enabled` (Boolean, défaut vrai pour DA, DC, DP),
`board_id` (Integer, optionnel, pour les sprints).

### `jira.version`
`jira_id` (Char, unique), `project_id` (Many2one), `name`, `released` (Boolean),
`archived` (Boolean), `release_date` (Date), `start_date` (Date), `description` (Char, tronquée à 255),
`open_issue_count` (Integer, calculé stocké, recalculé en fin de synchronisation).

### `jira.sprint`
`jira_id` (Integer, unique), `name`, `state` (Selection : future / active / closed), `start_date`,
`end_date`, `complete_date` (Datetime), `board_id` (Integer).
**Règle :** les noms de sprint ne sont pas uniques chez Eurekam (par exemple deux « Sprint DA 2 »).
Toujours rapprocher par `jira_id`, jamais par nom.

### `jira.issue` (cœur)

| Champ | Type | Source Jira | Remarque |
|---|---|---|---|
| `key` | Char, unique, indexé | `key` | ex. `DC-922` |
| `jira_id` | Char, unique | `id` | |
| `project_id` | Many2one `jira.project` | `fields.project` | |
| `summary` | Char | `fields.summary` | |
| `issue_type` | Char, indexé | `fields.issuetype.name` | Bug, Story, Tâche, Epic, Sous-tâche… |
| `status` | Char | `fields.status.name` | |
| `status_category` | Selection (new / indeterminate / done) | `fields.status.statusCategory.key` | |
| `priority` | Char | `fields.priority.name` | |
| `resolution` | Char | `fields.resolution.name` | |
| `created_at` / `updated_at` / `resolved_at` | Datetime (UTC) | `created` / `updated` / `resolutiondate` | |
| `due_date` | Date | `duedate` | |
| `fix_version_ids` | Many2many `jira.version` | `fixVersions` | |
| `components` | Char | `components[].name`, joints par « , » | |
| `labels` | Char | `labels`, joints par « , » | |
| `parent_key` | Char | `parent.key` | |
| `epic_key` | Char | `parent.key` **seulement si** `parent.fields.issuetype.name == "Epic"` | |
| `sprint_id` | Many2one `jira.sprint` | champ sprint (voir §6.3) | dernier sprint (actif sinon le plus récent) |
| `is_assigned` | Boolean | `assignee` non nul | **ne pas stocker le nom** |
| `is_open` | Boolean stocké | `status_category != 'done'` | |
| `is_declined` | Boolean stocké | `resolution == 'Declined'` | |
| `is_delivered` | Boolean stocké | catégorie done **et** non déclinée | |
| `lead_time_days` | Integer stocké | `resolved_at - created_at` en jours pleins | vide si non résolu |
| `url` | Char calculé | `https://eurekam.atlassian.net/browse/<key>` | |
| `active` | Boolean | — | faux si disparu de Jira |
| `last_synced_at` | Datetime | — | |

Tous les champs utiles aux tableaux de bord doivent être **stockés**, faute de quoi ils ne sont pas
regroupables dans un tableau croisé. Les champs ne sont pas modifiables dans l'interface Odoo
(`readonly=True`) : Jira fait foi.

### `jira.sync.log`
`started_at`, `ended_at`, `mode` (incremental / full / reconcile), `state` (running / done / failed),
`issues_created`, `issues_updated`, `issues_archived`, `versions_synced`, `sprints_synced`,
`message` (Text : erreurs résumées, **sans jeton ni en-tête d'authentification**). Purge automatique
des journaux de plus de 90 jours, par le cron : c'est la seule suppression permise, et elle porte sur
des journaux techniques.

## 6. Synchronisation

### 6.1 Authentification et paramètres

Les paramètres se trouvent dans Paramètres > Développement Drugcam. Ils sont réservés au groupe
`base.group_system`.
- `eurekam_jira.base_url` (défaut `https://eurekam.atlassian.net`)
- `eurekam_jira.user_email` : adresse d'un **compte technique** Atlassian, en lecture seule sur DA,
  DC et DP
- `eurekam_jira.api_token` : stocké dans `ir.config_parameter`, champ de paramètres de type mot de
  passe (`password=True`), jamais relu dans un log
- `eurekam_jira.project_keys` (défaut `DA,DC,DP`)
- `eurekam_jira.sprint_field` et `eurekam_jira.epic_link_field` : identifiants de champs
  personnalisés, détectés par le bouton « Détecter les champs » (§6.3)
- `eurekam_jira.last_sync_at` : horodatage de la dernière synchronisation réussie

Authentification : HTTP Basic `email:api_token`, en-tête `Accept: application/json`.

### 6.2 Recherche des tickets

Utiliser l'endpoint de recherche actuel de Jira Cloud : `POST /rest/api/3/search/jql`, avec
pagination par `nextPageToken`. L'ancien `/rest/api/3/search` à pagination `startAt` est obsolète.
**Vérifier ce point dans la documentation Atlassian au moment du développement.**

- `maxResults` : 100.
- `fields` : liste explicite, jamais `*all` : `summary, issuetype, status, priority, resolution,
  created, updated, resolutiondate, duedate, fixVersions, components, labels, parent, project,
  assignee`, plus le champ sprint.
- **Mode incrémental** (cron toutes les 30 minutes) :
  `project in (DA, DC, DP) AND updated >= "<last_sync_at − 10 min au format yyyy/MM/dd HH:mm>" ORDER BY updated ASC`.
  Les 10 minutes de recouvrement absorbent les décalages d'horloge. L'upsert par `key` rend les
  doublons inoffensifs. Attention : le JQL interprète la date dans le **fuseau du compte technique** ;
  le régler sur Europe/Paris ou convertir en conséquence, et le tester.
- **Mode complet** (bouton administrateur, et première installation) : même requête sans le filtre
  `updated`.
- **Réconciliation** (cron hebdomadaire) : liste de toutes les clés existantes (`fields=key`), puis
  archivage des `jira.issue` actifs absents de la réponse. Ne jamais supprimer.
- **Écriture par lots** : traiter page par page, avec un `commit` après chaque page (dans le cron
  seulement, jamais dans les tests). Mettre à jour `last_sync_at` uniquement à la fin d'une
  synchronisation réussie.

### 6.3 Versions, sprints, champs personnalisés

- Versions : `GET /rest/api/3/project/{key}/versions` pour chaque projet, avant les tickets. Upsert
  par `jira_id`.
- Champs personnalisés : `GET /rest/api/3/field`. Le champ sprint est celui dont
  `schema.custom == "com.pyxis.greenhopper.jira:gh-sprint"`. Sur le site Eurekam il s'agit
  aujourd'hui de `customfield_10020`, mais il faut le détecter, pas l'écrire en dur.
- Sprints : la valeur du champ sprint est une liste d'objets `{id, name, state, startDate, endDate,
  completeDate, boardId}`. Upsert de chaque sprint par `id` ; `sprint_id` du ticket = sprint actif
  s'il y en a un, sinon celui de plus grande `startDate`.
- Les story points ne sont pas utilisés chez Eurekam : ne pas les synchroniser.

### 6.4 Robustesse

- Délais d'attente : 10 s pour la connexion, 30 s pour la lecture.
- Réponse 429 : respecter `Retry-After`, puis un backoff exponentiel plafonné à 5 tentatives.
- Réponses 5xx : 3 tentatives avec backoff.
- Réponses 401 et 403 : arrêt immédiat, journal en échec, message clair (« jeton invalide ou droits
  insuffisants »).
- Une seule synchronisation à la fois : verrou via `SELECT … FOR UPDATE NOWAIT` sur la ligne de
  paramètre, ou via `ir.cron` et `_trigger`. Une seconde exécution concurrente se termine sans rien
  faire.
- Le client HTTP (`jira_client.py`) ne dépend pas de l'ORM, ce qui permet de le tester avec des
  réponses simulées.

## 7. Conventions métier (à respecter pour les indicateurs)

Ces règles viennent du tableau de pilotage Jira existant ; les tableaux de bord Odoo devront donner
les mêmes chiffres.

1. **Ouvert** = catégorie de statut différente de done. Les tickets au statut « Rejeté » comptent
   comme clos.
2. **Une clôture avec résolution `Declined` n'est pas une livraison.** D'où `is_declined` et
   `is_delivered` séparés.
3. **Versions livrées** = uniquement `released == True`. Une `release_date` renseignée ne suffit pas :
   elle peut être une date cible future.
4. **Épopée** : ne retenir comme épopée que les parents de type Epic (§5).
5. **Délai** = jours calendaires entre création et résolution, livraisons seulement, hors Declined.

## 8. Sécurité et interface

- Groupes :
  - « Jira : lecteur » : lecture sur `jira.*`. Il est implicitement donné par
    `helpdesk.group_helpdesk_user` (dans le module pont) et à donner aux membres du comité de
    direction et de la R&D.
  - « Jira : administrateur » : paramètres, synchronisation manuelle, journaux. Il implique le lecteur.
- `ir.model.access.csv` : lecture seule pour le lecteur. Pour l'administrateur, écriture sur les
  paramètres et les journaux uniquement, jamais d'écriture manuelle sur `jira.issue`. Les écritures
  du service se font en `sudo()` dans la synchronisation.
- Menu « Développement Drugcam » : Tickets Jira (liste, recherche, pivot, graphe), Versions, Sprints,
  Journal de synchronisation, Configuration.
- Filtres de recherche prêts à l'emploi : Ouverts, Anomalies ouvertes, Livrés sur 12 mois, Sans
  version cible, Ouverts depuis plus d'un an, Liés à un ticket d'assistance (module pont).
- Bouton « Synchroniser maintenant » et « Resynchronisation complète » : groupe administrateur,
  confirmation avant le mode complet.

## 9. Tests

### 9.1 Tests automatiques (`odoo-bin --test-enable`)

Tous les appels HTTP sont simulés avec `unittest.mock.patch` sur la session `requests`. **Aucun test
n'appelle le vrai Jira.** Les fixtures sont des réponses JSON réalistes mais fictives : clés de type
`DA-1`, titres génériques, aucune donnée réelle.

Cas à couvrir au minimum :
1. Pagination sur 3 pages par `nextPageToken` : tous les tickets sont importés.
2. Upsert : un même ticket reçu deux fois n'est créé qu'une fois et prend les dernières valeurs.
3. `is_declined`, `is_delivered`, `is_open`, `lead_time_days` sur des cas limites : clos Declined,
   clos Done, rouvert, non résolu.
4. `epic_key` rempli uniquement si le parent est de type Epic.
5. Sprints : rapprochement par id avec deux sprints de même nom ; choix du sprint actif.
6. Versions : `released` faux avec une date de livraison passée → non livrée.
7. Réconciliation : un ticket absent est archivé, pas supprimé.
8. Erreurs : 429 suivi d'un succès → succès ; 401 → journal en échec, `last_sync_at` inchangé.
9. Le jeton n'apparaît jamais dans `jira.sync.log.message`, ni dans les logs capturés (`assertLogs`).
10. Module pont, sur sandbox : la migration de la propriété « Ticket Jira » est idempotente, et
    `jira_issue_id` se remplit après synchronisation.

### 9.2 Où lancer les tests

- **Local** : `eurekam_jira_sync` seul, avec l'image Docker `odoo:18`, PostgreSQL 16 et une base
  jetable :
  `odoo -d test_jira --test-enable --stop-after-init -i eurekam_jira_sync --without-demo=False`
- **Sandbox Odoo.sh** : les deux modules. Les tests s'exécutent à chaque push sur la branche de
  développement ou de staging, puis la recette manuelle (§10) se fait sur `eurekam-sandbox.odoo.com`.

## 10. Recette sur sandbox (critères d'acceptation)

Avant la recette :
- vérifier l'UUID de la sandbox ;
- saisir les paramètres avec le compte technique ;
- lancer une resynchronisation complète.

Puis comparer avec Jira. Les écarts doivent rester inférieurs à 1 % ; un écart de 1 ou 2 tickets dû
à une modification pendant la synchronisation est acceptable.

| Contrôle | Requête JQL de référence | Odoo |
|---|---|---|
| Tickets ouverts DA + DC | `project in (DA, DC) AND statusCategory != Done` | filtre « Ouverts », projets DA, DC |
| Anomalies ouvertes | `project in (DA, DC) AND statusCategory != Done AND issuetype = Bug` | filtre « Anomalies ouvertes » |
| Livrés sur 12 mois | `project in (DA, DC) AND resolution = Done AND resolved > "-365d"` | `is_delivered` et `resolved_at` sur 365 jours |
| Ouverts depuis plus d'un an | `project in (DA, DC) AND statusCategory != Done AND created < "-365d"` | filtre correspondant |
| Versions livrées | versions `released = true` par projet | `jira.version` `released` |

Ordres de grandeur au 2 novembre 2026, pour se repérer : 214 ouverts (DA 80, DC 134), 25 anomalies
ouvertes, 525 livrés sur 12 mois, 107 ouverts depuis plus d'un an.

Recette complémentaire :
- modifier un ticket dans Jira, par exemple un titre de test sur un ticket de test DP, et le voir
  dans Odoo en moins de 35 minutes ;
- vérifier que rien n'a été écrit dans Jira (historique du ticket inchangé, hormis la modification
  manuelle) ;
- vérifier qu'un utilisateur sans le groupe « Jira : lecteur » ne voit pas le menu.

## 11. Ce que Claude Code doit faire, dans l'ordre

1. Lire ce fichier en entier. Poser ses questions avant de coder si un point est ambigu, en
   particulier : Odoo.sh confirmé ? nom de la branche sandbox ? compte technique créé ?
2. Créer `eurekam_jira_sync` : manifeste, modèles, sécurité, puis client HTTP et tests du client.
3. Écrire le service de synchronisation et ses tests (§9.1, cas 1 à 9) ; faire passer les tests en
   local.
4. Écrire les vues, menus, paramètres et crons. Vérifier l'installation et la désinstallation propres
   sur une base locale vierge.
5. Créer `eurekam_jira_helpdesk` : champs, vue, migration et test 10.
6. Préparer une note de livraison (`README.md` dans chaque module) : installation, paramètres,
   recette (§10), désinstallation.
7. Pousser sur la branche sandbox **seulement** après accord de Loïc ; puis dérouler la recette §10
   avec lui.
8. **Ne pas** préparer de déploiement en production : il fera l'objet d'une validation séparée.

Hors périmètre de cette version :
- tableaux de bord : ils seront construits ensuite, à partir de `jira.issue` ;
- écriture dans Jira ;
- webhooks Jira (la synchronisation planifiée suffit) ;
- synchronisation des commentaires, de la description, des pièces jointes et des personnes.

## 12. Ce que Loïc doit préparer (non technique)

1. **Confirmer avec le prestataire Odoo** que l'hébergement est Odoo.sh. Obtenir l'accès au dépôt
   GitHub lié et le nom de la branche qui alimente `eurekam-sandbox.odoo.com`.
2. **Créer un compte technique Atlassian**, par exemple `jira-odoo@eurekam.fr` :
   - accès en lecture seule aux projets DA, DC et DP ;
   - fuseau horaire Europe/Paris ;
   - générer pour ce compte un **jeton d'API** sur `id.atlassian.com` > Sécurité > Jetons d'API.
3. **Transmettre le jeton** directement dans les paramètres Odoo de la sandbox une fois le module
   installé, jamais par e-mail, chat ou fichier.
4. **Désigner un testeur** côté Service Client, pour la recette du lien ticket d'assistance ↔ Jira.
5. **Décider de la règle de saisie de la clé Jira sur les tickets d'assistance** : qui la saisit, à
   quel moment, et faut-il la rendre obligatoire pour les tickets escaladés en N2 ou plus.
