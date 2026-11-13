"""Test helpers shared by the ORM tests and the pure-Python tests.

No Odoo import here. NO TEST EVER CALLS THE REAL JIRA: every HTTP call goes
through ``FakeJira``, plugged in place of ``requests.Session.request``.
All data is fictional (keys like ``DA-1``, generic titles).
"""
import copy
import json
import os
from urllib.parse import urlparse

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
BASE_URL = 'https://eurekam.atlassian.net'
SEARCH_PATH = '/rest/api/3/search/jql'
FAKE_TOKEN = 'FAKE-TOKEN-abcdef0123456789'
FAKE_EMAIL = 'compte-technique@example.com'
SPRINT_FIELD = 'customfield_10020'
NATURE_FIELD = 'customfield_10574'


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding='utf-8') as handle:
        return json.load(handle)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError('no JSON')
        return copy.deepcopy(self._payload)


class FakeJira:
    """Callable used as ``side_effect`` of ``requests.Session.request``.

    Routes are queues of responses per ``(METHOD, path)``; the last response
    of a queue is repeated. Every call is recorded in ``self.calls``.
    """

    def __init__(self):
        self.routes = {}
        self.calls = []
        self.search_pages = None
        self.search_queue = []  # optional responses served before the pages

    def add(self, method, path, *responses):
        self.routes[(method.upper(), path)] = [
            r if isinstance(r, FakeResponse) else FakeResponse(200, r) for r in responses
        ]
        return self

    def set_search(self, pages, *before):
        """``pages``: list of lists of issues; ``before``: responses served
        first (e.g. a 429) before the normal paging."""
        self.search_pages = pages
        self.search_queue = list(before)
        return self

    def __call__(self, method, url, params=None, json=None, timeout=None, **kwargs):
        path = urlparse(url).path
        self.calls.append({'method': method.upper(), 'path': path, 'json': copy.deepcopy(json),
                           'params': params, 'timeout': timeout})
        if method.upper() == 'POST' and path == SEARCH_PATH and self.search_pages is not None:
            if self.search_queue:
                return self.search_queue.pop(0)
            return self._search(json or {})
        queue = self.routes.get((method.upper(), path))
        if not queue:
            return FakeResponse(404, {'errorMessages': ['Not found: %s' % path]})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def _search(self, body):
        token = body.get('nextPageToken')
        index = int(token.split('-')[1]) if token else 0
        pages = self.search_pages or [[]]
        is_last = index >= len(pages) - 1
        payload = {'issues': pages[index] if index < len(pages) else [], 'isLast': is_last}
        if not is_last:
            payload['nextPageToken'] = 'page-%d' % (index + 1)
        return FakeResponse(200, payload)

    # Helpers for assertions
    def search_bodies(self):
        return [c['json'] for c in self.calls if c['path'] == SEARCH_PATH]

    def writes(self):
        """Calls that would modify Jira (must always be empty)."""
        return [c for c in self.calls
                if c['method'] not in ('GET', 'POST')
                or (c['method'] == 'POST' and c['path'] != SEARCH_PATH)]


def standard_jira(versions=None):
    """FakeJira answering the non-search endpoints with the fixtures."""
    fake = FakeJira()
    fake.add('GET', '/rest/api/3/myself', load_fixture('myself.json'))
    fake.add('GET', '/rest/api/3/field', load_fixture('fields.json'))
    for key in ('DA', 'DC', 'DP'):
        fake.add('GET', '/rest/api/3/project/%s' % key, load_fixture('project_%s.json' % key))
        fake.add('GET', '/rest/api/3/project/%s/versions' % key,
                 (versions or {}).get(key, load_fixture('versions_%s.json' % key)))
    return fake


def make_sprint(sprint_id, name, state, start=None, end=None, complete=None, board=6):
    sprint = {'id': sprint_id, 'name': name, 'state': state, 'boardId': board}
    if start:
        sprint['startDate'] = start
    if end:
        sprint['endDate'] = end
    if complete:
        sprint['completeDate'] = complete
    return sprint


def make_issue(key, jira_id, summary='Ticket de test', issue_type='Story',
               status='À faire', category='new', resolution=None,
               created='2025-01-10T09:00:00.000+0100', updated='2025-02-01T10:00:00.000+0100',
               resolved=None, versions=(), sprints=None, parent=None, assigned=False,
               priority='Medium', labels=(), components=(), duedate=None, nature=None):
    """Realistic but fictional Jira issue payload."""
    project_key = key.split('-')[0]
    project_ids = {'DA': '10006', 'DC': '10007', 'DP': '10008'}
    fields = {
        'summary': summary,
        'issuetype': {'id': '1', 'name': issue_type},
        'status': {'name': status, 'statusCategory': {'key': category}},
        'priority': {'name': priority} if priority else None,
        'resolution': {'name': resolution} if resolution else None,
        'created': created,
        'updated': updated,
        'resolutiondate': resolved,
        'duedate': duedate,
        'fixVersions': [dict(v) for v in versions],
        'components': [{'name': c} for c in components],
        'labels': list(labels),
        'project': {'id': project_ids.get(project_key, '1'), 'key': project_key,
                    'name': 'Projet %s' % project_key},
        # Opaque id only: the module must never store who is assigned.
        'assignee': {'accountId': 'opaque-account-id'} if assigned else None,
        SPRINT_FIELD: sprints,
        NATURE_FIELD: {'id': '1', 'value': nature} if nature else None,
    }
    if parent:
        fields['parent'] = parent
    return {'id': str(jira_id), 'key': key, 'fields': fields}


def make_parent(key, issue_type):
    return {'id': '9%s' % key.split('-')[1], 'key': key,
            'fields': {'summary': 'Parent', 'issuetype': {'name': issue_type}}}
