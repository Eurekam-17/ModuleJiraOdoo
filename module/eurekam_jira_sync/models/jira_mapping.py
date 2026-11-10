"""Pure conversion helpers: Jira JSON -> plain Python values.

No dependency on the Odoo ORM (unit-testable on its own). The sync service
turns the output of ``issue_to_vals`` into ORM writes.

DATA MINIMISATION (GDPR + internal rule): only the fields listed in
``ISSUE_FIELDS`` are requested from Jira. Description, comments, attachments,
assignee/reporter identities are never requested nor returned here; the
assignee only yields the boolean ``is_assigned``.
"""
import re
from datetime import datetime, timedelta, timezone

ISSUE_FIELDS = (
    'summary', 'issuetype', 'status', 'priority', 'resolution', 'created',
    'updated', 'resolutiondate', 'duedate', 'fixVersions', 'components',
    'labels', 'parent', 'project', 'assignee',
)
STATUS_CATEGORIES = ('new', 'indeterminate', 'done')
SPRINT_STATES = ('future', 'active', 'closed')
DECLINED = 'declined'

_TZ_RE = re.compile(r'([+-])(\d{2}):?(\d{2})$')
_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9_]*-\d+)\b')


# ----------------------------------------------------------------------
# Dates
# ----------------------------------------------------------------------
def parse_jira_datetime(value):
    """Parse a Jira timestamp into a naive UTC datetime (Odoo convention).

    Accepted: ``2024-01-15T10:23:45.123+0100``, ``...+01:00``, ``...Z``,
    with or without milliseconds. Returns None for empty/invalid input.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    offset = timedelta(0)
    if text.endswith('Z'):
        text = text[:-1]
    else:
        match = _TZ_RE.search(text)
        if match:
            sign = 1 if match.group(1) == '+' else -1
            offset = sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
            text = text[:match.start()]
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return (parsed - offset).replace(microsecond=0)
    return None


def parse_jira_date(value):
    """Parse ``YYYY-MM-DD`` (or a timestamp) into a date. None if invalid."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def to_timezone(dt_utc, tz_name):
    """Convert a naive UTC datetime to a naive local datetime in ``tz_name``.

    Falls back to UTC when the time zone is unknown.
    """
    aware = dt_utc.replace(tzinfo=timezone.utc)
    tz = None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001 - tzdata may be missing
            try:
                import pytz
                tz = pytz.timezone(tz_name)
            except Exception:  # noqa: BLE001
                tz = None
    if tz is None:
        return dt_utc
    return aware.astimezone(tz).replace(tzinfo=None)


def format_jql_datetime(dt_utc, tz_name):
    """Format for JQL (``yyyy/MM/dd HH:mm``) in the Jira account's time zone.

    JQL interprets dates in the time zone of the account running the query.
    """
    return to_timezone(dt_utc, tz_name).strftime('%Y/%m/%d %H:%M')


# ----------------------------------------------------------------------
# Issue helpers
# ----------------------------------------------------------------------
def _name(obj):
    return (obj or {}).get('name') or False


def pick_sprint(sprints):
    """Return the issue's current sprint: the active one, else the latest
    by start date. Sprints are matched by id, never by name (names are not
    unique at Eurekam)."""
    sprints = [s for s in (sprints or []) if isinstance(s, dict) and s.get('id') is not None]
    if not sprints:
        return None
    active = [s for s in sprints if s.get('state') == 'active']
    if active:
        return active[-1]
    # Sprints without a start date (future ones) sort first.
    return max(sprints, key=lambda s: (parse_jira_datetime(s.get('startDate')) or datetime.min,
                                       int(s.get('id') or 0)))


def sprint_to_vals(sprint):
    state = sprint.get('state')
    return {
        'jira_id': int(sprint['id']),
        'name': sprint.get('name') or str(sprint['id']),
        'state': state if state in SPRINT_STATES else False,
        'start_date': parse_jira_datetime(sprint.get('startDate')) or False,
        'end_date': parse_jira_datetime(sprint.get('endDate')) or False,
        'complete_date': parse_jira_datetime(sprint.get('completeDate')) or False,
        'board_id': sprint.get('boardId') or False,
    }


def version_to_vals(version):
    description = (version.get('description') or '')[:255]
    return {
        'jira_id': str(version['id']),
        'name': version.get('name') or str(version['id']),
        'released': bool(version.get('released')),
        'archived': bool(version.get('archived')),
        'release_date': parse_jira_date(version.get('releaseDate')) or False,
        'start_date': parse_jira_date(version.get('startDate')) or False,
        'description': description or False,
    }


def issue_to_vals(issue, sprint_field=None):
    """Flatten a Jira issue into plain values.

    Relational data is returned raw under ``_project``, ``_versions`` and
    ``_sprints`` for the service to resolve into record ids.
    """
    fields = issue.get('fields') or {}
    status = fields.get('status') or {}
    category = (status.get('statusCategory') or {}).get('key')
    parent = fields.get('parent') or {}
    parent_type = ((parent.get('fields') or {}).get('issuetype') or {}).get('name')
    sprints = fields.get(sprint_field) if sprint_field else None
    if sprints and not isinstance(sprints, list):
        sprints = [sprints]
    return {
        'key': issue['key'],
        'jira_id': str(issue['id']),
        'summary': fields.get('summary') or False,
        'issue_type': _name(fields.get('issuetype')),
        'status': status.get('name') or False,
        'status_category': category if category in STATUS_CATEGORIES else False,
        'priority': _name(fields.get('priority')),
        'resolution': _name(fields.get('resolution')),
        'created_at': parse_jira_datetime(fields.get('created')) or False,
        'updated_at': parse_jira_datetime(fields.get('updated')) or False,
        'resolved_at': parse_jira_datetime(fields.get('resolutiondate')) or False,
        'due_date': parse_jira_date(fields.get('duedate')) or False,
        'components': ', '.join(c['name'] for c in fields.get('components') or [] if c.get('name')) or False,
        'labels': ', '.join(fields.get('labels') or []) or False,
        'parent_key': parent.get('key') or False,
        'epic_key': parent.get('key') if parent_type == 'Epic' else False,
        'is_assigned': bool(fields.get('assignee')),
        '_project': fields.get('project') or {},
        '_versions': fields.get('fixVersions') or [],
        '_sprints': sprints or [],
    }


# ----------------------------------------------------------------------
# Business rules (single source of truth, also used by the ORM computes)
# ----------------------------------------------------------------------
def compute_flags(status_category, resolution, created_at, resolved_at):
    """Return ``(is_open, is_declined, is_delivered, lead_time_days)``.

    * open = status category is not ``done`` ("Rejeté" counts as closed);
    * a closure with resolution ``Declined`` is not a delivery;
    * lead time = calendar days creation -> resolution, deliveries only.
    """
    is_open = status_category != 'done'
    is_declined = bool(resolution) and resolution.strip().lower() == DECLINED
    is_delivered = status_category == 'done' and not is_declined
    lead_time = False
    if is_delivered and created_at and resolved_at:
        lead_time = max((resolved_at - created_at).days, 0)
    return is_open, is_declined, is_delivered, lead_time


# ----------------------------------------------------------------------
# Helpdesk "Ticket Jira" property normalisation
# ----------------------------------------------------------------------
def normalize_jira_key(value):
    """Normalise a manually typed Jira reference.

    Returns ``(key, None)`` on success, ``(None, reason)`` otherwise.
    Accepts ``dc-922``, `` DC 922 ``, ``DC-922``, and Jira URLs such as
    ``https://eurekam.atlassian.net/browse/DC-922`` or ``...?selectedIssue=DC-922``.
    """
    if value is None or value is False:
        return None, 'vide'
    text = str(value).strip().upper()
    if not text:
        return None, 'vide'
    # Whole value typed as "DC 922", "DC_922" or "DC - 922" -> "DC-922"
    loose = re.fullmatch(r'([A-Z][A-Z0-9]*)\s*[-_ ]\s*(\d+)', text)
    if loose:
        text = '%s-%s' % loose.groups()
    keys = []
    for key in _KEY_RE.findall(text):
        if key not in keys:
            keys.append(key)
    if not keys:
        return None, 'aucune clé Jira reconnue'
    if len(keys) > 1:
        return None, 'plusieurs clés Jira (%s)' % ', '.join(keys)
    return keys[0], None
