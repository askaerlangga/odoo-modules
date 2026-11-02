import logging
from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

_BASE_IGNORED_FIELDS = {
    "message_follower_ids",
    "message_ids",
    "activity_ids",
    "access_token",
    "message_main_attachment_id",
    "write_date",
    "write_uid",
}


def _merge_view_fields(all_models: dict, new_models: dict):
    """Merge new_models into all_models dictionary."""
    for model, view_fields in new_models.items():
        if model in all_models:
            all_models[model] = tuple(set(all_models[model]) | set(view_fields))
        else:
            all_models[model] = tuple(view_fields)


class BaseModelExtend(models.AbstractModel):
    _inherit = "base"

    approval_state = fields.Selection(
        selection="_get_approval_state_selection",
        compute="_compute_approval_state",
        string="Approval Status",
    )
    approval_need_validation = fields.Boolean(
        compute="_compute_approval_state",
        string="Need Approval",
    )
    approval_user_can_approve = fields.Boolean(
        compute="_compute_approval_state",
        string="Can Approve",
    )
    approval_can_restart = fields.Boolean(
        compute="_compute_approval_state",
        string="Can Restart",
    )
    approval_next_review = fields.Char(
        compute="_compute_approval_state",
        string="Next Approver Level",
    )
    approval_review_ids = fields.One2many(
        "approval.review",
        inverse_name="res_id",
        string="Approval Reviews",
        domain=lambda self: [("res_model", "=", self._name)],
        auto_join=True,
    )

    @api.model
    def _get_approval_state_selection(self):
        return [
            ("draft", _("Draft")),
            ("waiting", _("Waiting")),
            ("pending", _("In Review")),
            ("approved", _("Approved")),
            ("rejected", _("Rejected")),
            ("cancel", _("Cancelled")),
        ]

    @api.depends_context("uid")
    def _compute_approval_state(self):
        active_models = self.env["approval.matrix"]._get_active_models_cache()
        if self._name not in active_models:
            for rec in self:
                rec.approval_state = "draft"
                rec.approval_need_validation = False
                rec.approval_user_can_approve = False
                rec.approval_can_restart = False
                rec.approval_next_review = False
            return

        user = self.env.user
        uid = user.id
        is_mgr = user.has_group("ae_approval_matrix.group_approval_manager")
        Matrix = self.env["approval.matrix"].sudo()
        candidate_matrices = Matrix.search([
            ("res_model", "=", self._name),
            ("active", "=", True),
        ], order="sequence asc")
        # Evaluate every matrix domain once for the whole batch (list views).
        matches_by_rec = Matrix.find_matching_matrices_batch(self, candidate_matrices)

        for rec in self:
            if not rec.id or not isinstance(rec.id, int):
                # Unsaved (new) record: still evaluate the matrix so that
                # hidden buttons (e.g. Confirm) stay hidden on "New".
                # The state is NOT checked here: during the initial onchange the
                # compute runs before default values (e.g. state='draft') are
                # applied, and a new record is by definition in its initial state.
                rec.approval_state = "draft"
                rec.approval_need_validation = bool(matches_by_rec.get(rec.id))
                rec.approval_user_can_approve = False
                rec.approval_can_restart = False
                rec.approval_next_review = False
                continue

            reviews = rec.approval_review_ids
            matching_matrices = matches_by_rec.get(rec.id, Matrix)
            if not reviews:
                if matching_matrices:
                    matrix = matching_matrices[0]
                    state_fname = matrix.state_field_id.name if matrix.state_field_id else "state"
                    doc_state = str(rec[state_fname]) if state_fname in rec._fields else False
                    source_states = set(matrix.source_state_ids.mapped("value"))
                    need_val = not source_states or doc_state in source_states
                else:
                    need_val = False

                rec.approval_need_validation = need_val
                rec.approval_state = "draft"
                rec.approval_user_can_approve = False
                rec.approval_can_restart = False
                rec.approval_next_review = False
            else:
                rec.approval_need_validation = True
                statuses = reviews.mapped("status")
                matrix = (
                    reviews[0].sudo().matrix_id
                    or (matching_matrices[0] if matching_matrices else False)
                )
                if matrix:
                    matrix = matrix.sudo()
                state_fname = matrix.state_field_id.name if matrix and matrix.state_field_id else "state"
                doc_state = str(rec[state_fname]) if state_fname in rec._fields else False
                target_states = set(matrix.target_state_ids.mapped("value")) if matrix else set()
                cancel_states = set(matrix.cancel_state_ids.mapped("value")) if matrix else set()

                if doc_state in cancel_states or all(s == "cancel" for s in statuses):
                    rec.approval_state = "cancel"
                    rec.approval_user_can_approve = False
                    rec.approval_can_restart = False
                    rec.approval_next_review = False
                elif "rejected" in statuses:
                    rec.approval_state = "rejected"
                    rec.approval_user_can_approve = False
                    creator_uid = getattr(rec, "create_uid", None)
                    rec.approval_can_restart = bool((creator_uid and creator_uid.id == uid) or is_mgr)
                    rec.approval_next_review = False
                elif all(s == "approved" for s in statuses):
                    rec.approval_state = "approved"
                    rec.approval_user_can_approve = False
                    if doc_state not in target_states:
                        creator_uid = getattr(rec, "create_uid", None)
                        rec.approval_can_restart = bool((creator_uid and creator_uid.id == uid) or is_mgr)
                    else:
                        rec.approval_can_restart = False
                    rec.approval_next_review = False
                elif "pending" in statuses:
                    rec.approval_state = "pending"
                    pending = reviews.filtered(lambda r: r.status == "pending")
                    rec.approval_user_can_approve = any(r.user_can_approve for r in pending)
                    rec.approval_can_restart = is_mgr
                    rec.approval_next_review = (
                        pending[0].name or pending[0].approval_header or _("Level %d") % pending[0].sequence
                    )
                else:
                    rec.approval_state = "waiting"
                    rec.approval_user_can_approve = False
                    rec.approval_can_restart = is_mgr
                    waiting = reviews.filtered(lambda r: r.status == "waiting")
                    rec.approval_next_review = (
                        (waiting[0].name or waiting[0].approval_header or _("Level %d") % waiting[0].sequence)
                        if waiting
                        else False
                    )

    # ─── Native Arch & Toolbar Injection via get_views / get_view ───
    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options=options)
        if self._name and not self.env.context.get("skip_approval_inject"):
            Matrix = self.env["approval.matrix"]
            if self._name in Matrix._get_active_models_cache():
                matrices = Matrix.sudo().search([
                    ("res_model", "=", self._name),
                    ("active", "=", True),
                ])
                hidden_names = set(matrices.mapped("hide_button_ids.name"))
                hidden_strings = set(matrices.mapped("hide_button_ids.string"))

                for v_info in res.get("views", {}).values():
                    toolbar = v_info.get("toolbar")
                    if toolbar and "action" in toolbar:
                        filtered = []
                        for act in toolbar["action"]:
                            act_name = act.get("name")
                            act_id = str(act.get("id"))
                            xml_id = act.get("xml_id")
                            if (
                                act_name in hidden_names
                                or act_name in hidden_strings
                                or act_id in hidden_names
                                or (xml_id and xml_id in hidden_names)
                            ):
                                continue
                            filtered.append(act)
                        toolbar["action"] = filtered
        return res

    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        res = super().get_view(view_id=view_id, view_type=view_type, **options)
        if self._name and not self.env.context.get("skip_approval_inject"):
            Matrix = self.env["approval.matrix"]
            if self._name in Matrix._get_active_models_cache():
                display = Matrix._get_display_models_cache()
                if view_type == "form":
                    # With the form display disabled only the approval buttons are
                    # skipped; banner, history and the hide_button_ids guard remain.
                    res = self._inject_approval_view_arch(
                        res, guard_only=self._name not in display["form"], **options
                    )
                elif (
                    view_type in ("list", "tree")
                    and self._name in display["list"]
                    and (
                        options.get("action_id")
                        or not (
                            self.env.context.get("is_dialog")
                            or self.env.context.get("select_create")
                            or options.get("embedded")
                        )
                    )
                ):
                    res = self._inject_approval_list_arch(res, **options)
        return res

    @api.model
    def _inject_approval_list_arch(self, res, **options):
        """Add the approval status badge and per-row action buttons to a main list view."""
        View = self.env["ir.ui.view"]
        doc = etree.XML(res["arch"])
        if doc.tag not in ("tree", "list"):
            return res
        all_models = dict(res.get("models", {}))

        def _render(template):
            node = etree.fromstring(self.env["ir.qweb"]._render(template))
            arch, models_ = View.postprocess_and_fields(node, model=self._name)
            _merge_view_fields(all_models, models_)
            return list(etree.fromstring(arch))

        for el in _render("ae_approval_matrix.approval_list_fields"):
            doc.append(el)
        for el in _render("ae_approval_matrix.approval_list_status"):
            doc.append(el)
        group = etree.SubElement(doc, "button_group")
        for el in _render("ae_approval_matrix.approval_list_buttons"):
            group.append(el)

        # Override buttons in tree: hide buttons configured in hide_button_ids while not approved
        matrices = self.env["approval.matrix"].sudo().search([
            ("res_model", "=", self._name),
            ("active", "=", True),
        ])
        hidden_buttons = set(matrices.mapped("hide_button_ids.name"))
        always_hidden_buttons = set(
            matrices.filtered(
                lambda m: (m.manual_domain or "[]").strip() in ("", "[]")
            ).mapped("hide_button_ids.name")
        )
        approval_btn_names = {
            "action_request_approval",
            "action_approve_matrix",
            "action_reject_matrix",
            "action_approve_workflow",
            "action_reject_workflow",
            "action_restart_approval",
            "action_view_approval_history",
        }
        for btn in doc.xpath(".//button"):
            name = btn.attrib.get("name")
            if name in approval_btn_names:
                continue
            # Header buttons in a tree view belong to the control panel (view level),
            # where per-record fields (approval_need_validation, approval_state, id) do not exist.
            # If configured in hide_button_ids, hide them globally via invisible="1".
            parent = btn.getparent()
            if parent is not None and parent.tag == "header":
                if name in hidden_buttons:
                    old_inv = btn.attrib.get("invisible")
                    guard = "(approval_need_validation and approval_state != 'approved')"
                    if old_inv:
                        btn.attrib["invisible"] = f"({old_inv}) or ({guard})"
                    else:
                        btn.attrib["invisible"] = guard
                continue
            if name in hidden_buttons:
                old_inv = btn.attrib.get("invisible")
                if name in always_hidden_buttons:
                    guard = "((approval_need_validation or not id) and approval_state != 'approved')"
                else:
                    guard = "(approval_need_validation and approval_state != 'approved')"
                if old_inv:
                    btn.attrib["invisible"] = f"({old_inv}) or ({guard})"
                else:
                    btn.attrib["invisible"] = guard

        if any(m.hide_list_custom_buttons for m in matrices):
            existing_cls = doc.attrib.get("class", "")
            if "ae_hide_list_custom_buttons" not in existing_cls:
                doc.attrib["class"] = f"{existing_cls} ae_hide_list_custom_buttons".strip()

        self._inject_approval_readonly_modifiers(doc)

        all_models[self._name] = tuple(set(all_models.get(self._name, ())) | {
            "approval_state",
            "approval_need_validation",
            "approval_user_can_approve",
            "approval_can_restart",
        })
        self._inject_approval_readonly_modifiers(doc)

        res_dict = dict(res)
        res_dict["arch"] = etree.tostring(doc, encoding="unicode")
        res_dict["models"] = {m: tuple(f) for m, f in all_models.items()}
        return res_dict

    @api.model
    def _inject_approval_readonly_modifiers(self, doc):
        """Inject dynamic readonly modifier on form and tree fields under approval validation."""
        exempt_fields = _BASE_IGNORED_FIELDS | {
            "approval_state",
            "approval_need_validation",
            "approval_user_can_approve",
            "approval_can_restart",
            "approval_next_review",
            "approval_review_ids",
        }
        exc_records = self.env["approval.exception"].sudo().search([
            ("model_name", "=", self._name),
            ("allow_write_under_validation", "=", True),
        ])
        exempt_fields |= set(exc_records.mapped("field_ids.name"))

        guard_expr = "approval_state in ('waiting', 'pending')"

        for field_node in doc.xpath(".//field"):
            # Only target direct fields of this model, not nested relational subviews
            if field_node.xpath("ancestor::field"):
                continue
            parent = field_node.getparent()
            if parent is not None and parent.tag == "header":
                continue
            fname = field_node.attrib.get("name")
            if not fname or fname not in self._fields or fname in exempt_fields:
                continue
            # Skip statically invisible fields
            if (
                field_node.attrib.get("invisible") in ("1", "True", "true")
                or field_node.attrib.get("column_invisible") in ("1", "True", "true")
            ):
                continue
            curr_ro = field_node.attrib.get("readonly")
            if curr_ro in ("1", "True", "true"):
                continue
            if curr_ro:
                field_node.attrib["readonly"] = f"({curr_ro}) or ({guard_expr})"
            else:
                field_node.attrib["readonly"] = guard_expr

    @api.model
    def _inject_approval_view_arch(self, res, guard_only=False, **options):
        """Inject approval elements in a form; ``guard_only`` skips the approval buttons."""
        View = self.env["ir.ui.view"]
        doc = etree.XML(res["arch"])
        all_models = dict(res.get("models", {}))

        # 1. Header Buttons & Statusbar
        header_nodes = doc.xpath("/form/header")
        if not header_nodes:
            header_node = etree.Element("header")
            doc.insert(0, header_node)
        else:
            header_node = header_nodes[0]

        if guard_only:
            # No approval buttons in the form: only add the (invisible) fields needed
            # by the button guard, the banner and the history below.
            for fname in (
                "approval_state",
                "approval_need_validation",
                "approval_user_can_approve",
                "approval_can_restart",
                "approval_next_review",
            ):
                etree.SubElement(header_node, "field", {"name": fname, "invisible": "1"})
        else:
            btn_xml = self.env["ir.qweb"]._render("ae_approval_matrix.approval_buttons")
            btn_node = etree.fromstring(btn_xml)
            btn_arch, btn_models = View.postprocess_and_fields(btn_node, model=self._name)
            processed_btn_node = etree.fromstring(btn_arch)

            existing_buttons = header_node.xpath("./button[last()]")
            if existing_buttons:
                target = existing_buttons[0]
                for el in reversed(list(processed_btn_node)):
                    target.addnext(el)
            else:
                for el in processed_btn_node:
                    header_node.append(el)
            _merge_view_fields(all_models, btn_models)

        # 2. Alert Banner above /form/sheet
        sheet_nodes = doc.xpath("/form/sheet")
        if sheet_nodes:
            sheet_node = sheet_nodes[0]
            alert_xml = self.env["ir.qweb"]._render("ae_approval_matrix.approval_label")
            alert_node = etree.fromstring(alert_xml)
            alert_arch, alert_models = View.postprocess_and_fields(alert_node, model=self._name)
            processed_alert_node = etree.fromstring(alert_arch)
            for el in processed_alert_node:
                sheet_node.addprevious(el)
            _merge_view_fields(all_models, alert_models)

            # 3. Review Table inside Notebook or Sheet
            review_xml = self.env["ir.qweb"]._render("ae_approval_matrix.approval_reviews")
            review_node = etree.fromstring(review_xml)
            rev_arch, rev_models = View.postprocess_and_fields(review_node, model=self._name)
            processed_rev_node = etree.fromstring(rev_arch)

            notebook_nodes = sheet_node.xpath("./notebook")
            if notebook_nodes:
                page = etree.Element("page", {
                    "string": _("Approval History"),
                    "name": "approval_reviews",
                    "invisible": "not approval_review_ids",
                })
                for child in list(processed_rev_node):
                    page.append(child)
                notebook_nodes[0].append(page)
            else:
                for child in list(processed_rev_node):
                    sheet_node.append(child)
            _merge_view_fields(all_models, rev_models)

        # 4. Override header buttons: hide standard buttons while document is under approval
        matrices = self.env["approval.matrix"].sudo().search([
            ("res_model", "=", self._name),
            ("active", "=", True),
        ])
        hidden_buttons = set(matrices.mapped("hide_button_ids.name"))
        # Buttons hidden by a matrix without domain condition: such a matrix always
        # applies, so the button must also be hidden on unsaved (new) records, for
        # which the computed approval_need_validation is reset to False by the
        # initial onchange.
        always_hidden_buttons = set(
            matrices.filtered(
                lambda m: (m.manual_domain or "[]").strip() in ("", "[]")
            ).mapped("hide_button_ids.name")
        )
        approval_btn_names = {
            "action_request_approval",
            "action_approve_matrix",
            "action_reject_matrix",
            "action_approve_workflow",
            "action_reject_workflow",
            "action_restart_approval",
            "action_view_approval_history",
        }
        for btn in header_node.xpath(".//button"):
            name = btn.attrib.get("name")
            if name in approval_btn_names:
                continue
            old_inv = btn.attrib.get("invisible")
            if name in always_hidden_buttons:
                guard = "((approval_need_validation or not id) and approval_state != 'approved')"
            elif name in hidden_buttons:
                guard = "(approval_need_validation and approval_state != 'approved')"
            else:
                guard = "approval_state in ('waiting', 'pending', 'rejected')"

            if old_inv:
                btn.attrib["invisible"] = f"({old_inv}) or ({guard})"
            else:
                btn.attrib["invisible"] = guard

        approval_fields = {
            "approval_state",
            "approval_need_validation",
            "approval_user_can_approve",
            "approval_can_restart",
            "approval_next_review",
            "approval_review_ids",
        }
        all_models[self._name] = tuple(set(all_models.get(self._name, ())) | approval_fields)

        self._inject_approval_readonly_modifiers(doc)

        res_dict = dict(res)
        res_dict["arch"] = etree.tostring(doc, encoding="unicode")
        res_dict["models"] = {m: tuple(f) for m, f in all_models.items()}
        return res_dict

    # ─── Native Object Action Methods ───
    def action_request_approval(self):
        """Native button click handler for 'Request Approval'."""
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")

        matrices = self.env["approval.matrix"].sudo().find_matching_matrices(self._name, self)
        if not matrices:
            raise UserError(_("No active approval matrix matches this document."))

        existing = self.env["approval.review"].sudo().search_count([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("status", "in", ["waiting", "pending", "approved"]),
        ])
        if existing:
            raise UserError(_("An approval process is already active for this document."))

        matrix = matrices[0]
        created_reviews = matrix.generate_reviews(self)
        if not created_reviews:
            raise UserError(_("No approval levels were generated for this approval matrix."))

        sorted_reviews = created_reviews.sorted("sequence")
        if matrix.approve_sequence:
            min_seq = sorted_reviews[0].sequence
            initial_reviews = sorted_reviews.filtered(lambda r: r.sequence == min_seq)
        else:
            initial_reviews = sorted_reviews

        initial_reviews.sudo().write({"status": "pending"})
        for rev in initial_reviews:
            if matrix.notify_on_create:
                rev._send_request_notification()
            if matrix.create_activity:
                rev._create_scheduled_activities()
            rev._bus_notify()

        self._on_approval_requested()
        self.invalidate_recordset()
        return True

    def action_approve_matrix(self):
        """Native button click handler for 'Approve'."""
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")

        reviews = self.approval_review_ids.filtered(lambda r: r.user_can_approve)
        if not reviews:
            raise UserError(_("You have no pending approval action for this document."))
        review = reviews[0]
        matrix = review.matrix_id or review.workflow_id
        if matrix and matrix.require_approve_comment:
            return {
                "name": _("Approve Document"),
                "type": "ir.actions.act_window",
                "res_model": "approval.comment.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {
                    "default_res_model": self._name,
                    "default_res_id": self.id,
                    "default_review_id": review.id,
                    "default_action_type": "approve",
                },
            }
        review.action_approve()
        self.invalidate_recordset()
        return True

    action_approve_workflow = action_approve_matrix

    def action_reject_matrix(self):
        """Native button click handler for 'Reject'."""
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")

        reviews = self.approval_review_ids.filtered(lambda r: r.user_can_approve)
        if not reviews:
            raise UserError(_("You have no pending approval action for this document."))
        return {
            "name": _("Reject Document"),
            "type": "ir.actions.act_window",
            "res_model": "approval.comment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_review_id": reviews[0].id,
                "default_action_type": "reject",
            },
        }

    action_reject_workflow = action_reject_matrix

    def action_view_approval_history(self):
        """Open a modal window showing the approval review history for this document."""
        self.ensure_one()
        view_tree_id = self.env.ref("ae_approval_matrix.view_approval_review_tree_dialog").id
        view_form_id = self.env.ref("ae_approval_matrix.view_approval_review_form").id
        doc_name = self.display_name or (getattr(self, "name", None)) or f"{self._name},{self.id}"
        return {
            "name": _("Approval History - %s") % doc_name,
            "type": "ir.actions.act_window",
            "res_model": "approval.review",
            "view_mode": "tree,form",
            "views": [(view_tree_id, "tree"), (view_form_id, "form")],
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "target": "new",
            "context": {
                "create": False,
                "edit": False,
                "delete": False,
                "is_dialog": True,
            },
        }

    def action_restart_approval(self):
        """Native button click handler for 'Restart Validation'."""
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")

        if not self.approval_can_restart:
            raise AccessError(_("You are not authorized to restart validation for this document."))

        reviews = self.env["approval.review"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        for rev in reviews:
            rev._close_all_activities()
        reviews.unlink()

        self._on_approval_reset()
        self.invalidate_recordset()
        self.env["approval.review"]._bus_notify()
        return True

    # ─── Write Guard Engine ───
    def write(self, vals):
        active_models = self.env["approval.matrix"]._get_active_models_cache()
        if self._name not in active_models or self.env.context.get("skip_approval_check"):
            return super().write(vals)

        Matrix = self.env["approval.matrix"].sudo()
        candidate_matrices = Matrix.search([
            ("res_model", "=", self._name),
            ("active", "=", True),
        ], order="sequence asc")

        # Capture pre-write status for non-state lifecycle handling
        pre_write_status = {
            rec.id: (rec.approval_state, bool(rec.approval_review_ids))
            for rec in self
        }

        for rec in self:
            rec._check_approval_write_guard(vals, candidate_matrices=candidate_matrices)

        res = super().write(vals)

        # ─── Post-Write Lifecycle for Non-State Models (e.g. stock.quant) ───
        ignored = _BASE_IGNORED_FIELDS | {"write_date", "write_uid", "create_date", "create_uid"}
        modified_fields = {
            f for f in (set(vals.keys()) - ignored)
            if f in self._fields and self._fields[f].store
        }

        if modified_fields:
            for rec in self:
                old_status, had_reviews = pre_write_status.get(rec.id, (False, False))
                if not had_reviews:
                    continue

                matching = Matrix.find_matching_matrices(self._name, rec, matrices=candidate_matrices)
                matrix = matching[0] if matching else False
                state_fname = matrix.state_field_id.name if matrix and matrix.state_field_id else "state"

                # Check if this model lacks state management
                if not state_fname or state_fname not in rec._fields:
                    existing_reviews = self.env["approval.review"].sudo().search([
                        ("res_model", "=", rec._name),
                        ("res_id", "=", rec.id),
                    ])
                    if not matching:
                        # Auto-Consume: Record no longer matches the matrix domain (e.g. Applied or Cleared)
                        if existing_reviews:
                            for rev in existing_reviews:
                                rev._close_all_activities()
                            existing_reviews.unlink()
                            rec._on_approval_reset()
                            rec.env["approval.review"]._bus_notify()
                    elif old_status == "approved":
                        # Auto-Void: Record was approved, but adjustment values were modified while still matching matrix
                        if existing_reviews:
                            for rev in existing_reviews:
                                rev._close_all_activities()
                            existing_reviews.unlink()
                            rec._on_approval_reset()
                            if hasattr(rec, "message_post"):
                                try:
                                    body = Markup(
                                        '<div class="border-start border-3 border-primary ps-2">'
                                        '<div class="fw-bold text-primary">%(title)s</div>'
                                        '<div class="small text-muted">%(reason)s</div>'
                                        '</div>'
                                    ) % {
                                        "title": _("Approval Reset"),
                                        "reason": _("Values modified after approval."),
                                    }
                                    rec.message_post(
                                        body=body,
                                        message_type="notification",
                                        subtype_xmlid="ae_approval_matrix.mt_approval_reset",
                                    )
                                except Exception:
                                    pass
                            rec.env["approval.review"]._bus_notify()

        self.invalidate_recordset([
            "approval_state",
            "approval_need_validation",
            "approval_user_can_approve",
            "approval_can_restart",
            "approval_next_review",
        ])
        return res

    def _check_approval_write_guard(self, vals, candidate_matrices=None):
        """Guard method transitions and field edits for models with approval matrices."""
        self.ensure_one()
        matrices = self.env["approval.matrix"].sudo().find_matching_matrices(
            self._name, self, matrices=candidate_matrices
        )
        if not matrices:
            return

        matrix = matrices[0]
        state_fname = matrix.state_field_id.name if matrix.state_field_id else "state"
        status = self.approval_state

        if state_fname in vals:
            new_state = str(vals[state_fname])
            curr_state = str(self[state_fname]) if state_fname in self._fields else False
            source_states = set(matrix.source_state_ids.mapped("value"))
            target_states = set(matrix.target_state_ids.mapped("value"))
            cancel_states = set(matrix.cancel_state_ids.mapped("value"))

            # 1. Return to initial/source state (e.g. Set to Quotation / Reset to Draft)
            is_return_to_source = False
            if source_states:
                if new_state in source_states and curr_state not in source_states:
                    is_return_to_source = True
            elif curr_state in (cancel_states | target_states) and (
                new_state in ("draft", "quotation") or new_state not in (cancel_states | target_states)
            ):
                is_return_to_source = True

            if is_return_to_source:
                existing_reviews = self.env["approval.review"].sudo().search([
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                ])
                if existing_reviews:
                    for rev in existing_reviews:
                        rev._close_all_activities()
                    existing_reviews.unlink()
                    self._on_approval_reset()
                    if hasattr(self, "message_post"):
                        try:
                            body = Markup(
                                '<div class="border-start border-3 border-primary ps-2">'
                                '<div class="fw-bold text-primary">%(title)s</div>'
                                '<div class="small text-muted">%(reason)s</div>'
                                '</div>'
                            ) % {
                                "title": _("Approval Reset"),
                                "reason": _("Returned to draft/quotation."),
                            }
                            self.message_post(
                                body=body,
                                message_type="notification",
                                subtype_xmlid="ae_approval_matrix.mt_approval_reset",
                            )
                        except Exception:
                            pass
                    self.invalidate_recordset()
                    self.env["approval.review"]._bus_notify()
                return

            # 2. Cancel transition
            if new_state in cancel_states:
                active_reviews = self.env["approval.review"].sudo().search([
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("status", "in", ["waiting", "pending"]),
                ])
                if active_reviews:
                    active_reviews.write({"status": "cancel"})
                    for rev in active_reviews:
                        rev._close_all_activities()
                return

            # 3. Target transition without approval
            if new_state in target_states and curr_state not in target_states:
                if status != "approved":
                    raise ValidationError(
                        _("Approval is required before confirming this document.\n"
                          "Current status: %s.\n"
                          "Please click 'Request Approval' and complete all required approval levels.")
                        % status.capitalize()
                    )
                return

        self._check_approval_write_allowed(vals, matrix, status)

    def _check_approval_write_allowed(self, vals, matrix, status):
        """Enforces field locking under validation or after validation."""
        self.ensure_one()
        if status not in ("waiting", "pending", "approved"):
            return

        state_fname = matrix.state_field_id.name if matrix.state_field_id else "state"
        if not state_fname or state_fname not in self._fields:
            # Models without a state field (or matrix without state tracking) use approval
            # to authorize action execution. Field edits are locked while validation is pending,
            # but once approved, the action is permitted to apply/write its changes.
            if status == "approved":
                return
            state_fname = False
        else:
            curr_state = str(self[state_fname])
            target_states = set(matrix.target_state_ids.mapped("value"))
            cancel_states = set(matrix.cancel_state_ids.mapped("value"))

            if curr_state in (target_states | cancel_states):
                exceptions = self.env["approval.exception"].sudo().search([
                    ("model_name", "=", self._name),
                    ("allow_write_after_validation", "=", True),
                ])
                if not exceptions:
                    return

        ignored = _BASE_IGNORED_FIELDS | ({state_fname} if state_fname else set())
        modified_fields = {
            f for f in (set(vals.keys()) - ignored)
            if f in self._fields and self._fields[f].store
        }
        if not modified_fields:
            return

        domain = [("model_name", "=", self._name)]
        if status in ("waiting", "pending"):
            domain.append(("allow_write_under_validation", "=", True))
        elif status == "approved":
            domain.append(("allow_write_after_validation", "=", True))

        exceptions = self.env["approval.exception"].sudo().search(domain)
        user_groups = self.env.user.groups_id.ids
        allowed_fields = set()
        for exc in exceptions:
            if not exc.group_ids or any(g in user_groups for g in exc.group_ids.ids):
                allowed_fields.update(exc.field_ids.mapped("name"))

        blocked = modified_fields - allowed_fields
        if blocked:
            field_labels = [self._fields[f].string or f for f in blocked if f in self._fields]
            phase_name = (
                _("while validation is pending")
                if status in ("waiting", "pending")
                else _("after the document is approved")
            )
            raise ValidationError(
                _("The following fields cannot be modified %s:\n- %s\n\n"
                  "If you need to make changes, please restart validation or contact an administrator.")
                % (phase_name, "\n- ".join(field_labels))
            )

    # ─── Developer Hook Placeholders ───
    def _on_approval_requested(self):
        """Hook called immediately after approval is requested."""
        pass

    def _on_approval_approved(self):
        """Hook called when the final approval level is reached and document is approved."""
        pass

    def _on_approval_rejected(self, reason=False):
        """Hook called when any reviewer rejects the document."""
        pass

    def _on_approval_reset(self):
        """Hook called when validation is restarted or reset."""
        pass
