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
    on_behalf_of_ids = fields.Many2many(
        "res.users",
        "approval_review_on_behalf_rel",
        "review_id",
        "user_id",
        string="On Behalf Of",
        tracking=True,
    )
    delegated_info = fields.Char(
        string="Delegation Audit",
        readonly=True,
        tracking=True,
    )
    pending_date = fields.Datetime(
        string="Pending Since",
        readonly=True,
    )
    sla_deadline = fields.Datetime(
        string="SLA Deadline",
        compute="_compute_sla_deadline",
        store=True,
        index=True,
    )
    sla_triggered = fields.Boolean(
        string="SLA Triggered",
        default=False,
        readonly=True,
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
        now = fields.Datetime.now()
        for vals in vals_list:
            if not vals.get("name") and vals.get("approval_header"):
                vals["name"] = vals["approval_header"]
            if vals.get("status") == "pending" and not vals.get("pending_date"):
                vals["pending_date"] = now
        records = super().create(vals_list)
        for rec in records:
            doc = rec._get_document(sudo=False)
            if doc:
                doc.invalidate_recordset()
        return records

    def write(self, vals):
        if vals.get("status") == "pending" and "pending_date" not in vals:
            vals = dict(vals, pending_date=fields.Datetime.now(), sla_triggered=False)
        res = super().write(vals)
        if any(f in vals for f in ("status", "approved_by_ids", "rejected_by_ids", "on_behalf_of_ids", "approver_ids", "minimum_approved")):
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

    @api.depends("approved_by_ids", "rejected_by_ids", "delegated_info", "status")
    def _compute_reviewed_users_display(self):
        for rec in self:
            users = rec.approved_by_ids | rec.rejected_by_ids
            if rec.delegated_info:
                extra_names = [u.name for u in users if u.name and u.name not in rec.delegated_info]
                if extra_names:
                    rec.reviewed_users_display = f"{', '.join(extra_names)}, {rec.delegated_info}"
                else:
                    rec.reviewed_users_display = rec.delegated_info
            else:
                rec.reviewed_users_display = ", ".join(users.mapped("name")) if users else ""

    @api.depends("status", "pending_date", "level_id.sla_hours")
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.status == "pending" and rec.pending_date and rec.level_id and rec.level_id.sla_hours > 0:
                rec.sla_deadline = fields.Datetime.add(rec.pending_date, hours=rec.level_id.sla_hours)
            else:
                rec.sla_deadline = False

    @api.depends("matrix_id.company_id", "res_model", "res_id")
    def _compute_company_id(self):
        by_model = defaultdict(list)
        for rec in self:
            matrix = rec.matrix_id
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

    def _is_self_approval_blocked(self, uid):
        """Return True if ``uid`` is blocked from approving ``self`` due to Maker-Checker policy."""
        self.ensure_one()
        matrix = self.matrix_id.sudo() if self.matrix_id else False
        if not matrix or not matrix.prevent_self_approval:
            return False
        doc = self._get_document(sudo=True)
        if not doc:
            return False
        return uid in matrix._get_document_requester_uids(doc)

    def _resolve_acting_approver(self, uid=None):
        """Determine how ``uid`` is authorized to act on this review.

        :return:
            - ``False`` if ``uid`` is a direct approver acting for themselves,
            - a ``res.users`` record of the delegator if ``uid`` is acting as a substitute,
            - ``None`` if ``uid`` is not authorized.
        """
        self.ensure_one()
        uid = uid or self.env.user.id
        if self._is_self_approval_blocked(uid):
            raise UserError(_("Maker-Checker Policy: You cannot approve or reject your own document."))

        used_slot_uids = (
            set(self.approved_by_ids.ids)
            | set(self.rejected_by_ids.ids)
            | set(self.on_behalf_of_ids.ids)
        )
        if uid in self.approver_ids.ids and uid not in used_slot_uids:
            return False

        remaining_approver_uids = set(self.approver_ids.ids) - used_slot_uids
        if not remaining_approver_uids:
            return None

        active_delegations = self.env["approval.delegate"]._get_active_delegations_for_user(uid)
        for d in active_delegations:
            delegator_uid = d.delegator_id.id
            if delegator_uid not in remaining_approver_uids:
                continue
            if d.company_id and self.company_id and d.company_id.id != self.company_id.id:
                continue
            if d.matrix_ids and (not self.matrix_id or self.matrix_id.id not in d.matrix_ids.ids):
                continue
            if self._is_self_approval_blocked(delegator_uid):
                continue
            return d.delegator_id
        return None

    @api.depends_context("uid")
    @api.depends(
        "status",
        "approver_ids",
        "approved_by_ids",
        "rejected_by_ids",
        "on_behalf_of_ids",
        "minimum_approved",
        "matrix_id.prevent_self_approval",
    )
    def _compute_user_can_approve(self):
        uid = self.env.user.id
        pending_recs = self.filtered(lambda r: r.status == "pending")
        active_delegations = (
            self.env["approval.delegate"]._get_active_delegations_for_user(uid)
            if pending_recs
            else self.env["approval.delegate"]
        )

        for rec in self:
            quorum_met = (
                rec.approved_count >= rec.minimum_approved
                or rec.rejected_count >= rec.minimum_approved
            )
            if (
                quorum_met
                or rec.status != "pending"
                or uid in rec.approved_by_ids.ids
                or uid in rec.rejected_by_ids.ids
            ):
                rec.user_can_approve = False
                continue

            if rec.matrix_id and rec.matrix_id.sudo().prevent_self_approval and rec._is_self_approval_blocked(uid):
                rec.user_can_approve = False
                continue

            used_slot_uids = (
                set(rec.approved_by_ids.ids)
                | set(rec.rejected_by_ids.ids)
                | set(rec.on_behalf_of_ids.ids)
            )
            if uid in rec.approver_ids.ids and uid not in used_slot_uids:
                rec.user_can_approve = True
                continue

            remaining_uids = set(rec.approver_ids.ids) - used_slot_uids
            can_delegate = False
            if remaining_uids and active_delegations:
                for d in active_delegations:
                    if d.delegator_id.id not in remaining_uids:
                        continue
                    if d.company_id and rec.company_id and d.company_id.id != rec.company_id.id:
                        continue
                    if d.matrix_ids and (not rec.matrix_id or rec.matrix_id.id not in d.matrix_ids.ids):
                        continue
                    if rec.matrix_id and rec.matrix_id.sudo().prevent_self_approval and rec._is_self_approval_blocked(d.delegator_id.id):
                        continue
                    can_delegate = True
                    break
            rec.user_can_approve = can_delegate

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
        matrix = self.matrix_id
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
        if uid in self.approved_by_ids.ids:
            raise UserError(_("You have already approved this review."))
        if uid in self.rejected_by_ids.ids:
            raise UserError(_("You have already rejected this review."))
        if self.approved_count >= self.minimum_approved or self.rejected_count >= self.minimum_approved:
            raise UserError(_("This review level has already been resolved."))

        delegator = self._resolve_acting_approver(uid)
        if delegator is None:
            raise UserError(_("You are not listed as an approver for this review."))

        self._check_sequence_cleared()

        vals = {
            "approved_by_ids": [(4, uid)],
            "action_datetime": fields.Datetime.now(),
        }
        if delegator:
            vals["on_behalf_of_ids"] = [(4, delegator.id)]
            entry = _("%(delegate)s (on behalf of %(delegator)s)", delegate=self.env.user.name, delegator=delegator.name)
            vals["delegated_info"] = f"{self.delegated_info}, {entry}" if self.delegated_info else entry
        if comment:
            vals["comment"] = comment

        rev_sudo = self.sudo()
        rev_sudo.write(vals)
        is_final = rev_sudo._update_status_after_action()
        self._notify_approved(is_final=is_final, delegator=delegator)
        if rev_sudo.status == "approved":
            rev_sudo._close_all_activities()
        else:
            rev_sudo._close_user_activity(uid)
            if delegator:
                rev_sudo._close_user_activity(delegator.id)
        rev_sudo._bus_notify()
        if is_final:
            doc = self._get_document(sudo=False)
            matrix = self.matrix_id
            if matrix and matrix.auto_confirm_button_id:
                self._execute_auto_confirm(doc)

    def action_reject(self, reason=False):
        self.ensure_one()
        self._lock_review_row()
        uid = self.env.user.id
        if self.status != "pending":
            raise UserError(_("This review level is not currently pending approval."))
        if uid in self.approved_by_ids.ids:
            raise UserError(_("You have already approved this review."))
        if uid in self.rejected_by_ids.ids:
            raise UserError(_("You have already rejected this review."))

        delegator = self._resolve_acting_approver(uid)
        if delegator is None:
            raise UserError(_("You are not listed as an approver for this review."))

        vals = {
            "rejected_by_ids": [(4, uid)],
            "action_datetime": fields.Datetime.now(),
        }
        if delegator:
            vals["on_behalf_of_ids"] = [(4, delegator.id)]
            entry = _("%(delegate)s (on behalf of %(delegator)s)", delegate=self.env.user.name, delegator=delegator.name)
            vals["delegated_info"] = f"{self.delegated_info}, {entry}" if self.delegated_info else entry
        if reason:
            vals["rejection_reason"] = reason

        rev_sudo = self.sudo()
        rev_sudo.write(vals)
        is_rejected = rev_sudo._update_status_after_action()
        self._notify_rejected(delegator=delegator)
        rev_sudo._close_all_activities()
        rev_sudo._bus_notify()
        if is_rejected:
            doc = self._get_document(sudo=False)
            matrix = self.matrix_id
            if matrix and matrix.auto_reject_button_id:
                self._execute_auto_reject(doc)

    def action_send_back(self, target_review, reason=False):
        """Send approval back from the current level to a previous level (`target_review`)."""
        self.ensure_one()
        target_review.ensure_one()
        self._lock_review_row()
        uid = self.env.user.id

        if self.status != "pending":
            raise UserError(_("This review level is not currently pending approval."))
        matrix = self.matrix_id
        if not matrix or not matrix.approve_sequence or not matrix.allow_send_back:
            raise UserError(_("Sending back to a previous level is not enabled for this approval matrix."))
        if target_review.res_model != self.res_model or target_review.res_id != self.res_id:
            raise UserError(_("Target review level belongs to a different document."))
        if target_review.sequence >= self.sequence:
            raise UserError(_("You can only send back to a level earlier than the current level."))

        delegator = self._resolve_acting_approver(uid)
        if delegator is None:
            raise UserError(_("You are not listed as an approver for this review."))

        affected_reviews = self.env["approval.review"].sudo().search([
            ("res_model", "=", self.res_model),
            ("res_id", "=", self.res_id),
            ("sequence", ">=", target_review.sequence),
        ])
        for rev in affected_reviews:
            rev._close_all_activities()

        later_reviews = affected_reviews.filtered(lambda r: r.id != target_review.id)
        if later_reviews:
            later_reviews.write({
                "status": "waiting",
                "approved_by_ids": [fields.Command.clear()],
                "rejected_by_ids": [fields.Command.clear()],
                "on_behalf_of_ids": [fields.Command.clear()],
                "delegated_info": False,
                "pending_date": False,
                "sla_triggered": False,
            })

        self.sudo().write({
            "rejection_reason": reason or False,
            "action_datetime": fields.Datetime.now(),
        })

        target_sudo = target_review.sudo()
        target_sudo.write({
            "status": "pending",
            "approved_by_ids": [fields.Command.clear()],
            "rejected_by_ids": [fields.Command.clear()],
            "on_behalf_of_ids": [fields.Command.clear()],
            "delegated_info": False,
            "comment": False,
            "rejection_reason": False,
            "pending_date": fields.Datetime.now(),
            "sla_triggered": False,
        })

        self._notify_sent_back(target_sudo, reason=reason, delegator=delegator)
        if matrix.notify_on_pending:
            target_sudo._send_pending_notification()
        if matrix.create_activity:
            target_sudo._create_scheduled_activities()
        affected_reviews._bus_notify()

        doc = self._get_document(sudo=False)
        if doc:
            doc.invalidate_recordset()
        return True

    def action_bulk_approve_wizard(self):
        """Open wizard to bulk approve selected review records."""
        eligible = self.filtered(lambda r: r.user_can_approve)
        if not eligible:
            raise UserError(_("None of the selected review records can currently be approved by you."))
        first = eligible[0]
        return {
            "name": _("Bulk Approve (%d Reviews)") % len(eligible) if len(eligible) > 1 else _("Approve Document"),
            "type": "ir.actions.act_window",
            "res_model": "approval.comment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": first.res_model,
                "default_res_id": first.res_id,
                "default_review_id": first.id if len(eligible) == 1 else False,
                "default_review_ids": [fields.Command.set(eligible.ids)],
                "default_action_type": "approve",
            },
        }

    def action_bulk_reject_wizard(self):
        """Open wizard to bulk reject selected review records."""
        eligible = self.filtered(lambda r: r.user_can_approve)
        if not eligible:
            raise UserError(_("None of the selected review records can currently be rejected by you."))
        first = eligible[0]
        return {
            "name": _("Bulk Reject (%d Reviews)") % len(eligible) if len(eligible) > 1 else _("Reject Document"),
            "type": "ir.actions.act_window",
            "res_model": "approval.comment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": first.res_model,
                "default_res_id": first.res_id,
                "default_review_id": first.id if len(eligible) == 1 else False,
                "default_review_ids": [fields.Command.set(eligible.ids)],
                "default_action_type": "reject",
            },
        }

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
        matrix = self.matrix_id
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
        matrix = self.matrix_id
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
        matrix = self.matrix_id
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
        matrix = self.matrix_id
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

    def _notify_approved(self, is_final=False, delegator=False):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        if delegator:
            approver_name = _("%(delegate)s (on behalf of %(delegator)s)", delegate=self.env.user.name, delegator=delegator.name)
        else:
            approver_name = self.env.user.name

        comment_html = Markup("")
        if self.comment:
            comment_html = Markup('<div class="small mt-1 text-muted"><b>%s:</b> %s</div>') % (
                _("Note"), tools.html_escape(self.comment)
            )

        remaining_approvers = self.approver_ids - self.approved_by_ids - self.on_behalf_of_ids
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

    def _notify_rejected(self, delegator=False):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        if delegator:
            approver_name = _("%(delegate)s (on behalf of %(delegator)s)", delegate=self.env.user.name, delegator=delegator.name)
        else:
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

    def _notify_sent_back(self, target_review, reason=False, delegator=False):
        doc = self._get_document(sudo=True)
        if not doc or not hasattr(doc, "message_post"):
            return

        header = self.name or self.approval_header or _("Level %s", self.sequence)
        target_header = target_review.name or target_review.approval_header or _("Level %s", target_review.sequence)
        if delegator:
            approver_name = _("%(delegate)s (on behalf of %(delegator)s)", delegate=self.env.user.name, delegator=delegator.name)
        else:
            approver_name = self.env.user.name

        reason_html = Markup("")
        if reason:
            reason_html = Markup('<div class="small mt-1"><b>%s:</b> %s</div>') % (
                _("Reason"), tools.html_escape(reason)
            )

        body = Markup(
            '<div class="border-start border-3 border-warning ps-2">'
            '<div class="fw-bold text-warning">%(title)s</div>'
            '<div class="small">%(by_label)s: <b>%(approver)s</b> (%(from_level)s &rarr; %(to_level)s)</div>'
            '%(reason)s'
            '</div>'
        ) % {
            "title": _("Sent Back for Revision"),
            "by_label": _("Returned by"),
            "approver": approver_name,
            "from_level": f"Level {self.sequence}: {header}",
            "to_level": f"Level {target_review.sequence}: {target_header}",
            "reason": reason_html,
        }
        doc.message_post(
            body=body,
            subtype_xmlid="ae_approval_matrix.mt_approval_reset",
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
        matrix = self.matrix_id
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
        """Notify users (and active delegates) via bus.bus to update systray realtime."""
        approver_users = self.approver_ids
        if approver_users:
            today = fields.Date.context_today(self)
            delegations = self.env["approval.delegate"].sudo().search([
                ("active", "=", True),
                ("delegator_id", "in", approver_users.ids),
                ("date_from", "<=", today),
                ("date_to", ">=", today),
            ])
            approver_users |= delegations.mapped("delegate_id")
        partners = approver_users.mapped("partner_id")
        for partner in partners:
            self.env["bus.bus"]._sendone(partner, "approval_matrix/updated", {"status": "updated"})

    def _get_document(self, sudo=True):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        model_env = self.env[self.res_model].sudo() if sudo else self.env[self.res_model]
        doc = model_env.browse(self.res_id)
        return doc if doc.exists() else False

    # ─── SLA Timeout & Escalation Engine ───
    @api.model
    def _cron_process_sla_reviews(self):
        """Scheduled job to process pending reviews that have exceeded their SLA deadline."""
        now = fields.Datetime.now()
        overdue_reviews = self.sudo().search([
            ("status", "=", "pending"),
            ("sla_triggered", "=", False),
            ("sla_deadline", "!=", False),
            ("sla_deadline", "<=", now),
        ])
        if overdue_reviews:
            overdue_reviews._process_sla_timeout()

    def _process_sla_timeout(self):
        """Process SLA timeout actions on the recordset."""
        for rev in self.sudo():
            if rev.status != "pending" or rev.sla_triggered:
                continue
            level = rev.level_id
            action = level.sla_action if level and level.sla_action else "remind"
            rev.sla_triggered = True
            if action == "remind":
                rev._execute_sla_remind()
            elif action == "escalate":
                rev._execute_sla_escalate()
            elif action == "auto_approve":
                rev._execute_sla_auto_approve()

    def _execute_sla_remind(self):
        self.ensure_one()
        doc = self._get_document(sudo=True)
        remaining = self.approver_ids - self.approved_by_ids - self.on_behalf_of_ids
        if not remaining:
            return
        header = self.name or self.approval_header or _("Level %s", self.sequence)
        if doc and hasattr(doc, "message_post"):
            partner_ids = remaining.mapped("partner_id").ids
            body = Markup(
                '<div class="border-start border-3 border-warning ps-2">'
                '<div class="fw-bold text-warning">%(title)s</div>'
                '<div class="small text-muted mt-1">%(level)s &bull; %(pending)s: %(approvers)s</div>'
                '</div>'
            ) % {
                "title": _("SLA Approval Reminder"),
                "level": f"Level {self.sequence}: {header}",
                "pending": _("Pending Approvers"),
                "approvers": ", ".join(remaining.mapped("name")),
            }
            doc.message_post(
                body=body,
                partner_ids=partner_ids,
                subtype_xmlid="ae_approval_matrix.mt_approval_requested",
            )
        if self.matrix_id and self.matrix_id.create_activity and doc and hasattr(doc, "activity_schedule"):
            act_type = self.matrix_id.activity_type_id or self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
            if act_type:
                for user in remaining:
                    doc.activity_schedule(
                        activity_type_id=act_type.id,
                        summary=_("SLA Reminder: Approval Needed (%s)") % header,
                        note=_("SLA deadline exceeded for Level %s (%s).") % (self.sequence, header),
                        user_id=user.id,
                    )
        self._bus_notify()

    def _execute_sla_escalate(self):
        self.ensure_one()
        level = self.level_id
        remaining = self.approver_ids - self.approved_by_ids - self.on_behalf_of_ids
        escalation_users = self.env["res.users"]
        if level and level.sla_escalate_user_id:
            escalation_users |= level.sla_escalate_user_id
        elif remaining:
            employees = self.env["hr.employee"].sudo().search([("user_id", "in", remaining.ids)])
            for emp in employees:
                if emp.parent_id and emp.parent_id.user_id:
                    escalation_users |= emp.parent_id.user_id
                elif emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
                    escalation_users |= emp.department_id.manager_id.user_id

        if self.matrix_id and self.matrix_id.prevent_self_approval:
            doc = self._get_document(sudo=True)
            forbidden_uids = self.matrix_id._get_document_requester_uids(doc) if doc else set()
            if forbidden_uids:
                escalation_users = escalation_users.filtered(lambda u: u.id not in forbidden_uids)

        new_users = escalation_users - self.approver_ids
        if new_users:
            self.write({"approver_ids": [fields.Command.link(u.id) for u in new_users]})

        doc = self._get_document(sudo=True)
        header = self.name or self.approval_header or _("Level %s", self.sequence)
        if doc and hasattr(doc, "message_post") and escalation_users:
            partner_ids = escalation_users.mapped("partner_id").ids
            if hasattr(doc, "message_subscribe"):
                doc.message_subscribe(partner_ids=partner_ids)
            body = Markup(
                '<div class="border-start border-3 border-danger ps-2">'
                '<div class="fw-bold text-danger">%(title)s</div>'
                '<div class="small text-muted mt-1">%(level)s &bull; %(escalated)s: <b>%(users)s</b></div>'
                '</div>'
            ) % {
                "title": _("SLA Escalation Triggered"),
                "level": f"Level {self.sequence}: {header}",
                "escalated": _("Escalated to"),
                "users": ", ".join(escalation_users.mapped("name")),
            }
            doc.message_post(
                body=body,
                partner_ids=partner_ids,
                subtype_xmlid="ae_approval_matrix.mt_approval_requested",
            )
            if self.matrix_id and self.matrix_id.create_activity and hasattr(doc, "activity_schedule"):
                act_type = self.matrix_id.activity_type_id or self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
                if act_type:
                    for user in new_users:
                        doc.activity_schedule(
                            activity_type_id=act_type.id,
                            summary=_("Escalated Approval Needed: %s") % header,
                            note=_("Approval escalated due to SLA timeout on Level %s (%s).") % (self.sequence, header),
                            user_id=user.id,
                        )
        self._bus_notify()

    def _execute_sla_auto_approve(self):
        self.ensure_one()
        self._close_all_activities()
        self.write({
            "status": "approved",
            "action_datetime": fields.Datetime.now(),
            "comment": _("Auto-approved due to SLA timeout."),
        })
        doc = self._get_document(sudo=False)
        has_next = self._activate_next_pending()
        is_final = False
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
        if doc:
            doc.invalidate_recordset()

        doc_sudo = self._get_document(sudo=True)
        if doc_sudo and hasattr(doc_sudo, "message_post"):
            header = self.name or self.approval_header or _("Level %s", self.sequence)
            body = Markup(
                '<div class="border-start border-3 border-info ps-2">'
                '<div class="fw-bold text-info">%(title)s</div>'
                '<div class="small text-muted mt-1">%(level)s</div>'
                '</div>'
            ) % {
                "title": _("SLA Auto-Approved / Bypassed"),
                "level": f"Level {self.sequence}: {header}",
            }
            doc_sudo.message_post(
                body=body,
                subtype_xmlid="ae_approval_matrix.mt_approval_approved",
            )
        self._bus_notify()
        if is_final and doc:
            matrix = self.matrix_id
            if matrix and matrix.auto_confirm_button_id:
                self._execute_auto_confirm(doc)
