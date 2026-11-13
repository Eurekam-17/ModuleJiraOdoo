# Eurekam - Synchronisation Jira (`eurekam_jira_sync`)

Copie dans Odoo, **en lecture seule et en sens unique (Jira → Odoo)**, les tickets,
versions et sprints des projets Jira du développement Drugcam (DA, DC, DP).
Les données servent aux tableaux de bord Odoo et au lien avec l'Assistance
(module `eurekam_jira_helpdesk`).

## Règles respectées

- **Rien n'est jamais écrit dans Jira** : le client HTTP n'autorise que `GET`, plus
  `POST` sur l'endpoint de recherche `/rest/api/3/search/jql` (une lecture). Toute
  autre requête est refusée dans le code, et chaque test le vérifie.
- **Rien n'est supprimé dans Odoo** : un ticket disparu de Jira est archivé
  (`active = False`). Seuls les journaux techniques de plus de 90 jours sont purgés.
- **Données minimales** : ni description, ni commentaires, ni pièces jointes, ni nom
  d'assigné ou de rapporteur. Seul le booléen « Assigné » est conservé.
- **Jeton hors du code** : saisi dans les paramètres, visible des seuls
  administrateurs système, retiré de tout message de journal.

## Installation (sandbox uniquement)

1. Le dépôt est intégré au dépôt Odoo.sh du prestataire (branche `sandbox`) : voir le
   `README.md` à la racine du dépôt.
2. Une fois le build vert : **Applications → Mettre à jour la liste des applications**,
   rechercher « Synchronisation Jira », installer. Installer ensuite
   « Lien Assistance / Jira » (`eurekam_jira_helpdesk`).
3. Donner le groupe **« Jira : administrateur »** à la personne qui configure
   (Paramètres → Utilisateurs). Les administrateurs système l'ont automatiquement.
4. Donner **« Jira : lecteur »** aux membres du comité de direction et de la R&D. Les
   utilisateurs de l'Assistance l'ont automatiquement (module pont).

## Paramètres

**Paramètres → Développement Drugcam** (administrateurs système) :

| Paramètre | Clé `ir.config_parameter` | Défaut |
|---|---|---|
| URL Jira | `eurekam_jira.base_url` | `https://eurekam.atlassian.net` |
| Compte technique | `eurekam_jira.user_email` | — |
| Jeton d'API | `eurekam_jira.api_token` | — (à saisir directement ici, jamais par e-mail, chat ou fichier) |
| Expiration du jeton | `eurekam_jira.token_expires_on` | — (date choisie à la création du jeton ; Atlassian ne permet pas de la relire) |
| Projets synchronisés | `eurekam_jira.project_keys` | `DA,DC,DP` |
| Champ sprint / Epic Link | `eurekam_jira.sprint_field`, `eurekam_jira.epic_link_field` | détectés automatiquement |
| Dernière synchronisation | `eurekam_jira.last_sync_at` | renseignée à chaque succès |

Boutons :
- **Tester la connexion** : appelle `/rest/api/3/myself` et affiche le fuseau horaire
  du compte technique (attendu : `Europe/Paris`).
- **Détecter les champs** : lit `/rest/api/3/field` et retient le champ sprint
  (`com.pyxis.greenhopper.jira:gh-sprint`, aujourd'hui `customfield_10020`).
- **Synchroniser maintenant** / **Resynchronisation complète** : lancent la tâche
  planifiée en arrière-plan ; le résultat apparaît dans le journal de synchronisation.

## Fonctionnement

| Tâche planifiée | Fréquence | Effet |
|---|---|---|
| Jira : synchronisation incrémentale | 30 min | Tickets modifiés depuis la dernière synchronisation réussie, moins 10 minutes de recouvrement. La toute première exécution (ou après « Resynchronisation complète ») est une synchronisation complète. |
| Jira : réconciliation hebdomadaire | 1 semaine | Liste toutes les clés Jira et archive les tickets disparus. Purge les journaux de plus de 90 jours. |

- La date du filtre `updated >=` est convertie dans le **fuseau du compte technique**,
  lu à chaque exécution via `/myself` (le JQL interprète les dates dans ce fuseau).
- Les tickets sont rapprochés par **identifiant Jira** (stable même si un ticket change
  de projet), puis par clé. Les sprints sont rapprochés par identifiant, jamais par nom.
- Les écritures sont validées page par page (100 tickets) dans la tâche planifiée.
- Une seule synchronisation à la fois : verrou `SELECT … FOR UPDATE NOWAIT` sur le
  paramètre `eurekam_jira.sync_lock` ; une exécution concurrente se termine sans rien faire.
- Erreurs : 429 → respect de `Retry-After` puis attente exponentielle (5 tentatives) ;
  5xx → 3 tentatives ; 401/403 → arrêt immédiat, journal en échec
  (« jeton invalide ou droits insuffisants »), `last_sync_at` inchangé.
- Réconciliation : par sécurité, rien n'est archivé si Jira ne renvoie aucun ticket, ni
  si plus de la moitié des tickets actifs (et plus de 10) devaient être archivés.

### Indicateurs (conventions du tableau de pilotage Jira)

| Champ | Règle |
|---|---|
| `is_open` (Ouvert) | catégorie de statut différente de « Terminé » ; « Rejeté » compte comme clos |
| `is_declined` (Décliné) | résolution `Declined` |
| `is_delivered` (Livré) | catégorie « Terminé » et non décliné |
| `lead_time_days` (Délai) | jours calendaires création → résolution, **livrés seulement** ; vaut 0 sinon (Odoo stocke 0 pour un entier vide) : filtrer sur « Livré » pour calculer une moyenne |
| `epic_key` (Épopée) | clé du parent seulement si ce parent est de type Epic |
| Version livrée | uniquement `released = vrai` ; une date de livraison seule ne suffit pas |

## Recette sur sandbox (§10 du CLAUDE.md)

Avant : vérifier l'UUID de la sandbox (`python scripts/00_check_environment.py`),
saisir les paramètres avec le compte technique, cliquer « Tester la connexion », puis
« Resynchronisation complète » et attendre un journal « Terminée ».

| Contrôle | JQL de référence dans Jira | Dans Odoo (Tickets Jira) |
|---|---|---|
| Ouverts DA + DC | `project in (DA, DC) AND statusCategory != Done` | filtres « Ouverts » + « Projets DA et DC » |
| Anomalies ouvertes | `… AND issuetype = Bug` | « Anomalies ouvertes » + « Projets DA et DC » |
| Livrés sur 12 mois | `project in (DA, DC) AND resolution = Done AND resolved > "-365d"` | « Livrés sur 12 mois » + « Projets DA et DC » |
| Ouverts depuis plus d'un an | `… AND created < "-365d"` | « Ouverts depuis plus d'un an » + « Projets DA et DC » |
| Versions livrées | versions `released = true` par projet | Versions, filtre « Livrées », regroupé par projet |

Écart toléré : moins de 1 % (1 ou 2 tickets modifiés pendant la synchronisation).
Repères au 2 novembre 2026 : 214 ouverts (DA 80, DC 134), 25 anomalies ouvertes,
525 livrés sur 12 mois, 107 ouverts depuis plus d'un an.

Note : « Livrés sur 12 mois » côté Odoo compte les tickets clos non déclinés, alors que
le JQL ne retient que la résolution `Done`. Si d'autres résolutions existent (ex.
« Won't Do »), un petit écart est attendu : à examiner pendant la recette.

Recette complémentaire :
- modifier le titre d'un ticket de test DP dans Jira : il doit apparaître dans Odoo en
  moins de 35 minutes ;
- vérifier dans l'historique Jira du ticket que rien n'a été écrit par l'intégration ;
- vérifier qu'un utilisateur sans « Jira : lecteur » ne voit pas le menu
  « Développement Drugcam ».

## Tests

```bash
# Local, sans Odoo : client HTTP et règles de conversion (18 tests)
python scripts/run_local_tests.py

# Avec Odoo 18 (local ou build Odoo.sh)
odoo -d test_jira --test-enable --stop-after-init -i eurekam_jira_sync --test-tags eurekam_jira
```

Aucun test n'appelle le vrai Jira : toutes les réponses sont simulées
(`unittest.mock.patch` sur `requests.Session.request`), avec des données fictives
(`tests/fixtures/`).

## Désinstallation

Applications → « Synchronisation Jira » → Désinstaller (désinstaller d'abord
`eurekam_jira_helpdesk`). Les tables `jira_*`, les tâches planifiées, menus et groupes
sont supprimés. Les paramètres saisis à la main (`eurekam_jira.user_email`,
`eurekam_jira.api_token`, `eurekam_jira.last_sync_at`, champs détectés) restent dans
**Paramètres techniques → Paramètres système** : les supprimer, puis **révoquer le jeton**
sur id.atlassian.com. Rien n'est à défaire côté Jira : l'intégration n'y a rien écrit.
