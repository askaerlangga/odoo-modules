from collections import defaultdict
import logging
from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

REVIEW_STATUS = [
    ("waiting", "Waiting"),
    ("pending", "Pending"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("cancel", "Cancelled"),
]

_FORBIDDEN_AUTO_METHODS = {"write", "create", "unlink", "copy", "sudo", "with_user"}


class ApprovalReview(models.Model):
    _name = "approval.review"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Approval Review Record"
    _order = "sequence, id"

    res_model_id = fields.Many2one(
        "ir.model",
        string="Document Model",
        required=True,
        ondelete="cascade",
        index=True,
    )
    res_model = fields.Char(
        string="Model Name",
        related="res_model_id.model",
        store=True,
        readonly=True,
        index=True,
    )
    res_id = fields.Many2oneReference(
        string="Document ID",
        model_field="res_model",
        required=True,
        index=True,
    )
    res_name = fields.Char(
        string="Document",
        compute="_compute_res_name",
        store=True,
        readonly=True,
    )
    matrix_id = fields.Many2one(
        "approval.matrix",
        string="Approval Matrix",
        ondelete="set null",
        index=True,
    )
    workflow_id = fields.Many2one(
        "approval.matrix",
        related="matrix_id",
        string="Legacy Matrix Reference",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        index=True,
    )
    level_id = fields.Many2one(
        "approval.matrix.approver",
        string="Matrix Level",
        ondelete="set null",
    )
    sequence = fields.Integer(string="Level", required=True, default=1)
    name = fields.Char(string="Description")
    approval_header = fields.Char(
        string="Description (Legacy)",
        compute="_compute_approval_header",
        inverse="_inverse_approval_header",
        store=True,
    )

    @api.depends("name")
    def _compute_approval_header(self):
        for rec in self:
            rec.approval_header = rec.name

    def _inverse_approval_header(self):
        for rec in self:
            if rec.approval_header:
                rec.name = rec.approval_header

    approver_ids = fields.Many2many(
        "res.users",
        "approval_review_approver_rel",
        "review_id",
        "user_id",
        string="Approvers",
    )
    approved_by_ids = fields.Many2many(
        "res.users",
        "approval_review_approved_by_rel",
        "review_id",
        "user_id",
        string="Approved By",
        tracking=True,
    )
    rejected_by_ids = fields.Many2many(
        "res.users",
        "approval_review_rejected_by_rel",
        "review_id",
        "user_id",
        string="Rejected By",
        tracking=True,
    )

    minimum_approved = fields.Integer(
        string="Min. Approvals Required",
        required=True,
        default=1,
    )
    approved_count = fields.Integer(
        string="Approved Count",
        compute="_compute_counts",
        store=True,
    )
    rejected_count = fields.Integer(
        string="Rejected Count",
        compute="_compute_counts",
        store=True,
    )
    status = fields.Selection(
        REVIEW_STATUS,
        string="Status",
        default="waiting",
        required=True,
        index=True,
        tracking=True,
    )
    comment = fields.Text(string="Approve Comment", tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    action_datetime = fields.Datetime(string="Action Date/Time", readonly=True)

    user_can_approve = fields.Boolean(
        string="Current User Can Approve",
        compute="_compute_user_can_approve",
    )
    reviewed_users_display = fields.Char(
        string="Reviewed By",
        compute="_compute_reviewed_users_display",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") and vals.get("approval_header"):
                vals["name"] = vals["approval_header"]
        records = super().create(vals_list)
        for rec in records:
            doc = rec._get_document(sudo=False)
            if doc:
                doc.invalidate_recordset()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("status", "approved_by_ids", "rejected_by_ids", "approver_ids", "minimum_approved")):
            for rec in self:
                doc = rec._get_document(sudo=False)
                if doc:
                    doc.invalidate_recordset()
        return res

    def unlink(self):
        docs = [rec._get_document(sudo=False) for rec in self]
        res = super().unlink()
        for doc in docs:
            if doc:
                doc.invalidate_recordset()
        return res

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'approval_review' AND column_name = 'approval_header'
                ) THEN
                    UPDATE approval_review
                    SET name = approval_header
                    WHERE name IS NULL AND approval_header IS NOT NULL;
                END IF;
            END $$;
        """)
        return res

    _model_res_status_idx = models.Index("(res_model, res_id, status)")

    @api.depends("res_name", "name", "approval_header", "sequence")
    def _compute_display_name(self):
        for rec in self:
            doc = rec.res_name or _("Document")
            title = rec.name or rec.approval_header
            if title:
                rec.display_name = f"{doc} - Level {rec.sequence} ({title})"
            else:
                rec.display_name = f"{doc} - Level {rec.sequence}"

    @api.depends("approved_by_ids", "rejected_by_ids", "status")
    def _compute_reviewed_users_display(self):
        for rec in self:
            users = rec.approved_by_ids | rec.rejected_by_ids
            rec.reviewed_users_display = ", ".join(users.mapped("name")) if users else ""

    @api.depends("matrix_id.company_id", "workflow_id.company_id", "res_model", "res_id")
    def _compute_company_id(self):
        by_model = defaultdict(list)
        for rec in self:
            matrix = rec.matrix_id or rec.workflow_id
            if matrix and matrix.company_id:
                rec.company_id = matrix.company_id
            elif rec.res_model and rec.res_id and rec.res_model in self.env:
                by_model[rec.res_model].append(rec)
            else:
                rec.company_id = self.env.company

        for model_name, recs in by_model.items():
            docs = {
                d.id: d
                for d in self.env[model_name].sudo().browse([r.res_id for r in recs]).exists()
            }
            for rec in recs:
                doc = docs.get(rec.res_id)
                rec.company_id = getattr(doc, "company_id", False) or self.env.company

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        by_model = defaultdict(list)
        for rec in self:
            if rec.res_model and rec.res_id and rec.res_model in self.env:
                by_model[rec.res_model].append(rec)
            else:
                rec.res_name = str(rec.res_id) if rec.res_id else False

        for model_name, recs in by_model.items():
            docs = {
                d.id: d.display_name
                for d in self.env[model_name].sudo().browse([r.res_id for r in recs]).exists()
            }
            for rec in recs:
                rec.res_name = docs.get(rec.res_id) or str(rec.res_id)

    @api.depends("approved_by_ids", "rejected_by_ids")
    def _compute_counts(self):
        for rec in self:
            rec.approved_count = len(rec.approved_by_ids)
            rec.rejected_count = len(rec.rejected_by_ids)

    @api.depends_context("uid")
    @api.depends("status", "approver_ids", "approved_by_ids", "rejected_by_ids", "minimum_approved")
    def _compute_user_can_approve(self):
        uid = self.env.user.id
        for rec in self:
            quorum_met = (
                rec.approved_count >= rec.minimum_approved
                or rec.rejected_count >= rec.minimum_approved
            )
            rec.user_can_approve = (
                not quorum_met
                and rec.status == "pending"
                and uid in rec.approver_ids.ids
                and uid not in rec.approved_by_ids.ids
                and uid not in rec.rejected_by_ids.ids
            )

    def action_open_document(self):
        """Open the target document form view."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            raise UserError(_("No target document associated with this review."))
        doc = self._get_document(sudo=False)
        if not doc or not doc.exists():
            raise UserError(_("The referenced document does not exist or has been deleted."))
        doc.check_access("read")

        return {
            "type": "ir.actions.act_window",
            "name": doc.display_name or self.res_name or _("Document"),
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }

    def _lock_review_row(self):
        """Acquire a row-level lock on this review record to prevent race conditions."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM approval_review WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self.invalidate_recordset(["status", "approved_count", "rejected_count"])

    def _check_sequence_cleared(self):
        self.ensure_one()
        matrix = self.matrix_id or self.workflow_id
        if not matrix or not matrix.approve_sequence:
            return
        lower_reviews = self.env["approval.review"].sudo().search([
            ("matrix_id", "=", matrix.id),
            ("res_model", "=", self.res_model),
            ("res_id", "=", self.res_id),
            ("sequence", "<", self.sequence),
            ("status", "!=", "approved"),
        ])
        if lower_reviews:
            approver_names = ", ".join(lower_reviews.mapped("approver_ids.name"))
            raise UserError(_("Cannot approve yet. Pending approval from previous levels: %s") % approver_names)

    def action_approve(self, comment=False):
        self.ensure_one()
        self._lock_review_row()
        uid = self.env.user.id
        if self.status != "pending":
            raise UserError(_("This review level is not currently pending approval."))
        if uid not in self.approver_ids.ids:
            raise UserError(_("You are not listed as an approver for this review."))
        if uid in self.approved_by_ids.ids:
            raise UserError(_("You have already approved this review."))
        if uid in self.rejected_by_ids.ids:
            raise UserError(_("You have already rejected this review."))
        if self.approved_count >= self.minimum_approved or self.rejected_count >= self.minimum_approved:
            raise UserError(_("This review level has already been resolved."))

        self._check_sequence_cleared()

        vals = {
            "approved_by_ids": [(4, uid)],
            "action_datetime": fields.Datetime.now(),
        }
        if comment:
            vals["comment"] = comment

        rev_sudo = self.sudo()
        rev_sudo.write(vals)
        is_final = rev_sudo._update_status_after_action()
        self._notify_approved(is_final=is_final)
        if rev_sudo.status == "approved":
            rev_sudo._close_all_activities()
        else:
            rev_sudo._close_user_activity(uid)
        rev_sudo._bus_notify()
        if is_final:
            doc = self._get_document(sudo=False)
            matrix = self.matrix_id or self.workflow_id
            if matrix and matrix.auto_confirm_button_id:
                self._execute_auto_confirm(doc)

    def action_reject(self, reason=False):
        self.ensure_one()
        self._lock_review_row()
        uid = self.env.user.id
        if self.status != "pending":
            raise UserError(_("This review level is not currently pending approval."))
        if uid not in self.approver_ids.ids:
            raise UserError(_("You are not listed as an approver for this review."))
        if uid in self.approved_by_ids.ids:
            raise UserError(_("You have already approved this review."))
        if uid in self.rejected_by_ids.ids:
            raise UserError(_("You have already rejected this review."))

        vals = {
            "rejected_by_ids": [(4, uid)],
            "action_datetime": fields.Datetime.now(),
        }
        if reason:
            vals["rejection_reason"] = reason

        rev_sudo = self.sudo()
        rev_sudo.write(vals)
        is_rejected = rev_sudo._update_status_after_action()
        self._notify_rejected()
        rev_sudo._close_all_activities()
        rev_sudo._bus_notify()
        if is_rejected:
            doc = self._get_document(sudo=False)
            matrix = self.matrix_id or self.workflow_id
            if matrix and matrix.auto_reject_button_id:
                self._execute_auto_reject(doc)

    def _update_status_after_action(self):
        self.ensure_one()
        doc = self._get_document(sudo=False)
        is_final = False
        if self.approved_count >= self.minimum_approved:
            self.status = "approved"
            has_next = self._activate_next_pending()
            if not has_next:
                remaining_active = self.env["approval.review"].sudo().search_count([
                    ("res_model", "=", self.res_model),
                    ("res_id", "=", self.res_id),
                    ("status", "!=", "approved"),
                ])
                if not remaining_active:
                    is_final = True
                    if doc and hasattr(doc, "_on_approval_approved"):
                        doc._on_approval_approved()
        elif self.rejected_count >= self.minimum_approved:
            self.status = "rejected"
            self._cancel_waiting_on_rejection()
            if doc and hasattr(doc, "_on_approval_rejected"):
                doc._on_approval_rejected(reason=self.rejection_reason)
            is_final = True
        if doc:
            doc.invalidate_recordset()
        return is_final

    def _execute_auto_confirm(self, doc):
        """Execute configured confirmation button/method on final approval."""
        if not doc:
            return
        matrix = self.matrix_id or self.workflow_id
        btn = matrix.auto_confirm_button_id if matrix else False
        if not btn or not btn.name:
            return
        method_name = btn.name.strip()
        if method_name.startswith("_") or method_name in _FORBIDDEN_AUTO_METHODS:
            _logger.warning("Blocked unsafe auto_confirm method '%s' on %s", method_name, doc)
            return
        if hasattr(doc, method_name):
            doc.invalidate_recordset()
            getattr(doc.with_context(skip_approval_check=True), method_name)()

    def _execute_auto_reject(self, doc):
        """Execute configured button/method on document rejection (e.g. action_cancel)."""
        if not doc:
            return
        matrix = self.matrix_id or self.workflow_id
        btn = matrix.auto_reject_button_id if matrix else False
        if not btn or not btn.name:
            return
        method_name = btn.name.strip()
        if method_name.startswith("_") or method_name in _FORBIDDEN_AUTO_METHODS:
            _logger.warning("Blocked unsafe auto_reject method '%s' on %s", method_name, doc)
            return
        if hasattr(doc, method_name):
            doc.invalidate_recordset()
            getattr(doc.with_context(skip_approval_check=True), method_name)()

    def _activate_next_pending(self):
        self.ensure_one()
        matrix = self.matrix_id or self.workflow_id
        if not matrix or not matrix.approve_sequence:
            return False

        next_reviews = self.env["approval.review"].sudo().search([
            ("matrix_id", "=", matrix.id),
            ("res_model", "=", self.res_model),
            ("res_id", "=", self.res_id),
            ("sequence", ">", self.sequence),
            ("status", "=", "waiting"),
        ], order="sequence asc", limit=1)

        if not next_reviews:
            return False

        bypass_uids = self.approved_by_ids.ids if matrix.approve_sequence_bypass else []
        for nr in next_reviews:
            if bypass_uids and all(uid in bypass_uids for uid in nr.approver_ids.ids):
                nr.write({
                    "approved_by_ids": [(4, uid) for uid in nr.approver_ids.ids],
                    "status": "approved",
                    "action_datetime": fields.Datetime.now(),
                })
                return nr._activate_next_pending()

            nr.status = "pending"
            if matrix.notify_on_pending:
                nr._send_pending_notification()
            if matrix.create_activity:
                nr._create_scheduled_activities()
        return True

    def _cancel_waiting_on_rejection(self):
        self.ensure_one()
        matrix = self.matrix_id or self.workflow_id
        waiting = self.env["approval.review"].sudo().search([
            ("matrix_id", "=", matrix.id if matrix else False),
            ("res_model", "=", self.res_model),
            ("res_id", "=", self.res_id),
            ("status", "in", ["waiting", "pending"]),
        ])
        if waiting:
            waiting.write({"status": "cancel"})
            for rev in waiting:
                rev._close_all_activities()

    def _notify_approved(self, is_final=False):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        approver_name = self.env.user.name

        comment_html = Markup("")
        if self.comment:
            comment_html = Markup('<div class="small mt-1 text-muted"><b>%s:</b> %s</div>') % (
                _("Note"), tools.html_escape(self.comment)
            )

        remaining_approvers = self.approver_ids - self.approved_by_ids
        remaining_html = Markup("")
        if remaining_approvers and not is_final and self.status != "approved":
            remaining_html = Markup('<div class="small text-muted mt-1"><b>%s:</b> %s</div>') % (
                _("Pending"), ", ".join(remaining_approvers.mapped("name"))
            )

        if is_final:
            body = Markup(
                '<div class="border-start border-3 border-primary ps-2">'
                '<div class="fw-bold text-primary">%(title)s</div>'
                '<div class="text-success small fw-semibold">%(status)s</div>'
                '<div class="small text-muted mt-1">%(approver_label)s: %(approver)s (%(level)s)</div>'
                '%(comment)s'
                '</div>'
            ) % {
                "title": _("Approval Completed"),
                "status": _("All levels approved."),
                "approver_label": _("Final Approver"),
                "approver": approver_name,
                "level": f"Level {self.sequence}: {header}",
                "comment": comment_html,
            }
            doc.message_post(
                body=body,
                subtype_xmlid="ae_approval_matrix.mt_approval_completed",
            )
        else:
            status_text = (
                _("Level approved.")
                if self.status == "approved"
                else _("Approval registered (%(count)s/%(min)s).", count=self.approved_count, min=self.minimum_approved)
            )
            body = Markup(
                '<div class="border-start border-3 border-primary ps-2">'
                '<div class="fw-bold text-primary">%(level)s</div>'
                '<div class="small">%(approver_label)s: <b>%(approver)s</b> &bull; %(status)s</div>'
                '%(remaining)s'
                '%(comment)s'
                '</div>'
            ) % {
                "level": f"Level {self.sequence}: {header}",
                "approver_label": _("Approved by"),
                "approver": approver_name,
                "status": status_text,
                "remaining": remaining_html,
                "comment": comment_html,
            }
            doc.message_post(
                body=body,
                subtype_xmlid="ae_approval_matrix.mt_approval_approved",
            )

    def _notify_rejected(self):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        approver_name = self.env.user.name

        reason_html = Markup("")
        if self.rejection_reason:
            reason_html = Markup('<div class="small mt-1"><b>%s:</b> %s</div>') % (
                _("Reason"), tools.html_escape(self.rejection_reason)
            )

        body = Markup(
            '<div class="border-start border-3 border-primary ps-2">'
            '<div class="fw-bold text-primary">%(level)s</div>'
            '<div class="small text-danger fw-semibold">%(rejected_by)s: <b>%(approver)s</b></div>'
            '%(reason)s'
            '</div>'
        ) % {
            "level": f"Level {self.sequence}: {header}",
            "rejected_by": _("Rejected by"),
            "approver": approver_name,
            "reason": reason_html,
        }
        doc.message_post(
            body=body,
            subtype_xmlid="ae_approval_matrix.mt_approval_rejected",
        )

    def _send_pending_notification(self):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return
        partner_ids = self.approver_ids.mapped("partner_id").ids
        if not partner_ids:
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        approver_names = ", ".join(self.approver_ids.mapped("name"))
        quorum_info = _("(%s required)", self.minimum_approved) if self.minimum_approved > 1 else ""

        body = Markup(
            '<div class="border-start border-3 border-primary ps-2">'
            '<div class="fw-bold text-primary">%(level)s</div>'
            '<div class="small text-muted mt-1">%(label)s: %(approvers)s %(quorum)s</div>'
            '</div>'
        ) % {
            "level": f"Level {self.sequence}: {header}",
            "label": _("Assigned Approvers"),
            "approvers": approver_names,
            "quorum": quorum_info,
        }
        if hasattr(doc, "message_subscribe"):
            doc.message_subscribe(partner_ids=partner_ids)
        doc.message_post(
            body=body,
            partner_ids=partner_ids,
            subtype_xmlid="ae_approval_matrix.mt_approval_requested",
        )

    def _send_request_notification(self):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return
        partner_ids = self.approver_ids.mapped("partner_id").ids
        if not partner_ids:
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        approver_names = ", ".join(self.approver_ids.mapped("name"))
        quorum_info = _("(%s required)", self.minimum_approved) if self.minimum_approved > 1 else ""

        body = Markup(
            '<div class="border-start border-3 border-primary ps-2">'
            '<div class="fw-bold text-primary">%(level)s</div>'
            '<div class="small text-muted mt-1">%(label)s: %(approvers)s %(quorum)s</div>'
            '</div>'
        ) % {
            "level": f"Level {self.sequence}: {header}",
            "label": _("Assigned Approvers"),
            "approvers": approver_names,
            "quorum": quorum_info,
        }
        if hasattr(doc, "message_subscribe"):
            doc.message_subscribe(partner_ids=partner_ids)
        doc.message_post(
            body=body,
            partner_ids=partner_ids,
            subtype_xmlid="ae_approval_matrix.mt_approval_requested",
        )

    def _create_scheduled_activities(self):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "activity_schedule"):
            return
        matrix = self.matrix_id or self.workflow_id
        act_type = (matrix.activity_type_id if matrix else False) or self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not act_type:
            return
        doc_name = self.res_name or _("Document")
        header = self.name or self.approval_header or _("Level %s", self.sequence)
        summary = _("Approval Needed: %s") % (header or doc_name)
        note = _("Please review and approve document %s (Level %s: %s).") % (doc_name, self.sequence, header)
        for user in self.approver_ids:
            doc.activity_schedule(
                activity_type_id=act_type.id,
                summary=summary,
                note=note,
                user_id=user.id,
            )

    def _close_user_activity(self, user_id):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "activity_ids"):
            return
        activities = doc.activity_ids.filtered(
            lambda a: a.user_id.id == user_id and (
                "Approval Required" in (a.summary or "")
                or "Approval Needed" in (a.summary or "")
                or (self.name and self.name in (a.summary or ""))
                or (self.approval_header and self.approval_header in (a.summary or ""))
            )
        )
        if activities:
            activities.action_done()

    def _close_all_activities(self):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "activity_ids"):
            return
        approver_uids = self.approver_ids.ids
        activities = doc.activity_ids.filtered(
            lambda a: a.user_id.id in approver_uids and (
                "Approval Required" in (a.summary or "")
                or "Approval Needed" in (a.summary or "")
                or (self.name and self.name in (a.summary or ""))
                or (self.approval_header and self.approval_header in (a.summary or ""))
            )
        )
        if activities:
            activities.unlink()

    def _bus_notify(self):
        """Notify users via bus.bus to update systray realtime."""
        partners = self.approver_ids.mapped("partner_id")
        for partner in partners:
            self.env["bus.bus"]._sendone(partner, "approval_matrix/updated", {"status": "updated"})

    def _get_document(self, sudo=True):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        model_env = self.env[self.res_model].sudo() if sudo else self.env[self.res_model]
        doc = model_env.browse(self.res_id)
        return doc if doc.exists() else False
