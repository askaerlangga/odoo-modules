{
    "name": "Datepicker Dynamic Limit",
    "summary": "Support min_date_field/max_date_field options on date/datetime fields",
    "version": "17.0.1.0.0",
    "author": "Aska Erlangga",
    "website": "https://www.askaerlangga.my.id",
    "category": "Technical",
    "depends": ["web"],
    "license": "AGPL-3",
    "assets": {
        "web.assets_backend": [
            "ae_datepicker_limit/static/src/js/datetime_field_limit.js",
        ],
        "web.qunit_suite_tests": [
            "ae_datepicker_limit/static/tests/datetime_field_limit_tests.js",
        ],
    },
}
