from . import models


def post_init_hook(env):
    """Copy the legacy "Ticket Jira" property into the new field (idempotent)."""
    env['helpdesk.ticket'].sudo()._migrate_jira_property()
