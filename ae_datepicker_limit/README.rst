========================
Datepicker Dynamic Limit
========================

Module to dynamically limit minimum and maximum values on
``date`` and ``datetime`` fields based on other fields from the same record.

Overview
========

``min_date`` and ``max_date`` options are static (ISO date string or
``today``). This module adds dynamic options:

- ``min_date_field``: field name used as dynamic minimum value
- ``max_date_field``: field name used as dynamic maximum value

The datepicker updates automatically when referenced field values change.

Installation
============

1. Put this module in your addons path.
2. Add dependency in your target module:

::

   "depends": ["web", "ae_datepicker_limit"]

3. Install or upgrade the target module.

Usage
=====

Min date from another field:

::

   <field name="date_end" options="{'min_date_field': 'date_start'}"/>

Max date from another field:

::

   <field name="date_start" options="{'max_date_field': 'date_end'}"/>

Min and max from other fields:

::

   <field name="date_progress" options="{'min_date_field': 'date_start', 'max_date_field': 'date_end'}"/>

Combine with Odoo built-in options:

::

   <field name="date_end" options="{'min_date': 'today', 'max_date_field': 'date_deadline'}"/>
   <field name="date_end" options="{'min_date_field': 'date_start', 'max_date': '2026-12-31'}"/>

Notes
=====

- Referenced fields should be ``date`` or ``datetime``.
- Referenced fields do not have to be displayed in the view.
- Referenced fields must exist on the same model.

Technical Details
=================

This module patches ``DateTimeField`` and field descriptors:

- extends ``DateTimeField`` props with ``minDateField`` and ``maxDateField``
- updates ``this.state.minDate`` / ``this.state.maxDate`` in ``onWillRender``
  so the picker refreshes with the current record values
- extends ``dateField`` and ``dateTimeField`` ``extractProps``
- extends ``dateField`` and ``dateTimeField`` ``fieldDependencies``

Tests
=====

Hoot tests are provided in:

- ``ae_datepicker_limit/static/tests/datetime_field_limit.test.js``

These tests cover both the option wiring and the reactive datepicker
behavior when the referenced field value changes.
