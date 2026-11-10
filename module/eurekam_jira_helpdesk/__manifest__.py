{
    'name': 'Eurekam - Lien Assistance / Jira',
    'version': '18.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': "Affiche sur les tickets d'assistance l'état du ticket Jira lié",
    'description': """
Pont Assistance <-> Jira
========================

* Champ « Ticket Jira » (clé, ex. DC-922) sur les tickets d'assistance, relié
  automatiquement au ticket Jira synchronisé.
* Bloc « Développement » : statut, version cible, date de résolution, lien vers Jira.
* Délai entre la demande client et la livraison du correctif.
* Migration des valeurs de l'ancien champ propriété « Ticket Jira ».

Lecture seule côté Jira : rien n'est jamais écrit dans Jira.
""",
    'author': 'Eurekam',
    'website': 'https://www.eurekam.fr',
    'license': 'LGPL-3',
    'depends': ['eurekam_jira_sync', 'helpdesk'],
    'data': [
        'security/security.xml',
        'views/helpdesk_ticket_views.xml',
        'views/jira_issue_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
