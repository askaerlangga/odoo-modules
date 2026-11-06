from odoo import _, api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _get_actionable_pending_reviews(self):
        """Return recordset of pending approval reviews actionable by the active user (including delegations)."""
        uid = self.env.user.id
        delegator_uids = self.env["approval.delegate"]._get_delegator_uids_for_user(uid)
        candidate_uids = list({uid} | delegator_uids)
        candidates = self.env["approval.review"].search(
            [
                ("approver_ids", "in", candidate_uids),
                ("status", "=", "pending"),
                ("approved_by_ids", "not in", [uid]),
                ("rejected_by_ids", "not in", [uid]),
            ],
            order="write_date desc, id desc",
        )
        return candidates.filtered(lambda r: r.user_can_approve)

    @api.model
    def get_approval_review_count(self):
        """Returns the number of reviews currently pending action by the active user."""
        return len(self._get_actionable_pending_reviews())

    @api.model
    def get_pending_approval_reviews(self, limit=10):
        """Returns pending approval reviews and count for active user popup preview."""
        actionable = self._get_actionable_pending_reviews()
        count = len(actionable)
        reviews = actionable[:limit]

        now = fields.Datetime.now()
        items = []
        for r in reviews:
            # Model human name (use sudo for ir.model access)
            model_name = r.sudo().res_model_id.name if r.res_model_id else (r.res_model or "Document")
            doc_name = r.res_name or f"{model_name} #{r.res_id}"

            # Calculate relative time string
            dt = r.write_date or r.create_date
            time_ago = ""
            if dt:
                diff = now - dt
                secs = int(diff.total_seconds())
                if secs < 60:
                    time_ago = _("Just now")
                elif secs < 3600:
                    mins = secs // 60
                    time_ago = _("%d minutes ago") % mins if mins > 1 else _("1 minute ago")
                elif secs < 86400:
                    hrs = secs // 3600
                    time_ago = _("%d hours ago") % hrs if hrs > 1 else _("1 hour ago")
                elif diff.days == 1:
                    time_ago = _("Yesterday")
                elif diff.days < 30:
                    time_ago = _("%d days ago") % diff.days
                elif diff.days < 365:
                    months = diff.days // 30
                    time_ago = _("%d months ago") % months if months > 1 else _("1 month ago")
                else:
                    years = diff.days // 365
                    time_ago = _("%d years ago") % years if years > 1 else _("1 year ago")

            items.append({
                "id": r.id,
                "res_model": r.res_model,
                "res_id": r.res_id,
                "res_name": doc_name,
                "model_name": model_name,
                "name": r.name or f"Level {r.sequence}",
                "sequence": r.sequence,
                "minimum_approved": r.minimum_approved,
                "approved_count": r.approved_count,
                "time_ago": time_ago,
            })

        return {
            "count": count,
            "reviews": items,
        }
