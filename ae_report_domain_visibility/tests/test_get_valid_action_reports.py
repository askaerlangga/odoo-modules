from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGetValidActionReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.report_no_domain = cls.env['ir.actions.report'].create({
            'name': 'Test Report No Domain',
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'web.report_layout',
            'binding_model_id': cls.partner_model.id,
        })
        cls.report_company_only = cls.env['ir.actions.report'].create({
            'name': 'Test Report Companies Only',
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'web.report_layout',
            'binding_model_id': cls.partner_model.id,
            'domain': "[('is_company', '=', True)]",
        })
        cls.report_invalid_domain = cls.env['ir.actions.report'].create({
            'name': 'Test Report Invalid Domain',
            'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'web.report_layout',
            'binding_model_id': cls.partner_model.id,
            'domain': "not a valid domain",
        })
        cls.company = cls.env['res.partner'].create({
            'name': 'Acme Corp',
            'is_company': True,
        })
        cls.individual = cls.env['res.partner'].create({
            'name': 'John Doe',
            'is_company': False,
        })

    def _call(self, action_ids, record_ids):
        return self.env['ir.actions.report'].get_valid_action_reports(
            action_ids, 'res.partner', record_ids
        )

    def test_no_domain_always_valid(self):
        valid = self._call([self.report_no_domain.id], [self.individual.id])
        self.assertIn(self.report_no_domain.id, valid)

    def test_domain_match_company(self):
        valid = self._call([self.report_company_only.id], [self.company.id])
        self.assertIn(self.report_company_only.id, valid)

    def test_domain_no_match_individual(self):
        valid = self._call([self.report_company_only.id], [self.individual.id])
        self.assertNotIn(self.report_company_only.id, valid)

    def test_domain_partial_match_returns_valid(self):
        valid = self._call(
            [self.report_company_only.id],
            [self.individual.id, self.company.id],
        )
        self.assertIn(self.report_company_only.id, valid)

    def test_invalid_domain_excluded(self):
        valid = self._call([self.report_invalid_domain.id], [self.company.id])
        self.assertNotIn(self.report_invalid_domain.id, valid)

    def test_mixed_actions_individual_selected(self):
        valid = self._call(
            [
                self.report_no_domain.id,
                self.report_company_only.id,
                self.report_invalid_domain.id,
            ],
            [self.individual.id],
        )
        self.assertEqual(set(valid), {self.report_no_domain.id})

    def test_mixed_actions_company_selected(self):
        valid = self._call(
            [
                self.report_no_domain.id,
                self.report_company_only.id,
                self.report_invalid_domain.id,
            ],
            [self.company.id],
        )
        self.assertEqual(set(valid), {self.report_no_domain.id, self.report_company_only.id})
