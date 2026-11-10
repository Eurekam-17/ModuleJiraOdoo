from odoo import fields, models


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
    jira_project_keys = fields.Char(
        string='Projets', config_parameter='eurekam_jira.project_keys', default='DA,DC,DP',
        help="Clés des projets Jira à synchroniser, séparées par des virgules.")
    jira_sprint_field = fields.Char(
        string='Champ sprint', config_parameter='eurekam_jira.sprint_field',
        help="Identifiant du champ personnalisé « Sprint », détecté automatiquement.")
    jira_epic_link_field = fields.Char(
        string='Champ « Epic Link »', config_parameter='eurekam_jira.epic_link_field')
    # Display only (not a config_parameter field: saving the settings page
    # must never overwrite the value written by the cron).
    jira_last_sync_at = fields.Datetime(
        string='Dernière synchronisation réussie', compute='_compute_jira_last_sync_at')

    def _compute_jira_last_sync_at(self):
        value = self.env['ir.config_parameter'].sudo().get_param('eurekam_jira.last_sync_at')
        for settings in self:
            settings.jira_last_sync_at = fields.Datetime.to_datetime(value) if value else False

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
