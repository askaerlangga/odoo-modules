import logging
from ast import literal_eval
from lxml import etree

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ApprovalMatrixStateOption(models.Model):
    _name = "approval.matrix.state.option"
    _description = "Document State Option"
    _order = "name, value"

    model_id = fields.Many2one("ir.model", string="Model", required=True, ondelete="cascade")
    value = fields.Char(string="Technical Value", required=True)
    name = fields.Char(string="Display Label", required=True)

    _model_val_unique = models.Constraint(
        "UNIQUE(model_id, value)",
        "State value must be unique per model.",
    )

    @api.depends("name", "value")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.value})" if rec.value else (rec.name or "")


class ApprovalMatrixButtonOption(models.Model):
    _name = "approval.matrix.button.option"
    _description = "Document Header Button Option"
    _order = "string, name"

    model_id = fields.Many2one("ir.model", string="Model", required=True, ondelete="cascade")
    name = fields.Char(string="Button Method/Action", required=True)
    string = fields.Char(string="Button Label", required=True)

    _model_btn_unique = models.Constraint(
        "UNIQUE(model_id, name)",
        "Button must be unique per model.",
    )

    @api.depends("string", "name")
    def _compute_display_name(self):
        for rec in self:
            if rec.string and rec.name and rec.string != rec.name:
                rec.display_name = f"{rec.string} ({rec.name})"
            else:
                rec.display_name = rec.string or rec.name or ""


class ApprovalMatrix(models.Model):
    _name = "approval.matrix"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Approval Matrix"
    _order = "sequence, name"

    name = fields.Char(string="Matrix Name", required=True, tracking=True)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.company,
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Document Model",
        required=True,
        ondelete="cascade",
        domain="[('transient', '=', False)]",
        tracking=True,
    )
    res_model = fields.Char(
        string="Model Name",
        related="model_id.model",
        store=True,
        readonly=True,
        index=True,
    )

    # ─── State & Button Scanner Configuration ───
    state_field_id = fields.Many2one(
        "ir.model.fields",
        string="State Field",
        domain="[('model_id', '=', model_id), ('ttype', '=', 'selection')]",
        help="Selection field representing the document state (usually 'state').",
    )
    source_state_ids = fields.Many2many(
        "approval.matrix.state.option",
        "approval_matrix_source_state_rel",
        "matrix_id",
        "state_id",
        string="Initial / Draft States",
        domain="[('model_id', '=', model_id)]",
        help="States where 'Request Approval' is allowed and validation is required before proceeding.",
    )
    target_state_ids = fields.Many2many(
        "approval.matrix.state.option",
        "approval_matrix_target_state_rel",
        "matrix_id",
        "state_id",
        string="Target / Confirmed States",
        domain="[('model_id', '=', model_id)]",
        help="States that require 'Approved' status before transition is permitted.",
    )
    cancel_state_ids = fields.Many2many(
        "approval.matrix.state.option",
        "approval_matrix_cancel_state_rel",
        "matrix_id",
        "state_id",
        string="Cancel States",
        domain="[('model_id', '=', model_id)]",
        help="States that automatically cancel pending/waiting approval reviews.",
    )
    hide_button_ids = fields.Many2many(
        "approval.matrix.button.option",
        "approval_matrix_hide_btn_rel",
        "matrix_id",
        "button_id",
        string="Hide Buttons Before Approval",
        domain="[('model_id', '=', model_id)]",
        help="Buttons in the document header hidden while validation is required and not yet approved.",
    )
    auto_confirm_button_id = fields.Many2one(
        "approval.matrix.button.option",
        string="Trigger Button on Approved",
        domain="[('model_id', '=', model_id)]",
        help="Optional header button/method to execute automatically once all approval levels are approved. Leave empty to confirm manually.",
    )
    auto_reject_button_id = fields.Many2one(
        "approval.matrix.button.option",
        string="Trigger Button on Rejected",
        domain="[('model_id', '=', model_id)]",
        help="Optional button/method to execute automatically when the document is rejected (e.g. action_cancel). Leave empty to handle manually.",
    )

    # ─── Display Options ───
    show_in_form = fields.Boolean(
        string="Show in Form View",
        default=True,
        help="Inject approval buttons, banner and history into the form view of the document.",
    )
    show_in_list = fields.Boolean(
        string="Show in List View",
        default=True,
        help="Inject approval status and per-row action buttons into the main list view of the document.",
    )
    hide_list_custom_buttons = fields.Boolean(
        string="Hide Extra List Buttons",
        default=False,
        help="Hide custom action buttons in the list view control panel beside the 'New' button when this matrix is active.",
    )

    # ─── Condition Engine ───
    manual_domain = fields.Char(
        string="Trigger Domain Filter",
        help="Standard Odoo domain evaluated against documents to check whether this matrix applies.",
        default="[]",
    )

    # ─── Approval Levels ───
    approver_ids = fields.One2many(
        "approval.matrix.approver", "matrix_id", string="Approval Levels", copy=True
    )

    # ─── Matrix Execution Options ───
    approve_sequence = fields.Boolean(
        string="Approve by Sequence",
        default=True,
        help="Enforce reviewers to approve sequentially level by level.",
    )
    approve_sequence_bypass = fields.Boolean(
        string="Sequence Bypass",
        default=False,
        help="Automatically bypass later levels if already approved by the same user in an earlier level.",
    )
    require_approve_comment = fields.Boolean(
        string="Require Comment on Approve",
        default=False,
        help="If checked, clicking Approve prompts for a comment wizard. Otherwise, 1-click immediate approve.",
    )
    user_request_field_id = fields.Many2one(
        "ir.model.fields",
        string="Requester / Employee User Field",
        domain="[('model_id', '=', model_id), ('ttype', '=', 'many2one'), ('relation', 'in', ['res.users', 'hr.employee'])]",
        help="Field on the document identifying the requester (used for Department Manager and Direct Manager lookup).",
    )

    # ─── Notification & Activity Options ───
    notify_on_create = fields.Boolean(
        string="Notify on Request",
        default=True,
        help="Send Chatter notification to approvers when approval is requested.",
    )
    notify_on_pending = fields.Boolean(
        string="Notify When Turn Arrives",
        default=True,
        help="Send notification when a sequence level becomes pending.",
    )
    create_activity = fields.Boolean(
        string="Create Scheduled Activity",
        default=False,
        help="Automatically schedule a mail.activity for pending approvers and complete it once responded.",
    )
    activity_type_id = fields.Many2one(
        "mail.activity.type",
        string="Activity Type",
        domain="[('category', '!=', 'phonecall')]",
    )

    @api.model
    def _get_model_bridge_requirements(self):
        """Extensible registry mapping {res_model: (required_module_name, human_label)}."""
        return {
            "stock.quant": ("ae_approval_matrix_stock", _("Advanced Approval Matrix - Stock Inventory")),
        }

    @api.constrains("model_id")
    def _check_required_bridge_modules(self):
        bridge_requirements = self._get_model_bridge_requirements()
        for matrix in self:
            res_model = matrix.res_model or matrix.model_id.model
            if not res_model:
                continue
            req = bridge_requirements.get(res_model)
            if req:
                mod_name, mod_label = req
                mod = self.env["ir.module.module"].sudo().search([
                    ("name", "=", mod_name),
                    ("state", "=", "installed"),
                ], limit=1)
                if not mod:
                    raise ValidationError(_(
                        "The model '%(model)s' requires the bridge module '%(module)s' (%(label)s) to be installed.\n"
                        "Please install '%(module)s' before creating an Approval Matrix for this model."
                    ) % {
                        "model": matrix.model_id.name or res_model,
                        "module": mod_name,
                        "label": mod_label,
                    })

    @api.constrains("show_in_form", "show_in_list")
    def _check_display_locations(self):
        for rec in self:
            if not rec.show_in_form and not rec.show_in_list:
                raise ValidationError(_(
                    "At least one display location (Form or List) must be enabled, "
                    "otherwise users cannot request approval."
                ))

    @api.constrains("name", "company_id")
    def _check_name_company_unique(self):
        for rec in self:
            domain = [
                ("name", "=", rec.name),
                ("company_id", "=", rec.company_id.id),
                ("id", "!=", rec.id),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_("Approval matrix name must be unique per company."))

    _name_company_unique = models.Constraint(
        "UNIQUE(name, company_id)",
        "Approval matrix name must be unique per company.",
    )

    def _auto_init(self):
        from odoo.tools.sql import constraint_definition, drop_constraint
        # Drop legacy workflow constraints if they still exist in PostgreSQL
        for table, con in [
            ("approval_matrix", "approval_workflow_name_company_unique"),
            ("approval_matrix_state_option", "approval_workflow_state_option_model_val_unique"),
            ("approval_matrix_button_option", "approval_workflow_button_option_model_btn_unique"),
        ]:
            if constraint_definition(self.env.cr, table, con):
                drop_constraint(self.env.cr, table, con)
        self.env.cr.execute("""
            DELETE FROM ir_model_constraint
            WHERE name IN (
                'approval_workflow_name_company_unique',
                'approval_workflow_state_option_model_val_unique',
                'approval_workflow_button_option_model_btn_unique'
            )
        """)
        return super()._auto_init()

    # ─── Cache Management ───
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._clear_matrix_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._clear_matrix_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self._clear_matrix_cache()
        return res

    def copy(self, default=None):
        default = dict(default or {})
        if not default.get("name"):
            company_id = default.get("company_id", self.company_id.id)
            name = _("%s (copy)", self.name)
            while self.search_count([("name", "=", name), ("company_id", "=", company_id)]):
                name = _("%s (copy)", name)
            default["name"] = name
        return super().copy(default=default)

    @tools.ormcache()
    def _get_active_models_cache(self):
        """Returns set of res_model strings that have at least one active approval matrix."""
        return set(self.sudo().search([("active", "=", True)]).mapped("res_model"))

    @tools.ormcache()
    def _get_display_models_cache(self):
        """Returns {"form": set(res_model), "list": set(res_model)} for active matrices."""
        matrices = self.sudo().search([("active", "=", True)])
        return {
            "form": set(matrices.filtered("show_in_form").mapped("res_model")),
            "list": set(matrices.filtered("show_in_list").mapped("res_model")),
        }

    def _clear_matrix_cache(self):
        self.env.registry.clear_cache()

    # ─── Scanner & Metadata Population ───
    @api.onchange("model_id")
    def _onchange_model_id(self):
        if not self.model_id:
            return
        state_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.model_id.id),
            ("name", "=", "state"),
            ("ttype", "=", "selection"),
        ], limit=1)
        if state_field:
            self.state_field_id = state_field.id

        requester_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.model_id.id),
            ("name", "in", ["user_id", "employee_id", "create_uid"]),
            ("ttype", "=", "many2one"),
        ], order="id asc", limit=1)
        if requester_field:
            self.user_request_field_id = requester_field.id

        self.action_scan_model()

        res_model = self.res_model or self.model_id.model
        if res_model:
            req = self._get_model_bridge_requirements().get(res_model)
            if req:
                mod_name, mod_label = req
                mod = self.env["ir.module.module"].sudo().search([
                    ("name", "=", mod_name),
                    ("state", "=", "installed"),
                ], limit=1)
                if not mod:
                    return {
                        "warning": {
                            "title": _("Bridge Module Required"),
                            "message": _(
                                "To enable approval on '%(model)s', please ensure the bridge module "
                                "'%(module)s' (%(label)s) is installed."
                            ) % {
                                "model": self.model_id.name or res_model,
                                "module": mod_name,
                                "label": mod_label,
                            },
                        }
                    }

    def action_scan_model(self):
        """Scan model selection values and form header buttons (including inherited views)."""
        self.ensure_one()
        if not self.model_id or not self.res_model:
            return

        model_name = self.res_model
        if model_name not in self.env:
            return

        ModelObj = self.env[model_name]

        # 1. Scan state options
        if self.state_field_id:
            field_name = self.state_field_id.name
            field = ModelObj._fields.get(field_name)
            if field and field.type == "selection":
                sel_list = ModelObj.fields_get([field_name]).get(field_name, {}).get("selection", [])
                created_states = []
                for val, label in sel_list:
                    opt = self.env["approval.matrix.state.option"].sudo().search([
                        ("model_id", "=", self.model_id.id),
                        ("value", "=", str(val)),
                    ], limit=1)
                    if not opt:
                        opt = self.env["approval.matrix.state.option"].sudo().create({
                            "model_id": self.model_id.id,
                            "value": str(val),
                            "name": str(label),
                        })
                    created_states.append(opt)

                if not self.source_state_ids:
                    defaults = [s.id for s in created_states if s.value in ("draft", "sent", "to_approve")]
                    if defaults:
                        self.source_state_ids = [fields.Command.set(defaults)]
                if not self.target_state_ids:
                    defaults = [s.id for s in created_states if s.value in ("confirm", "confirmed", "sale", "purchase", "posted", "done")]
                    if defaults:
                        self.target_state_ids = [fields.Command.set(defaults)]
                if not self.cancel_state_ids:
                    defaults = [s.id for s in created_states if s.value in ("cancel", "cancelled")]
                    if defaults:
                        self.cancel_state_ids = [fields.Command.set(defaults)]

        # 2. Scan buttons from combined form and list views (with fallback to ir.ui.view records)
        found_buttons = {}
        arches = []
        for vtype in ("form", "list"):
            try:
                view_res = ModelObj.with_context(skip_approval_inject=True).get_view(view_type=vtype)
                if view_res and view_res.get("arch"):
                    arches.append(view_res["arch"])
            except Exception:
                pass

        views = self.env["ir.ui.view"].sudo().search([
            ("model", "=", model_name),
            ("type", "in", ("form", "list")),
        ], limit=20)
        for v in views:
            if v.arch and v.arch not in arches:
                arches.append(v.arch)

        ignored_btn_names = {
            "action_request_approval",
            "action_approve_matrix",
            "action_reject_matrix",
            "action_restart_approval",
            "action_view_approval_history",
        }
        for arch in arches:
            try:
                doc = etree.fromstring(arch)
                is_list = doc.tag in ("list", "tree")
                # Scan both header buttons and inline buttons
                for btn in doc.xpath(".//button"):
                    name = btn.attrib.get("name")
                    if not name or name.startswith("_") or name in ignored_btn_names:
                        continue
                    if btn.attrib.get("special") in ("cancel", "save"):
                        continue
                    raw_string = btn.attrib.get("string") or btn.attrib.get("title") or name
                    parent = btn.getparent()
                    is_header = parent is not None and parent.tag == "header"

                    if is_list:
                        suffix = " (Header)" if is_header else " (Row)"
                        label = raw_string if raw_string.endswith(suffix) else f"{raw_string}{suffix}"
                    else:
                        label = raw_string

                    if (
                        name not in found_buttons
                        or found_buttons[name] == name
                        or (is_list and ("(Header)" in label or "(Row)" in label))
                    ):
                        found_buttons[name] = label
            except etree.XMLSyntaxError:
                continue

        created_btns = []
        for btn_name, btn_string in found_buttons.items():
            opt = self.env["approval.matrix.button.option"].sudo().search([
                ("model_id", "=", self.model_id.id),
                ("name", "=", btn_name),
            ], limit=1)
            if not opt:
                opt = self.env["approval.matrix.button.option"].sudo().create({
                    "model_id": self.model_id.id,
                    "name": btn_name,
                    "string": btn_string,
                })
            elif opt.string != btn_string and btn_string != btn_name:
                opt.sudo().write({"string": btn_string})
            created_btns.append(opt)

        if not self.hide_button_ids and created_btns:
            defaults = [b.id for b in created_btns if any(k in b.name.lower() for k in ("confirm", "validate", "post", "approve", "apply"))]
            if defaults:
                self.hide_button_ids = [fields.Command.set(defaults)]

    # ─── Domain Matching ───
    def matches(self, record):
        self.ensure_one()
        domain_str = (self.manual_domain or "[]").strip()
        if not domain_str or domain_str == "[]":
            return True
        try:
            domain = literal_eval(domain_str)
        except (ValueError, SyntaxError):
            _logger.error("approval.matrix %s: cannot parse domain '%s'", self.name, domain_str)
            return False
        if not domain:
            return True
        return bool(record.filtered_domain(domain))

    @api.model
    def find_matching_matrices(self, res_model, record, matrices=None):
        comp = getattr(record, "company_id", False)
        if not comp:
            comp = self.env.company
        comp_id = comp.id if hasattr(comp, "id") else comp

        if matrices is None:
            matrices = self.sudo().search([
                ("res_model", "=", res_model),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", comp_id),
            ], order="sequence asc")
        else:
            matrices = matrices.filtered(
                lambda w: not w.company_id or w.company_id.id == comp_id
            )
        return matrices.filtered(lambda w: w.matches(record))

    def _filter_matching_records(self, records):
        """Return the subset of ``records`` matching this matrix' domain."""
        self.ensure_one()
        domain_str = (self.manual_domain or "[]").strip()
        if not domain_str or domain_str == "[]":
            return records
        try:
            domain = literal_eval(domain_str)
        except (ValueError, SyntaxError):
            _logger.error("approval.matrix %s: cannot parse domain '%s'", self.name, domain_str)
            return records.browse()
        if not domain:
            return records
        return records.filtered_domain(domain)

    @api.model
    def find_matching_matrices_batch(self, records, matrices):
        """Batch version of :meth:`find_matching_matrices`.

        Each matrix domain is evaluated once for the whole recordset.

        :return: dict mapping record id (or NewId) to the ordered matching matrices
        """
        matched_ids = {
            matrix.id: {r.id for r in matrix._filter_matching_records(records)}
            for matrix in matrices
        }
        result = {}
        for rec in records:
            comp = getattr(rec, "company_id", False) or self.env.company
            comp_id = comp.id if hasattr(comp, "id") else comp
            result[rec.id] = matrices.filtered(
                lambda m: rec.id in matched_ids[m.id]
                and (not m.company_id or m.company_id.id == comp_id)
            )
        return result

    # ─── Review Generation ───
    def _resolve_approver_users(self, approver, record):
        """Resolves the user records based on approver_type."""
        self.ensure_one()
        if approver.approver_type == "users":
            return approver.user_ids

        if approver.approver_type == "group":
            if approver.group_id:
                return approver.group_id.all_user_ids.filtered(lambda u: u.active)
            return self.env["res.users"]

        requester_uid = False
        if self.user_request_field_id and self.user_request_field_id.name in record._fields:
            val = record[self.user_request_field_id.name]
            if val:
                if self.user_request_field_id.relation == "hr.employee":
                    requester_uid = val.user_id.id if val.user_id else False
                else:
                    requester_uid = val.id
        elif "user_id" in record._fields and record.user_id:
            requester_uid = record.user_id.id

        if not requester_uid and hasattr(record, "create_uid") and record.create_uid:
            requester_uid = record.create_uid.id

        if not requester_uid:
            return self.env["res.users"]

        employee = self.env["hr.employee"].sudo().search([("user_id", "=", requester_uid)], limit=1)
        if not employee:
            return self.env["res.users"]

        if approver.approver_type == "dept_manager":
            if employee.department_id and employee.department_id.manager_id and employee.department_id.manager_id.user_id:
                return employee.department_id.manager_id.user_id
            return self.env["res.users"]

        if approver.approver_type == "employee_manager":
            if employee.parent_id and employee.parent_id.user_id:
                return employee.parent_id.user_id
            return self.env["res.users"]

        return self.env["res.users"]

    def generate_reviews(self, record):
        self.ensure_one()
        model = self.env["ir.model"].sudo().search([("model", "=", record._name)], limit=1)
        vals_list = []

        for idx, approver in enumerate(self.approver_ids.sorted(lambda a: (a.sequence, a.id)), start=1):
            if approver.level_domain and approver.level_domain.strip() not in ("", "[]"):
                try:
                    lvl_domain = literal_eval(approver.level_domain)
                    if not record.filtered_domain(lvl_domain):
                        continue
                except (ValueError, SyntaxError):
                    pass

            users = self._resolve_approver_users(approver, record)
            if not users:
                if approver.skip_if_empty:
                    _logger.info("approval.matrix %s: Level %s approver empty, skipped.", self.name, idx)
                    continue
                raise ValidationError(
                    _("Approval Matrix '%s' Level %d (%s) requires an approver, but no user could be determined.\n"
                      "Please ensure the department/direct manager or group is properly assigned, or contact your administrator.")
                    % (self.name, idx, approver.name or approver.approval_header or _("Level %d") % idx)
                )

            min_app = approver.minimum_approved if not approver.require_all else len(users)
            if min_app > len(users):
                min_app = len(users)

            header_title = approver.name or approver.approval_header or approver._get_default_name() or (_("Level %d") % idx)
            vals_list.append({
                "res_model_id": model.id,
                "res_id": record.id,
                "matrix_id": self.id,
                "level_id": approver.id,
                "sequence": idx,
                "name": header_title,
                "approval_header": header_title,
                "approver_ids": [fields.Command.set(users.ids)],
                "minimum_approved": max(1, min_app),
                "status": "waiting",
            })

        if vals_list:
            return self.env["approval.review"].sudo().create(vals_list)
        return self.env["approval.review"]


class ApprovalMatrixApprover(models.Model):
    _name = "approval.matrix.approver"
    _description = "Approval Matrix Level"
    _order = "sequence, id"

    matrix_id = fields.Many2one(
        "approval.matrix",
        string="Matrix",
        required=True,
        ondelete="cascade",
    )
    res_model = fields.Char(
        string="Model",
        related="matrix_id.res_model",
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string="Sequence", required=True, default=1)
    level = fields.Integer(string="Level Number", compute="_compute_level")
    level_display = fields.Char(string="Level", compute="_compute_level")
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
    approver_type = fields.Selection(
        [
            ("users", "Specific Users"),
            ("group", "Security Group"),
            ("dept_manager", "Department Manager (HR)"),
            ("employee_manager", "Direct Manager (HR)"),
        ],
        string="Approver Type",
        required=True,
        default="users",
    )
    user_ids = fields.Many2many(
        "res.users",
        "approval_matrix_approver_user_rel",
        "approver_id",
        "user_id",
        string="Specific Approvers",
    )
    group_id = fields.Many2one(
        "res.groups",
        string="Security Group",
    )
    approver_summary = fields.Char(
        string="Assigned To",
        compute="_compute_approver_summary",
    )
    quorum_display = fields.Char(
        string="Approval Quorum",
        compute="_compute_approver_summary",
    )
    skip_if_empty = fields.Boolean(
        string="Skip if Empty",
        default=False,
        help="If checked, this level is skipped if no approver user is resolved. Otherwise, raises a validation error.",
    )
    require_all = fields.Boolean(
        string="Require All Approvers",
        default=True,
        help="If checked, all users in this level must approve. Otherwise, Minimum Approvers Required is used.",
    )
    minimum_approved = fields.Integer(
        string="Min. Approvers Required",
        default=1,
        help="Minimum number of approvals needed for this level when Require All is disabled.",
    )
    level_domain = fields.Char(
        string="Level Threshold / Condition",
        help="Optional domain condition for this specific level (e.g. [('amount_total', '>=', 10000000)]).",
        default="[]",
    )
    has_domain = fields.Boolean(
        string="Has Condition",
        compute="_compute_has_domain",
    )

    @api.depends("level_domain")
    def _compute_has_domain(self):
        for rec in self:
            rec.has_domain = bool(rec.level_domain and rec.level_domain.strip() not in ("", "[]"))

    def action_configure_domain(self):
        self.ensure_one()
        if not self.id:
            raise UserError(_("Please save the approval matrix first before configuring level conditions."))
        return {
            "name": _("Level Condition: %s") % (self.name or self.approval_header or _("Level %s") % (self.sequence or 1)),
            "type": "ir.actions.act_window",
            "res_model": "approval.matrix.approver",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("ae_approval_matrix.view_approval_matrix_approver_condition_dialog").id,
            "target": "new",
            "context": dict(self.env.context, default_res_model=self.res_model),
        }

    @api.depends("sequence", "matrix_id.approver_ids")
    def _compute_level(self):
        for matrix in self.mapped("matrix_id"):
            for idx, line in enumerate(matrix.approver_ids, start=1):
                line.level = idx
                line.level_display = _("Level %d") % idx
        for rec in self.filtered(lambda r: not r.matrix_id):
            lvl = rec.sequence or 1
            rec.level = lvl
            rec.level_display = _("Level %d") % lvl

    @api.depends("approver_type", "user_ids", "group_id", "require_all", "minimum_approved")
    def _compute_approver_summary(self):
        for rec in self:
            if rec.approver_type == "users":
                rec.approver_summary = ", ".join(rec.user_ids.mapped("name")) or "-"
            elif rec.approver_type == "group":
                rec.approver_summary = rec.group_id.display_name or "-"
            elif rec.approver_type == "dept_manager":
                rec.approver_summary = _("Department Manager (HR)")
            elif rec.approver_type == "employee_manager":
                rec.approver_summary = _("Direct Manager (HR)")
            else:
                rec.approver_summary = "-"

            if rec.require_all:
                rec.quorum_display = _("All Approvers")
            else:
                rec.quorum_display = _("Min. %d") % max(1, rec.minimum_approved)

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'approval_matrix_approver' AND column_name = 'approval_header'
                ) THEN
                    UPDATE approval_matrix_approver
                    SET name = approval_header
                    WHERE name IS NULL AND approval_header IS NOT NULL;
                END IF;
            END $$;
        """)
        return res

    @api.depends("name", "sequence")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or (_("Level %s") % (rec.sequence or 1))

    def _get_default_name(self):
        self.ensure_one()
        if self.approver_type == "dept_manager":
            return _("Department Manager")
        if self.approver_type == "employee_manager":
            return _("Direct Manager")
        if self.approver_type == "group" and self.group_id:
            return self.group_id.name
        if self.approver_type == "users" and self.user_ids:
            names = [u.name for u in self.user_ids if u.name]
            if len(names) <= 2:
                return ", ".join(names)
            return _("%s (+%d others)") % (names[0], len(names) - 1)
        return False

    _get_default_header = _get_default_name

    @api.onchange("approver_type", "group_id", "user_ids")
    def _onchange_approver_type_and_targets(self):
        current_title = self.name or self.approval_header
        auto_title = self._get_default_name()
        if auto_title:
            auto_prefixes = {
                _("Department Manager"),
                _("Direct Manager"),
                "Department Manager",
                "Direct Manager",
            }
            if not current_title or current_title in auto_prefixes:
                self.name = auto_title
            elif not self.name and self.approval_header:
                self.name = self.approval_header
        elif not self.name and self.approval_header:
            self.name = self.approval_header

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") and vals.get("approval_header"):
                vals["name"] = vals["approval_header"]
        records = super().create(vals_list)
        for rec in records:
            if not rec.name:
                default_title = rec._get_default_name()
                if default_title:
                    rec.name = default_title
        return records

    @api.onchange("user_ids", "require_all")
    def _onchange_user_ids(self):
        if self.require_all:
            self.minimum_approved = len(self.user_ids) if self.user_ids else 1
        elif not self.minimum_approved:
            self.minimum_approved = 1

    @api.constrains("minimum_approved", "require_all", "approver_type", "user_ids", "group_id", "skip_if_empty")
    def _check_approver_config(self):
        for rec in self:
            lvl = rec.level or rec.sequence
            if rec.approver_type == "users" and not rec.user_ids and not rec.skip_if_empty:
                raise ValidationError(_("Level %d: Please select at least one approver user or enable 'Skip if Empty'.") % lvl)
            if rec.approver_type == "group" and not rec.group_id and not rec.skip_if_empty:
                raise ValidationError(_("Level %d: Please select a Security Group or enable 'Skip if Empty'.") % lvl)
            if not rec.require_all and rec.minimum_approved <= 0:
                raise ValidationError(_("Level %d: Minimum approvers required must be at least 1.") % lvl)
