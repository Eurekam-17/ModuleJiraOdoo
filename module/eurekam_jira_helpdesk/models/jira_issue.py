from odoo import fields, models


class JiraIssue(models.Model):
    _inherit = 'jira.issue'

    # Restricted to helpdesk users: a Jira reader without helpdesk rights
    # (e.g. R&D) must not hit an access error on the issue form.
    helpdesk_ticket_ids = fields.One2many(
        'helpdesk.ticket', 'jira_issue_id', string="Tickets d'assistance", readonly=True,
        groups='helpdesk.group_helpdesk_user')
    helpdesk_ticket_count = fields.Integer(
        string="Nombre de tickets d'assistance", compute='_compute_helpdesk_ticket_count',
        groups='helpdesk.group_helpdesk_user')

    def _compute_helpdesk_ticket_count(self):
        counts = {
            issue.id: count
            for issue, count in self.env['helpdesk.ticket']._read_group(
                [('jira_issue_id', 'in', self.ids)], ['jira_issue_id'], ['__count'])
        }
        for issue in self:
            issue.helpdesk_ticket_count = counts.get(issue.id, 0)

    def action_view_helpdesk_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Tickets d'assistance",
            'res_model': 'helpdesk.ticket',
            'view_mode': 'list,form',
            'domain': [('jira_issue_id', '=', self.id)],
        }
