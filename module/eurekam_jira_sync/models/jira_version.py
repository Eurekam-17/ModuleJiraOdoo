from odoo import api, fields, models


class JiraVersion(models.Model):
    _name = 'jira.version'
    _description = 'Version Jira'
    _order = 'release_date desc, name desc'

    jira_id = fields.Char(string='Identifiant Jira', required=True, readonly=True, index=True)
    project_id = fields.Many2one(
        'jira.project', string='Projet', readonly=True, index=True, ondelete='restrict')
    name = fields.Char(string='Nom', required=True, readonly=True)
    released = fields.Boolean(
        string='Livrée', readonly=True,
        help="Seul ce drapeau indique une version livrée : une date de livraison "
             "renseignée peut être une date cible future.")
    archived = fields.Boolean(string='Archivée dans Jira', readonly=True)
    release_date = fields.Date(string='Date de livraison', readonly=True)
    start_date = fields.Date(string='Date de début', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    issue_ids = fields.Many2many(
        'jira.issue', 'jira_issue_jira_version_rel', 'version_id', 'issue_id',
        string='Tickets', readonly=True)
    open_issue_count = fields.Integer(
        string='Tickets ouverts', compute='_compute_open_issue_count', store=True)

    _sql_constraints = [
        ('jira_id_unique', 'unique(jira_id)', 'Cette version Jira existe déjà.'),
    ]

    @api.depends('issue_ids.is_open', 'issue_ids.active')
    def _compute_open_issue_count(self):
        for version in self:
            version.open_issue_count = len(
                version.issue_ids.filtered(lambda i: i.is_open and i.active))

    def _compute_display_name(self):
        for version in self:
            version.display_name = (
                '%s %s' % (version.project_id.key, version.name)
                if version.project_id else version.name)
