from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import make_issue, make_parent, standard_jira
from .orm_common import JiraSyncCase


@tagged('post_install', '-at_install', 'eurekam_jira')
class TestJiraRules(JiraSyncCase):

    # 3. Business flags on edge cases ----------------------------------------
    def test_03_flags_edge_cases(self):
        created = '2025-01-01T09:00:00.000+0100'
        resolved = '2025-01-31T08:00:00.000+0100'
        page = [
            make_issue('DA-70', 50070, category='done', status='Rejeté', resolution='Declined',
                       created=created, resolved=resolved),
            make_issue('DA-71', 50071, category='done', status='Terminé', resolution='Done',
                       created=created, resolved=resolved),
            make_issue('DA-72', 50072, category='indeterminate', status='Réouvert',
                       resolution='Done', created=created),
            make_issue('DA-73', 50073, created=created),
        ]
        self.sync(standard_jira().set_search([page]))
        expected = {
            # key: (is_open, is_declined, is_delivered, lead_time_days)
            'DA-70': (False, True, False, 0),
            'DA-71': (False, False, True, 29),
            'DA-72': (True, False, False, 0),
            'DA-73': (True, False, False, 0),
        }
        for key, flags in expected.items():
            issue = self.issue(key)
            self.assertEqual(
                (issue.is_open, issue.is_declined, issue.is_delivered, issue.lead_time_days),
                flags, key)
        # Delivered then reopened in Jira: no longer delivered.
        self.sync(standard_jira().set_search([[make_issue(
            'DA-71', 50071, category='indeterminate', status='Réouvert', created=created)]]))
        issue = self.issue('DA-71')
        self.assertEqual((issue.is_open, issue.is_delivered, issue.lead_time_days),
                         (True, False, 0))

    def test_03b_is_assigned_without_name(self):
        self.sync(standard_jira().set_search([[make_issue('DA-74', 50074, assigned=True),
                                               make_issue('DA-75', 50075)]]))
        self.assertTrue(self.issue('DA-74').is_assigned)
        self.assertFalse(self.issue('DA-75').is_assigned)
        for forbidden in ('assignee', 'assignee_id', 'reporter', 'reporter_id', 'description'):
            self.assertNotIn(forbidden, self.env['jira.issue']._fields)

    # 4. Epics --------------------------------------------------------------
    def test_04_epic_key_only_for_epic_parent(self):
        self.sync(standard_jira().set_search([[
            make_issue('DA-80', 50080, parent=make_parent('DA-1', 'Epic')),
            make_issue('DA-81', 50081, issue_type='Sous-tâche',
                       parent=make_parent('DA-80', 'Story')),
        ]]))
        self.assertEqual(self.issue('DA-80').epic_key, 'DA-1')
        self.assertEqual(self.issue('DA-81').parent_key, 'DA-80')
        self.assertFalse(self.issue('DA-81').epic_key)

    # Read-only in Odoo --------------------------------------------------------
    def test_fields_read_only(self):
        magic = {'id', 'display_name', 'create_uid', 'create_date', 'write_uid', 'write_date'}
        for name, field in self.env['jira.issue']._fields.items():
            if name not in magic:
                self.assertTrue(field.readonly, "jira.issue.%s must be read-only" % name)

    def test_access_rights(self):
        self.sync(standard_jira().set_search([[make_issue('DA-90', 50090)]]))
        issue = self.issue('DA-90')
        reader = new_test_user(self.env, login='jira_reader_test',
                               groups='base.group_user,eurekam_jira_sync.group_jira_reader')
        admin = new_test_user(self.env, login='jira_admin_test',
                              groups='base.group_user,eurekam_jira_sync.group_jira_admin')
        outsider = new_test_user(self.env, login='jira_outsider_test', groups='base.group_user')

        self.assertEqual(issue.with_user(reader).key, 'DA-90')
        for user in (reader, admin):
            with self.assertRaises(AccessError):
                issue.with_user(user).write({'summary': 'modifié'})
            with self.assertRaises(AccessError):
                issue.with_user(user).unlink()
            with self.assertRaises(AccessError):
                self.env['jira.issue'].with_user(user).create(
                    {'key': 'DA-999', 'jira_id': '999'})
        with self.assertRaises(AccessError):
            issue.with_user(outsider).read(['key'])
        with self.assertRaises(AccessError):
            self.env['jira.sync.log'].with_user(reader).search([])
        self.env['jira.sync.log'].with_user(admin).search([])

        root_menu = self.env.ref('eurekam_jira_sync.menu_jira_root')
        visible = self.env['ir.ui.menu'].with_user(outsider).search([('id', '=', root_menu.id)])
        self.assertFalse(visible, "A user without 'Jira : lecteur' must not see the menu")
        visible = self.env['ir.ui.menu'].with_user(reader).search([('id', '=', root_menu.id)])
        self.assertTrue(visible)

    def test_log_purge_only_old_logs(self):
        Log = self.env['jira.sync.log']
        old = Log.create({'mode': 'full', 'state': 'done', 'started_at': '2020-01-01 00:00:00'})
        recent = Log.create({'mode': 'full', 'state': 'done'})
        Log._purge_old_logs()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
