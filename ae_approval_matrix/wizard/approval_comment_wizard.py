from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ApprovalCommentWizard(models.TransientModel):
    _name = "approval.comment.wizard"
    _description = "Approval Comment / Rejection Wizard"

    res_model = fields.Char(string="Document Model", required=True)
    res_id = fields.Integer(string="Document ID", required=True)
    review_id = fields.Many2one("approval.review", string="Review Record")
    action_type = fields.Selection(
        [("approve", "Approve"), ("reject", "Reject")],
        string="Action",
        required=True,
        default="reject",
    )
    comment = fields.Text(string="Reason / Note")

    @api.constrains("action_type", "comment")
    def _check_comment(self):
        for rec in self:
            if rec.action_type == "reject" and not rec.comment:
                raise ValidationError(_("A rejection reason is required."))

    def action_confirm(self):
        self.ensure_one()
        uid = self.env.user.id
        review = self.review_id
        if not review:
            review = self.env["approval.review"].search([
                ("res_model", "=", self.res_model),
                ("res_id", "=", self.res_id),
                ("status", "=", "pending"),
                ("approver_ids", "in", [uid]),
            ], limit=1)

        if not review or not review.user_can_approve:
            raise UserError(_("You have no pending approval action for this document."))

        if self.action_type == "approve":
            review.action_approve(comment=self.comment)
        else:
            review.action_reject(reason=self.comment)

        if self.res_model and self.res_id and self.res_model in self.env:
            self.env[self.res_model].browse(self.res_id).invalidate_recordset()

        return {"type": "ir.actions.act_window_close"}
