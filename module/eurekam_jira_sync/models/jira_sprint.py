from odoo import fields, models


class JiraSprint(models.Model):
    """Jira sprint. Sprint names are NOT unique at Eurekam (e.g. two
    "Sprint DA 2"): always match by ``jira_id``, never by name."""
    _name = 'jira.sprint'
    _description = 'Sprint Jira'
    _order = 'start_date desc, jira_id desc'

    jira_id = fields.Integer(string='Identifiant Jira', required=True, readonly=True, index=True)
    name = fields.Char(string='Nom', required=True, readonly=True)
    state = fields.Selection(
        [('future', 'À venir'), ('active', 'Actif'), ('closed', 'Terminé')],
        string='État', readonly=True)
    start_date = fields.Datetime(string='Début', readonly=True)
    end_date = fields.Datetime(string='Fin prévue', readonly=True)
    complete_date = fields.Datetime(string='Clôture', readonly=True)
    board_id = fields.Integer(string='Tableau Jira (board)', readonly=True)

    _sql_constraints = [
        ('jira_id_unique', 'unique(jira_id)', 'Ce sprint Jira existe déjà.'),
    ]
