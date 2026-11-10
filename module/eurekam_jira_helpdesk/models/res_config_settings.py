from odoo import models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    def action_migrate_jira_property(self):
        self.env['jira.sync.service']._check_admin()
        log = self.env['helpdesk.ticket'].sudo()._migrate_jira_property()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Migration « Ticket Jira »",
                'message': log.message.split('\n')[0],
                'type': 'success',
                'sticky': True,
            },
        }
