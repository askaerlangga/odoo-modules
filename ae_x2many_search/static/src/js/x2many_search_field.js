/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useState, useRef, useEffect, markRaw } from "@odoo/owl";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFieldStringValue(record, fieldName) {
    const val = record.data[fieldName];
    if (val === undefined || val === null || val === false) {
        return null;
    }
    if (Array.isArray(val)) {
        return String(val[1] ?? "");
    }
    return String(val);
}

function matchesQuery(record, searchFields, query) {
    const q = query.toLowerCase();
    for (const fieldName of searchFields) {
        const strVal = getFieldStringValue(record, fieldName);
        if (strVal && strVal.toLowerCase().includes(q)) {
            return true;
        }
    }
    return false;
}

function buildListProxy(list, records) {
    return markRaw(
        new Proxy(list, {
            get(target, prop) {
                if (prop === "records") {
                    return records;
                }
                const val = target[prop];
                return typeof val === "function" ? val.bind(target) : val;
            },
        })
    );
}

// ---------------------------------------------------------------------------
// X2ManySearchListRenderer
// ---------------------------------------------------------------------------

export class X2ManySearchListRenderer extends ListRenderer {
    static rowsTemplate = "ae_x2many_search.ListRenderer.Rows";

    getGroupValue(record) {
        const { groupField } = this.props;
        if (!groupField) {
            return null;
        }
        return getFieldStringValue(record, groupField) || _t("(empty)");
    }

    isGroupCollapsed(groupKey) {
        return !!(this.props.collapsedGroups || {})[groupKey];
    }

    onToggleGroup(groupKey) {
        this.props.onToggleGroup?.(groupKey);
    }

    getGroupCount(groupKey) {
        return this.props.groupCounts?.[groupKey] ?? 0;
    }
}

X2ManySearchListRenderer.template = ListRenderer.template;
X2ManySearchListRenderer.recordRowTemplate = ListRenderer.recordRowTemplate;
X2ManySearchListRenderer.groupRowTemplate = ListRenderer.groupRowTemplate;
X2ManySearchListRenderer.props = {
    ...ListRenderer.props,
    groupField: { type: String, optional: true },
    collapsedGroups: { type: Object, optional: true },
    groupCounts: { type: Object, optional: true },
    onToggleGroup: { type: Function, optional: true },
};

// ---------------------------------------------------------------------------
// X2ManySearchField
// ---------------------------------------------------------------------------

export class X2ManySearchField extends X2ManyField {
    static template = "ae_x2many_search.X2ManySearchField";
    static components = {
        ...X2ManyField.components,
        ListRenderer: X2ManySearchListRenderer,
    };
    static props = {
        ...X2ManyField.props,
        searchFields: { type: Array, optional: true },
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        ...(X2ManyField.defaultProps || {}),
        searchFields: [],
        placeholder: "",
    };

    setup() {
        super.setup(...arguments);
        this.searchState = useState({
            inputValue: "",
            showDropdown: false,
            focusedIndex: -1,
            activeFilter: null,
        });
        this.groupState = useState({
            activeField: null,
            showDropdown: false,
            collapsedGroups: {},
        });
        this.searchWrapperRef = useRef("searchWrapper");
        this.groupWrapperRef = useRef("groupWrapper");

        this._fieldLabelCache = null;
        this._searchFieldsCache = null;
        this._fieldListCache = null;

        this._filterProxyKey = null;
        this._filterProxy = null;

        this._groupProxyKey = null;
        this._groupProxy = null;
        this._groupCounts = null;

        this._onToggleGroup = (groupKey) => {
            this.groupState.collapsedGroups = {
                ...this.groupState.collapsedGroups,
                [groupKey]: !this.groupState.collapsedGroups[groupKey],
            };
        };

        useEffect(
            () => {
                const onMouseDown = (ev) => {
                    const searchEl = this.searchWrapperRef.el;
                    if (searchEl && !searchEl.contains(ev.target)) {
                        this.searchState.showDropdown = false;
                    }
                    const groupEl = this.groupWrapperRef.el;
                    if (groupEl && !groupEl.contains(ev.target)) {
                        this.groupState.showDropdown = false;
                    }
                };
                document.addEventListener("mousedown", onMouseDown);
                return () => document.removeEventListener("mousedown", onMouseDown);
            },
            () => []
        );
    }

    get searchPlaceholder() {
        return this.props.placeholder || _t("Search...");
    }

    get activeSearchFields() {
        if (this._searchFieldsCache) {
            return this._searchFieldsCache;
        }
        let result;
        if (this.props.searchFields && this.props.searchFields.length) {
            result = this.props.searchFields;
        } else {
            const columns = (this.archInfo?.columns || []).filter(
                (col) => col.fieldName && col.type === "field"
            );
            result = columns.map((col) => col.fieldName);
        }
        this._searchFieldsCache = result;
        return result;
    }

    get fieldLabelMap() {
        if (this._fieldLabelCache) {
            return this._fieldLabelCache;
        }
        const map = {};
        const columns = this.archInfo?.columns || [];
        for (const col of columns) {
            if (col.fieldName && col.label) {
                map[col.fieldName] = col.label;
            }
            if (col.name && col.label) {
                map[col.name] = col.label;
            }
        }
        const fields = this.list.fields || {};
        for (const fieldName of this.activeSearchFields) {
            if (!map[fieldName]) {
                map[fieldName] = fields[fieldName]?.string || fieldName;
            }
        }
        this._fieldLabelCache = map;
        return map;
    }

    get fieldList() {
        if (this._fieldListCache) {
            return this._fieldListCache;
        }
        const labelMap = this.fieldLabelMap;
        this._fieldListCache = this.activeSearchFields.map((fieldName) => ({
            fieldName,
            label: labelMap[fieldName] || fieldName,
        }));
        return this._fieldListCache;
    }

    get dropdownSuggestions() {
        if (!this.searchState.inputValue) {
            return [];
        }
        return this.fieldList;
    }

    get groupByFields() {
        return this.fieldList;
    }

    get activeGroupLabel() {
        if (!this.groupState.activeField) {
            return null;
        }
        return this.fieldLabelMap[this.groupState.activeField] || this.groupState.activeField;
    }

    _getFieldLabel(fieldName) {
        return this.fieldLabelMap[fieldName] || fieldName;
    }

    _getFilteredRecords() {
        const { activeFilter } = this.searchState;
        if (!activeFilter) {
            return this.list.records;
        }
        const proxyKey = `${activeFilter.fieldName}::${activeFilter.query}::${this.list.records.length}`;
        if (proxyKey !== this._filterProxyKey) {
            const fields = activeFilter.fieldName
                ? [activeFilter.fieldName]
                : this.activeSearchFields;
            this._filterProxy = this.list.records.filter((r) =>
                matchesQuery(r, fields, activeFilter.query)
            );
            this._filterProxyKey = proxyKey;
        }
        return this._filterProxy;
    }

    _buildGroupCounts(records, groupField) {
        const counts = {};
        for (const r of records) {
            const key = getFieldStringValue(r, groupField) || _t("(empty)");
            counts[key] = (counts[key] || 0) + 1;
        }
        return counts;
    }

    get rendererProps() {
        const props = super.rendererProps;
        const filteredRecords = this._getFilteredRecords();
        const { activeField: groupField } = this.groupState;

        if (groupField) {
            const groupKey = `${groupField}::${filteredRecords.length}`;
            if (groupKey !== this._groupProxyKey) {
                const sorted = [...filteredRecords].sort((a, b) => {
                    const va = getFieldStringValue(a, groupField) || "";
                    const vb = getFieldStringValue(b, groupField) || "";
                    return va.localeCompare(vb);
                });
                this._groupProxy = buildListProxy(this.list, sorted);
                this._groupCounts = this._buildGroupCounts(sorted, groupField);
                this._groupProxyKey = groupKey;
            }
            props.list = this._groupProxy;
            props.groupField = groupField;
            props.collapsedGroups = this.groupState.collapsedGroups;
            props.groupCounts = this._groupCounts;
            props.onToggleGroup = this._onToggleGroup;
        } else if (filteredRecords !== this.list.records) {
            props.list = buildListProxy(this.list, filteredRecords);
            props.groupField = undefined;
            props.collapsedGroups = undefined;
            props.groupCounts = undefined;
            props.onToggleGroup = undefined;
        }

        return props;
    }

    onSelectGroupBy(fieldName) {
        this.groupState.activeField = fieldName;
        this.groupState.showDropdown = false;
        this.groupState.collapsedGroups = {};
        this._groupProxyKey = null;
    }

    onClearGroupBy() {
        this.groupState.activeField = null;
        this.groupState.showDropdown = false;
        this.groupState.collapsedGroups = {};
        this._groupProxy = null;
        this._groupProxyKey = null;
        this._groupCounts = null;
    }

    onToggleGroupDropdown() {
        this.groupState.showDropdown = !this.groupState.showDropdown;
    }

    _commitSearch(fieldName) {
        const query = this.searchState.inputValue.trim();
        if (!query) {
            return;
        }
        this.searchState.activeFilter = {
            query,
            fieldName: fieldName || null,
            fieldLabel: fieldName ? this._getFieldLabel(fieldName) : null,
        };
        this.searchState.inputValue = "";
        this.searchState.showDropdown = false;
        this.searchState.focusedIndex = -1;
    }

    onSearchInput(ev) {
        this.searchState.inputValue = ev.target.value;
        this.searchState.showDropdown = !!ev.target.value;
        this.searchState.focusedIndex = ev.target.value ? 0 : -1;
    }

    onSearchFocus() {
        if (this.searchState.inputValue) {
            this.searchState.showDropdown = true;
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Backspace" && !this.searchState.inputValue && this.searchState.activeFilter) {
            this.onClearFilter();
            return;
        }
        if (ev.key === "Escape") {
            this.searchState.showDropdown = false;
            this.searchState.focusedIndex = -1;
            return;
        }
        const suggestions = this.dropdownSuggestions;
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            this.searchState.showDropdown = true;
            this.searchState.focusedIndex = Math.min(
                this.searchState.focusedIndex + 1,
                suggestions.length - 1
            );
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            this.searchState.focusedIndex = Math.max(this.searchState.focusedIndex - 1, -1);
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            const idx = this.searchState.focusedIndex;
            if (idx >= 0 && suggestions[idx]) {
                this._commitSearch(suggestions[idx].fieldName);
            } else {
                this._commitSearch(suggestions.length > 0 ? suggestions[0].fieldName : null);
            }
        }
    }

    onSelectField(fieldName) {
        this._commitSearch(fieldName);
    }

    onClearFilter() {
        this.searchState.activeFilter = null;
        this._filterProxy = null;
        this._filterProxyKey = null;
        this._groupProxyKey = null;
        this.searchState.inputValue = "";
        this.searchState.showDropdown = false;
        this.searchState.focusedIndex = -1;
    }
}

export const x2ManySearchField = {
    ...x2ManyField,
    component: X2ManySearchField,
    displayName: _t("Relational table with search"),
    extractProps: (fieldInfo, dynamicInfo) => {
        const props = x2ManyField.extractProps(fieldInfo, dynamicInfo);
        const options = fieldInfo.options || {};
        props.searchFields = options.search_fields || [];
        props.placeholder = options.placeholder || "";
        return props;
    },
};

registry.category("fields").add("x2many_search", x2ManySearchField);
