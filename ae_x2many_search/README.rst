=================
X2many Search Bar
=================

Adds a client-side **search bar** and **group by** button above ``one2many`` / ``many2many``
tree views inside notebook pages.

Features
--------

- **Search bar** with field-scoped filtering — type a query, pick a field from the dropdown,
  and only matching records are shown.
- **Group By** menu — group records client-side by any configured field, with
  collapse/expand per group.
- Both features work simultaneously; active filter/group chips are shown as **facets**
  ordered by insertion (whichever was applied first appears first).
- Zero server round-trips — all filtering and grouping happen on already-loaded records.
- Full compatibility with all standard ``one2many`` / ``many2many`` widget options.
- **Section & Note support** — when the ``account`` module is installed, the widget
  automatically inherits the section/note behaviour of Sales Orders and Invoices
  (no extra module or configuration required).

Usage
-----

Add ``widget="x2many_search"`` to any ``one2many`` or ``many2many`` field and specify
the searchable/groupable fields via ``search_fields``::

    <field name="order_line" widget="x2many_search"
           options="{'search_fields': ['product_id', 'name', 'qty_done']}"/>

Options
-------

``search_fields`` (list, optional)
    Names of the fields to search and group by. Values are matched case-insensitively
    as substrings. For ``many2one`` fields the display name is used.
    If omitted, all columns visible in the list view are used automatically.

Search Bar — Behaviour
----------------------

1. Type a query → a dropdown appears listing available fields.
2. Click a field (or press **Enter** to auto-select the first) → a filter facet
   ``[Field]  value  ×`` appears in the search bar and records are filtered.
3. Press **Backspace** with an empty input to remove the last facet
   (filter first, then group by).
4. Click **×** inside a facet to remove it.
5. **ArrowDown / ArrowUp** navigate the dropdown; **Escape** closes it.

Group By — Behaviour
--------------------

1. Click the caret (**▾**) next to the search bar → the Group By menu opens.
2. Click a field → records are sorted and grouped, and a group facet appears in
   the search bar. Groups start **collapsed**; each header shows the group label
   and record count.
3. Click a group header to **collapse / expand** that group.
4. Click **×** on the group facet (or Backspace) to remove grouping.
5. Filter and group by can be active simultaneously; facets keep insertion order.

Notes
-----

- All operations are **client-side only**: only records loaded in the current page
  are affected. For paginated x2many fields the default page size is 80 records.
- The widget registers under the key ``x2many_search`` and supports both
  ``one2many`` and ``many2many`` field types.
- Standard options such as ``editable``, ``create``, ``delete``, ``no_open``, etc.
  continue to work alongside the new options.
- For **section/note** rows the column bound to ``name`` (usually *Description*)
  must be visible; if it is hidden via the optional-columns menu, section/note
  lines cannot be edited (this is standard Odoo behaviour).

Technical
---------

- ``X2ManySearchField`` — extends ``X2ManyField``; manages search/group state,
  caches filtered/sorted record proxies, and passes ``groupField``, ``collapsedGroups``,
  ``groupCounts``, and ``onToggleGroup`` as props to the renderer.
- ``makeSearchListRenderer(Base)`` — factory that produces a search-aware list
  renderer from any base ``ListRenderer`` (shared group methods are mixed in via
  ``GroupMethods``). The custom ``rowsTemplate``
  (``ae_x2many_search.ListRenderer.Rows``) injects group header rows directly
  inside the native ``<tbody>`` render loop without extra component instances.
- Section/note is wired **without a hard dependency** on ``account``: the widget
  listens on the ``fields`` registry and, once ``section_and_note_one2many`` is
  registered, rebuilds its list renderer from that base and detaches the listener.
- Proxy objects are ``markRaw``-wrapped to prevent OWL reactivity loops.
- Sort and filter results are cached by key and only recomputed when the underlying
  records or active query/field change.
