{
    "name": "Report Domain Visibility",
    "summary": "Backport Odoo 18: filter Print menu by domain on ir.actions.report",
    "version": "17.0.1.0.0",
    "author": "Aska Erlangga",
    "website": "https://www.askaerlangga.my.id",
    "category": "Technical",
    "depends": ["base", "web"],
    "license": "LGPL-3",
    "data": [
        "views/ir_actions_report_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ae_report_domain_visibility/static/src/js/action_menus_patch.js",
        ],
    },
}
