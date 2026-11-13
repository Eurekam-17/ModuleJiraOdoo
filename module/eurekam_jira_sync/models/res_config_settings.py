from odoo import api, fields, models

from .jira_mapping import token_expiry_status

TOKEN_EXPIRY_PARAM = 'eurekam_jira.token_expires_on'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    jira_base_url = fields.Char(
        string='URL Jira', config_parameter='eurekam_jira.base_url',
        default='https://eurekam.atlassian.net')
    jira_user_email = fields.Char(
        string='Compte technique Atlassian', config_parameter='eurekam_jira.user_email',
        help="Adresse d'un compte technique en lecture seule sur les projets "
             "synchronisés (pas un compte personnel).")
    jira_api_token = fields.Char(
        string="Jeton d'API", config_parameter='eurekam_jira.api_token',
        groups='base.group_system',
        help="Jeton d'API du compte technique (id.atlassian.com > Sécurité > "
             "Jetons d'API). Visible des seuls administrateurs système ; il "
             "n'est jamais écrit dans les journaux.")
    # Saved by set_values() (a Date is not a config_parameter type).
    jira_token_expires_on = fields.Date(
        string="Expiration du jeton",
        help="Date d'expiration choisie lors de la création du jeton sur "
             "id.atlassian.com. Atlassian ne permet pas de la relire avec le "
             "jeton : saisissez-la à chaque nouveau jeton. La synchronisation "
             "le signale dans son journal 15 jours avant l'échéance.")
    jira_token_expiry_alert = fields.Char(
        string='Alerte jeton', compute='_compute_jira_token_expiry')
    jira_token_expiry_info = fields.Char(
        string='Validité du jeton', compute='_compute_jira_token_expiry')
    jira_project_keys = fields.Char(
        string='Projets', config_parameter='eurekam_jira.project_keys', default='DA,DC,DP',
        help="Clés des projets Jira à synchroniser, séparées par des virgules.")
    jira_sprint_field = fields.Char(
        string='Champ sprint', config_parameter='eurekam_jira.sprint_field',
        help="Identifiant du champ personnalisé « Sprint », détecté automatiquement.")
    jira_epic_link_field = fields.Char(
        string='Champ « Epic Link »', config_parameter='eurekam_jira.epic_link_field')
    jira_nature_field = fields.Char(
        string='Champ « Nature du travail »', config_parameter='eurekam_jira.nature_field',
        help="Identifiant du champ personnalisé « Nature du travail », détecté "
             "automatiquement.")
    # Display only (not a config_parameter field: saving the settings page
    # must never overwrite the value written by the cron). Loaded by
    # get_values(): a dependency-less compute is not evaluated when the
    # settings page opens, so the field stayed empty.
    jira_last_sync_at = fields.Datetime(
        string='Dernière synchronisation réussie', readonly=True)

    @api.model
    def get_values(self):
        res = super().get_values()
        value = self.env['ir.config_parameter'].sudo().get_param('eurekam_jira.last_sync_at')
        res['jira_last_sync_at'] = fields.Datetime.to_datetime(value) if value else False
        expiry = self.env['ir.config_parameter'].sudo().get_param(TOKEN_EXPIRY_PARAM)
        res['jira_token_expires_on'] = fields.Date.to_date(expiry) if expiry else False
        return res

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        value = fields.Date.to_string(self.jira_token_expires_on) or False
        if (params.get_param(TOKEN_EXPIRY_PARAM) or False) != value:
            params.set_param(TOKEN_EXPIRY_PARAM, value)

    @api.depends('jira_token_expires_on')
    def _compute_jira_token_expiry(self):
        today = fields.Date.context_today(self)
        for settings in self:
            _days, alert, info = token_expiry_status(settings.jira_token_expires_on, today)
            settings.jira_token_expiry_alert = alert
            settings.jira_token_expiry_info = info

    def _jira_save(self):
        """Buttons act on saved parameters: save the form first."""
        self.ensure_one()
        self.set_values()

    def action_jira_test_connection(self):
        self._jira_save()
        return self.env['jira.sync.service'].action_test_connection()

    def action_jira_detect_fields(self):
        self._jira_save()
        action = self.env['jira.sync.service'].action_detect_fields()
        # Reload so the page shows the detected ids (and a later "Save" does
        # not write the stale ones back).
        action['params']['next'] = {'type': 'ir.actions.client', 'tag': 'reload'}
        return action

    def action_jira_sync_now(self):
        self._jira_save()
        return self.env['jira.sync.service'].action_sync_now()

    def action_jira_full_resync(self):
        self._jira_save()
        return self.env['jira.sync.service'].action_full_resync()
