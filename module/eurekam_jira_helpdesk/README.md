# Eurekam - Lien Assistance / Jira (`eurekam_jira_helpdesk`)

Relie les tickets d'assistance Odoo (`helpdesk.ticket`) aux tickets Jira synchronisés
par `eurekam_jira_sync`. Lecture seule côté Jira.

## Ce que le module ajoute

Sur le ticket d'assistance, bloc **« Développement »** (bas du formulaire) :

| Champ | Description |
|---|---|
| Ticket Jira (`jira_key`) | clé saisie, ex. `DC-922`. Une URL Jira collée est convertie en clé ; la saisie est mise en majuscules. Suivi dans le fil de discussion. |
| Ticket Jira lié (`jira_issue_id`) | rempli automatiquement dès que le ticket Jira est synchronisé (y compris si la clé a été saisie avant) |
| Statut Jira, catégorie, version cible, date de résolution, correctif livré | champs stockés, utilisables dans les tableaux de bord |
| Délai de livraison du correctif (`jira_delivery_days`) | jours entre la création du ticket d'assistance et la résolution Jira, si le correctif est livré (0 sinon : filtrer sur « Correctif livré » pour une moyenne) |
| Ouvrir dans Jira | lien cliquable |

Filtres de recherche sur l'Assistance : « Lié à un ticket Jira », « Correctif Jira en
attente », « Correctif livré », « Clé Jira introuvable », regroupement par statut Jira.

Sur le ticket Jira : bouton « Tickets d'assistance » et filtre « Liés à un ticket
d'assistance » (visibles des utilisateurs de l'Assistance seulement).

Droits : le groupe Assistance « Utilisateur » donne automatiquement « Jira : lecteur ».

## Migration de l'ancien champ propriété « Ticket Jira »

La valeur de la propriété (clé `f4ebc7ff7e3532f8`, type texte) est recopiée dans
`jira_key` :
- automatiquement à l'installation (`post_init_hook`) ;
- à la demande : **Paramètres → Développement Drugcam → Assistance → Lancer la migration**.

La migration est idempotente (un ticket déjà renseigné n'est jamais modifié), normalise
la saisie (majuscules, espaces, URL → clé) et signale les valeurs illisibles ou ambiguës
dans le **journal de synchronisation** (mode « Migration « Ticket Jira » »), avec le
numéro du ticket d'assistance. L'ancienne propriété n'est pas effacée.

## Recette (testeur du Service Client)

1. Ouvrir un ticket d'assistance migré : le bloc « Développement » montre le statut et
   la version cible, identiques à Jira.
2. Saisir `dc-xxx` (une clé existante) sur un autre ticket : elle devient `DC-XXX` et le
   lien se remplit immédiatement.
3. Saisir une clé de ticket Jira très récent : le lien se remplit après la
   synchronisation suivante (35 minutes au plus).
4. Consulter le journal de migration et corriger à la main les valeurs illisibles.

## Tests

`tests/test_helpdesk.py` (sandbox Odoo.sh, Assistance requise) : migration idempotente,
normalisation, liaison après synchronisation et mise à jour du statut.

## Désinstallation

Applications → « Lien Assistance / Jira » → Désinstaller. Les champs `jira_*` des
tickets d'assistance sont supprimés ; l'ancienne propriété « Ticket Jira » n'a jamais
été touchée et reste en place.
