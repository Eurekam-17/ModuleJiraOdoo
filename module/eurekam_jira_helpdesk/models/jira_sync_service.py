from odoo import models


class JiraSyncService(models.AbstractModel):
    _inherit = 'jira.sync.service'

    def _after_issues_synced(self, issues):
        """Link helpdesk tickets whose key was typed before the Jira issue
        reached Odoo.

        ``modified(['jira_key'])`` (not ``add_to_compute`` on the link alone)
        so that the stored fields depending on the link (status, versions,
        resolution date, delivery delay) are recomputed too."""
        res = super()._after_issues_synced(issues)
        if issues:
            Ticket = self.env['helpdesk.ticket'].sudo().with_context(active_test=False)
            tickets = Ticket.search([('jira_key', 'in', issues.mapped('key')),
                                     ('jira_issue_id', '=', False)])
            if tickets:
                tickets.modified(['jira_key'])
        return res
