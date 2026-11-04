from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestStockQuantApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.user_approver = cls.env["res.users"].create({
            "name": "Warehouse Approver",
            "login": "wh_approver",
            "email": "wh_approver@example.com",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("stock.group_stock_manager").id,
                cls.env.ref("ae_approval_matrix.group_approval_user").id,
            ])],
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
        })

        cls.product = cls.env["product.product"].create({
            "name": "Test Approval Widget",
            "is_storable": True,
            "company_id": cls.company.id,
        })

        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        if not cls.warehouse:
            cls.warehouse = cls.env["stock.warehouse"].create({
                "name": "Test WH",
                "code": "TWH",
                "company_id": cls.company.id,
            })
        cls.stock_location = cls.warehouse.lot_stock_id

        quant_model = cls.env["ir.model"].search([("model", "=", "stock.quant")], limit=1)
        btn_apply = cls.env["approval.matrix.button.option"].search([
            ("model_id.model", "=", "stock.quant"),
            ("name", "=", "action_apply_inventory"),
        ], limit=1)

        cls.matrix = cls.env["approval.matrix"].create({
            "name": "Stock Quant Matrix",
            "model_id": quant_model.id,
            "company_id": cls.company.id,
            "sequence": 1,
            "manual_domain": "[]",
            "auto_confirm_button_id": btn_apply.id if btn_apply else False,
            "approver_ids": [
                (0, 0, {
                    "sequence": 1,
                    "approval_header": "WH Manager Review",
                    "approver_type": "users",
                    "user_ids": [(6, 0, [cls.user_approver.id])],
                }),
            ],
        })

    def test_01_quant_apply_requires_approval(self):
        """action_apply_inventory must raise UserError when approval is pending."""
        quant = self.env["stock.quant"].create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "company_id": self.company.id,
            "quantity": 10.0,
            "inventory_quantity": 25.0,
        })
        self.assertTrue(quant.approval_need_validation)
        self.assertEqual(quant.approval_state, "draft")

        # Direct apply must be blocked by bridge module
        with self.assertRaises(UserError):
            quant.action_apply_inventory()

        # Request approval -> state pending
        quant.action_request_approval()
        self.assertEqual(quant.approval_state, "pending")

        # Approve review -> auto confirms apply inventory and sets stock
        review = quant.approval_review_ids[0]
        review.with_user(self.user_approver).action_approve()

        self.assertEqual(quant.approval_state, "approved")
        self.assertEqual(quant.quantity, 25.0)

    def test_02_locations_view_auto_apply_readonly(self):
        """Locations view has readonly modifier on inventory_quantity_auto_apply."""
        view_res = self.env["stock.quant"].get_view(
            view_id=self.env.ref("stock.view_stock_quant_tree_editable").id,
            view_type="list",
        )
        from lxml import etree
        doc = etree.XML(view_res["arch"])
        field_node = doc.xpath(".//field[@name='inventory_quantity_auto_apply']")
        self.assertTrue(field_node, "inventory_quantity_auto_apply field must be present in view")
        readonly_attr = field_node[0].attrib.get("readonly", "")
        self.assertIn("approval_need_validation", readonly_attr)
        self.assertIn("approval_state in ('waiting', 'pending')", readonly_attr)

    def test_03_locations_edit_in_draft_no_auto_apply(self):
        """Editing inventory_quantity_auto_apply in draft does not bypass approval."""
        quant = self.env["stock.quant"].create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "quantity": 10.0,
            "company_id": self.company.id,
        })
        self.assertEqual(quant.approval_state, "draft")

        # Simulate writing inventory_quantity_auto_apply in inventory mode (as user does in Locations tree)
        quant.with_context(inventory_mode=True).write({
            "inventory_quantity_auto_apply": 30.0,
        })

        # Stock quantity should NOT be updated yet
        self.assertEqual(quant.quantity, 10.0)
        self.assertEqual(quant.inventory_quantity, 30.0)
        self.assertEqual(quant.approval_state, "draft")

        # Now request approval and approve
        quant.action_request_approval()
        self.assertEqual(quant.approval_state, "pending")
        review = quant.approval_review_ids[0]
        review.with_user(self.user_approver).action_approve()

        self.assertEqual(quant.approval_state, "approved")
        self.assertEqual(quant.quantity, 30.0)
