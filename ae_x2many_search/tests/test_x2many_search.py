from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestX2ManySearch(TransactionCase):

    def test_module_installed(self):
        """Verify ae_x2many_search is loaded and installed in database."""
        module = self.env["ir.module.module"].search([("name", "=", "ae_x2many_search")])
        self.assertTrue(module)
        self.assertEqual(module.state, "installed")

    def test_assets_backend_registered(self):
        """Verify JS, XML and SCSS assets are configured in manifest web.assets_backend."""
        info = self.env["ir.module.module"].get_module_info("ae_x2many_search")
        backend_assets = info.get("assets", {}).get("web.assets_backend", [])
        self.assertTrue(any("x2many_search_field.js" in p for p in backend_assets))
        self.assertTrue(any("x2many_search_field.xml" in p for p in backend_assets))
        self.assertTrue(any("x2many_search_field.scss" in p for p in backend_assets))
