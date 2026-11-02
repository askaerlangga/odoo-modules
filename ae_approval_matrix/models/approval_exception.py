from odoo import fields, models


class ApprovalException(models.Model):
    _name = "approval.exception"
    _description = "Approval Field Edit Exception"
    _order = "name, id"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        ondelete="cascade",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Document Model",
        required=True,
        ondelete="cascade",
        domain="[('transient', '=', False)]",
    )
    model_name = fields.Char(
        related="model_id.model",
        string="Model Name",
        store=True,
        readonly=True,
        index=True,
    )
    field_ids = fields.Many2many(
        "ir.model.fields",
        "approval_exception_field_rel",
        "exception_id",
        "field_id",
        string="Allowed Fields",
        domain="[('model_id', '=', model_id)]",
        required=True,
    )
    group_ids = fields.Many2many(
        "res.groups",
        "approval_exception_group_rel",
        "exception_id",
        "group_id",
        string="User Groups",
        help="Leave empty to apply to all users.",
    )
    allow_write_under_validation = fields.Boolean(
        string="Allow Write Under Validation",
        default=True,
        help="These fields can be modified while approval is in progress (waiting/pending).",
    )
    allow_write_after_validation = fields.Boolean(
        string="Allow Write After Validation",
        default=False,
        help="These fields can be modified even after the document is approved.",
    )
