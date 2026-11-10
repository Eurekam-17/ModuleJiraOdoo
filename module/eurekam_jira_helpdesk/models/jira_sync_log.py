from odoo import fields, models


class JiraSyncLog(models.Model):
    _inherit = 'jira.sync.log'

    mode = fields.Selection(
        selection_add=[('migration', 'Migration « Ticket Jira »')],
        ondelete={'migration': 'cascade'})
