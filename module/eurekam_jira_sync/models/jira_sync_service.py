"""Jira -> Odoo synchronisation orchestrator (one-way, read-only on Jira).

Modes:
* ``incremental`` (cron every 30 min): issues updated since the last
  successful sync minus a 10-minute overlap;
* ``full`` (admin button, first run): every issue of the synced projects;
* ``reconcile`` (weekly cron): lists every issue key and ARCHIVES the
  Odoo copies that disappeared from Jira. Nothing is ever deleted.
"""
import logging
import re
import threading
import traceback
from contextlib import contextmanager
from datetime import timedelta

import psycopg2

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .jira_client import JiraAuthError, JiraClient, JiraError, scrub
from .jira_mapping import (
    ISSUE_FIELDS, format_jql_datetime, issue_to_vals, pick_sprint, sprint_to_vals,
    token_expiry_status, version_to_vals,
)

_logger = logging.getLogger(__name__)

P = 'eurekam_jira.'
DEFAULT_BASE_URL = 'https://eurekam.atlassian.net'
DEFAULT_PROJECT_KEYS = 'DA,DC,DP'
OVERLAP = timedelta(minutes=10)
PAGE_SIZE = 100
LOCK_PARAM = P + 'sync_lock'
# Reconciliation safety net: refuse to archive more than this share of the
# active issues in one run (e.g. the technical account lost a permission).
MAX_ARCHIVE_RATIO = 0.5
_PROJECT_KEY_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


def _is_testing():
    return bool(getattr(threading.current_thread(), 'testing', False))


class _SyncRun:
    """Per-run state: counters and caches."""

    def __init__(self, mode, started_at):
        self.mode = mode
        self.started_at = started_at
        self.issues_created = 0
        self.issues_updated = 0
        self.issues_archived = 0
        self.version_ids = set()
        self.sprint_ids = set()
        self.warnings = []
        self.projects = {}  # key -> jira.project record

    def log_vals(self):
        return {
            'issues_created': self.issues_created,
            'issues_updated': self.issues_updated,
            'issues_archived': self.issues_archived,
            'versions_synced': len(self.version_ids),
            'sprints_synced': len(self.sprint_ids),
        }


class JiraSyncService(models.AbstractModel):
    _name = 'jira.sync.service'
    _description = 'Service de synchronisation Jira'

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------
    def _param(self, name, default=False):
        return self.env['ir.config_parameter'].sudo().get_param(P + name, default)

    def _set_param(self, name, value):
        # False removes the parameter (its value column is required).
        self.env['ir.config_parameter'].sudo().set_param(P + name, value or False)

    def _project_keys(self):
        raw = self._param('project_keys') or DEFAULT_PROJECT_KEYS
        keys = []
        for key in raw.replace(';', ',').split(','):
            key = key.strip().upper()
            if not key:
                continue
            if not _PROJECT_KEY_RE.match(key):
                raise UserError(_("Clé de projet Jira invalide : %s", key))
            if key not in keys:
                keys.append(key)
        return keys

    def _is_configured(self):
        return bool(self._param('base_url') and self._param('user_email')
                    and self._param('api_token'))

    def _get_client(self):
        if not self._is_configured():
            raise UserError(_(
                "Paramètres Jira incomplets : renseigner l'URL, l'adresse du compte "
                "technique et le jeton d'API (Paramètres > Développement Drugcam)."))
        return JiraClient(
            self._param('base_url') or DEFAULT_BASE_URL,
            self._param('user_email'),
            self._param('api_token'),
        )

    def _commit(self, commit):
        if commit and not _is_testing():
            self.env.cr.commit()  # pylint: disable=invalid-commit

    # ------------------------------------------------------------------
    # Concurrency: a single sync at a time
    # ------------------------------------------------------------------
    @contextmanager
    def _sync_lock(self):
        """Hold ``SELECT ... FOR UPDATE NOWAIT`` on the lock parameter row in a
        separate transaction for the whole run. A concurrent run fails to get
        the row and exits without doing anything. (Skipped under tests: the
        test cursor cannot be shared with a second transaction.)"""
        if _is_testing():
            yield True
            return
        with self.env.registry.cursor() as lock_cr:
            try:
                lock_cr.execute(
                    "SELECT id FROM ir_config_parameter WHERE key = %s FOR UPDATE NOWAIT",
                    (LOCK_PARAM,))
                acquired = bool(lock_cr.fetchone())
                if not acquired:
                    _logger.warning("Jira sync: lock parameter %s is missing", LOCK_PARAM)
            except psycopg2.errors.LockNotAvailable:
                acquired = False
                lock_cr.rollback()
            yield acquired

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    @api.model
    def _cron_sync(self):
        """Cron (every 30 min). Full mode on first run or when requested."""
        if not self._is_configured():
            _logger.info("Jira sync skipped: parameters not configured")
            return False
        mode = 'incremental'
        if self._param('force_full') or not self._param('last_sync_at'):
            mode = 'full'
        log = self.run(mode, commit=True)
        if mode == 'full' and log and log.state == 'done':
            self._set_param('force_full', False)
            self._commit(True)
        return log

    @api.model
    def _cron_reconcile(self):
        """Weekly cron: purge old technical logs, then archive vanished issues."""
        self.env['jira.sync.log']._purge_old_logs()
        self._commit(True)
        if not self._is_configured():
            return False
        return self.run('reconcile', commit=True)

    @api.model
    def run(self, mode='incremental', commit=False):
        """Run one synchronisation. Returns the ``jira.sync.log`` record, or
        False when another run holds the lock / Jira is not configured.

        ``commit`` (cron only, never in tests): commit after each page so a
        long run is not lost and does not hold huge transactions."""
        assert mode in ('incremental', 'full', 'reconcile')
        with self._sync_lock() as acquired:
            if not acquired:
                _logger.info("Jira sync (%s) skipped: another sync is running", mode)
                return False
            return self._run_locked(mode, commit)

    def _run_locked(self, mode, commit):
        Log = self.env['jira.sync.log'].sudo()
        started_at = fields.Datetime.now()
        log = Log.create({'mode': mode, 'state': 'running', 'started_at': started_at})
        self._commit(commit)
        run = _SyncRun(mode, started_at)
        token = self._param('api_token') or ''
        try:
            client = self._get_client()
            account = client.myself() or {}
            self._sync_projects(client, run)
            if not run.projects:
                raise JiraError("Aucun projet Jira à synchroniser.")
            if mode == 'reconcile':
                self._reconcile(client, run, commit)
            else:
                sprint_field, nature_field = self._ensure_custom_fields(client)
                self._sync_versions(client, run)
                self._commit(commit)
                jql = self._build_jql(run, mode, account.get('timeZone'))
                fields_list = list(ISSUE_FIELDS) + [f for f in (sprint_field, nature_field) if f]
                for page in client.search_pages(jql, fields_list, max_results=PAGE_SIZE):
                    self._upsert_issues(page, sprint_field, run, nature_field)
                    self._commit(commit)
                # Only after a fully successful run. The START time is stored
                # so that updates made during the run are fetched next time.
                self._set_param('last_sync_at', fields.Datetime.to_string(started_at))
            self._check_token_expiry(run)
            message = '\n'.join(run.warnings) or False
            log.write(dict(run.log_vals(), state='done', ended_at=fields.Datetime.now(),
                           message=scrub(message, token) if message else False))
            self._commit(commit)
            _logger.info("Jira sync (%s) done: %s", mode, run.log_vals())
            return log
        except Exception as exc:  # noqa: BLE001 - every failure must be logged
            if isinstance(exc, (JiraError, UserError)):
                text = str(exc.args[0]) if exc.args else str(exc)
                _logger.error("Jira sync (%s) failed: %s", mode, scrub(text, token))
            else:
                text = "Erreur inattendue : %s" % exc
                _logger.error("Jira sync (%s) failed:\n%s", mode,
                              scrub(traceback.format_exc(), token))
            if commit and not _is_testing():
                self.env.cr.rollback()
                log = Log.browse(log.id)
            self._check_token_expiry(run)
            details = '\n'.join([text] + run.warnings)
            log.write(dict(run.log_vals(), state='failed', ended_at=fields.Datetime.now(),
                           message=scrub(details, token)))
            self._commit(commit)
            return log

    def _check_token_expiry(self, run):
        """Add a warning to the run when the API token expires soon."""
        alert = token_expiry_status(self._param('token_expires_on'),
                                    fields.Date.context_today(self))[1]
        if alert:
            run.warnings.append(alert)
            _logger.warning("Jira sync: %s", alert)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def _sync_projects(self, client, run):
        Project = self.env['jira.project'].sudo()
        for key in self._project_keys():
            project = Project.search([('key', '=', key)], limit=1)
            if project and not project.sync_enabled:
                continue
            try:
                data = client.get_project(key) or {}
            except JiraAuthError:
                raise
            except JiraError as exc:
                run.warnings.append("Projet %s ignoré : %s" % (key, exc))
                continue
            vals = {'key': key, 'jira_id': str(data.get('id') or ''), 'name': data.get('name')}
            if project:
                project.write(vals)
            else:
                project = Project.create(vals)
            run.projects[key] = project

    def _ensure_custom_fields(self, client):
        """Return ``(sprint_field, nature_field)``: custom field ids detected,
        never hard-coded. Detection runs again while one is still unknown, so
        a field created later in Jira is picked up without any action."""
        sprint_field = self._param('sprint_field')
        nature_field = self._param('nature_field')
        if not sprint_field or not nature_field:
            self._store_custom_fields(client.detect_custom_fields())
            sprint_field = self._param('sprint_field')
            nature_field = self._param('nature_field')
        return sprint_field or False, nature_field or False

    def _store_custom_fields(self, found):
        self._set_param('sprint_field', found.get('sprint'))
        self._set_param('epic_link_field', found.get('epic_link'))
        self._set_param('nature_field', found.get('nature'))

    def _sync_versions(self, client, run):
        Version = self.env['jira.version'].sudo()
        for key, project in run.projects.items():
            versions = client.get_project_versions(key) or []
            existing = {
                v.jira_id: v for v in Version.search(
                    [('jira_id', 'in', [str(v['id']) for v in versions])])
            }
            to_create = []
            for data in versions:
                vals = dict(version_to_vals(data), project_id=project.id)
                record = existing.get(vals['jira_id'])
                if record:
                    record.write(vals)
                else:
                    to_create.append(vals)
                run.version_ids.add(vals['jira_id'])
            if to_create:
                Version.create(to_create)

    def _build_jql(self, run, mode, tz_name):
        keys = ', '.join('"%s"' % key for key in run.projects)
        jql = 'project in (%s)' % keys
        if mode == 'incremental':
            last = fields.Datetime.to_datetime(self._param('last_sync_at'))
            if last:
                since = format_jql_datetime(last - OVERLAP, tz_name)
                jql += ' AND updated >= "%s"' % since
        return jql + ' ORDER BY updated ASC'

    def _resolve_sprints(self, sprint_dicts, run):
        """Upsert sprints by Jira id (never by name). Returns {jira_id: id}."""
        Sprint = self.env['jira.sprint'].sudo()
        by_id = {}
        for data in sprint_dicts:
            by_id[int(data['id'])] = data
        if not by_id:
            return {}
        existing = {s.jira_id: s for s in Sprint.search([('jira_id', 'in', list(by_id))])}
        result = {}
        to_create = []
        for jira_id, data in by_id.items():
            vals = sprint_to_vals(data)
            record = existing.get(jira_id)
            if record:
                record.write(vals)
                result[jira_id] = record.id
            else:
                to_create.append(vals)
            run.sprint_ids.add(jira_id)
        for record in Sprint.create(to_create):
            result[record.jira_id] = record.id
        return result

    def _resolve_versions(self, version_dicts):
        """Map fix versions to records; create any version not yet known
        (e.g. a version of another project). Returns {jira_id: id}."""
        Version = self.env['jira.version'].sudo()
        by_id = {str(v['id']): v for v in version_dicts if v.get('id') is not None}
        if not by_id:
            return {}
        result = {v.jira_id: v.id for v in Version.search([('jira_id', 'in', list(by_id))])}
        missing = [version_to_vals(data) for jid, data in by_id.items() if jid not in result]
        for record in Version.create(missing):
            result[record.jira_id] = record.id
        return result

    def _resolve_project(self, data, run):
        key = (data or {}).get('key')
        if not key:
            return False
        if key in run.projects:
            return run.projects[key].id
        Project = self.env['jira.project'].sudo()
        project = Project.search([('key', '=', key)], limit=1) or Project.create(
            {'key': key, 'jira_id': str(data.get('id') or ''), 'name': data.get('name')})
        run.projects[key] = project
        return project.id

    def _upsert_issues(self, page, sprint_field, run, nature_field=False):
        """Upsert one page of issues, matched by Jira id (stable even when an
        issue moves to another project), then by key."""
        if not page:
            return self.env['jira.issue']
        Issue = self.env['jira.issue'].sudo().with_context(active_test=False)
        rows = {}
        for raw in page:
            vals = issue_to_vals(raw, sprint_field, nature_field)
            rows[vals['jira_id']] = vals  # last occurrence wins
        rows = list(rows.values())

        all_sprints = [s for vals in rows for s in vals['_sprints']
                       if isinstance(s, dict) and s.get('id') is not None]
        sprint_map = self._resolve_sprints(all_sprints, run)
        version_map = self._resolve_versions([v for vals in rows for v in vals['_versions']])

        existing = Issue.search(['|', ('jira_id', 'in', [r['jira_id'] for r in rows]),
                                 ('key', 'in', [r['key'] for r in rows])])
        by_jira_id = {r.jira_id: r for r in existing}
        by_key = {r.key: r for r in existing}

        now = fields.Datetime.now()
        touched = Issue.browse()
        to_create = []
        for vals in rows:
            project = vals.pop('_project')
            versions = vals.pop('_versions')
            sprints = vals.pop('_sprints')
            picked = pick_sprint(sprints)
            vals.update({
                'project_id': self._resolve_project(project, run),
                'fix_version_ids': [Command.set([
                    version_map[str(v['id'])] for v in versions
                    if str(v.get('id')) in version_map])],
                'sprint_id': sprint_map.get(int(picked['id'])) if picked else False,
                'active': True,
                'last_synced_at': now,
            })
            record = by_jira_id.get(vals['jira_id']) or by_key.get(vals['key'])
            if record:
                record.write(vals)
                touched |= record
                run.issues_updated += 1
            else:
                to_create.append(vals)
        if to_create:
            touched |= Issue.create(to_create)
            run.issues_created += len(to_create)
        self._after_issues_synced(touched)
        return touched

    def _after_issues_synced(self, issues):
        """Hook for extension modules (e.g. link helpdesk tickets)."""
        return True

    def _reconcile(self, client, run, commit):
        """Archive (never delete) active issues that no longer exist in Jira."""
        Issue = self.env['jira.issue'].sudo().with_context(active_test=False)
        keys = ', '.join('"%s"' % key for key in run.projects)
        seen = set()
        for page in client.search_pages('project in (%s)' % keys, ['key'],
                                        max_results=PAGE_SIZE):
            seen.update(str(issue['id']) for issue in page)
        project_ids = [p.id for p in run.projects.values()]
        active = Issue.search([('project_id', 'in', project_ids), ('active', '=', True)])
        if not seen and active:
            raise JiraError("Jira n'a renvoyé aucun ticket : réconciliation annulée "
                            "par sécurité, rien n'a été archivé.")
        to_archive = active.filtered(lambda i: i.jira_id not in seen)
        if active and len(to_archive) > MAX_ARCHIVE_RATIO * len(active) and len(to_archive) > 10:
            raise JiraError(
                "Réconciliation annulée par sécurité : %s tickets sur %s auraient été "
                "archivés. Vérifier les droits du compte technique Jira."
                % (len(to_archive), len(active)))
        if to_archive:
            to_archive.write({'active': False, 'last_synced_at': fields.Datetime.now()})
            run.issues_archived = len(to_archive)
        # Issues archived earlier that are back in Jira.
        revived = Issue.search([('project_id', 'in', project_ids), ('active', '=', False),
                                ('jira_id', 'in', list(seen))])
        if revived:
            revived.write({'active': True})
            run.issues_updated += len(revived)
        self._commit(commit)

    # ------------------------------------------------------------------
    # Admin actions (called from the settings page)
    # ------------------------------------------------------------------
    def _notify(self, message, kind='success', title=None):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title or _("Jira"), 'message': message,
                       'type': kind, 'sticky': kind != 'success'},
        }

    def _check_admin(self):
        if not (self.env.user.has_group('eurekam_jira_sync.group_jira_admin')
                or self.env.user.has_group('base.group_system')
                or self.env.is_superuser()):
            raise UserError(_("Action réservée au groupe « Jira : administrateur »."))

    @api.model
    def action_sync_now(self):
        self._check_admin()
        self.env.ref('eurekam_jira_sync.ir_cron_jira_sync').sudo()._trigger()
        return self._notify(_("Synchronisation lancée en arrière-plan. Le résultat "
                              "apparaîtra dans le journal de synchronisation."))

    @api.model
    def action_full_resync(self):
        self._check_admin()
        self._set_param('force_full', '1')
        self.env.ref('eurekam_jira_sync.ir_cron_jira_sync').sudo()._trigger()
        return self._notify(_("Resynchronisation complète lancée en arrière-plan."))

    @api.model
    def action_test_connection(self):
        self._check_admin()
        token = self._param('api_token') or ''
        try:
            account = self._get_client().myself() or {}
        except JiraError as exc:
            return self._notify(scrub(str(exc), token), kind='danger')
        return self._notify(_("Connexion réussie. Fuseau horaire du compte technique : %s",
                              account.get('timeZone') or '?'))

    @api.model
    def action_detect_fields(self):
        self._check_admin()
        token = self._param('api_token') or ''
        try:
            found = self._get_client().detect_custom_fields()
        except JiraError as exc:
            return self._notify(scrub(str(exc), token), kind='danger')
        self._store_custom_fields(found)
        missing = _('non trouvé')
        return self._notify(_(
            "Champ sprint : %(sprint)s — champ « Epic Link » : %(epic)s — "
            "champ « Nature du travail » : %(nature)s",
            sprint=found.get('sprint') or missing, epic=found.get('epic_link') or missing,
            nature=found.get('nature') or missing))
