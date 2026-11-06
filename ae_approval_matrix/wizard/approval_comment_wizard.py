from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ApprovalCommentWizard(models.TransientModel):
    _name = "approval.comment.wizard"
    _description = "Approval Comment / Rejection Wizard"

    res_model = fields.Char(string="Document Model")
    res_id = fields.Integer(string="Document ID")
    review_id = fields.Many2one("approval.review", string="Review Record")
    review_ids = fields.Many2many(
        "approval.review",
        "approval_comment_wizard_review_rel",
        "wizard_id",
        "review_id",
        string="Selected Reviews",
    )
    review_count = fields.Integer(compute="_compute_wizard_capabilities")
    is_bulk = fields.Boolean(compute="_compute_wizard_capabilities")
    can_send_back = fields.Boolean(compute="_compute_wizard_capabilities")
    available_previous_review_ids = fields.Many2many(
        "approval.review",
        compute="_compute_wizard_capabilities",
        string="Available Previous Levels",
    )
    action_type = fields.Selection(
        [("approve", "Approve"), ("reject", "Reject")],
        string="Action",
        required=True,
        default="reject",
    )
    reject_mode = fields.Selection(
        [
            ("reject", "Full Reject (Cancel Approval)"),
            ("send_back", "Send Back to Previous Level"),
        ],
        string="Rejection Mode",
        required=True,
        default="reject",
    )
    target_review_id = fields.Many2one(
        "approval.review",
        string="Return to Level",
        domain="[('id', 'in', available_previous_review_ids)]",
    )
    comment = fields.Text(string="Reason / Note")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        rev_id = res.get("review_id") or self.env.context.get("default_review_id")
        if rev_id and "target_review_id" in fields_list and not res.get("target_review_id"):
            review = self.env["approval.review"].browse(rev_id).exists()
            if review and review.matrix_id and review.matrix_id.approve_sequence and review.matrix_id.allow_send_back:
                prev = self.env["approval.review"].sudo().search([
                    ("res_model", "=", review.res_model),
                    ("res_id", "=", review.res_id),
                    ("sequence", "<", review.sequence),
                    ("status", "=", "approved"),
                ], order="sequence desc", limit=1)
                if prev:
                    res["target_review_id"] = prev.id
        return res

    @api.depends("review_id", "review_ids", "action_type")
    def _compute_wizard_capabilities(self):
        for rec in self:
            count = len(rec.review_ids)
            rec.review_count = count or (1 if rec.review_id else 0)
            rec.is_bulk = count > 1

            single_rev = rec.review_id or (rec.review_ids[0] if count == 1 else self.env["approval.review"])
            if (
                not rec.is_bulk
                and single_rev
                and single_rev.id
                and single_rev.matrix_id
                and single_rev.matrix_id.approve_sequence
                and single_rev.matrix_id.allow_send_back
                and single_rev.sequence > 1
            ):
                prev_reviews = self.env["approval.review"].sudo().search([
                    ("res_model", "=", single_rev.res_model),
                    ("res_id", "=", single_rev.res_id),
                    ("sequence", "<", single_rev.sequence),
                    ("status", "=", "approved"),
                ], order="sequence desc")
                rec.available_previous_review_ids = prev_reviews
                rec.can_send_back = bool(prev_reviews)
            else:
                rec.available_previous_review_ids = self.env["approval.review"]
                rec.can_send_back = False

    @api.onchange("review_id", "reject_mode")
    def _onchange_reject_mode(self):
        if self.reject_mode == "send_back" and not self.target_review_id and self.available_previous_review_ids:
            self.target_review_id = self.available_previous_review_ids.sorted(
                lambda r: r.sequence, reverse=True
            )[0]

    @api.constrains("action_type", "comment")
    def _check_comment(self):
        for rec in self:
            if rec.action_type == "reject" and not rec.comment:
                raise ValidationError(_("A rejection reason is required."))

    def action_confirm(self):
        self.ensure_one()
        if self.review_ids and len(self.review_ids) > 1:
            eligible = self.review_ids.filtered(lambda r: r.user_can_approve)
            if not eligible:
                raise UserError(_("You have no pending approval action for the selected documents."))
            for rev in eligible:
                if self.action_type == "approve":
                    rev.action_approve(comment=self.comment)
                else:
                    rev.action_reject(reason=self.comment)
                if rev.res_model and rev.res_id and rev.res_model in self.env:
                    self.env[rev.res_model].browse(rev.res_id).invalidate_recordset()
            return {"type": "ir.actions.act_window_close"}

        review = self.review_id or (self.review_ids[:1] if self.review_ids else self.env["approval.review"])
        if not review and self.res_model and self.res_id:
            candidates = self.env["approval.review"].search([
                ("res_model", "=", self.res_model),
                ("res_id", "=", self.res_id),
                ("status", "=", "pending"),
            ])
            review = candidates.filtered(lambda r: r.user_can_approve)[:1]

        if not review or not review.user_can_approve:
            raise UserError(_("You have no pending approval action for this document."))

        if self.action_type == "approve":
            review.action_approve(comment=self.comment)
        else:
            if self.reject_mode == "send_back":
                target = self.target_review_id or self.available_previous_review_ids.sorted(
                    lambda r: r.sequence, reverse=True
                )[:1]
                if not target:
                    raise ValidationError(_("Please select a previous approval level to return to."))
                review.action_send_back(target, reason=self.comment)
            else:
                review.action_reject(reason=self.comment)

        res_model = self.res_model or review.res_model
        res_id = self.res_id or review.res_id
        if res_model and res_id and res_model in self.env:
            self.env[res_model].browse(res_id).invalidate_recordset()

        return {"type": "ir.actions.act_window_close"}
