from lxml import etree

from odoo.fields import Command
from odoo.tests.common import TransactionCase
from odoo.tools.misc import mute_logger
from odoo.exceptions import AccessError, UserError, ValidationError


class TestApprovalMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        partner_mgr_group = cls.env.ref("base.group_partner_manager").id
        user_group = cls.env.ref("base.group_user").id

        # Users
        cls.user_requester = cls.env["res.users"].create({
            "name": "Test Requester",
            "login": "test_requester",
            "email": "requester@example.com",
            "group_ids": [(6, 0, [user_group, partner_mgr_group])],
        })
        cls.user_approver_1 = cls.env["res.users"].create({
            "name": "Approver Level 1",
            "login": "test_approver1",
            "email": "approver1@example.com",
            "group_ids": [(6, 0, [user_group, partner_mgr_group])],
        })
        cls.user_approver_2 = cls.env["res.users"].create({
            "name": "Approver Level 2",
            "login": "test_approver2",
            "email": "approver2@example.com",
            "group_ids": [(6, 0, [user_group, partner_mgr_group])],
        })
        cls.user_bystander = cls.env["res.users"].create({
            "name": "Random Bystander",
            "login": "test_bystander",
            "email": "bystander@example.com",
            "group_ids": [(6, 0, [user_group, partner_mgr_group])],
        })
        cls.user_manager = cls.env["res.users"].create({
            "name": "Approval Manager",
            "login": "test_app_manager",
            "email": "manager@example.com",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("ae_approval_matrix.group_approval_manager").id,
            ])],
        })

        # HR Department & Manager
        cls.department = cls.env["hr.department"].create({
            "name": "Finance Dept",
        })
        cls.employee_manager = cls.env["hr.employee"].create({
            "name": "Finance Manager Emp",
            "user_id": cls.user_approver_2.id,
            "department_id": cls.department.id,
        })
        cls.department.write({"manager_id": cls.employee_manager.id})

        cls.employee_requester = cls.env["hr.employee"].create({
            "name": "Requester Emp",
            "user_id": cls.user_requester.id,
            "department_id": cls.department.id,
        })

        # Partner model as target for testing
        cls.partner_model = cls.env["ir.model"].search([("model", "=", "res.partner")], limit=1)

        # Create test document
        cls.test_partner = cls.env["res.partner"].with_user(cls.user_requester).create({
            "name": "Acme Corp",
            "email": "contact@acme.com",
            "user_id": cls.user_requester.id,
            "company_id": cls.company.id,
        })

        user_field = cls.env["ir.model.fields"].search([
            ("model_id", "=", cls.partner_model.id),
            ("name", "=", "user_id"),
        ], limit=1)

        # Create Matrix
        cls.matrix = cls.env["approval.matrix"].create({
            "name": "Partner Approval Matrix",
            "model_id": cls.partner_model.id,
            "company_id": cls.company.id,
            "approve_sequence": True,
            "user_request_field_id": user_field.id if user_field else False,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Level 1 - User Review",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [cls.user_approver_1.id])],
                    "require_all": True,
                }),
                (0, 0, {
                    "sequence": 2,
                    "name": "Level 2 - Dept Manager",
                    "approver_type": "dept_manager",
                    "require_all": True,
                }),
            ],
        })

    def test_01_scanner_and_matrix_setup(self):
        """Test scanning metadata and matrix domain evaluation."""
        self.matrix.action_scan_model()
        self.assertTrue(self.matrix.active)
        self.assertEqual(self.matrix.res_model, "res.partner")
        self.assertEqual(len(self.matrix.approver_ids), 2)
        self.assertTrue(self.matrix.matches(self.test_partner))

    def test_02_request_approval_and_levels(self):
        """Test requesting approval generates correct reviews with sequential activation."""
        doc = self.test_partner

        # 1. Request approval
        doc.with_user(self.user_requester).action_request_approval()

        reviews = doc.approval_review_ids.sorted("sequence")
        self.assertEqual(len(reviews), 2)

        rev_lvl1 = reviews[0]
        rev_lvl2 = reviews[1]

        # First review is pending, second is waiting
        self.assertEqual(rev_lvl1.status, "pending")
        self.assertIn(self.user_approver_1.id, rev_lvl1.approver_ids.ids)
        self.assertEqual(rev_lvl2.status, "waiting")
        self.assertIn(self.user_approver_2.id, rev_lvl2.approver_ids.ids)

        # Check computed state for Approver 1 vs Approver 2
        self.assertEqual(doc.approval_state, "pending")
        self.assertTrue(doc.with_user(self.user_approver_1).approval_user_can_approve)
        self.assertFalse(doc.with_user(self.user_approver_2).approval_user_can_approve)

        # Approver 1 approves Level 1 with comment via review action
        rev_lvl1.with_user(self.user_approver_1).action_approve(comment="LGTM <script>alert(1)</script>")
        self.assertEqual(rev_lvl1.status, "approved")
        self.assertEqual(rev_lvl1.comment, "LGTM <script>alert(1)</script>")

        # Now Level 2 automatically becomes pending
        self.assertEqual(rev_lvl2.status, "pending")
        self.assertTrue(doc.with_user(self.user_approver_2).approval_user_can_approve)

        # Approver 2 approves Level 2 via native matrix action
        doc.with_user(self.user_approver_2).action_approve_matrix()
        self.assertEqual(rev_lvl2.status, "approved")
        self.assertEqual(doc.approval_state, "approved")

    def test_03_rejection_security_and_restart(self):
        """Test rejection flow, unauthorized restart prevention, and restart by owner."""
        doc = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Beta Corp",
            "email": "beta@example.com",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })

        doc.with_user(self.user_requester).action_request_approval()

        # Bystander cannot restart while pending
        with self.assertRaises(AccessError):
            doc.with_user(self.user_bystander).action_restart_approval()

        # Regular user cannot write directly to approval.review via ORM
        rev = doc.approval_review_ids[0]
        with self.assertRaises(AccessError):
            rev.with_user(self.user_bystander).write({"status": "approved"})

        # Level 1 approver rejects with reason via comment wizard
        wiz_action = doc.with_user(self.user_approver_1).action_reject_matrix()
        wiz = self.env["approval.comment.wizard"].with_user(self.user_approver_1).with_context(
            wiz_action["context"]
        ).create({"comment": "Missing tax ID"})
        wiz.action_confirm()

        self.assertEqual(doc.approval_state, "rejected")
        self.assertTrue(doc.with_user(self.user_requester).approval_can_restart)
        self.assertFalse(doc.with_user(self.user_bystander).approval_can_restart)

        # Bystander still cannot restart after rejection
        with self.assertRaises(AccessError):
            doc.with_user(self.user_bystander).action_restart_approval()

        # Requester restarts validation
        doc.with_user(self.user_requester).action_restart_approval()
        self.assertEqual(doc.approval_state, "draft")
        self.assertTrue(doc.approval_need_validation)

    def test_04_field_exception_guard(self):
        """Test that non-excepted fields are locked during pending validation."""
        doc = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Gamma Corp",
            "email": "gamma@example.com",
            "comment": "Initial note",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })

        field_comment = self.env["ir.model.fields"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "comment"),
        ], limit=1)

        self.env["approval.exception"].create({
            "name": "Allow Comment Edit",
            "model_id": self.partner_model.id,
            "field_ids": [(6, 0, [field_comment.id])],
            "allow_write_under_validation": True,
        })

        doc.with_user(self.user_requester).action_request_approval()

        # Modifying 'comment' succeeds because of exception
        doc.write({"comment": "Updated note during review"})
        self.assertIn("Updated note during review", doc.comment)

        # Modifying 'email' raises ValidationError because it's locked
        with self.assertRaises(ValidationError):
            doc.write({"email": "new_email@example.com"})

    def test_05_native_header_and_arch_injection(self):
        """Test get_view dynamically injects native approval header buttons, alerts, and reviews."""
        views = self.env["res.partner"].get_views([(False, "form")])
        self.assertIn("form", views["views"])
        form_view = self.env["res.partner"].get_view(view_type="form")
        arch = form_view["arch"]
        self.assertIn("action_request_approval", arch)
        self.assertIn("action_approve_matrix", arch)
        self.assertIn("action_reject_matrix", arch)
        self.assertIn("action_restart_approval", arch)
        self.assertIn("approval_review_ids", arch)
        self.assertIn("approval_next_review", arch)
        self.assertIn("approval_need_validation", arch)
        self.assertIn("approval_state", arch)
        self.assertIn("approval_need_validation", form_view["models"]["res.partner"])
        self.assertIn("approval_state", form_view["models"]["res.partner"])

        # Test parallel matrix (approve_sequence = False)
        self.matrix.write({"approve_sequence": False})
        doc = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Delta Systems",
            "email": "delta@example.com",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        self.assertTrue(doc.approval_need_validation)
        self.assertEqual(doc.approval_state, "draft")

        doc.with_user(self.user_requester).action_request_approval()
        self.assertEqual(doc.approval_state, "pending")
        # Both approvers can approve immediately in parallel mode
        self.assertTrue(doc.with_user(self.user_approver_1).approval_user_can_approve)
        self.assertTrue(doc.with_user(self.user_approver_2).approval_user_can_approve)

        doc.with_user(self.user_approver_2).action_approve_matrix()
        self.assertEqual(doc.approval_state, "pending")
        doc.with_user(self.user_approver_1).action_approve_matrix()
        self.assertEqual(doc.approval_state, "approved")
        self.matrix.write({"approve_sequence": True})

    def test_06_confirmation_and_write_after_approval(self):
        """Test confirming document after approval transitions state and allows write without lock error."""
        field_type = self.env["ir.model.fields"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "type"),
        ], limit=1)

        state_contact = self.env["approval.matrix.state.option"].create({
            "model_id": self.partner_model.id,
            "name": "Contact",
            "value": "contact",
        })
        state_invoice = self.env["approval.matrix.state.option"].create({
            "model_id": self.partner_model.id,
            "name": "Invoice",
            "value": "invoice",
        })

        self.env["approval.matrix"].create({
            "name": "Partner State Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "sequence": 1,
            "state_field_id": field_type.id,
            "source_state_ids": [(6, 0, [state_contact.id])],
            "target_state_ids": [(6, 0, [state_invoice.id])],
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Manager Approval",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Epsilon Inc",
            "type": "contact",
            "company_id": self.company.id,
        })

        # Cannot transition to target state without approval
        with self.assertRaises(ValidationError):
            partner.write({"type": "invoice"})

        # Request and approve
        partner.with_user(self.user_requester).action_request_approval()
        partner.with_user(self.user_approver_1).action_approve_matrix()
        self.assertEqual(partner.approval_state, "approved")

        # Confirming to target state together with metadata fields succeeds
        partner.write({
            "type": "invoice",
            "comment": "Confirmed on approval",
        })
        self.assertEqual(partner.type, "invoice")

        # Writing after confirmation when no after-validation exception exists is allowed
        partner.write({"phone": "123456789"})
        self.assertEqual(partner.phone, "123456789")

    def test_07_level_condition_action_and_domain(self):
        """Verify level condition action opens modal window and has_domain computes correctly."""
        approver = self.matrix.approver_ids[0]
        self.assertFalse(approver.has_domain)

        act = approver.action_configure_domain()
        self.assertEqual(act["type"], "ir.actions.act_window")
        self.assertEqual(act["target"], "new")
        self.assertEqual(act["res_model"], "approval.matrix.approver")
        self.assertEqual(act["res_id"], approver.id)

        approver.write({"level_domain": "[('name', '!=', False)]"})
        self.assertTrue(approver.has_domain)

    # ─── List view support ───
    def test_08_list_arch_injection(self):
        """Main list view (with action_id or dynamic top-level) gets badge + row buttons; dialogs stay untouched."""
        Partner = self.env["res.partner"]
        res = Partner.get_view(view_type="list", action_id=1)
        for token in ("action_request_approval", "action_approve_matrix",
                      "action_reject_matrix", "action_restart_approval", "button_group"):
            self.assertIn(token, res["arch"])
        self.assertIn("approval_state", res["models"]["res.partner"])

        # Top-level dynamic list view without action_id (e.g. stock.quant.action_view_inventory) gets injected
        dynamic_list = Partner.get_view(view_type="list")
        self.assertIn("action_request_approval", dynamic_list["arch"])

        # Dialog selector list view (e.g. Many2one 'Search More...') stays untouched
        dialog_list = Partner.with_context(is_dialog=True).get_view(view_type="list")
        self.assertNotIn("action_request_approval", dialog_list["arch"])

        no_inject = Partner.with_context(skip_approval_inject=True).get_view(view_type="list", action_id=1)
        self.assertNotIn("action_request_approval", no_inject["arch"])

    def test_09_display_location_flags(self):
        """show_in_form / show_in_list control injection; at least one must remain enabled."""
        Partner = self.env["res.partner"]
        self.matrix.show_in_list = False
        self.assertNotIn(
            "action_request_approval",
            Partner.get_view(view_type="list", action_id=1)["arch"],
        )
        self.assertIn("action_request_approval", Partner.get_view(view_type="form")["arch"])

        self.matrix.write({"show_in_list": True, "show_in_form": False})
        self.assertIn(
            "action_request_approval",
            Partner.get_view(view_type="list", action_id=1)["arch"],
        )
        form_arch = Partner.get_view(view_type="form")["arch"]
        self.assertNotIn("action_request_approval", form_arch)
        # Guard, banner and history remain; only the buttons are skipped.
        self.assertIn('name="approval_state"', form_arch)
        self.assertIn('name="approval_need_validation"', form_arch)
        self.assertIn("Approval Required", form_arch)

        with self.assertRaises(ValidationError):
            self.matrix.write({"show_in_list": False, "show_in_form": False})

    def test_10_batch_compute_consistency_and_queries(self):
        """Batch compute equals per-record compute and does not scale queries with records."""
        Partner = self.env["res.partner"]
        partners = Partner.create([{"name": "Batch %d" % i, "user_id": self.user_requester.id} for i in range(20)])
        partners[0].with_user(self.user_requester).action_request_approval()
        partners[1].with_user(self.user_requester).action_request_approval()
        partners[1].with_user(self.user_approver_1).action_approve_matrix()

        def snapshot(recs):
            return [(r.approval_state, r.approval_need_validation, r.approval_user_can_approve,
                     r.approval_can_restart, r.approval_next_review) for r in recs]

        batch = partners.with_user(self.user_approver_1)
        batch.invalidate_recordset()
        batch_values = snapshot(batch)
        single_values = []
        for rec in partners:
            rec = rec.with_user(self.user_approver_1)
            rec.invalidate_recordset()
            single_values.extend(snapshot(rec))
        self.assertEqual(batch_values, single_values)
        self.assertEqual(batch_values[0][0], "pending")
        self.assertTrue(batch_values[0][2])
        self.assertEqual(batch_values[2][0], "draft")

        def query_count(recs):
            recs = recs.with_user(self.user_approver_1)
            recs.invalidate_recordset()
            before = self.cr.sql_log_count
            recs.mapped("approval_state")
            return self.cr.sql_log_count - before

        query_count(partners[:2])  # warm up caches
        small = query_count(partners[:5])
        large = query_count(partners)
        self.assertLessEqual(large - small, 3, "approval compute must be batched (%s vs %s)" % (small, large))

    def test_11_list_button_hiding(self):
        """Buttons configured in hide_button_ids are hidden in list view while unapproved."""
        btn_opt = self.env["approval.matrix.button.option"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "open_commercial_entity"),
        ], limit=1) or self.env["approval.matrix.button.option"].create({
            "model_id": self.partner_model.id,
            "name": "open_commercial_entity",
            "string": "Open Commercial Entity",
        })
        self.matrix.write({"hide_button_ids": [(4, btn_opt.id)]})

        Partner = self.env["res.partner"]
        arch = '<list><button name="open_commercial_entity" string="Commercial" type="object"/></list>'
        view = self.env["ir.ui.view"].create({
            "name": "test_partner_tree_btn",
            "model": "res.partner",
            "type": "list",
            "arch": arch,
        })
        res = Partner.get_view(view_id=view.id, view_type="list", action_id=1)
        self.assertIn('name="open_commercial_entity"', res["arch"])
        self.assertIn("approval_state != 'approved'", res["arch"])

    def test_12_auto_reject_button(self):
        """Configured auto_reject_button_id is executed automatically on rejection."""
        btn_opt = self.env["approval.matrix.button.option"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "open_commercial_entity"),
        ], limit=1) or self.env["approval.matrix.button.option"].create({
            "model_id": self.partner_model.id,
            "name": "open_commercial_entity",
            "string": "Open Commercial Entity",
        })
        self.matrix.write({"auto_reject_button_id": btn_opt.id})

        doc = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Delta Corp",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        doc.with_user(self.user_requester).action_request_approval()

        rev = doc.approval_review_ids.filtered(lambda r: r.sequence == 1)
        rev.with_user(self.user_approver_1).action_reject(reason="Testing auto reject")
        self.assertEqual(doc.approval_state, "rejected")

    def test_13_toolbar_and_tree_header_button_hiding(self):
        """Header buttons in tree get invisible='1' and actions in toolbar are filtered."""
        btn_opt = self.env["approval.matrix.button.option"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "open_commercial_entity"),
        ], limit=1) or self.env["approval.matrix.button.option"].create({
            "model_id": self.partner_model.id,
            "name": "open_commercial_entity",
            "string": "Apply Commercial",
        })
        self.matrix.write({"hide_button_ids": [(4, btn_opt.id)]})

        Partner = self.env["res.partner"]
        arch = '<list><header><button name="open_commercial_entity" string="Apply Commercial" type="object"/></header></list>'
        view = self.env["ir.ui.view"].create({
            "name": "test_partner_tree_header_btn",
            "model": "res.partner",
            "type": "list",
            "arch": arch,
        })
        res = Partner.get_view(view_id=view.id, view_type="list", action_id=1)
        # Header button gets dynamic approval guard
        self.assertIn('name="open_commercial_entity"', res["arch"])
        self.assertIn("approval_state != 'approved'", res["arch"])

    def test_14_hide_list_custom_buttons(self):
        """When hide_list_custom_buttons is enabled, ae_hide_list_custom_buttons class is injected."""
        self.matrix.write({"hide_list_custom_buttons": True})
        Partner = self.env["res.partner"]
        res = Partner.get_view(view_type="list", action_id=1)
        self.assertIn("ae_hide_list_custom_buttons", res["arch"])

        # When disabled, class should not be present
        self.matrix.write({"hide_list_custom_buttons": False})
        res2 = Partner.get_view(view_type="list", action_id=1)
        self.assertNotIn("ae_hide_list_custom_buttons", res2["arch"])

    def test_15_action_view_approval_history(self):
        """action_view_approval_history returns act_window with dialog target and review domain."""
        doc = self.test_partner
        doc.with_user(self.user_requester).action_request_approval()
        self.assertEqual(doc.approval_state, "pending")

        action = doc.action_view_approval_history()
        self.assertEqual(action.get("type"), "ir.actions.act_window")
        self.assertEqual(action.get("res_model"), "approval.review")
        self.assertEqual(action.get("target"), "new")
        self.assertIn(("res_model", "=", "res.partner"), action.get("domain"))
        self.assertIn(("res_id", "=", doc.id), action.get("domain"))
        self.assertIn("Approval History", action.get("name"))

    def test_16_return_to_draft_resets_approval(self):
        """When document returns from cancel/target state back to source state, approval is reset."""
        self.env["approval.matrix"].search([("res_model", "=", "res.partner")]).write({"active": False})
        field_type = self.env["ir.model.fields"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "type"),
        ], limit=1)
        state_contact = self.env["approval.matrix.state.option"].create({
            "model_id": self.partner_model.id,
            "name": "Contact",
            "value": "contact",
        })
        state_invoice = self.env["approval.matrix.state.option"].create({
            "model_id": self.partner_model.id,
            "name": "Invoice Address",
            "value": "invoice",
        })
        state_other = self.env["approval.matrix.state.option"].create({
            "model_id": self.partner_model.id,
            "name": "Other",
            "value": "other",
        })

        self.env["approval.matrix"].create({
            "name": "Partner Return to Draft Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "sequence": 1,
            "state_field_id": field_type.id,
            "source_state_ids": [(6, 0, [state_contact.id])],
            "target_state_ids": [(6, 0, [state_invoice.id])],
            "cancel_state_ids": [(6, 0, [state_other.id])],
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Manager Approval",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Zeta Corp",
            "type": "contact",
            "company_id": self.company.id,
        })

        # 1. Request and approve
        partner.with_user(self.user_requester).action_request_approval()
        partner.with_user(self.user_approver_1).action_approve_matrix()
        self.assertEqual(partner.approval_state, "approved")

        # 2. Confirm to target state ('invoice')
        partner.write({"type": "invoice"})
        self.assertEqual(partner.type, "invoice")

        # 3. Cancel document ('other')
        partner.write({"type": "other"})
        self.assertEqual(partner.type, "other")
        self.assertEqual(partner.approval_state, "cancel")

        # 4. Set back to quotation / draft ('contact' - source state)
        partner.write({"type": "contact"})
        self.assertEqual(partner.type, "contact")
        # Reviews should be unlinked/reset
        self.assertFalse(partner.approval_review_ids)
        self.assertEqual(partner.approval_state, "draft")
        self.assertTrue(partner.approval_need_validation)

        # 5. Confirming again without new approval must fail
        with self.assertRaises(ValidationError):
            partner.write({"type": "invoice"})

    def test_17_non_state_model_lifecycle(self):
        """Non-state models auto-void on value modification and auto-consume when condition ends."""
        self.env["approval.matrix"].search([("res_model", "=", "res.partner")]).write({"active": False})

        # Matrix for non-state model conditioned on domain (like stock.quant on diff != 0)
        self.env["approval.matrix"].create({
            "name": "Non-State Partner Limit Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "sequence": 1,
            "manual_domain": "[('comment', '!=', False)]",
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Limit Approval",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Theta Corp",
            "comment": "Inventory Diff Counted",
            "company_id": self.company.id,
        })

        # 1. Request and approve
        partner.with_user(self.user_requester).action_request_approval()
        partner.with_user(self.user_approver_1).action_approve_matrix()
        self.assertEqual(partner.approval_state, "approved")
        self.assertEqual(len(partner.approval_review_ids), 1)

        # 2. Modify values while approved (Auto-Void): comment altered
        partner.write({"comment": "Modified Diff Counted"})
        self.assertIn("Modified Diff Counted", str(partner.comment))
        # Approval should be auto-voided and reset to draft
        self.assertFalse(partner.approval_review_ids)
        self.assertEqual(partner.approval_state, "draft")
        self.assertTrue(partner.approval_need_validation)

        # 3. Request and approve new value
        partner.with_user(self.user_requester).action_request_approval()
        partner.with_user(self.user_approver_1).action_approve_matrix()
        self.assertEqual(partner.approval_state, "approved")

        # 4. Operation completed / cleared (comment = False, no longer matches matrix domain)
        # (Equivalent to stock.quant inventory applied or cleared)
        partner.write({"comment": False})
        self.assertFalse(partner.comment)
        # Approval should be auto-consumed (unlinked/closed)
        self.assertFalse(partner.approval_review_ids)
        self.assertEqual(partner.approval_state, "draft")
        self.assertFalse(partner.approval_need_validation)

    def test_18_dynamic_readonly_modifiers_form_and_tree(self):
        """Form and tree fields get dynamic readonly guard, except exempt/exception fields."""
        self.matrix.active = True
        Partner = self.env["res.partner"]

        # 1. Form View Check
        form_res = Partner.get_view(view_type="form")
        form_arch = form_res["arch"]
        self.assertIn("approval_state in ('waiting', 'pending')", form_arch)

        # 2. List View Check
        tree_res = Partner.get_view(view_type="list", action_id=1)
        tree_arch = tree_res["arch"]
        self.assertIn("approval_state in ('waiting', 'pending')", tree_arch)

        # 3. Exception Check: field allowed under validation should not be readonly-locked
        phone_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.partner_model.id),
            ("name", "=", "phone"),
        ], limit=1)
        self.env["approval.exception"].create({
            "name": "Test Phone Exception",
            "model_id": self.partner_model.id,
            "field_ids": [(6, 0, [phone_field.id])],
            "allow_write_under_validation": True,
        })
        form_res2 = Partner.get_view(view_type="form")
        form_doc = etree.fromstring(form_res2["arch"])
        phone_nodes = form_doc.xpath(".//field[@name='phone']")
        if phone_nodes:
            self.assertNotIn("approval_state in ('waiting', 'pending')", phone_nodes[0].attrib.get("readonly", ""))

    @mute_logger("odoo.sql_db")
    def test_19_unique_constraint_approval_matrix_name(self):
        """Test unique constraint on (name, company_id) raises constraint violation."""
        with mute_logger("odoo.sql_db"):
            with self.assertRaises(Exception) as cm:
                with self.cr.savepoint():
                    self.env["approval.matrix"].create({
                        "name": self.matrix.name,
                        "company_id": self.matrix.company_id.id,
                        "model_id": self.matrix.model_id.id,
                    })
            self.assertIn("approval_matrix_name_company_unique", str(cm.exception))

    def test_20_approval_matrix_copy_appends_copy(self):
        """Test duplicating an approval matrix appends '(copy)' and copies approval levels."""
        copied = self.matrix.copy()
        self.assertEqual(copied.name, f"{self.matrix.name} (copy)")
        self.assertEqual(len(copied.approver_ids), len(self.matrix.approver_ids))
        self.assertEqual(copied.model_id, self.matrix.model_id)

        # Second copy should append another (copy) without constraint violation
        copied_second = self.matrix.copy()
        self.assertEqual(copied_second.name, f"{self.matrix.name} (copy) (copy)")

    def test_21_auto_and_manual_approval_title(self):
        """Test automatic description (name) generation while allowing manual override."""
        Approver = self.env["approval.matrix.approver"]

        # 1. Automatic title for dept_manager
        app_dept = Approver.new({"approver_type": "dept_manager"})
        app_dept._onchange_approver_type_and_targets()
        self.assertEqual(app_dept.name, "Department Manager")

        # 2. Automatic title for employee_manager
        app_dir = Approver.new({"approver_type": "employee_manager"})
        app_dir._onchange_approver_type_and_targets()
        self.assertEqual(app_dir.name, "Direct Manager")

        # 3. Manual override is preserved
        app_manual = Approver.new({"approver_type": "dept_manager", "name": "Head of Engineering"})
        app_manual._onchange_approver_type_and_targets()
        self.assertEqual(app_manual.name, "Head of Engineering")

    def test_22_direct_manager_and_dynamic_requester(self):
        """Test employee_manager approver type resolves direct manager from document's user_request_field_id."""
        self.employee_requester.parent_id = self.employee_manager

        matrix = self.env["approval.matrix"].create({
            "name": "Direct Manager Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "user_request_field_id": self.env["ir.model.fields"].search([
                ("model_id", "=", self.partner_model.id),
                ("name", "=", "user_id"),
            ], limit=1).id,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Direct Manager",
                    "approver_type": "employee_manager",
                }),
            ],
        })

        partner = self.env["res.partner"].create({
            "name": "Test Partner DM",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })

        reviews = matrix.generate_reviews(partner)
        self.assertEqual(len(reviews), 1)
        self.assertIn(self.user_approver_2, reviews.approver_ids)
        self.assertEqual(reviews.name, "Direct Manager")

    def test_23_skip_if_empty_level_handling(self):
        """Test level is skipped when skip_if_empty is True and no approver resolved."""
        self.employee_requester.parent_id = False

        matrix = self.env["approval.matrix"].create({
            "name": "Skip Empty Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "approve_sequence": True,
            "user_request_field_id": self.env["ir.model.fields"].search([
                ("model_id", "=", self.partner_model.id),
                ("name", "=", "user_id"),
            ], limit=1).id,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Direct Manager (Optional)",
                    "approver_type": "employee_manager",
                    "skip_if_empty": True,
                }),
                (0, 0, {
                    "sequence": 2,
                    "name": "Final Approver",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].create({
            "name": "Test Partner Skip Empty",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })

        reviews = matrix.generate_reviews(partner)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews.name, "Final Approver")
        self.assertIn(self.user_approver_1, reviews.approver_ids)

    def test_24_quorum_partial_approval(self):
        """Test partial quorum: minimum_approved=2 with 3 approvers."""
        matrix = self.env["approval.matrix"].create({
            "name": "Quorum Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Committee Approval",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id, self.user_approver_2.id, self.user_bystander.id])],
                    "require_all": False,
                    "minimum_approved": 2,
                }),
            ],
        })

        partner = self.env["res.partner"].create({
            "name": "Test Quorum Partner",
            "company_id": self.company.id,
        })

        reviews = matrix.generate_reviews(partner)
        review = reviews[0]
        review.status = "pending"

        # 1. First approval
        review.with_user(self.user_approver_1).action_approve()
        self.assertEqual(review.status, "pending")
        self.assertEqual(review.approved_count, 1)
        self.assertIn(self.user_approver_1, review.approved_by_ids)

        # Approver 1 already approved: must be excluded from action_my_approval_review list & count
        my_action = self.env.ref("ae_approval_matrix.action_my_approval_review")
        self.assertIn("approved_by_ids", my_action.domain)
        my_reviews_u1 = self.env["approval.review"].search([
            ("id", "=", review.id),
            ("approver_ids", "in", [self.user_approver_1.id]),
            ("status", "=", "pending"),
            ("approved_by_ids", "not in", [self.user_approver_1.id]),
        ])
        self.assertFalse(my_reviews_u1, "User who already approved should be excluded from My Pending list")

        # Approver 2 has not approved yet: must remain in My Pending list & count
        my_reviews_u2 = self.env["approval.review"].search([
            ("id", "=", review.id),
            ("approver_ids", "in", [self.user_approver_2.id]),
            ("status", "=", "pending"),
            ("approved_by_ids", "not in", [self.user_approver_2.id]),
        ])
        self.assertTrue(my_reviews_u2, "User who has not approved must remain in My Pending list")

        # 2. Second approval -> Quorum reached (2/2) -> Approved!
        review.with_user(self.user_approver_2).action_approve()
        self.assertEqual(review.status, "approved")
        self.assertEqual(review.approved_count, 2)

    def test_25_approve_sequence_bypass_behavior(self):
        """Test approve_sequence_bypass auto-approves subsequent levels if already approved by same user."""
        matrix = self.env["approval.matrix"].create({
            "name": "Bypass Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "approve_sequence": True,
            "approve_sequence_bypass": True,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Level 1",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
                (0, 0, {
                    "sequence": 2,
                    "name": "Level 2 (Same Approver)",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].create({
            "name": "Test Bypass Partner",
            "company_id": self.company.id,
        })

        reviews = matrix.generate_reviews(partner).sorted("sequence")
        rev1, rev2 = reviews[0], reviews[1]
        rev1.status = "pending"
        rev2.status = "waiting"

        rev1.with_user(self.user_approver_1).action_approve()
        self.assertEqual(rev1.status, "approved")
        self.assertEqual(rev2.status, "approved")

    def test_26_approval_comment_wizard_approval_and_rejection(self):
        """Test approval.comment.wizard for notes and required rejection reason."""
        partner = self.env["res.partner"].create({
            "name": "Wizard Test Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        self.matrix.active = True
        partner.with_user(self.user_requester).action_request_approval()

        pending_rev = partner.approval_review_ids.filtered(lambda r: r.status == "pending")[0]

        # 1. Rejection without comment raises ValidationError
        wiz_reject_empty = self.env["approval.comment.wizard"].with_user(self.user_approver_1).new({
            "res_model": "res.partner",
            "res_id": partner.id,
            "review_id": pending_rev.id,
            "action_type": "reject",
            "comment": "",
        })
        with self.assertRaises(ValidationError):
            wiz_reject_empty._check_comment()

        # 2. Rejection with reason records rejection_reason and rejects review
        wiz_reject = self.env["approval.comment.wizard"].with_user(self.user_approver_1).create({
            "res_model": "res.partner",
            "res_id": partner.id,
            "review_id": pending_rev.id,
            "action_type": "reject",
            "comment": "Price discount is too high",
        })
        wiz_reject.action_confirm()
        self.assertEqual(pending_rev.status, "rejected")
        self.assertEqual(pending_rev.rejection_reason, "Price discount is too high")
        self.assertEqual(partner.approval_state, "rejected")

        # 3. Restart and approve with comment
        partner.action_restart_approval()
        partner.with_user(self.user_requester).action_request_approval()
        new_pending_rev = partner.approval_review_ids.filtered(lambda r: r.status == "pending")[0]

        wiz_approve = self.env["approval.comment.wizard"].with_user(self.user_approver_1).create({
            "res_model": "res.partner",
            "res_id": partner.id,
            "review_id": new_pending_rev.id,
            "action_type": "approve",
            "comment": "Approved with special commercial agreement",
        })
        wiz_approve.action_confirm()
        self.assertEqual(new_pending_rev.status, "approved")
        self.assertEqual(new_pending_rev.comment, "Approved with special commercial agreement")

    def test_27_mail_activity_lifecycle(self):
        """Test mail.activity is automatically scheduled on request and completed on approval."""
        self.matrix.write({"create_activity": True})
        partner = self.env["res.partner"].create({
            "name": "Activity Test Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        partner.with_user(self.user_requester).action_request_approval()

        activities = partner.activity_ids.filtered(lambda a: a.user_id == self.user_approver_1)
        self.assertTrue(activities, "Activity should be created for pending approver")
        self.assertIn("Approval Needed", activities[0].summary)

        partner.with_user(self.user_approver_1).action_approve_matrix()
        active_activities = partner.activity_ids.filtered(lambda a: a.user_id == self.user_approver_1)
        self.assertFalse(active_activities, "Activity should be closed once approved")

    def test_28_matrix_sequence_priority_and_domain_fallback(self):
        """Test matrix matching selects lowest sequence first and falls back properly."""
        Matrix = self.env["approval.matrix"]

        matrix_vip = Matrix.create({
            "name": "VIP Matrix (Seq 5)",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "sequence": 5,
            "manual_domain": "[('ref', '=', 'VIP')]",
            "approver_ids": [(0, 0, {
                "sequence": 1,
                "name": "VIP Approver",
                "approver_type": "users",
                "user_ids": [(6, 0, [self.user_approver_2.id])],
            })],
        })

        matrix_general = Matrix.create({
            "name": "General Matrix (Seq 10)",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "sequence": 10,
            "manual_domain": "[]",
            "approver_ids": [(0, 0, {
                "sequence": 1,
                "name": "General Approver",
                "approver_type": "users",
                "user_ids": [(6, 0, [self.user_approver_1.id])],
            })],
        })

        candidate_pool = matrix_vip | matrix_general

        partner_vip = self.env["res.partner"].create({
            "name": "VIP Partner",
            "ref": "VIP",
            "company_id": self.company.id,
        })
        matched_vip = Matrix.find_matching_matrices(
            "res.partner", partner_vip, matrices=candidate_pool
        )
        self.assertEqual(matched_vip[0], matrix_vip)

        partner_std = self.env["res.partner"].create({
            "name": "Standard Partner",
            "ref": "STD",
            "company_id": self.company.id,
        })
        matched_std = Matrix.find_matching_matrices(
            "res.partner", partner_std, matrices=candidate_pool
        )
        self.assertEqual(matched_std[0], matrix_general)

    def test_29_systray_pending_approval_reviews(self):
        """Scenario 29: Systray count and popup previews exclude already approved items and return formatted data."""
        partner = self.env["res.partner"].create({
            "name": "Systray Test Partner",
            "company_id": self.company.id,
            "user_id": self.user_requester.id,
        })
        partner.with_user(self.user_requester).action_request_approval()

        # Before approval: approver_1 has 1 pending review, approver_2 has 0 (waiting)
        count_u1 = self.env["res.users"].with_user(self.user_approver_1).get_approval_review_count()
        self.assertEqual(count_u1, 1)

        data_u1 = self.env["res.users"].with_user(self.user_approver_1).get_pending_approval_reviews(limit=5)
        self.assertEqual(data_u1["count"], 1)
        self.assertEqual(len(data_u1["reviews"]), 1)
        rev_item = data_u1["reviews"][0]
        self.assertEqual(rev_item["res_model"], "res.partner")
        self.assertEqual(rev_item["res_id"], partner.id)
        self.assertEqual(rev_item["res_name"], "Systray Test Partner")
        self.assertTrue(bool(rev_item["time_ago"]))

        # Bystander has 0
        count_bystander = self.env["res.users"].with_user(self.user_bystander).get_approval_review_count()
        self.assertEqual(count_bystander, 0)
        data_bystander = self.env["res.users"].with_user(self.user_bystander).get_pending_approval_reviews()
        self.assertEqual(data_bystander["count"], 0)
        self.assertEqual(len(data_bystander["reviews"]), 0)

        # Approver 1 approves level 1
        rev1 = partner.approval_review_ids.filtered(lambda r: r.sequence == 1)
        rev1.with_user(self.user_approver_1).action_approve()

        # Now Approver 1 has 0 pending reviews
        count_u1_after = self.env["res.users"].with_user(self.user_approver_1).get_approval_review_count()
        self.assertEqual(count_u1_after, 0)
        data_u1_after = self.env["res.users"].with_user(self.user_approver_1).get_pending_approval_reviews()
        self.assertEqual(data_u1_after["count"], 0)
        self.assertEqual(len(data_u1_after["reviews"]), 0)

        # Approver 2 now has 1 pending review (level 2 became pending)
        count_u2 = self.env["res.users"].with_user(self.user_approver_2).get_approval_review_count()
        self.assertEqual(count_u2, 1)
        data_u2 = self.env["res.users"].with_user(self.user_approver_2).get_pending_approval_reviews()
        self.assertEqual(data_u2["count"], 1)
        self.assertEqual(len(data_u2["reviews"]), 1)

    def test_30_draft_fields_editable_before_approval(self):
        """Fields are freely editable in draft, and become read-only only during validation."""
        partner = self.env["res.partner"].create({
            "name": "Draft Test Partner",
            "company_id": self.company.id,
            "user_id": self.user_requester.id,
            "phone": "111222333",
        })
        self.assertTrue(partner.approval_need_validation)
        self.assertEqual(partner.approval_state, "draft")

        # 1. In draft, field can be updated freely
        partner.write({"phone": "999888777", "website": "https://example.com"})
        self.assertEqual(partner.phone, "999888777")
        self.assertEqual(partner.website, "https://example.com")

        # 2. Check view injection: fields have readonly modifier only while in review ('waiting', 'pending')
        view_res = partner.get_view(view_type="form")
        from lxml import etree
        doc = etree.XML(view_res["arch"])
        field_nodes = doc.xpath(".//field[@name='phone']")
        if field_nodes:
            ro_attr = field_nodes[0].attrib.get("readonly", "")
            self.assertIn("approval_state in ('waiting', 'pending')", ro_attr)
            self.assertNotIn("approval_state != 'approved'", ro_attr)

        # 3. Once submitted for approval, fields are locked under validation
        partner.action_request_approval()
        self.assertEqual(partner.approval_state, "pending")
        with self.assertRaises(ValidationError):
            partner.with_user(self.user_requester).write({"phone": "000000000"})

    def test_31_bridge_module_requirement(self):
        """Matrix creation validates required bridge modules."""
        from unittest.mock import patch
        partner_model = self.env["ir.model"].search([("model", "=", "res.partner")], limit=1)

        matrix_cls = type(self.env["approval.matrix"])
        fake_reqs = {"res.partner": ("non_existent_bridge_module", "Non Existent Bridge")}

        with patch.object(matrix_cls, "_get_model_bridge_requirements", return_value=fake_reqs):
            with self.assertRaises(ValidationError) as cm:
                self.env["approval.matrix"].create({
                    "name": "Partner With Missing Bridge",
                    "model_id": partner_model.id,
                    "company_id": self.company.id,
                })
            self.assertIn("non_existent_bridge_module", str(cm.exception))

    def test_32_approval_delegation_realtime_and_on_behalf_of(self):
        """Test real-time approval delegation, access control, systray count, and on-behalf-of audit."""
        from odoo import fields as odoo_fields
        today = odoo_fields.Date.context_today(self.env["approval.delegate"])

        # 1. Validation: cannot delegate to self or with invalid dates
        with self.assertRaises(ValidationError):
            self.env["approval.delegate"].create({
                "delegator_id": self.user_approver_1.id,
                "delegate_id": self.user_approver_1.id,
                "date_from": today,
                "date_to": today,
            })

        # 2. Access control: regular user cannot create delegation for another user
        with self.assertRaises(AccessError):
            self.env["approval.delegate"].with_user(self.user_bystander).create({
                "delegator_id": self.user_approver_1.id,
                "delegate_id": self.user_bystander.id,
                "date_from": today,
                "date_to": today,
            })

        # 3. Document is already pending before delegation is created
        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Delegation Test Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        partner.with_user(self.user_requester).action_request_approval()
        self.assertFalse(partner.with_user(self.user_bystander).approval_user_can_approve)

        # 4. Approver 1 creates their own delegation to Bystander
        delegation = self.env["approval.delegate"].with_user(self.user_approver_1).create({
            "delegator_id": self.user_approver_1.id,
            "delegate_id": self.user_bystander.id,
            "date_from": today,
            "date_to": today,
            "notes": "Annual Leave",
        })
        self.assertTrue(delegation.name)

        # 5. Real-time evaluation: Bystander can now approve and sees review in systray
        partner.invalidate_recordset()
        partner.approval_review_ids.invalidate_recordset()
        self.assertTrue(partner.with_user(self.user_bystander).approval_user_can_approve)
        bystander_count = self.env["res.users"].with_user(self.user_bystander).get_approval_review_count()
        self.assertEqual(bystander_count, 1)

        # 6. Bystander approves Level 1 on behalf of Approver 1
        partner.with_user(self.user_bystander).action_approve_matrix()
        rev1 = partner.approval_review_ids.sorted("sequence")[0]
        self.assertEqual(rev1.status, "approved")
        self.assertIn(self.user_bystander, rev1.approved_by_ids)
        self.assertIn(self.user_approver_1, rev1.on_behalf_of_ids)
        self.assertIn("on behalf of", rev1.delegated_info)
        self.assertIn(self.user_approver_1.name, rev1.reviewed_users_display)

    def test_33_maker_checker_prevent_self_approval_and_fallback(self):
        """Test prevent_self_approval excludes requester and falls back to HR Direct Manager."""
        self.env["approval.matrix"].search([("res_model", "=", "res.partner")]).write({"active": False})
        self.employee_requester.parent_id = self.employee_manager

        matrix = self.env["approval.matrix"].create({
            "name": "Maker Checker Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "prevent_self_approval": True,
            "user_request_field_id": self.env["ir.model.fields"].search([
                ("model_id", "=", self.partner_model.id),
                ("name", "=", "user_id"),
            ], limit=1).id,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Self Configured Level",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_requester.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "SoD Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        partner.with_user(self.user_requester).action_request_approval()

        rev = partner.approval_review_ids[0]
        # Requester was excluded and replaced by their HR Direct Manager (user_approver_2)
        self.assertNotIn(self.user_requester, rev.approver_ids)
        self.assertIn(self.user_approver_2, rev.approver_ids)

        # Even if requester is manually added to approver_ids, runtime guard blocks self-approval
        rev.sudo().write({"approver_ids": [(4, self.user_requester.id)]})
        rev.invalidate_recordset()
        self.assertFalse(rev.with_user(self.user_requester).user_can_approve)
        with self.assertRaises(UserError):
            rev.with_user(self.user_requester).action_approve()

        # Direct Manager can approve normally
        rev.with_user(self.user_approver_2).action_approve()
        self.assertEqual(rev.status, "approved")
        self.assertEqual(partner.approval_state, "approved")
        matrix.active = False

    def test_34_sla_timeout_remind_escalate_and_auto_approve(self):
        """Test SLA timeout cron actions: remind, escalate, and auto_approve."""
        from odoo import fields as odoo_fields
        self.env["approval.matrix"].search([("res_model", "=", "res.partner")]).write({"active": False})

        matrix = self.env["approval.matrix"].create({
            "name": "SLA Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "approve_sequence": True,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Level 1 Escalate",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                    "sla_hours": 2.0,
                    "sla_action": "escalate",
                    "sla_escalate_user_id": self.user_approver_2.id,
                }),
                (0, 0, {
                    "sequence": 2,
                    "name": "Level 2 Auto Approve",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_2.id])],
                    "sla_hours": 1.0,
                    "sla_action": "auto_approve",
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "SLA Test Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        partner.with_user(self.user_requester).action_request_approval()

        reviews = partner.approval_review_ids.sorted("sequence")
        rev1, rev2 = reviews[0], reviews[1]
        self.assertTrue(rev1.sla_deadline)

        # Backdate pending_date on Level 1 to trigger SLA escalation
        past_dt = odoo_fields.Datetime.subtract(odoo_fields.Datetime.now(), hours=5)
        rev1.sudo().write({"pending_date": past_dt})
        self.env["approval.review"]._cron_process_sla_reviews()

        self.assertTrue(rev1.sla_triggered)
        self.assertIn(self.user_approver_2, rev1.approver_ids, "Escalation user should be added to Level 1")

        #Escalated user (Approver 2) approves Level 1 -> Level 2 becomes pending
        rev1.with_user(self.user_approver_2).action_approve()
        self.assertEqual(rev1.status, "approved")
        self.assertEqual(rev2.status, "pending")

        # Backdate pending_date on Level 2 to trigger SLA auto-approve
        rev2.sudo().write({"pending_date": past_dt})
        self.env["approval.review"]._cron_process_sla_reviews()

        self.assertTrue(rev2.sla_triggered)
        self.assertEqual(rev2.status, "approved")
        self.assertEqual(partner.approval_state, "approved")
        matrix.active = False

    def test_35_send_back_to_previous_level(self):
        """Test sending back a review from Level 3 to a chosen previous level via comment wizard."""
        self.env["approval.matrix"].search([("res_model", "=", "res.partner")]).write({"active": False})

        matrix = self.env["approval.matrix"].create({
            "name": "Send Back 3-Tier Matrix",
            "model_id": self.partner_model.id,
            "company_id": self.company.id,
            "approve_sequence": True,
            "allow_send_back": True,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "name": "Level 1 Review",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_1.id])],
                }),
                (0, 0, {
                    "sequence": 2,
                    "name": "Level 2 Review",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_approver_2.id])],
                }),
                (0, 0, {
                    "sequence": 3,
                    "name": "Level 3 Director",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [self.user_manager.id])],
                }),
            ],
        })

        partner = self.env["res.partner"].with_user(self.user_requester).create({
            "name": "Send Back Partner",
            "user_id": self.user_requester.id,
            "company_id": self.company.id,
        })
        partner.with_user(self.user_requester).action_request_approval()

        reviews = partner.approval_review_ids.sorted("sequence")
        rev1, rev2, rev3 = reviews[0], reviews[1], reviews[2]

        # Approve Level 1 and Level 2
        partner.with_user(self.user_approver_1).action_approve_matrix()
        partner.with_user(self.user_approver_2).action_approve_matrix()
        self.assertEqual(rev3.status, "pending")

        # Level 3 opens reject wizard; default target_review_id is Level 2 (immediately preceding)
        wiz_act = partner.with_user(self.user_manager).action_reject_matrix()
        wiz = self.env["approval.comment.wizard"].with_user(self.user_manager).with_context(
            wiz_act["context"]
        ).create({
            "reject_mode": "send_back",
            "comment": "Please re-verify Level 1 & 2 figures",
        })
        self.assertTrue(wiz.can_send_back)
        self.assertEqual(wiz.target_review_id, rev2)

        # Choose to send back all the way to Level 1
        wiz.target_review_id = rev1
        wiz.action_confirm()

        self.assertEqual(rev1.status, "pending")
        self.assertFalse(rev1.approved_by_ids)
        self.assertEqual(rev2.status, "waiting")
        self.assertFalse(rev2.approved_by_ids)
        self.assertEqual(rev3.status, "waiting")
        self.assertEqual(partner.approval_state, "pending")
        matrix.active = False

    def test_36_mass_bulk_approve_and_reject(self):
        """Test mass/bulk approve and reject wizard across multiple review records."""
        partners = self.env["res.partner"].with_user(self.user_requester).create([
            {"name": f"Bulk Partner {i}", "user_id": self.user_requester.id, "company_id": self.company.id}
            for i in range(3)
        ])
        for p in partners:
            p.with_user(self.user_requester).action_request_approval()

        lvl1_reviews = partners.mapped("approval_review_ids").filtered(lambda r: r.sequence == 1)
        self.assertEqual(len(lvl1_reviews), 3)

        # 1. Bulk Approve all 3 Level 1 reviews as Approver 1
        act_approve = lvl1_reviews.with_user(self.user_approver_1).action_bulk_approve_wizard()
        wiz_app = self.env["approval.comment.wizard"].with_user(self.user_approver_1).with_context(
            act_approve["context"]
        ).create({"comment": "Batch approved L1"})
        self.assertTrue(wiz_app.is_bulk)
        self.assertEqual(wiz_app.review_count, 3)
        wiz_app.action_confirm()

        for rev in lvl1_reviews:
            self.assertEqual(rev.status, "approved")
            self.assertEqual(rev.comment, "Batch approved L1")

        # 2. Bulk Reject all 3 Level 2 reviews as Approver 2
        lvl2_reviews = partners.mapped("approval_review_ids").filtered(lambda r: r.sequence == 2)
        act_reject = lvl2_reviews.with_user(self.user_approver_2).action_bulk_reject_wizard()
        wiz_rej = self.env["approval.comment.wizard"].with_user(self.user_approver_2).with_context(
            act_reject["context"]
        ).create({"comment": "Batch rejected L2"})
        wiz_rej.action_confirm()

        for p in partners:
            p.invalidate_recordset()
            self.assertEqual(p.approval_state, "rejected")









