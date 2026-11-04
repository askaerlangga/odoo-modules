# Odoo Custom Modules (19.0)

This repository contains custom Odoo modules developed for **Odoo 19.0**.

## Available Modules

| Module Name | Technical Name | Description | Version |
| :--- | :--- | :--- | :--- |
| [**Advanced Approval Matrix**](./ae_approval_matrix) | `ae_approval_matrix` | Universal No-Code multi-tier approval matrix engine for any Odoo model. Includes metadata auto-scanner, multi-level quorum, HR manager & group resolution, field lock exceptions, and realtime OWL Systray badge. | 19.0.1.0.0 |
| [**Advanced Approval Matrix - Stock Inventory**](./ae_approval_matrix_stock) | `ae_approval_matrix_stock` | Stock inventory & physical adjustment bridge for Advanced Approval Matrix. Intercepts `stock.quant` adjustments, guards auto-apply, and secures approval workflows. | 19.0.1.0.0 |

> [!TIP]
> To download a specific module folder individually, you can use the [GitHub Directory Downloader](https://www.askaerlangga.my.id/github-directory-downloader/).

## Installation

1. Clone the specific Odoo version branch (19.0):
   ```bash
   git clone -b 19.0 https://github.com/askaerlangga/odoo-modules.git
   ```
2. Add the path of this repository folder to the `addons_path` parameter in your Odoo configuration file (`odoo.conf`).
3. Restart the Odoo service.
4. Activate **Developer Mode**, then navigate to **Apps** > **Update Apps List**.
5. Search for the module you want to install and click **Install**.

## License

All modules in this repository are licensed under the **LGPL-3** (GNU Lesser General Public License), unless stated otherwise in their respective `__manifest__.py` files.
