from ast import literal_eval

from odoo import api, fields, models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    domain = fields.Char(
        string='Filter domain',
        help='If set, the action will only appear on records that match the domain.',
    )

    def _get_readable_fields(self):
        return super()._get_readable_fields() | {'domain'}

    @api.model
    def get_valid_action_reports(self, action_ids, model, record_ids):
        """Return IDs of actions whose domain matches at least one record.

        Actions without a domain are always considered valid.
        Actions with an invalid domain expression are excluded (fail-safe).

        :param action_ids: list of ir.actions.report IDs to evaluate
        :param model: model name of the records, e.g. 'res.partner'
        :param record_ids: list of record IDs currently selected
        :return: list of valid action IDs
        """
        actions = self.browse(action_ids).sudo()
        records = self.env[model].browse(record_ids)
        actions_with_domain = actions.filtered('domain')
        valid_ids = (actions - actions_with_domain).ids
        for action in actions_with_domain:
            try:
                domain = literal_eval(action.domain)
            except (ValueError, SyntaxError):
                continue
            if records.filtered_domain(domain):
                valid_ids.append(action.id)
        return valid_ids
