from odoo.tests import TransactionCase, tagged

from .cases_pure import ClientCases, MappingCases


@tagged('post_install', '-at_install', 'eurekam_jira')
class TestJiraClient(ClientCases, TransactionCase):
    """HTTP client: pagination, retries, errors, read-only, no secret leak."""


@tagged('post_install', '-at_install', 'eurekam_jira')
class TestJiraMapping(MappingCases, TransactionCase):
    """Jira JSON -> values: dates, epics, sprints, business flags, keys."""
