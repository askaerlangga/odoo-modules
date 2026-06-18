# Odoo Custom Modules

This repository contains a collection of custom Odoo modules developed to add various technical features and additional functionalities to Odoo.

## Available Modules

| Module Name | Technical Name | Description | Version |
| :--- | :--- | :--- | :--- |
| [**Report Domain Visibility**](./ae_report_domain_visibility) | `ae_report_domain_visibility` | Odoo 18 backport: provides the ability to hide or filter the *Print* menu based on a domain in `ir.actions.report`. | 17.0.1.0.0 |
| [**Datepicker Dynamic Limit**](./ae_datepicker_limit) | `ae_datepicker_limit` | Adds support for `min_date_field` and `max_date_field` options on date/datetime fields in the web client to dynamically limit the selectable date range. | 17.0.1.0.0 |

> [!TIP]
> To download a specific module folder individually, you can use the [GitHub Directory Downloader](https://www.askaerlangga.my.id/github-directory-downloader/).

## Installation

1. Clone the specific Odoo version branch (e.g., `17.0`):
   ```bash
   git clone -b 17.0 https://github.com/askaerlangga/odoo-modules.git
   ```
2. Add the path of this repository folder to the `addons_path` parameter in your Odoo configuration file (`odoo.conf`).
3. Restart the Odoo service.
4. Activate **Developer Mode**, then navigate to **Apps** > **Update Apps List**.
5. Search for the module you want to install and click **Install**.

## License

All modules in this repository are licensed under the **LGPL-3** (GNU Lesser General Public License), unless stated otherwise in their respective `__manifest__.py` files.
