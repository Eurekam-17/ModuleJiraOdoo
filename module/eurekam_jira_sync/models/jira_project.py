from odoo import fields, models


class JiraProject(models.Model):
    _name = 'jira.project'
    _description = 'Projet Jira'
    _order = 'key'
    _rec_name = 'key'

    key = fields.Char(string='Clé', required=True, readonly=True, index=True)
    jira_id = fields.Char(string='Identifiant Jira', readonly=True)
    name = fields.Char(string='Nom', readonly=True)
    sync_enabled = fields.Boolean(
        string='Synchronisé', default=True,
        help="Décocher pour ne plus synchroniser ce projet (les tickets déjà "
             "copiés sont conservés).")
    board_id = fields.Integer(string='Tableau Jira (board)')
    issue_count = fields.Integer(string='Tickets', compute='_compute_issue_count')

    _sql_constraints = [
        ('key_unique', 'unique(key)', 'Un projet Jira avec cette clé existe déjà.'),
    ]

    def _compute_issue_count(self):
        counts = {
            project.id: count
            for project, count in self.env['jira.issue']._read_group(
                [('project_id', 'in', self.ids)], ['project_id'], ['__count'])
        }
        for project in self:
            project.issue_count = counts.get(project.id, 0)

    def _compute_display_name(self):
        for project in self:
            project.display_name = (
                '%s - %s' % (project.key, project.name) if project.name else project.key)
