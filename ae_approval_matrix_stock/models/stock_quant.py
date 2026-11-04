from odoo import _, api, models
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _compute_inventory_quantity_auto_apply(self):
        super()._compute_inventory_quantity_auto_apply()
        for quant in self:
            if quant.inventory_quantity_set and quant.approval_need_validation and quant.approval_state != "approved":
                quant.inventory_quantity_auto_apply = quant.inventory_quantity

    def _set_inventory_quantity(self):
        """Inverse method to handle auto-apply in Locations view when approval is required.
        Instead of immediately updating stock moves, it retains the counted quantity
        and waits for approval matrix flow.
        """
        if not self._is_inventory_mode():
            return
        quant_to_inventory = self.env["stock.quant"]
        for quant in self:
            if quant.quantity == quant.inventory_quantity_auto_apply:
                continue
            quant.inventory_quantity = quant.inventory_quantity_auto_apply
            if not (quant.approval_need_validation and quant.approval_state != "approved"):
                quant_to_inventory |= quant
        if quant_to_inventory:
            quant_to_inventory.action_apply_inventory()

    def action_apply_inventory(self, date=False):
        """Enforce approval matrix validation before applying physical inventory adjustment."""
        if not self.env.context.get("skip_approval_check"):
            active_models = self.env["approval.matrix"]._get_active_models_cache()
            if "stock.quant" in active_models:
                unapproved_quants = self.filtered(
                    lambda q: q.approval_need_validation and q.approval_state != "approved"
                )
                if unapproved_quants:
                    products = ", ".join(unapproved_quants.mapped("product_id.display_name"))
                    raise UserError(_(
                        "The inventory adjustment for '%(products)s' requires approval.\n"
                        "Please request and complete all required approval levels before applying."
                    ) % {"products": products})

        return super().action_apply_inventory(date=date)

