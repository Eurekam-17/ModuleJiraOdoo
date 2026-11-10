"""Pure-Python test cases (no ORM): the HTTP client and the mapping rules.

They are mixins, run by ``test_client.py`` under Odoo, and also runnable
without Odoo by ``scripts/run_local_tests.py``. They never call the real Jira.
"""
from datetime import datetime
from unittest.mock import patch

from ..models import jira_client, jira_mapping
from .common import (
    BASE_URL, FAKE_EMAIL, FAKE_TOKEN, SEARCH_PATH, SPRINT_FIELD, FakeJira, FakeResponse,
    load_fixture, make_issue, make_parent, make_sprint,
)


class ClientCases:
    """Cases for ``models/jira_client.py``."""

    def _client(self, fake):
        self.sleeps = []
        self._patcher = patch('requests.Session.request', side_effect=fake)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        return jira_client.JiraClient(BASE_URL, FAKE_EMAIL, FAKE_TOKEN, sleep=self.sleeps.append)

    def test_client_pagination_next_page_token(self):
        pages = [load_fixture('search_page%d.json' % i) for i in (1, 2, 3)]
        fake = FakeJira().set_search(pages)
        client = self._client(fake)
        got = [issue['key'] for page in client.search_pages('project = DA', ['summary'])
               for issue in page]
        self.assertEqual(got, ['DA-1', 'DA-2', 'DC-1', 'DC-2', 'DP-1'])
        bodies = fake.search_bodies()
        self.assertEqual(len(bodies), 3)
        self.assertNotIn('nextPageToken', bodies[0])
        self.assertEqual(bodies[1]['nextPageToken'], 'page-1')
        self.assertEqual(bodies[2]['nextPageToken'], 'page-2')
        self.assertEqual(bodies[0]['maxResults'], 100)
        self.assertNotIn('startAt', bodies[0])  # legacy pagination not used

    def test_client_timeouts_and_headers(self):
        fake = FakeJira().add('GET', '/rest/api/3/myself', {'timeZone': 'Europe/Paris'})
        client = self._client(fake)
        client.myself()
        self.assertEqual(fake.calls[0]['timeout'], (10, 30))
        self.assertEqual(client.session.headers['Accept'], 'application/json')
        self.assertEqual(client.session.auth, (FAKE_EMAIL, FAKE_TOKEN))

    def test_client_429_then_success(self):
        fake = FakeJira().add(
            'GET', '/rest/api/3/myself',
            FakeResponse(429, {}, {'Retry-After': '3'}),
            FakeResponse(200, {'timeZone': 'UTC'}))
        client = self._client(fake)
        self.assertEqual(client.myself()['timeZone'], 'UTC')
        self.assertEqual(self.sleeps, [3])

    def test_client_429_backoff_capped(self):
        fake = FakeJira().add('GET', '/rest/api/3/myself', FakeResponse(429, {}))
        client = self._client(fake)
        with self.assertRaises(jira_client.JiraError):
            client.myself()
        self.assertEqual(len(fake.calls), 6)  # 1 + 5 retries
        self.assertEqual(self.sleeps, [2, 4, 8, 16, 32])

    def test_client_5xx_retries(self):
        fake = FakeJira().add('GET', '/rest/api/3/myself', FakeResponse(503, None),
                              FakeResponse(502, None), FakeResponse(200, {'ok': 1}))
        client = self._client(fake)
        self.assertEqual(client.myself(), {'ok': 1})
        fake = FakeJira().add('GET', '/rest/api/3/myself', FakeResponse(500, None))
        client = self._client(fake)
        with self.assertRaises(jira_client.JiraError):
            client.myself()
        self.assertEqual(len(fake.calls), 4)  # 1 + 3 retries

    def test_client_401_403_stop_immediately(self):
        for status in (401, 403):
            fake = FakeJira().add('GET', '/rest/api/3/myself', FakeResponse(status, {}))
            client = self._client(fake)
            with self.assertRaises(jira_client.JiraAuthError) as ctx:
                client.myself()
            self.assertIn('jeton invalide ou droits insuffisants', str(ctx.exception))
            self.assertEqual(len(fake.calls), 1)

    def test_client_is_read_only(self):
        fake = FakeJira()
        client = self._client(fake)
        for method, path in (('PUT', '/rest/api/3/issue/DA-1'),
                             ('DELETE', '/rest/api/3/issue/DA-1'),
                             ('POST', '/rest/api/3/issue'),
                             ('POST', '/rest/api/3/issue/DA-1/comment'),
                             ('POST', '/rest/api/3/issue/DA-1/transitions')):
            with self.assertRaises(jira_client.JiraError):
                client._request(method, path, json={})
        self.assertEqual(fake.calls, [])

    def test_client_error_messages_never_contain_token(self):
        fake = FakeJira().add('GET', '/rest/api/3/myself', FakeResponse(
            400, {'errorMessages': ['bad auth %s / Authorization: Basic Zm9vOmJhcmJheg==' % FAKE_TOKEN]}))
        client = self._client(fake)
        with self.assertRaises(jira_client.JiraError) as ctx:
            client.myself()
        text = str(ctx.exception)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertNotIn('Zm9vOmJhcmJheg==', text)

    def test_client_detect_custom_fields(self):
        fake = FakeJira().add('GET', '/rest/api/3/field', load_fixture('fields.json'))
        client = self._client(fake)
        self.assertEqual(client.detect_custom_fields(), ('customfield_10020', 'customfield_10014'))

    def test_scrub(self):
        self.assertEqual(jira_client.scrub('a SECRETVALUE b', 'SECRETVALUE'), 'a *** b')
        self.assertNotIn('xyz', jira_client.scrub('Authorization: Basic xyzxyzxyzxyz'))


class MappingCases:
    """Cases for ``models/jira_mapping.py``."""

    def test_parse_datetime_variants(self):
        expected = datetime(2025, 1, 10, 8, 0, 0)
        for value in ('2025-01-10T09:00:00.000+0100', '2025-01-10T09:00:00+01:00',
                      '2025-01-10T08:00:00.000Z', '2025-01-10T08:00:00.123Z'):
            self.assertEqual(jira_mapping.parse_jira_datetime(value), expected, value)
        self.assertIsNone(jira_mapping.parse_jira_datetime(None))
        self.assertIsNone(jira_mapping.parse_jira_datetime('pas une date'))
        self.assertEqual(str(jira_mapping.parse_jira_date('2025-03-01')), '2025-03-01')

    def test_jql_datetime_in_account_time_zone(self):
        winter = jira_mapping.format_jql_datetime(datetime(2026, 1, 15, 10, 0), 'Europe/Paris')
        summer = jira_mapping.format_jql_datetime(datetime(2026, 7, 1, 10, 0), 'Europe/Paris')
        self.assertEqual(winter, '2026/01/15 11:00')
        self.assertEqual(summer, '2026/07/01 12:00')
        self.assertEqual(jira_mapping.format_jql_datetime(datetime(2026, 1, 15, 10, 0), None),
                         '2026/01/15 10:00')

    def test_issue_to_vals_minimal_data(self):
        raw = make_issue('DA-7', 7, assigned=True, labels=('a', 'b'),
                         components=('Interface', 'Détection'))
        raw['fields']['description'] = 'Données patient fictives'
        raw['fields']['reporter'] = {'displayName': 'Personne Fictive'}
        vals = jira_mapping.issue_to_vals(raw, SPRINT_FIELD)
        self.assertTrue(vals['is_assigned'])
        self.assertEqual(vals['labels'], 'a, b')
        self.assertEqual(vals['components'], 'Interface, Détection')
        flat = repr(vals)
        self.assertNotIn('Données patient', flat)
        self.assertNotIn('Personne Fictive', flat)
        self.assertNotIn('opaque-account-id', flat)
        # 'assignee' is requested only to derive the is_assigned boolean.
        for forbidden in ('description', 'comment', 'attachment', 'reporter', '*all'):
            self.assertNotIn(forbidden, jira_mapping.ISSUE_FIELDS)
        self.assertEqual(set(vals) - {'_project', '_versions', '_sprints'}, {
            'key', 'jira_id', 'summary', 'issue_type', 'status', 'status_category',
            'priority', 'resolution', 'created_at', 'updated_at', 'resolved_at', 'due_date',
            'components', 'labels', 'parent_key', 'epic_key', 'is_assigned'})

    def test_epic_key_only_for_epic_parent(self):
        epic = jira_mapping.issue_to_vals(make_issue('DA-2', 2, parent=make_parent('DA-1', 'Epic')))
        story = jira_mapping.issue_to_vals(
            make_issue('DA-3', 3, issue_type='Sous-tâche', parent=make_parent('DA-2', 'Story')))
        orphan = jira_mapping.issue_to_vals(make_issue('DA-4', 4))
        self.assertEqual((epic['parent_key'], epic['epic_key']), ('DA-1', 'DA-1'))
        self.assertEqual((story['parent_key'], story['epic_key']), ('DA-2', False))
        self.assertEqual((orphan['parent_key'], orphan['epic_key']), (False, False))

    def test_pick_sprint(self):
        old = make_sprint(1, 'Sprint DA 2', 'closed', start='2025-01-01T08:00:00.000Z')
        same_name = make_sprint(2, 'Sprint DA 2', 'closed', start='2025-03-01T08:00:00.000Z')
        active = make_sprint(3, 'Sprint DA 3', 'active', start='2025-02-01T08:00:00.000Z')
        future = make_sprint(4, 'Sprint DA 9', 'future')
        self.assertEqual(jira_mapping.pick_sprint([old, active, same_name])['id'], 3)
        self.assertEqual(jira_mapping.pick_sprint([same_name, old, future])['id'], 2)
        self.assertIsNone(jira_mapping.pick_sprint(None))
        self.assertEqual(jira_mapping.pick_sprint([future])['id'], 4)

    def test_compute_flags(self):
        created = datetime(2025, 1, 1, 9, 0)
        resolved = datetime(2025, 1, 31, 8, 0)
        flags = jira_mapping.compute_flags
        self.assertEqual(flags('done', 'Declined', created, resolved), (False, True, False, False))
        self.assertEqual(flags('done', 'Done', created, resolved), (False, False, True, 29))
        # Reopened: back to an open category, resolution may linger.
        self.assertEqual(flags('indeterminate', 'Done', created, resolved),
                         (True, False, False, False))
        self.assertEqual(flags('new', False, created, False), (True, False, False, False))

    def test_normalize_jira_key(self):
        norm = jira_mapping.normalize_jira_key
        self.assertEqual(norm(' dc-922 '), ('DC-922', None))
        self.assertEqual(norm('DC 922'), ('DC-922', None))
        self.assertEqual(norm('da_12'), ('DA-12', None))
        self.assertEqual(norm('https://eurekam.atlassian.net/browse/DC-922'), ('DC-922', None))
        self.assertEqual(
            norm('https://eurekam.atlassian.net/jira/software/projects/DC/boards/7?selectedIssue=DC-15'),
            ('DC-15', None))
        self.assertEqual(norm('DC-922, DC-922'), ('DC-922', None))
        self.assertIsNone(norm('voir avec la R&D')[0])
        self.assertIsNone(norm('DC-1 et DA-2')[0])
        self.assertIsNone(norm(False)[0])
        self.assertIsNone(norm('   ')[0])

    def test_version_released_flag_only(self):
        past_unreleased = jira_mapping.version_to_vals(load_fixture('versions_DA.json')[1])
        self.assertFalse(past_unreleased['released'])
        self.assertEqual(str(past_unreleased['release_date']), '2025-06-01')
        long_text = jira_mapping.version_to_vals({'id': 1, 'name': 'x', 'description': 'y' * 400})
        self.assertEqual(len(long_text['description']), 255)


# Silence "unused import" for helpers re-exported to test modules.
__all__ = ['ClientCases', 'MappingCases', 'SEARCH_PATH']
