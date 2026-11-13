from unittest.mock import patch

from odoo.tests import TransactionCase

from .common import BASE_URL, FAKE_EMAIL, FAKE_TOKEN

LOGGER = 'odoo.addons.eurekam_jira_sync'


class JiraSyncCase(TransactionCase):
    """Base for ORM tests. Every HTTP call is answered by a FakeJira; the
    sync runs without commit (tests never commit)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        for key, value in (('base_url', BASE_URL), ('user_email', FAKE_EMAIL),
                           ('api_token', FAKE_TOKEN), ('project_keys', 'DA,DC,DP'),
                           ('sprint_field', False), ('epic_link_field', False),
                           ('nature_field', False), ('token_expires_on', False),
                           ('last_sync_at', False), ('force_full', False)):
            params.set_param('eurekam_jira.%s' % key, value)
        cls.Service = cls.env['jira.sync.service']
        cls.Issue = cls.env['jira.issue'].with_context(active_test=False)

    def setUp(self):
        super().setUp()
        self.sleeps = []
        patcher = patch('time.sleep', side_effect=self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def param(self, name):
        return self.env['ir.config_parameter'].sudo().get_param('eurekam_jira.%s' % name)

    def set_param(self, name, value):
        self.env['ir.config_parameter'].sudo().set_param('eurekam_jira.%s' % name, value or False)

    def sync(self, fake, mode='full'):
        with patch('requests.Session.request', side_effect=fake):
            log = self.Service.run(mode)
        self.assertFalse(fake.writes(), "The integration must never write to Jira")
        return log

    def issue(self, key):
        return self.Issue.search([('key', '=', key)])
