================
X2many Search Bar
================

Adds a client-side **search bar** and **group by** button above ``one2many`` / ``many2many``
tree views inside notebook pages.

Features
--------

- **Search bar** with field-scoped filtering — type a query, pick a field from the dropdown,
  and only matching records are shown.
- **Group By** button — group records client-side by any configured field, with
  collapse/expand per group.
- Both features work simultaneously (filter + group by).
- Zero server round-trips — all filtering and grouping happen on already-loaded records.
- Full compatibility with all standard ``one2many`` / ``many2many`` widget options.

Usage
-----

Add ``widget="x2many_search"`` to any ``one2many`` or ``many2many`` field and specify
the searchable/groupable fields via ``search_fields``:

.. code-block:: xml

    <field name="order_line" widget="x2many_search"
           options="{'search_fields': ['product_id', 'name', 'qty_done']}"/>

Options
-------

``search_fields`` (list, optional)
    Names of the fields to search and group by. Values are matched case-insensitively
    as substrings. For ``many2one`` fields the display name is used.
    If omitted, all columns visible in the list view are used automatically.

``placeholder`` (string, optional)
    Placeholder text for the search input. Defaults to *"Search..."*.

Search Bar — Behaviour
----------------------

1. Type a query → a dropdown appears listing available fields.
2. Click a field (or press **Enter** to auto-select the first) → a filter chip
   ``[Field]  value  ×`` appears in the search bar and records are filtered.
3. Press **Backspace** with an empty input to remove the active filter chip.
4. Click **×** inside the chip or clear the input to reset.
5. **ArrowDown / ArrowUp** navigate the dropdown; **Escape** closes it.

Group By — Behaviour
--------------------

1. Click **Group By** button → dropdown lists available fields.
2. Click a field → records are sorted and grouped; a header row shows the group
   label and record count. The button turns purple with the active field name.
3. Click a group header to **collapse / expand** that group.
4. Click **×** on the Group By button to remove grouping.
5. Filter and group by can be active simultaneously.

Notes
-----

- All operations are **client-side only**: only records loaded in the current page
  are affected. For paginated x2many fields the default page size is 80 records.
- The widget registers under the key ``x2many_search`` and supports both
  ``one2many`` and ``many2many`` field types.
- Standard options such as ``editable``, ``create``, ``delete``, ``no_open``, etc.
  continue to work alongside the new options.

Technical
---------

- ``X2ManySearchField`` — extends ``X2ManyField``; manages search/group state,
  caches filtered/sorted record proxies, and passes ``groupField``, ``collapsedGroups``,
  ``groupCounts``, and ``onToggleGroup`` as props to the renderer.
- ``X2ManySearchListRenderer`` — extends ``ListRenderer``; overrides
  ``rowsTemplate`` (``ae_x2many_search.ListRenderer.Rows``) to inject group header
  rows directly inside the native ``<tbody>`` render loop without extra component
  instances.
- Proxy objects are ``markRaw``-wrapped to prevent OWL reactivity loops.
- Sort and filter results are cached by key and only recomputed when the underlying
  records or active query/field changes.
