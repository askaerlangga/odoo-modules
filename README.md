# Odoo Custom Modules

This repository contains various custom Odoo modules organized by Odoo version branches.

## Available Modules (Odoo 17.0)

| Module Name | Technical Name | Description | Version |
| :--- | :--- | :--- | :--- |
| **Report Domain Visibility** | `ae_report_domain_visibility` | Odoo 18 backport: provides the ability to hide or filter the *Print* menu based on a domain in `ir.actions.report`. | [17.0.1.0.0](../../tree/17.0/ae_report_domain_visibility) |
| **Datepicker Dynamic Limit** | `ae_datepicker_limit` | Adds support for `min_date_field` and `max_date_field` options on date/datetime fields in the web client to dynamically limit the selectable date range. | [17.0.1.0.0](../../tree/17.0/ae_datepicker_limit) |

## Branches by Odoo Version

To access and download the code for a specific version, please switch to the corresponding branch (e.g., [`17.0`](../../tree/17.0)).

## Installation

1. Clone only the modules for a specific Odoo version (e.g., 17.0):
   ```bash
   git clone -b 17.0 https://github.com/your-username/odoo-modules.git
   ```
2. Add the path of this repository folder to the `addons_path` parameter in your Odoo configuration file (`odoo.conf`).
3. Restart the Odoo service.
4. Activate **Developer Mode**, then navigate to **Apps** > **Update Apps List**.
5. Search for the module you want to install and click **Install**.

> [!TIP]
> To download a specific module folder individually, you can use the [GitHub Directory Downloader](https://www.askaerlangga.my.id/github-directory-downloader/).
