"""Read-only HTTP client for Jira Cloud.

Pure Python: no dependency on the Odoo ORM, so it can be unit-tested with
mocked ``requests`` responses.

READ-ONLY CONTRACT: this client only issues GET requests, plus POST on the
search endpoint (``/rest/api/3/search/jql``), which is a read. Any other
method or any other POST target is refused by ``_request``. The integration
must never write to Jira (quality-management traceability).

SECRETS: the API token is kept in ``requests.Session.auth`` only. It is never
formatted into an exception message or a log line; ``scrub()`` is applied to
every error text as a second line of defence.
"""
import logging
import re
import time

import requests

_logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_RETRIES_429 = 5
MAX_RETRIES_5XX = 3
BACKOFF_BASE = 2  # seconds: 2, 4, 8, 16...
BACKOFF_CAP = 60

SEARCH_PATH = '/rest/api/3/search/jql'
SPRINT_SCHEMA = 'com.pyxis.greenhopper.jira:gh-sprint'
EPIC_LINK_SCHEMA = 'com.pyxis.greenhopper.jira:gh-epic-link'

# The only POST target allowed: Jira's search endpoint (a read).
_READ_ONLY_POSTS = (SEARCH_PATH,)


class JiraError(Exception):
    """Generic Jira error (network, unexpected status, bad payload)."""


class JiraAuthError(JiraError):
    """401 / 403: invalid token or insufficient rights. Never retried."""


_AUTH_RE = re.compile(r'(?i)(authorization|basic\s+[A-Za-z0-9+/=]{8,})[^\n]*')


def scrub(text, *secrets):
    """Remove secrets and authorization material from a text."""
    text = str(text or '')
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, '***')
    # Defensive: never let an Authorization header / Basic credential through.
    return _AUTH_RE.sub('Authorization: ***', text)


class JiraClient:
    """Minimal read-only Jira Cloud REST client."""

    def __init__(self, base_url, email, api_token, session=None, sleep=None):
        if not base_url or not email or not api_token:
            raise JiraError("Paramètres Jira incomplets (URL, adresse ou jeton).")
        self.base_url = base_url.rstrip('/')
        self._token = api_token
        self._email = email
        self.session = session or requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({'Accept': 'application/json'})
        self._sleep = sleep or time.sleep

    # ------------------------------------------------------------------
    # Low level
    # ------------------------------------------------------------------
    def _scrub(self, text):
        return scrub(text, self._token)

    def _backoff(self, attempt):
        return min(BACKOFF_BASE ** attempt, BACKOFF_CAP)

    def _request(self, method, path, params=None, json=None):
        method = method.upper()
        if method not in ('GET', 'POST'):
            raise JiraError("Méthode HTTP interdite : l'intégration Jira est en lecture seule.")
        if method == 'POST' and path not in _READ_ONLY_POSTS:
            raise JiraError("POST interdit hors de l'endpoint de recherche : lecture seule.")

        url = self.base_url + path
        tries_429 = 0
        tries_5xx = 0
        while True:
            try:
                response = self.session.request(
                    method, url, params=params, json=json,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.RequestException as exc:
                tries_5xx += 1
                if tries_5xx > MAX_RETRIES_5XX:
                    raise JiraError(self._scrub(
                        "Erreur réseau vers Jira (%s) : %s" % (path, exc.__class__.__name__)
                    )) from None
                _logger.warning("Jira: network error on %s, retry %s", path, tries_5xx)
                self._sleep(self._backoff(tries_5xx))
                continue

            status = response.status_code
            if status in (401, 403):
                raise JiraAuthError(
                    "Jira a refusé l'accès (HTTP %s) : jeton invalide ou droits "
                    "insuffisants." % status
                )
            if status == 429:
                tries_429 += 1
                if tries_429 > MAX_RETRIES_429:
                    raise JiraError("Jira : trop de requêtes (HTTP 429), abandon après "
                                    "%s tentatives." % MAX_RETRIES_429)
                wait = self._retry_after(response)
                if wait is None:
                    wait = self._backoff(tries_429)
                _logger.info("Jira: HTTP 429 on %s, waiting %ss (try %s)", path, wait, tries_429)
                self._sleep(wait)
                continue
            if status >= 500:
                tries_5xx += 1
                if tries_5xx > MAX_RETRIES_5XX:
                    raise JiraError("Jira : erreur serveur (HTTP %s) sur %s, abandon après "
                                    "%s tentatives." % (status, path, MAX_RETRIES_5XX))
                _logger.warning("Jira: HTTP %s on %s, retry %s", status, path, tries_5xx)
                self._sleep(self._backoff(tries_5xx))
                continue
            if status >= 400:
                detail = ''
                try:
                    payload = response.json()
                    messages = payload.get('errorMessages') or []
                    detail = '; '.join(str(m) for m in messages)[:500]
                except ValueError:
                    pass
                raise JiraError(self._scrub(
                    "Jira : requête refusée (HTTP %s) sur %s. %s" % (status, path, detail)
                ).strip())
            try:
                return response.json()
            except ValueError:
                raise JiraError("Jira : réponse illisible (JSON attendu) sur %s." % path) from None

    @staticmethod
    def _retry_after(response):
        value = (response.headers or {}).get('Retry-After')
        if value is None:
            return None
        try:
            return max(0, min(int(float(value)), BACKOFF_CAP))
        except (TypeError, ValueError):
            return None

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    def myself(self):
        """Technical account (used to check auth and read its time zone)."""
        return self.get('/rest/api/3/myself')

    def get_fields(self):
        return self.get('/rest/api/3/field')

    def get_project(self, key):
        return self.get('/rest/api/3/project/%s' % key)

    def get_project_versions(self, key):
        return self.get('/rest/api/3/project/%s/versions' % key)

    def detect_custom_fields(self):
        """Return ``(sprint_field_id, epic_link_field_id)``, either may be None."""
        sprint = epic = None
        for field in self.get_fields() or []:
            custom = (field.get('schema') or {}).get('custom')
            if custom == SPRINT_SCHEMA and not sprint:
                sprint = field.get('id')
            elif custom == EPIC_LINK_SCHEMA and not epic:
                epic = field.get('id')
        return sprint, epic

    def search_pages(self, jql, fields, max_results=100):
        """Yield pages (lists of issues) from ``POST /rest/api/3/search/jql``.

        Pagination uses ``nextPageToken`` (the legacy ``startAt`` endpoint is
        deprecated by Atlassian).
        """
        token = None
        seen_tokens = set()
        while True:
            body = {'jql': jql, 'fields': list(fields), 'maxResults': max_results}
            if token:
                body['nextPageToken'] = token
            payload = self._request('POST', SEARCH_PATH, json=body) or {}
            yield payload.get('issues') or []
            token = payload.get('nextPageToken')
            if payload.get('isLast') or not token:
                return
            if token in seen_tokens:  # defensive: never loop forever
                raise JiraError("Jira : pagination incohérente (jeton de page répété).")
            seen_tokens.add(token)
