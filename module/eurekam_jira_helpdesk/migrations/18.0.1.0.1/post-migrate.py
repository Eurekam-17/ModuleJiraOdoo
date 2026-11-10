"""Recompute the Jira fields of helpdesk tickets linked during a sync by
version 18.0.1.0.0, which left status / versions / dates empty."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tickets = env['helpdesk.ticket'].with_context(active_test=False).search(
        [('jira_key', '!=', False)])
    tickets.modified(['jira_key'])
    env.flush_all()
