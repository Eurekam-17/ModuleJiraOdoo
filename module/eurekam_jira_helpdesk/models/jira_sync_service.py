from odoo import models


class JiraSyncService(models.AbstractModel):
    _inherit = 'jira.sync.service'

    def _after_issues_synced(self, issues):
        """Link helpdesk tickets whose key was typed before the Jira issue
        reached Odoo."""
        res = super()._after_issues_synced(issues)
        if issues:
            Ticket = self.env['helpdesk.ticket'].sudo().with_context(active_test=False)
            tickets = Ticket.search([('jira_key', 'in', issues.mapped('key')),
                                     ('jira_issue_id', '=', False)])
            if tickets:
                self.env.add_to_compute(Ticket._fields['jira_issue_id'], tickets)
        return res
