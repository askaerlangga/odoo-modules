{
    "name": "Advanced Approval Matrix - Stock Inventory",
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Multi-tier approval matrix integration for Inventory Adjustments (stock.quant)",
    "description": """
Advanced Approval Matrix - Stock Inventory Bridge
=================================================
This module bridges ``ae_approval_matrix`` with Odoo's Inventory module (``stock.quant``):
- Enforces approval validation on Physical Inventory adjustments before ``action_apply_inventory`` can execute.
- Prevents accidental bypass in Locations view by making ``inventory_quantity_auto_apply`` read-only when approval is pending.
- Adds dedicated search filters: "Needs Approval", "To My Approval", and "Approved".
    """,
    "author": "Aska Erlangga",
    "website": "https://www.askaerlangga.my.id",
    "license": "LGPL-3",
    "images": [
        "static/description/icon.png",
    ],
    "depends": ["ae_approval_matrix", "stock"],
    "data": [
        "views/stock_quant_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
