{
    "name": "X2many Search Bar",
    "summary": "Add a client-side search bar above one2many/many2many list views in notebooks",
    "version": "19.0.1.1.0",
    "author": "Aska Erlangga",
    "website": "https://www.askaerlangga.my.id",
    "category": "Technical",
    "depends": ["web"],
    "license": "LGPL-3",
    "images": ["static/description/images/main_screenshot.png"],
    "assets": {
        "web.assets_backend": [
            "ae_x2many_search/static/src/js/x2many_search_field.js",
            "ae_x2many_search/static/src/xml/x2many_search_field.xml",
            "ae_x2many_search/static/src/scss/x2many_search_field.scss",
        ],
    },
    "installable": True,
    "application": False,
}
