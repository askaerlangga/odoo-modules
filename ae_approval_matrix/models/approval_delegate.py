from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ApprovalDelegate(models.Model):
    _name = "approval.delegate"
    _inherit = ["mail.thread"]
    _description = "Approval Delegation / Substitute Approver"
    _order = "date_from desc, id desc"

    name = fields.Char(
        string="Reference",
        compute="_compute_name",
        store=True,
        readonly=False,
    )
    active = fields.Boolean(string="Active", default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        ondelete="cascade",
    )
    delegator_id = fields.Many2one(
        "res.users",
        string="Original Approver",
        required=True,
        default=lambda self: self.env.user,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    delegate_id = fields.Many2one(
        "res.users",
        string="Substitute Approver",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    date_from = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_to = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    matrix_ids = fields.Many2many(
        "approval.matrix",
        "approval_delegate_matrix_rel",
        "delegate_rule_id",
        "matrix_id",
        string="Specific Matrices",
        help="Leave empty to delegate across all approval matrices.",
    )
    notes = fields.Text(string="Reason / Notes")

    @api.depends("delegator_id", "delegate_id", "date_from", "date_to")
    def _compute_name(self):
        for rec in self:
            if rec.delegator_id and rec.delegate_id:
                rec.name = _("%(delegator)s → %(delegate)s (%(start)s to %(end)s)") % {
                    "delegator": rec.delegator_id.name,
                    "delegate": rec.delegate_id.name,
                    "start": rec.date_from or "",
                    "end": rec.date_to or "",
                }
            else:
                rec.name = _("New Approval Delegation")

    @api.constrains("delegator_id", "delegate_id", "date_from", "date_to")
    def _check_delegation_validity(self):
        for rec in self:
            if rec.delegator_id and rec.delegate_id and rec.delegator_id == rec.delegate_id:
                raise ValidationError(_("A user cannot delegate approval authority to themselves."))
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_("End Date cannot be earlier than Start Date."))

    def _check_user_delegation_permission(self, vals=None):
        if self.env.su or self.env.user.has_group("ae_approval_matrix.group_approval_manager"):
            return
        uid = self.env.user.id
        if vals and "delegator_id" in vals and vals["delegator_id"] != uid:
            raise AccessError(_("You can only configure approval delegation for yourself."))
        for rec in self:
            if rec.delegator_id.id != uid:
                raise AccessError(_("You can only modify or delete your own approval delegations."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_user_delegation_permission(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_user_delegation_permission(vals)
        return super().write(vals)

    def unlink(self):
        self._check_user_delegation_permission()
        return super().unlink()

    @api.model
    def _get_active_delegations_for_user(self, user_id):
        """Return active delegation records where ``user_id`` is the substitute today."""
        today = fields.Date.context_today(self)
        return self.sudo().search([
            ("active", "=", True),
            ("delegate_id", "=", user_id),
            ("date_from", "<=", today),
            ("date_to", ">=", today),
        ])

    @api.model
    def _get_delegator_uids_for_user(self, user_id, matrix_id=False, company_id=False):
        """Return set of delegator user IDs that ``user_id`` can act on behalf of today."""
        delegations = self._get_active_delegations_for_user(user_id)
        if not delegations:
            return set()
        result = set()
        for d in delegations:
            if company_id and d.company_id and d.company_id.id != company_id:
                continue
            if matrix_id and d.matrix_ids and matrix_id not in d.matrix_ids.ids:
                continue
            result.add(d.delegator_id.id)
        return result
