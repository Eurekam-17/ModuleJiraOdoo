import logging

from odoo import api, fields, models

from odoo.addons.eurekam_jira_sync.models.jira_mapping import normalize_jira_key

_logger = logging.getLogger(__name__)

# Key of the legacy "Ticket Jira" property (type char) in helpdesk.ticket.properties.
JIRA_PROPERTY_KEY = 'f4ebc7ff7e3532f8'


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    jira_key = fields.Char(
        string='Ticket Jira', index=True, tracking=True, copy=False,
        help="Clé du ticket Jira de développement lié, par exemple DC-922. "
             "Une URL Jira collée ici est convertie en clé.")
    jira_issue_id = fields.Many2one(
        'jira.issue', string='Ticket Jira lié', compute='_compute_jira_issue_id',
        store=True, index=True, ondelete='set null')
    jira_status = fields.Char(
        string='Statut Jira', related='jira_issue_id.status', store=True)
    jira_status_category = fields.Selection(
        string='Catégorie de statut Jira', related='jira_issue_id.status_category', store=True)
    jira_fix_versions = fields.Char(
        string='Version cible', compute='_compute_jira_fix_versions', store=True)
    jira_resolved_at = fields.Datetime(
        string='Date de résolution Jira', related='jira_issue_id.resolved_at', store=True)
    jira_is_delivered = fields.Boolean(
        string='Correctif livré', related='jira_issue_id.is_delivered', store=True)
    jira_delivery_days = fields.Integer(
        string='Délai de livraison du correctif (jours)', compute='_compute_jira_delivery_days',
        store=True, aggregator='avg',
        help="Jours calendaires entre la création du ticket d'assistance et la "
             "résolution du ticket Jira, si le correctif est livré (0 sinon : "
             "filtrer sur « Correctif livré » pour les moyennes).")
    jira_url = fields.Char(string='Lien Jira', related='jira_issue_id.url')

    # ------------------------------------------------------------------
    @api.depends('jira_key')
    def _compute_jira_issue_id(self):
        keys = [key for key in set(self.mapped('jira_key')) if key]
        issues = self.env['jira.issue'].sudo().with_context(active_test=False).search(
            [('key', 'in', keys)]) if keys else self.env['jira.issue']
        by_key = {issue.key: issue.id for issue in issues}
        for ticket in self:
            ticket.jira_issue_id = by_key.get(ticket.jira_key, False)

    @api.depends('jira_issue_id.fix_version_ids.name')
    def _compute_jira_fix_versions(self):
        for ticket in self:
            ticket.jira_fix_versions = ', '.join(
                ticket.jira_issue_id.sudo().fix_version_ids.mapped('name')) or False

    @api.depends('create_date', 'jira_issue_id.resolved_at', 'jira_issue_id.is_delivered')
    def _compute_jira_delivery_days(self):
        for ticket in self:
            issue = ticket.jira_issue_id.sudo()
            if issue.is_delivered and issue.resolved_at and ticket.create_date:
                ticket.jira_delivery_days = max((issue.resolved_at - ticket.create_date).days, 0)
            else:
                ticket.jira_delivery_days = 0

    # ------------------------------------------------------------------
    @api.model
    def _normalize_jira_vals(self, vals):
        if vals.get('jira_key'):
            key, _reason = normalize_jira_key(vals['jira_key'])
            # An unreadable value is kept as typed (stripped): it simply
            # links to nothing until corrected.
            vals['jira_key'] = key or str(vals['jira_key']).strip()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_jira_vals(dict(vals)) for vals in vals_list])

    def write(self, vals):
        return super().write(self._normalize_jira_vals(dict(vals)))

    def action_open_jira(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self.jira_url, 'target': 'new'}

    # ------------------------------------------------------------------
    # Migration of the legacy "Ticket Jira" property
    # ------------------------------------------------------------------
    @api.model
    def _migrate_jira_property(self):
        """Copy the legacy property value into ``jira_key``.

        Idempotent: a ticket that already has a ``jira_key`` is never
        overwritten. Values are normalised (upper case, spaces, URL -> key);
        unreadable ones are reported in the sync log, never guessed.
        Returns the created ``jira.sync.log``.
        """
        self.env['helpdesk.ticket'].flush_model(['properties', 'jira_key'])
        self.env.cr.execute(
            """SELECT id, properties ->> %s
                 FROM helpdesk_ticket
                WHERE properties IS NOT NULL
                  AND COALESCE(properties ->> %s, '') NOT IN ('', 'false')""",
            (JIRA_PROPERTY_KEY, JIRA_PROPERTY_KEY))
        rows = self.env.cr.fetchall()
        Ticket = self.sudo().with_context(active_test=False)
        migrated, kept, unreadable = 0, 0, []
        for ticket_id, raw in rows:
            ticket = Ticket.browse(ticket_id)
            if ticket.jira_key:
                kept += 1
                continue
            key, reason = normalize_jira_key(raw)
            if not key:
                unreadable.append("Ticket d'assistance #%s : valeur « %s » illisible (%s)"
                                  % (ticket_id, (raw or '')[:60], reason))
                continue
            ticket.write({'jira_key': key})
            migrated += 1
        lines = ["Migration de la propriété « Ticket Jira » : %s valeur(s) trouvée(s), "
                 "%s copiée(s), %s déjà renseignée(s), %s illisible(s)."
                 % (len(rows), migrated, kept, len(unreadable))] + unreadable
        for line in unreadable:
            _logger.warning("Jira property migration: %s", line)
        now = fields.Datetime.now()
        return self.env['jira.sync.log'].sudo().create({
            'mode': 'migration', 'state': 'done', 'started_at': now, 'ended_at': now,
            'issues_updated': migrated, 'message': '\n'.join(lines),
        })
