from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestX2ManySearch(TransactionCase):

    def test_module_installed(self):
        """Verify ae_x2many_search is loaded and installed in database."""
        module = self.env["ir.module.module"].search([("name", "=", "ae_x2many_search")])
        self.assertTrue(module)
        self.assertEqual(module.state, "installed")
