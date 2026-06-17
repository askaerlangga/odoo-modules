========================
Report Domain Visibility
========================

Backport of the Odoo 18 ``domain`` visibility filter on ``ir.actions.report``
for Odoo 17.

Overview
========

In Odoo 18, the ``domain`` field on ``ir.actions.report`` controls whether a
report entry appears in the **Print** dropdown menu. This module brings that
behaviour to Odoo 17 Community Edition.

The ``domain`` field is a **visibility filter only** — it has no effect on the
records rendered inside the PDF/HTML. It simply hides or shows the Print menu
entry based on whether the currently selected record(s) match the domain.

- Actions **without** a domain are always shown.
- Actions **with** a domain are shown only if at least one selected record
  matches.
- If no records are selected, domain-based actions stay visible.
- If domain parsing or RPC validation fails, domain-based actions are hidden
  (fail-safe).

Installation
============

1. Copy this module to your Odoo addons path.
2. Add the path to ``addons_path`` in your ``odoo.conf`` if not already present.
3. Restart Odoo and install the module::

       ./odoo-bin -d <database> -i ae_report_domain_visibility

   Or install via **Settings → Apps → search "Report Domain Visibility"**.

For updates::

    ./odoo-bin -d <database> -u ae_report_domain_visibility

Usage
=====

Via XML (recommended for developers):

::

    <record id="my_report" model="ir.actions.report">
        <field name="name">Posted Invoices Report</field>
        <field name="model">account.move</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">account.report_invoice</field>
        <field name="binding_model_id" ref="account.model_account_move"/>
        <field name="domain">[('state', '=', 'posted')]</field>
    </record>

Via UI:

1. Go to **Settings → Technical → Actions → Reports**.
2. Open the report you want to filter.
3. Fill in the **Filter domain** field (located below **Printed Report Name**).

Notes
=====

- The ``domain`` field accepts any valid Odoo domain expression as a string.
- The domain is evaluated server-side using ``filtered_domain()``.
- Referenced fields must exist on the model bound to the report action.

Technical Details
=================

This module extends ``ir.actions.report`` and patches ``ActionMenus``:

- adds a ``domain`` field to ``ir.actions.report``
- exposes ``get_valid_action_reports(action_ids, model, record_ids)`` via RPC
- post-processes ``_get_bindings()`` to inject ``domain`` into the frontend payload
- patches ``ActionMenus.printItems`` to filter actions by domain validation result

Tests
=====

Run the test suite with::

    ./odoo-bin -d <database> -i ae_report_domain_visibility --test-enable --stop-after-init

Optional with tags::

    ./odoo-bin -d <database> --test-tags /ae_report_domain_visibility --stop-after-init

Test cases cover:

- Action without domain → always valid
- Domain matches selected record → valid
- Domain does not match selected record → invalid
- Partial match (multi-select, at least one matches) → valid
- Invalid domain expression → excluded (fail-safe)
- Mixed actions: only matching ones returned
