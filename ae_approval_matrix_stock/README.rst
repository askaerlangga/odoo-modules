=========================================
Advanced Approval Matrix - Stock Inventory
=========================================

.. image:: https://img.shields.io/badge/licence-LGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
   :alt: License: LGPL-3

.. image:: https://img.shields.io/badge/odoo-19.0-purple.svg
   :target: https://www.odoo.com/
   :alt: Odoo Version: 19.0

**Stock Inventory & Physical Adjustment Bridge for Advanced Approval Matrix.**

``ae_approval_matrix_stock`` is a specialized bridge addon that seamlessly connects the generic approval framework (``ae_approval_matrix``) to Odoo's Inventory engine (``stock`` / ``stock.quant``).

By using a dedicated bridge architecture, the core ``ae_approval_matrix`` module remains 100% generic, lightweight, and model-agnostic, while this module encapsulates all stock-specific business logic, views, and execution guards.

* **Depends:** ``ae_approval_matrix``, ``stock``

----

Table of Contents
=================

* `Key Features`_
* `Why a Dedicated Bridge Module?`_
* `How It Works`_
* `Configuration Guide`_
* `User Workflow`_
* `Automated Test Suite`_
* `Bug Tracker & Support`_

----

Key Features
============

1. Deep Stock Quant Integration
-------------------------------
* Binds approval matrix validation directly to **Physical Inventory Adjustments** (``stock.quant``).
* Intercepts ``action_apply_inventory()`` to strictly ensure approval clearance before stock ledger movements (``stock.move``) are committed.
* Prevents bypass attempts via RPC, automated actions, or standard UI buttons.

2. Dual-View Compatibility
--------------------------
Works harmoniously across both Odoo inventory views:

* **Physical Inventory** (``view_stock_quant_tree_inventory_editable``):
  Input counted quantities via the ``inventory_quantity`` field without premature application.
* **Location Report / Quants** (``view_stock_quant_tree_editable``):
  Safely edit ``inventory_quantity_auto_apply`` in Draft mode without triggering immediate stock moves when an approval matrix is active.

3. Context-Aware Auto-Confirm
-----------------------------
* When an approval matrix is configured with ``Auto Confirm Button = action_apply_inventory``, the system automatically posts the adjustment upon final approval.
* Passes the internal ``skip_approval_check=True`` context to ensure auto-confirm writes do not void or reset the approved record back to draft.

4. Smart Readonly Modifiers
---------------------------
* Allows full editing of counted quantities during the **Draft** phase.
* Automatically locks records to **Readonly** as soon as an approval is requested (``waiting`` / ``pending`` status), preventing data tampering while approvers review the numbers.
* Respects Matrix **Protected Fields** to detect unauthorized edits and guard inventory accuracy.

----

Why a Dedicated Bridge Module?
==============================

In Odoo, ``stock.quant`` differs significantly from conventional business documents (like Sales Orders or Invoices):

1. **No Standard State Field:** Quants are living records representing physical stock rather than stateful documents with explicit draft/done workflows.
2. **Auto-Apply Mechanism:** The standard Location view (``view_stock_quant_tree_editable``) executes ``action_apply_inventory()`` immediately upon editing ``inventory_quantity_auto_apply``.
3. **Core Operations Dependency:** Internal picking operations, scrap orders, and warehouse moves rely on ``stock.quant`` write permissions. Hardcoding restrictions in the generic approval engine risks interfering with non-inventory models or standard picking flows.

This bridge module isolates these warehouse-specific behaviors cleanly, following Odoo and OCA best practices.

----

How It Works
============

.. code-block:: text

   [ User Input Counted Qty ]
               |
               v
   [ Is Approval Matrix Active for Quant? ]
       /                                \
     No                                  Yes
     /                                    \
   [ Apply Immediately ]             [ Intercept Auto-Apply ]
   (Standard Odoo)                   [ Retain Counted Qty ]
                                     [ Status: Draft ]
                                              |
                                              v
                                     [ Click "Request Approval" ]
                                     [ Status: Pending / Readonly ]
                                              |
                                              v
                                     [ Approver Review ]
                                       /             \
                                  Reject             Approve
                                   /                   \
                        [ Status: Rejected ]     [ Status: Approved ]
                        (Re-count & Restart)           |
                                                       v
                                            [ Auto-Apply Inventory ]
                                            (Stock moves posted)

----

Configuration Guide
===================

1. Open **Approval Matrix > Approval Matrix**.
2. Click **New** to create a new matrix rule:
   * **Matrix Name:** ``Inventory Adjustment Approval``
   * **Model:** ``stock.quant`` (Quants / Inventory Adjustment)
   * **Auto Confirm Button:** ``action_apply_inventory`` (Recommended: automatically updates stock upon final approval)
   * **Protected Fields:** Select ``inventory_quantity``
3. In the **Approval Lines** tab:
   * Add required approvers (e.g., Level 1: Warehouse Supervisor, Level 2: Inventory Manager).
   * Specify Quorum rules (e.g., *All Approvers* or *At Least 1*).
4. Save the matrix.

----

User Workflow
=============

1. Step 1: Count Physical Stock
-------------------------------
* Navigate to **Inventory > Operations > Physical Inventory** (or **Inventory > Configuration > Locations > Quants**).
* Enter the actual count in **Counted Quantity** (or **Inventoried Quantity**).
* Notice that the record remains in ``Draft`` and the stock is not immediately altered.

2. Step 2: Request Approval
---------------------------
* Click **Request Approval** on the row (or select multiple rows and choose **Action > Request Approval**).
* The status updates to **Waiting / Pending**.
* The quantity field becomes **Readonly**, locking the values against changes during review.
* Approvers receive notifications in the Systray and scheduled activities.

3. Step 3: Review & Finalize
----------------------------
* The approver opens the notification or the inventory list.
* The approver clicks **Approve** (or **Reject** with a reason).
* Upon the final level approval:
  * The status changes to **Approved**.
  * The inventory adjustment is automatically applied to stock.
  * The status remains **Approved** without resetting to Draft.

----

Automated Test Suite
====================

The module includes comprehensive automated unit tests covering the end-to-end stock approval lifecycle:

* ``test_01_quant_apply_requires_approval``: Verifies unapproved quants cannot execute ``action_apply_inventory()`` and approves successfully via auto-confirm.
* ``test_02_locations_view_auto_apply_readonly``: Verifies dynamic readonly modifiers on ``inventory_quantity_auto_apply``.
* ``test_03_locations_edit_in_draft_no_auto_apply``: Verifies that editing in Locations view during Draft mode retains values without premature stock updates.

Run the test suite with:

.. code-block:: bash

   ./odoo-server -c <config_file> -d <database> -u ae_approval_matrix_stock --test-enable --test-tags=/ae_approval_matrix_stock --stop-after-init

----

Bug Tracker & Support
=====================

Bugs are tracked on `GitHub Issues <https://github.com/askaerlangga/odoo-modules/issues>`_.
In case of trouble, please check there to see if your issue has already been reported.
If you spotted it first, please help us by submitting a detailed bug report.
