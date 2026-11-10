from odoo.tests import tagged

from odoo.addons.eurekam_jira_sync.tests.common import make_issue, standard_jira
from odoo.addons.eurekam_jira_sync.tests.orm_common import JiraSyncCase

from ..models.helpdesk_ticket import JIRA_PROPERTY_KEY


@tagged('post_install', '-at_install', 'eurekam_jira')
class TestJiraHelpdesk(JiraSyncCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team = cls.env['helpdesk.team'].create({'name': 'Équipe de test Jira'})
        cls.Ticket = cls.env['helpdesk.ticket']

    def _ticket(self, name, **vals):
        return self.Ticket.create(dict(name=name, team_id=self.team.id, **vals))

    def _set_property(self, ticket, value):
        """Write the legacy property straight in the jsonb column, as Odoo stores it."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE helpdesk_ticket SET properties = jsonb_build_object(%s, %s::text) WHERE id = %s",
            (JIRA_PROPERTY_KEY, value, ticket.id))
        self.env.invalidate_all()

    # 10a. Migration of the "Ticket Jira" property ---------------------------
    def test_10_migration_idempotent(self):
        lower = self._ticket('Ticket A')
        url = self._ticket('Ticket B')
        junk = self._ticket('Ticket C')
        already = self._ticket('Ticket D', jira_key='DC-11')
        self._set_property(lower, ' dc-922 ')
        self._set_property(url, 'https://eurekam.atlassian.net/browse/DA-5')
        self._set_property(junk, 'voir avec la R&D')
        self._set_property(already, 'DC-10')

        log = self.Ticket._migrate_jira_property()
        self.assertEqual(log.mode, 'migration')
        self.assertEqual(lower.jira_key, 'DC-922')
        self.assertEqual(url.jira_key, 'DA-5')
        self.assertFalse(junk.jira_key)
        self.assertEqual(already.jira_key, 'DC-11', "An existing value must never be replaced")
        self.assertIn('#%s' % junk.id, log.message)
        self.assertIn('illisible', log.message)

        # Second run: nothing changes, nothing is overwritten.
        lower.jira_key = 'DC-1'
        log2 = self.Ticket._migrate_jira_property()
        self.assertEqual(lower.jira_key, 'DC-1')
        self.assertEqual(url.jira_key, 'DA-5')
        self.assertEqual(log2.issues_updated, 0)

    def test_10b_key_normalised_on_write(self):
        ticket = self._ticket('Ticket E', jira_key=' https://eurekam.atlassian.net/browse/dc-7 ')
        self.assertEqual(ticket.jira_key, 'DC-7')
        ticket.jira_key = 'da 12'
        self.assertEqual(ticket.jira_key, 'DA-12')

    # 10b. Link filled after synchronisation ----------------------------------
    def test_10c_issue_linked_after_sync(self):
        ticket = self._ticket('Ticket F', jira_key='da-200')
        self.assertFalse(ticket.jira_issue_id)  # issue not synced yet
        done = make_issue('DA-200', 50200, category='done', status='Terminé', resolution='Done',
                          created='2025-01-01T09:00:00.000+0100',
                          resolved='2099-01-01T09:00:00.000+0100',
                          versions=[{'id': '20001', 'name': '1.0.0'}])
        self.sync(standard_jira().set_search([[done]]))
        self.assertEqual(ticket.jira_issue_id.key, 'DA-200')
        self.assertEqual(ticket.jira_status, 'Terminé')
        self.assertEqual(ticket.jira_status_category, 'done')
        self.assertEqual(ticket.jira_fix_versions, '1.0.0')
        self.assertTrue(ticket.jira_is_delivered)
        self.assertGreater(ticket.jira_delivery_days, 0)
        self.assertEqual(ticket.jira_issue_id.helpdesk_ticket_count, 1)

        # Status change in Jira is reflected on the helpdesk ticket.
        reopened = make_issue('DA-200', 50200, category='indeterminate', status='Réouvert')
        self.sync(standard_jira().set_search([[reopened]]))
        self.assertEqual(ticket.jira_status, 'Réouvert')
        self.assertFalse(ticket.jira_is_delivered)
        self.assertEqual(ticket.jira_delivery_days, 0)

    def test_10d_ticket_created_after_sync(self):
        self.sync(standard_jira().set_search([[make_issue('DA-201', 50201)]]))
        ticket = self._ticket('Ticket G', jira_key='DA-201')
        self.assertEqual(ticket.jira_issue_id.key, 'DA-201')
        ticket.jira_key = False
        self.assertFalse(ticket.jira_issue_id)
