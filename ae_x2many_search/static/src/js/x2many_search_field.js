/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useState, useRef, useEffect, onWillUpdateProps, markRaw } from "@odoo/owl";

export function getFieldStringValue(record, fieldName) {
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

const GROUP_PROPS = ["groupField?", "collapsedGroups?", "groupCounts?", "onToggleGroup?"];

const GroupMethods = {
    getGroupValue(record) {
        const { groupField } = this.props;
        if (!groupField) {
            return null;
        }
        return getFieldStringValue(record, groupField) || _t("(empty)");
    },
    isGroupCollapsed(groupKey) {
        return !!(this.props.collapsedGroups || {})[groupKey];
    },
    onToggleGroup(groupKey) {
        this.props.onToggleGroup?.(groupKey);
    },
    getGroupCount(groupKey) {
        return this.props.groupCounts?.[groupKey] ?? 0;
    },
};

function makeSearchListRenderer(BaseListRenderer) {
    class SearchListRenderer extends BaseListRenderer {}
    Object.assign(SearchListRenderer.prototype, GroupMethods);
    SearchListRenderer.template = BaseListRenderer.template;
    SearchListRenderer.recordRowTemplate = BaseListRenderer.recordRowTemplate;
    SearchListRenderer.groupRowTemplate = BaseListRenderer.groupRowTemplate;
    SearchListRenderer.rowsTemplate = "ae_x2many_search.ListRenderer.Rows";
    SearchListRenderer.props = [...BaseListRenderer.props, ...GROUP_PROPS];
    return SearchListRenderer;
}

export const X2ManySearchListRenderer = makeSearchListRenderer(ListRenderer);

export class X2ManySearchField extends X2ManyField {
    static template = "ae_x2many_search.X2ManySearchField";
    static components = {
        ...X2ManyField.components,
        ListRenderer: X2ManySearchListRenderer,
    };
    static props = {
        ...X2ManyField.props,
        searchFields: { type: Array, optional: true },
    };
    static defaultProps = {
        ...(X2ManyField.defaultProps || {}),
        searchFields: [],
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
        this.facetOrder = useState({ order: [] });
        this.searchWrapperRef = useRef("searchWrapper");
        this.groupWrapperRef = useRef("groupWrapper");

        this._invalidateFieldCaches();

        this._filterProxyKey = null;
        this._filterProxy = null;

        this._groupProxyKey = null;
        this._groupProxy = null;
        this._groupCounts = null;

        this._onToggleGroup = (groupKey) => {
            const collapsed = this.groupState.collapsedGroups;
            this.groupState.collapsedGroups = {
                ...collapsed,
                [groupKey]: !collapsed[groupKey],
            };
        };

        onWillUpdateProps((nextProps) => {
            if (nextProps.searchFields !== this.props.searchFields) {
                this._invalidateFieldCaches();
                this._filterProxyKey = null;
                this._groupProxyKey = null;
            }
        });

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

    _invalidateFieldCaches() {
        this._fieldLabelCache = null;
        this._searchFieldsCache = null;
        this._fieldListCache = null;
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
        const records = this.list.records;
        const proxyKey = `${activeFilter.fieldName}::${activeFilter.query}::${records.length}::${records[0]?.id ?? ""}::${records[records.length - 1]?.id ?? ""}`;
        if (proxyKey !== this._filterProxyKey) {
            const fields = activeFilter.fieldName
                ? [activeFilter.fieldName]
                : this.activeSearchFields;
            this._filterProxy = records.filter((r) =>
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
            const records = this.list.records;
            const groupKey = `${groupField}::${filteredRecords.length}::${records[0]?.id ?? ""}::${records[records.length - 1]?.id ?? ""}`;
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
        if (!this.groupState.activeField) {
            this.facetOrder.order = [...this.facetOrder.order, "group"];
        }
        const collapsed = {};
        for (const r of this.list.records) {
            const key = getFieldStringValue(r, fieldName) || _t("(empty)");
            collapsed[key] = true;
        }
        this.groupState.activeField = fieldName;
        this.groupState.showDropdown = false;
        this.groupState.collapsedGroups = collapsed;
        this._groupProxyKey = null;
    }

    onClearGroupBy() {
        this.groupState.activeField = null;
        this.groupState.showDropdown = false;
        this.groupState.collapsedGroups = {};
        this._groupProxy = null;
        this._groupProxyKey = null;
        this._groupCounts = null;
        this.facetOrder.order = this.facetOrder.order.filter((t) => t !== "group");
    }

    onToggleGroupDropdown() {
        this.searchState.showDropdown = false;
        this.groupState.showDropdown = !this.groupState.showDropdown;
    }

    _commitSearch(fieldName) {
        const query = this.searchState.inputValue.trim();
        if (!query) {
            return;
        }
        if (!this.searchState.activeFilter) {
            this.facetOrder.order = [...this.facetOrder.order, "filter"];
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
        if (ev.key === "Backspace" && !this.searchState.inputValue) {
            if (this.searchState.activeFilter) {
                this.onClearFilter();
                return;
            }
            if (this.groupState.activeField) {
                this.onClearGroupBy();
                return;
            }
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
        this.facetOrder.order = this.facetOrder.order.filter((t) => t !== "filter");
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
        return props;
    },
};

registry.category("fields").add("x2many_search", x2ManySearchField);

let _patched = false;

function upgradeWithSectionAndNote() {
    if (_patched) {
        return true;
    }
    const sectionAndNoteField = registry.category("fields").get("section_and_note_one2many", null);
    const BaseListRenderer = sectionAndNoteField?.component.components?.ListRenderer;
    if (!BaseListRenderer) {
        return false;
    }
    X2ManySearchField.components = {
        ...X2ManySearchField.components,
        ListRenderer: makeSearchListRenderer(BaseListRenderer),
    };
    _patched = true;
    return true;
}

if (!upgradeWithSectionAndNote()) {
    const fieldsRegistry = registry.category("fields");
    const onFieldsUpdate = ({ detail: { operation, key } }) => {
        if (operation === "add" && key === "section_and_note_one2many" && upgradeWithSectionAndNote()) {
            fieldsRegistry.removeEventListener("UPDATE", onFieldsUpdate);
        }
    };
    fieldsRegistry.addEventListener("UPDATE", onFieldsUpdate);
}
