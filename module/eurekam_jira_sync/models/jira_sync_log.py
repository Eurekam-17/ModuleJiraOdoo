from datetime import timedelta

from odoo import api, fields, models

LOG_RETENTION_DAYS = 90


class JiraSyncLog(models.Model):
    """Technical log of a synchronisation run. The message never contains
    the API token nor an authorization header (scrubbed before writing)."""
    _name = 'jira.sync.log'
    _description = 'Journal de synchronisation Jira'
    _order = 'started_at desc, id desc'
    _rec_name = 'started_at'

    started_at = fields.Datetime(string='Début', readonly=True, default=fields.Datetime.now)
    ended_at = fields.Datetime(string='Fin', readonly=True)
    mode = fields.Selection(
        [('incremental', 'Incrémentale'), ('full', 'Complète'),
         ('reconcile', 'Réconciliation')],
        string='Mode', readonly=True, required=True)
    state = fields.Selection(
        [('running', 'En cours'), ('done', 'Terminée'), ('failed', 'En échec')],
        string='État', readonly=True, default='running', required=True)
    issues_created = fields.Integer(string='Tickets créés', readonly=True)
    issues_updated = fields.Integer(string='Tickets mis à jour', readonly=True)
    issues_archived = fields.Integer(string='Tickets archivés', readonly=True)
    versions_synced = fields.Integer(string='Versions synchronisées', readonly=True)
    sprints_synced = fields.Integer(string='Sprints synchronisés', readonly=True)
    message = fields.Text(string='Message', readonly=True)
    duration = fields.Float(string='Durée (s)', compute='_compute_duration')

    @api.depends('started_at', 'ended_at')
    def _compute_duration(self):
        for log in self:
            log.duration = (
                (log.ended_at - log.started_at).total_seconds()
                if log.started_at and log.ended_at else 0.0)

    @api.model
    def _purge_old_logs(self):
        """Delete technical logs older than 90 days: the ONLY deletion this
        module ever performs, and it targets technical logs only."""
        now = fields.Datetime.now()
        # A run interrupted by a server restart stays "running": close it.
        self.sudo().search([
            ('state', '=', 'running'), ('started_at', '<', now - timedelta(days=1)),
        ]).write({'state': 'failed', 'ended_at': now,
                  'message': "Synchronisation interrompue (redémarrage du serveur ?)."})
        limit = now - timedelta(days=LOG_RETENTION_DAYS)
        old = self.sudo().search([('started_at', '<', limit)])
        count = len(old)
        old.unlink()
        return count
