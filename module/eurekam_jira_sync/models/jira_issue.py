from odoo import api, fields, models

from .jira_mapping import compute_flags

DEFAULT_BASE_URL = 'https://eurekam.atlassian.net'


class JiraIssue(models.Model):
    """Read-only copy of a Jira issue. Jira is the source of truth: every
    field is read-only in the UI and only the sync service writes (sudo).

    Data minimisation: no description, comments, attachments, nor named
    assignee/reporter. Only ``is_assigned`` is kept."""
    _name = 'jira.issue'
    _description = 'Ticket Jira'
    _order = 'updated_at desc, id desc'
    _rec_name = 'key'
    _rec_names_search = ['key', 'summary']

    key = fields.Char(string='Clé', required=True, readonly=True, index=True)
    jira_id = fields.Char(string='Identifiant Jira', required=True, readonly=True, index=True)
    project_id = fields.Many2one(
        'jira.project', string='Projet', readonly=True, index=True, ondelete='restrict')
    summary = fields.Char(string='Titre', readonly=True)
    issue_type = fields.Char(string='Type', readonly=True, index=True)
    status = fields.Char(string='Statut', readonly=True)
    status_category = fields.Selection(
        [('new', 'À faire'), ('indeterminate', 'En cours'), ('done', 'Terminé')],
        string='Catégorie de statut', readonly=True, index=True)
    priority = fields.Char(string='Priorité', readonly=True)
    resolution = fields.Char(string='Résolution', readonly=True)
    created_at = fields.Datetime(string='Créé le', readonly=True, index=True)
    updated_at = fields.Datetime(string='Mis à jour le', readonly=True)
    resolved_at = fields.Datetime(string='Résolu le', readonly=True, index=True)
    due_date = fields.Date(string='Échéance', readonly=True)
    fix_version_ids = fields.Many2many(
        'jira.version', 'jira_issue_jira_version_rel', 'issue_id', 'version_id',
        string='Versions cibles', readonly=True)
    components = fields.Char(string='Composants', readonly=True)
    labels = fields.Char(string='Étiquettes', readonly=True)
    parent_key = fields.Char(string='Parent', readonly=True)
    epic_key = fields.Char(
        string='Épopée', readonly=True, index=True,
        help="Renseignée seulement si le parent Jira est de type Epic.")
    sprint_id = fields.Many2one(
        'jira.sprint', string='Sprint', readonly=True, index=True, ondelete='set null',
        help="Sprint actif du ticket, sinon le plus récent.")
    is_assigned = fields.Boolean(string='Assigné', readonly=True)

    is_open = fields.Boolean(
        string='Ouvert', compute='_compute_flags', store=True, index=True,
        help="Catégorie de statut différente de « Terminé ». Les tickets "
             "« Rejeté » comptent comme clos.")
    is_declined = fields.Boolean(
        string='Décliné', compute='_compute_flags', store=True,
        help="Clos avec la résolution « Declined » : ce n'est pas une livraison.")
    is_delivered = fields.Boolean(
        string='Livré', compute='_compute_flags', store=True, index=True,
        help="Catégorie « Terminé » et résolution différente de « Declined ».")
    lead_time_days = fields.Integer(
        string='Délai (jours)', compute='_compute_flags', store=True, aggregator='avg',
        help="Jours calendaires entre la création et la résolution, pour les "
             "tickets livrés seulement (vaut 0 sinon : filtrer sur « Livré » "
             "pour les moyennes).")

    url = fields.Char(string='Lien Jira', compute='_compute_url')
    active = fields.Boolean(
        string='Actif', default=True, readonly=True,
        help="Faux si le ticket a disparu de Jira (il n'est jamais supprimé d'Odoo).")
    last_synced_at = fields.Datetime(string='Dernière synchronisation', readonly=True)

    _sql_constraints = [
        ('key_unique', 'unique(key)', 'Un ticket Jira avec cette clé existe déjà.'),
        ('jira_id_unique', 'unique(jira_id)', 'Ce ticket Jira existe déjà.'),
    ]

    @api.depends('status_category', 'resolution', 'created_at', 'resolved_at')
    def _compute_flags(self):
        for issue in self:
            is_open, is_declined, is_delivered, lead_time = compute_flags(
                issue.status_category, issue.resolution, issue.created_at, issue.resolved_at)
            issue.is_open = is_open
            issue.is_declined = is_declined
            issue.is_delivered = is_delivered
            issue.lead_time_days = lead_time or 0

    @api.depends('key')
    def _compute_url(self):
        base_url = (self.env['ir.config_parameter'].sudo().get_param('eurekam_jira.base_url')
                    or DEFAULT_BASE_URL).rstrip('/')
        for issue in self:
            issue.url = '%s/browse/%s' % (base_url, issue.key) if issue.key else False

    def _compute_display_name(self):
        for issue in self:
            issue.display_name = (
                '%s - %s' % (issue.key, issue.summary) if issue.summary else issue.key)

    def action_open_in_jira(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self.url, 'target': 'new'}
