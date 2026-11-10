from unittest.mock import patch

from odoo.tests import tagged

from .common import (
    FAKE_TOKEN, FakeResponse, load_fixture, make_issue, make_sprint, standard_jira,
)
from .orm_common import LOGGER, JiraSyncCase


@tagged('post_install', '-at_install', 'eurekam_jira')
class TestJiraSync(JiraSyncCase):

    # 1. Pagination -------------------------------------------------------
    def test_01_pagination_three_pages(self):
        pages = [load_fixture('search_page%d.json' % i) for i in (1, 2, 3)]
        fake = standard_jira().set_search(pages)
        log = self.sync(fake, 'full')
        self.assertEqual(log.state, 'done', log.message)
        self.assertEqual(log.mode, 'full')
        self.assertEqual(log.issues_created, 5)
        keys = ['DA-1', 'DA-2', 'DC-1', 'DC-2', 'DP-1']
        self.assertEqual(len(self.Issue.search([('key', 'in', keys)])), 5)
        bodies = fake.search_bodies()
        self.assertEqual(len(bodies), 3)
        self.assertNotIn('updated >=', bodies[0]['jql'])
        self.assertIn('project in ("DA", "DC", "DP")', bodies[0]['jql'])
        self.assertIn('customfield_10020', bodies[0]['fields'])
        self.assertNotIn('*all', bodies[0]['fields'])
        self.assertNotIn('description', bodies[0]['fields'])
        da1 = self.issue('DA-1')
        self.assertEqual(da1.project_id.key, 'DA')
        self.assertEqual(da1.fix_version_ids.jira_id, '20001')
        self.assertEqual(da1.components, 'Interface')
        self.assertEqual(log.versions_synced, 3)
        self.assertTrue(self.param('last_sync_at'))
        self.assertEqual(self.param('sprint_field'), 'customfield_10020')
        self.assertEqual(self.param('epic_link_field'), 'customfield_10014')
        self.assertEqual(self.env['jira.project'].search([('key', '=', 'DC')]).jira_id, '10007')

    # 2. Upsert -------------------------------------------------------------
    def test_02_upsert_same_issue_twice(self):
        first = make_issue('DA-50', 50050, summary='Ancien titre')
        log1 = self.sync(standard_jira().set_search([[first]]))
        self.assertEqual(log1.issues_created, 1)
        second = make_issue('DA-50', 50050, summary='Nouveau titre', status='En cours',
                            category='indeterminate')
        log2 = self.sync(standard_jira().set_search([[first], [second]]))
        issues = self.Issue.search([('jira_id', '=', '50050')])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues.summary, 'Nouveau titre')
        self.assertEqual(issues.status_category, 'indeterminate')
        self.assertEqual((log2.issues_created, log2.issues_updated), (0, 2))

    def test_02b_moved_issue_keeps_record(self):
        """An issue moved to another project changes key but keeps its id."""
        self.sync(standard_jira().set_search([[make_issue('DA-51', 50051)]]))
        record = self.issue('DA-51')
        self.sync(standard_jira().set_search([[make_issue('DC-99', 50051)]]))
        self.assertEqual(record.key, 'DC-99')
        self.assertEqual(record.project_id.key, 'DC')
        self.assertEqual(len(self.Issue.search([('jira_id', '=', '50051')])), 1)

    # Incremental mode ------------------------------------------------------
    def test_03_incremental_jql_overlap_and_time_zone(self):
        self.set_param('last_sync_at', '2026-01-15 10:00:00')  # UTC
        fake = standard_jira().set_search([[make_issue('DA-52', 50052)]])
        log = self.sync(fake, 'incremental')
        self.assertEqual(log.state, 'done', log.message)
        jql = fake.search_bodies()[0]['jql']
        # 10:00 UTC = 11:00 Europe/Paris (account time zone), minus 10 minutes.
        self.assertIn('updated >= "2026/01/15 10:50"', jql)
        self.assertTrue(jql.endswith('ORDER BY updated ASC'))
        self.assertGreater(self.param('last_sync_at'), '2026-01-15 10:00:00')

    def test_03b_cron_first_run_is_full(self):
        fake = standard_jira().set_search([[make_issue('DA-53', 50053)]])
        with patch('requests.Session.request', side_effect=fake):
            log = self.Service._cron_sync()
        self.assertEqual((log.mode, log.state), ('full', 'done'))
        self.set_param('force_full', '1')
        with patch('requests.Session.request', side_effect=fake):
            log = self.Service._cron_sync()
        self.assertEqual(log.mode, 'full')
        self.assertFalse(self.param('force_full'))
        with patch('requests.Session.request', side_effect=fake):
            log = self.Service._cron_sync()
        self.assertEqual(log.mode, 'incremental')

    def test_03c_cron_without_configuration_does_nothing(self):
        self.set_param('api_token', '')
        count = self.env['jira.sync.log'].search_count([])
        self.assertFalse(self.Service._cron_sync())
        self.assertEqual(self.env['jira.sync.log'].search_count([]), count)

    # 5. Sprints ------------------------------------------------------------
    def test_05_sprints_matched_by_id(self):
        s1 = make_sprint(101, 'Sprint DA 2', 'closed', start='2025-01-06T08:00:00.000Z',
                         end='2025-01-20T08:00:00.000Z', complete='2025-01-20T09:00:00.000Z')
        s2 = make_sprint(102, 'Sprint DA 2', 'active', start='2025-03-03T08:00:00.000Z')
        s3 = make_sprint(103, 'Sprint DA 3', 'closed', start='2025-02-03T08:00:00.000Z')
        issue_a = make_issue('DA-54', 50054, sprints=[s1, s2])
        issue_b = make_issue('DA-55', 50055, sprints=[s1, s3])
        log = self.sync(standard_jira().set_search([[issue_a, issue_b]]))
        Sprint = self.env['jira.sprint']
        same_name = Sprint.search([('name', '=', 'Sprint DA 2')])
        self.assertEqual(len(same_name), 2)
        self.assertEqual(self.issue('DA-54').sprint_id.jira_id, 102)  # active one
        self.assertEqual(self.issue('DA-55').sprint_id.jira_id, 103)  # latest start
        self.assertEqual(log.sprints_synced, 3)
        closed = Sprint.search([('jira_id', '=', 101)])
        self.assertEqual(closed.state, 'closed')
        self.assertEqual(str(closed.complete_date), '2025-01-20 09:00:00')

    # 6. Versions -----------------------------------------------------------
    def test_06_versions_released_flag(self):
        open_issue = make_issue('DA-56', 50056, versions=[{'id': '20002', 'name': '1.1.0'}])
        self.sync(standard_jira().set_search([[open_issue]]))
        Version = self.env['jira.version']
        past_unreleased = Version.search([('jira_id', '=', '20002')])
        self.assertFalse(past_unreleased.released)
        self.assertEqual(str(past_unreleased.release_date), '2025-06-01')
        self.assertNotIn(past_unreleased, Version.search([('released', '=', True)]))
        self.assertEqual(Version.search([('jira_id', '=', '20001')]).released, True)
        self.assertEqual(past_unreleased.project_id.key, 'DA')
        self.assertEqual(past_unreleased.open_issue_count, 1)
        done = make_issue('DA-56', 50056, category='done', status='Terminé', resolution='Done',
                          resolved='2025-02-01T10:00:00.000+0100',
                          versions=[{'id': '20002', 'name': '1.1.0'}])
        self.sync(standard_jira().set_search([[done]]))
        self.assertEqual(past_unreleased.open_issue_count, 0)

    # 7. Reconciliation -----------------------------------------------------
    def test_07_reconcile_archives_never_deletes(self):
        issues = [make_issue('DA-%d' % n, 50000 + n) for n in (60, 61, 62)]
        self.sync(standard_jira().set_search([issues]))
        gone = self.issue('DA-62')
        fake = standard_jira().set_search([[{'id': '50060', 'key': 'DA-60'},
                                            {'id': '50061', 'key': 'DA-61'}]])
        log = self.sync(fake, 'reconcile')
        self.assertEqual((log.mode, log.state), ('reconcile', 'done'), log.message)
        self.assertEqual(log.issues_archived, 1)
        self.assertTrue(gone.exists(), "A vanished issue must be archived, not deleted")
        self.assertFalse(gone.active)
        self.assertTrue(self.issue('DA-60').active)
        self.assertEqual(fake.search_bodies()[0]['fields'], ['key'])
        # Back in Jira -> reactivated.
        self.sync(standard_jira().set_search([[{'id': '50060', 'key': 'DA-60'},
                                               {'id': '50061', 'key': 'DA-61'},
                                               {'id': '50062', 'key': 'DA-62'}]]), 'reconcile')
        self.assertTrue(gone.active)

    def test_07b_reconcile_empty_answer_archives_nothing(self):
        self.sync(standard_jira().set_search([[make_issue('DA-63', 50063)]]))
        with self.assertLogs(LOGGER, level='ERROR'):
            log = self.sync(standard_jira().set_search([[]]), 'reconcile')
        self.assertEqual(log.state, 'failed')
        self.assertTrue(self.issue('DA-63').active)

    # 8. Errors -------------------------------------------------------------
    def test_08_429_then_success(self):
        fake = standard_jira().set_search(
            [[make_issue('DA-64', 50064)]], FakeResponse(429, {}, {'Retry-After': '2'}))
        log = self.sync(fake)
        self.assertEqual(log.state, 'done', log.message)
        self.assertTrue(self.issue('DA-64'))
        self.assertEqual(self.sleeps, [2])

    def test_08b_401_fails_and_keeps_last_sync(self):
        self.set_param('last_sync_at', '2026-01-01 00:00:00')
        fake = standard_jira().add('GET', '/rest/api/3/myself', FakeResponse(401, {}))
        fake.set_search([[make_issue('DA-65', 50065)]])
        with self.assertLogs(LOGGER, level='ERROR'):
            log = self.sync(fake, 'incremental')
        self.assertEqual(log.state, 'failed')
        self.assertIn('jeton invalide ou droits insuffisants', log.message)
        self.assertEqual(self.param('last_sync_at'), '2026-01-01 00:00:00')
        self.assertFalse(self.issue('DA-65'))
        self.assertEqual(len(fake.calls), 1, "401 must stop immediately")

    # 9. Secrets ------------------------------------------------------------
    def test_09_token_never_in_log_message_nor_logs(self):
        scenarios = []
        # a) Jira echoes the token in an error message.
        leaky = standard_jira().set_search([[]], FakeResponse(
            400, {'errorMessages': ['Invalid credentials %s' % FAKE_TOKEN]}))
        scenarios.append(leaky)
        # b) 401.
        scenarios.append(standard_jira().add('GET', '/rest/api/3/myself', FakeResponse(401, {})))
        # c) Unexpected error (malformed issue) -> traceback logged.
        scenarios.append(standard_jira().set_search([[{'id': '1', 'fields': {}}]]))
        for fake in scenarios:
            with self.assertLogs(LOGGER, level='DEBUG') as captured:
                log = self.sync(fake)
            self.assertEqual(log.state, 'failed')
            self.assertNotIn(FAKE_TOKEN, log.message or '')
            for line in captured.output:
                self.assertNotIn(FAKE_TOKEN, line)
                self.assertNotIn('Basic ', line)
