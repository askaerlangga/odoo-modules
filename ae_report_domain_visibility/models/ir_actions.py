from collections import defaultdict

from odoo import models, tools
from odoo.tools import frozendict


class IrActions(models.Model):
    _inherit = 'ir.actions.actions'

    @tools.ormcache('model_name', 'self.env.lang')
    def _get_bindings(self, model_name):
        """Extend core _get_bindings to inject the 'domain' field for action
        models that define it (e.g. ir.actions.report).

        Strategy: call super() to preserve core logic and cache behaviour,
        then post-process the frozen result to attach domain values via a
        single additional DB query — only when at least one action has a
        domain field available on its model.
        """
        base_result = super()._get_bindings(model_name)

        all_action_ids = [
            action['id']
            for actions in base_result.values()
            for action in actions
            if action.get('id')
        ]
        if not all_action_ids:
            return base_result

        self.env.cr.execute(
            "SELECT id, type FROM ir_actions WHERE id IN %s",
            [tuple(all_action_ids)],
        )
        type_by_id = dict(self.env.cr.fetchall())

        action_ids_by_model = defaultdict(list)
        for action_id, action_model in type_by_id.items():
            if (
                action_model in self.env
                and 'domain' in self.env[action_model]._fields
            ):
                action_ids_by_model[action_model].append(action_id)

        if not action_ids_by_model:
            return base_result

        domain_by_id = {}
        for action_model, ids in action_ids_by_model.items():
            for rec in self.env[action_model].sudo().browse(ids):
                if rec.domain:
                    domain_by_id[rec.id] = rec.domain

        if not domain_by_id:
            return base_result

        new_result = {}
        for binding_type, actions in base_result.items():
            new_actions = []
            for action in actions:
                action_id = action.get('id')
                if action_id in domain_by_id:
                    new_action = dict(action)
                    new_action['domain'] = domain_by_id[action_id]
                    new_actions.append(frozendict(new_action))
                else:
                    new_actions.append(action)
            new_result[binding_type] = (
                tuple(new_actions) if isinstance(actions, tuple) else new_actions
            )
        return frozendict(new_result)
