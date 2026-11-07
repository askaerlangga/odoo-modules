========================
Advanced Approval Matrix
========================

.. image:: https://img.shields.io/badge/licence-LGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
   :alt: License: LGPL-3

.. image:: https://img.shields.io/badge/odoo-19.0-purple.svg
   :target: https://www.odoo.com/
   :alt: Odoo Version: 19.0

**Universal No-Code Multi-Tier Approval Matrix Engine for Any Odoo 19 Document.**

`ae_approval_matrix` is an enterprise-grade approval matrix engine developed for Odoo 19. It empowers administrators to attach fully customizable, sequential, multi-tiered approval processes to **any Odoo model** (e.g., *Purchase Orders*, *Sales Orders*, *Vendor Bills*, *Customer Invoices*, *Inventory Transfers*, *Leave Requests*, or custom addons) purely via the user interface without writing Python code, modifying XML views, or restarting the Odoo server.

----

Table of Contents
=================

* `Key Features`_
* `Enterprise Governance & Compliance`_
* `Architecture & Performance Highlights`_
* `Installation`_
* `Configuration Guide`_
* `User Workflow & Navigation`_
* `Field Edit Protection & Exceptions`_
* `Developer Hooks & API Reference`_
* `Automated Test Suite`_
* `Bug Tracker & Support`_

----

Key Features
============

1. 100% No-Code Configuration
-----------------------------
* Dynamically bind approval matrices to any installed Odoo model from the UI.
* Built-in **Metadata & Button Scanner**: Automatically detects model state fields, possible status selections, and header action buttons (e.g., *Confirm*, *Validate*, *Action Post*) so administrators can easily designate which actions require clearance.

2. Dynamic Approver Resolution
------------------------------
Each level in an approval matrix supports flexible resolution strategies:

* **Specific Users:** Assign approval rights to explicit user records.
* **Security Group:** Resolves all active users belonging to a specific group (e.g., *Purchase / Manager*, *Billing Administrator*).
* **Direct Manager:** Dynamically resolves the requester's direct HR manager (from `hr.employee.parent_id`).
* **Department Manager:** Dynamically resolves the manager of the requester's HR department (from `hr.department.manager_id`).
* **Fallback Behavior:** Option to automatically skip an approval level or throw an exception if the designated manager cannot be resolved.

3. Granular Quorum & Conditional Triggers
-----------------------------------------
* **Quorum Rules:** Require approval from *All Approvers* or specify a minimum threshold (e.g., *Minimum 2 of 5 approvers*).
* **Matrix-Level Trigger Domain:** Set top-level criteria determining when a matrix applies (e.g., only orders where ``amount_total >= 5,000``).
* **Level-Specific Conditions:** Define custom domain rules per tier (e.g., Level 1 triggers for all values; Level 2 only triggers if ``amount_total >= 25,000``; Level 3 triggers if ``amount_total >= 100,000``).
* **Priority Matching:** Supports matrix sequence and priority ranking when multiple matrices match a candidate record.

4. Modern OWL 2 Systray & Dropdown Popup
----------------------------------------
* **Interactive Systray Widget:** A persistent approval icon in the Odoo navbar with a real-time pending counter badge.
* **Rich Dropdown Popup:** Clicking the systray icon reveals an interactive notification popover showing pending reviews, document name, model label, review level description, quorum progress, and humanized relative timestamps (*"9 minutes ago"*, *"Yesterday"*).
* **Direct Document Navigation:** Clicking an item in the popup immediately opens the source document form view.
* **Instant Real-Time Sync:** Powered by Odoo 19 ``bus.bus`` web notifications. When an approval status changes, systray counters and lists update across all active user sessions instantly.

5. Safe & Resilient Validation Cycle
------------------------------------
* **PostgreSQL Row-Level Locking:** Prevents concurrency race conditions when multiple approvers validate a document simultaneously.
* **Interactive Comment & Rejection Wizard:** Prompts reviewers for mandatory rejection reasons or optional approval comments with automated chatter tracking and email notifications.
* **Restart Validation:** When a document is rejected or revised, authorized users can restart validation, resetting review states without losing review audit history.
* **Automated Confirmation:** Optional setting to auto-trigger document confirmation (e.g., ``button_confirm``) as soon as the final approval level is reached.

----

Enterprise Governance & Compliance
==================================

The module features a robust enterprise governance engine designed to enforce compliance, eliminate bottlenecks, and ensure institutional integrity across all workflows:

1. Out-of-Office Approval Delegation (``approval.delegate``)
-----------------------------------------------------------
* **Seamless Stand-In Approvers:** Approvers taking leave or traveling can delegate approval authority to a designated colleague with strict active date windows (``date_from`` to ``date_to``).
* **Flexible Matrix Scope:** Delegations can be applied globally across all assigned matrices or scoped specifically to selected approval matrices.
* **Transparent Audit Trails:** When a substitute signs off, the audit log records *"Approved by [Substitute] on behalf of [Original Approver]"* with full chatter tracking.
* **Self-Service Security:** Standard users can autonomously manage their own delegation rules via **Approvals > Management > Delegations** without requiring administrator privileges.

2. Maker-Checker Policy & Segregation of Duties
-----------------------------------------------
* **Self-Approval Prevention (``prevent_self_approval``):** Enforces segregation of duties by blocking document creators (e.g., purchase requesters or sales reps) from approving their own records, preventing internal conflict of interest.
* **Smart HR Manager Fallback:** If the document author is the only designated approver on an approval tier, the engine dynamically falls back to their **HR Direct Manager** (``employee_id.parent_id``) to ensure clearance without deadlocking the process.

3. SLA Timeouts & Automated Escalation
--------------------------------------
* **Per-Tier SLA Deadlines:** Define resolution deadlines in hours (e.g., 24h, 48h) individually for each approval level.
* **Automated Cron Actions (``ir.cron``):** When an approval level breaches its SLA window, the background scheduler automatically triggers configured policies:
  * **Remind:** Sends urgent reminder notifications and scheduled activities to pending reviewers.
  * **Escalate:** Escalates the pending review directly to the approver's HR manager or a designated escalation authority.
  * **Auto-Approve / Bypass:** Automatically marks the level approved to prevent operational gridlock on non-critical administrative tiers.

4. Send Back for Revision (``allow_send_back``)
-----------------------------------------------
* **Multi-Tier Revision Loops:** Level 2+ approvers in sequential matrices can return documents to an earlier approval level (e.g., Level 2 sends back to Level 1 or requester).
* **Mandatory Revision Context:** Prompts the reviewer for explicit revision comments via an interactive wizard, updating the document state and notifying earlier reviewers with the required corrections.

5. Mass & Bulk Decision Clearance
---------------------------------
* **Multi-Record Approval:** Department heads and executives can select multiple pending reviews in the **Pending Reviews** list view and execute batch **Approve** or **Reject** actions in one click.
* **Batch Comment Dialog:** Supports applying standardized batch comments across all cleared documents simultaneously.

----

Architecture & Performance Highlights
=====================================

* **Zero Schema Pollution:** The module does not inject redundant columns across existing model tables. All approval statuses, history logs, and review records are centrally managed and indexed in ``approval.review``.
* **Transparent Delegation:** Integrates natively with Odoo's ``mail.thread`` and ``mail.activity``. Assigned approvers receive automated activity reminders scheduled directly on the target record.
* **Strict Security & Record Rules:** Standard users only access reviews where they are explicitly designated as approvers. Managers retain overarching supervision rights.

----

Installation
============

1. Copy or clone the ``ae_approval_matrix`` directory into your Odoo custom addons path.
2. Ensure required Odoo standard modules are present in your environment:
   * ``base``
   * ``mail``
   * ``hr``
   * ``bus``
   * ``web``
3. Restart your Odoo server and activate **Developer Mode** in the web client.
4. Navigate to **Apps > Update Apps List**.
5. Search for **Advanced Approval Matrix** and click **Activate**.

----

Configuration Guide
===================

Step 1: Create an Approval Matrix
---------------------------------
1. Go to **Approvals > Configuration > Approval Matrices**.
2. Click **New**.
3. Fill in the primary matrix attributes:
   * **Matrix Name:** Give the matrix a descriptive title (e.g., *Purchase Order Multi-Tier Approval*).
   * **Document Model:** Select the target Odoo model (e.g., *Purchase Order* [``purchase.order``]).
   * **Enforce Sequential Approval:** Check this box to enforce sequential level progression (Level 1 must approve before Level 2 is activated).
   * **Sequence / Priority:** Set the priority order when multiple matrices match the same model (lowest sequence number takes precedence).
   * **Company:** Restrict to a specific company in multi-company setups.

.. image:: static/description/01_matrix_configuration.png
   :alt: Multi-Tier Approval Matrix Configuration Form
   :width: 100 %

Step 2: Auto-Scan States & Action Buttons
-----------------------------------------
1. Click the **"Re-Scan Model States & Buttons"** header action button on the matrix form.
2. The engine scans the target model definition and automatically populates:
   * **Draft / Initial States:** Statuses in which approval can be requested (e.g., ``draft``, ``sent``).
   * **Approved / Confirmed States:** Statuses indicating final approval (e.g., ``purchase``).
   * **Buttons to Hide Before Approval:** Action buttons to lock in the form view while the document is awaiting approval (e.g., ``button_confirm``, ``button_approve``).
   * **Action on Final Approval:** The button/method to execute automatically when the final approver signs off (e.g., ``button_confirm``).
   * **Action on Rejection:** The button/method to execute on rejection (e.g., ``button_cancel``).

Step 3: Define Approval Levels
------------------------------
Under the **Approval Levels** tab, configure the review tiers in sequential order:

.. list-table::
   :header-rows: 1
   :widths: 20 25 55

   * - Field
     - Value Type
     - Description
   * - **Sequence**
     - Integer
     - Determines the approval tier order (1, 2, 3, etc.).
   * - **Approver Type**
     - Selection
     - Choose between *Specific Users*, *Security Group*, *Department Manager*, or *Direct Manager*.
   * - **Approvers / Group**
     - Relational
     - Assign explicit users or select the target security group.
   * - **Description**
     - Char
     - Label displayed in approval tables and chatter (e.g., *Finance Manager Review*).
   * - **Quorum / Require All**
     - Boolean / Integer
     - Check *Require All Approvers* or specify a *Minimum Approvals Required*.
   * - **Skip If Empty**
     - Boolean
     - If true, automatically bypasses the level if no approver can be found (e.g., employee has no manager).
   * - **Condition (Domain)**
     - Python Domain
     - Optional filter condition for this level (e.g., ``[('amount_total', '>=', 50000)]``).

Step 4: Matrix Trigger Conditions (Optional)
--------------------------------------------
Under the **Trigger Conditions** tab, enter a domain filter to restrict when this matrix applies to records:

.. code-block:: python

   [("amount_total", ">", 10000), ("partner_id.country_id.code", "=", "US")]

Records not matching this domain will bypass approval and follow their default Odoo flow.

----

User Workflow & Navigation
==========================

1. Requesting Approval
----------------------
* When a user prepares a document (e.g., creating a quotation), the document's standard confirmation buttons remain hidden or locked.
* The user clicks **Request Approval** in the approval banner or header.
* The system evaluates candidate matrices, binds the appropriate rules, creates ``approval.review`` records, and sets Level 1 to ``pending`` while subsequent levels remain in ``waiting``.
* Email notifications and Odoo activities are automatically dispatched to Level 1 approvers.

.. image:: static/description/02_document_waiting_approval.png
   :alt: Document in Waiting Approval State with Action Banner and Locked Buttons
   :width: 100 %

.. image:: static/description/03_approval_lines_tab.png
   :alt: Multi-Tier Approval Lines Status Tab on Document Form
   :width: 100 %

2. Reviewing via Systray Popup
------------------------------
* Approvers see a counter badge in the top navbar.
* Clicking the badge opens the **Pending Approvals** popover.
* Approvers can inspect record details, model types, review levels, and submission timestamps.
* Clicking any review row navigates directly to the target document's form view.
* An approver who has already approved their portion of a quorum level will no longer see the item in their pending list.

.. image:: static/description/04_systray_dropdown.png
   :alt: OWL Systray Dropdown Menu Showing Pending Approvals
   :width: 100 %

3. Approving or Rejecting
-------------------------
* On the document form view, eligible approvers see **Approve** and **Reject** buttons in the approval banner.
* **Approve:** Opens a dialog for optional approval comments. Upon confirmation:
  * If quorum is satisfied, the tier advances to ``approved``.
  * The next sequential level is automatically set to ``pending``, triggering notifications for the next tier.
  * If the final tier is reached, the overall document status becomes ``approved`` and the configured confirmation action runs automatically.
* **Reject:** Prompts for a mandatory rejection reason. The document is marked as ``rejected``, notifying the requester via chatter.

.. image:: static/description/05_approval_wizard.png
   :alt: Interactive Approval and Rejection Comment Dialog
   :width: 100 %

4. Restarting Validation
------------------------
* If an order is rejected or requires amendments, the requester or an administrator can click **Restart Validation**.
* The document reverts to ``draft``, clearing pending blocks and allowing fields to be corrected and resubmitted.

----

Field Edit Protection & Exceptions
==================================

The module provides an integrated security mechanism to prevent unauthorized tampering of document fields while approval is in progress or after approval is completed.

1. Go to **Approvals > Configuration > Field Edit Exceptions**.
2. Select the **Document Model**.
3. Choose the fields that should remain editable (e.g., ``notes``, ``payment_term_id``).
4. Restrict editability by specific user groups (e.g., allow *Purchase Managers* to edit internal notes even while approval is pending).
5. All other fields are locked against modifications.

.. image:: static/description/06_field_exceptions.png
   :alt: Field Edit Protection & Exceptions Configuration
   :width: 100 %

----

Developer Hooks & API Reference
===============================

The approval engine provides optional lifecycle extension methods on any target model. Developers can override these methods in custom modules:

.. code-block:: python

   from odoo import models

   class SaleOrder(models.Model):
       _inherit = "sale.order"

       def _on_approval_requested(self):
           """Triggered when approval is submitted."""
           super()._on_approval_requested()
           # Custom business logic (e.g. notify external webhook)

       def _on_approval_approved(self):
           """Triggered when all approval tiers have been successfully completed."""
           super()._on_approval_approved()
           # Custom post-approval logic

       def _on_approval_rejected(self, reason=False):
           """Triggered when any approver rejects the document."""
           super()._on_approval_rejected(reason=reason)
           # Custom rejection logic

       def _on_approval_reset(self):
           """Triggered when approval validation is restarted."""
           super()._on_approval_reset()
           # Custom reset logic

----

Automated Test Suite
====================

The module comes with an automated test suite comprising **36 comprehensive test scenarios** located in ``tests/test_approval_matrix.py``:

1. Model metadata scanning and automated button extraction.
2. Multi-tier sequential approval workflow and activation.
3. User approval clearance and state progression.
4. Rejection flow, mandatory comments, and validation restart.
5. Auto-confirm button execution on final tier clearance.
6. Field edit lock enforcement during pending state.
7. Field edit exception overrides for authorized groups.
8. Group-based dynamic approver resolution.
9. Domain-specific level conditional filters.
10. Concurrency and PostgreSQL row-level locking validation.
11. Multi-company isolation and security constraints.
12. Chatter message generation and subtype notifications.
13. Access rule enforcement (standard user vs. approval manager).
14. Quorum approvals (partial vs. complete fulfillment).
15. Department manager dynamic HR resolution.
16. Direct manager dynamic HR resolution.
17. Skip-if-empty fallback handling when no approver is found.
18. Matrix priority sequence and domain fallback resolution.
19. Systray pending counter and preview RPC data accuracy.
20. Exclusion of already approved items from the active user's pending list.
21. Out-of-office approval delegation resolution and substitute permission checks.
22. Delegation expiration and matrix-specific scope filtering.
23. Substitute approval execution with 'on behalf of' audit logging.
24. Maker-checker policy enforcing self-approval prevention.
25. Self-approval manager fallback when creator is sole level approver.
26. Per-level SLA timeout evaluation and automated cron scheduler.
27. SLA escalation to manager and auto-approve/bypass actions.
28. Sequential revision loops with send back to earlier levels.
29. Revision reason wizard validation and review state resetting.
30. Mass / bulk approval action execution across multiple selected records.
31. Mass / bulk rejection with batch comment validation.
32. Model scanner button filtering with context-sensitive conditions.
33. Multiple matrix match prioritization based on domain specificity.
34. Real-time bus notification payloads for delegation state updates.
35. Cascade deletion hygiene and integrity locks on active reviews.
36. End-to-end full lifecycle integration test across all governance policies.

Run the test suite using standard Odoo test commands:

.. code-block:: bash

   ./odoo-bin -c odoo.conf -d <database_name> --test-enable --test-tags=ae_approval_matrix --stop-after-init

----

Bug Tracker & Support
=====================

Bugs are tracked on `GitHub Issues <https://github.com/askaerlangga/odoo-modules/issues>`_.
In case of trouble, please check there to see if your issue has already been reported.
If you spotted it first, please help us by submitting a detailed bug report.

----

Maintainer
==========

This module is maintained by **Aska Erlangga**.
Released under the **GNU Lesser General Public License, Version 3 (LGPL-3)**.
