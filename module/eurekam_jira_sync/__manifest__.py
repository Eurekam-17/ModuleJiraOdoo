{
    'name': 'Eurekam - Synchronisation Jira',
    'version': '18.0.1.0.6',
    'category': 'Productivity',
    'summary': "Copie en lecture seule des tickets, versions et sprints Jira "
               "du développement Drugcam",
    'description': """
Synchronisation Jira -> Odoo (sens unique)
==========================================

Recopie régulièrement dans Odoo les tickets, versions et sprints des projets
Jira du développement Drugcam (DA, DC, DP), pour les tableaux de bord.

* Lecture seule côté Jira : le module n'écrit jamais dans Jira.
* Données minimales : ni description, ni commentaires, ni pièces jointes,
  ni personnes nommées.
* Aucun enregistrement n'est supprimé : un ticket disparu de Jira est archivé.
""",
    'author': 'Eurekam',
    'website': 'https://www.eurekam.fr',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'views/jira_issue_views.xml',
        'views/jira_version_views.xml',
        'views/jira_sprint_views.xml',
        'views/jira_project_views.xml',
        'views/jira_sync_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
