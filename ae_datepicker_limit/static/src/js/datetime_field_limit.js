import { onWillRender } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import {
    DateTimeField,
    dateField,
    dateTimeField,
} from "@web/views/fields/datetime/datetime_field";

patch(DateTimeField, {
    props: {
        ...DateTimeField.props,
        minDateField: { type: String, optional: true },
        maxDateField: { type: String, optional: true },
    },
});

patch(DateTimeField.prototype, {
    setup() {
        super.setup(...arguments);

        onWillRender(() => {
            const record = this.props.record;
            if (this.props.minDateField) {
                const val = record.data[this.props.minDateField];
                this.state.minDate = val || false;
            }
            if (this.props.maxDateField) {
                const val = record.data[this.props.maxDateField];
                this.state.maxDate = val || false;
            }
        });
    },
});

const origDateExtract = dateField.extractProps;
dateField.extractProps = (fieldInfo, dynamicInfo) => ({
    ...origDateExtract(fieldInfo, dynamicInfo),
    minDateField: fieldInfo.options.min_date_field,
    maxDateField: fieldInfo.options.max_date_field,
});

const origDateFieldDeps = dateField.fieldDependencies;
dateField.fieldDependencies = (fieldNode) => {
    const deps = origDateFieldDeps ? origDateFieldDeps(fieldNode) : [];
    const { options, type } = fieldNode;
    if (options.min_date_field) {
        deps.push({ name: options.min_date_field, type, readonly: true });
    }
    if (options.max_date_field) {
        deps.push({ name: options.max_date_field, type, readonly: true });
    }
    return deps;
};

const origDtExtract = dateTimeField.extractProps;
dateTimeField.extractProps = (fieldInfo, dynamicInfo) => ({
    ...origDtExtract(fieldInfo, dynamicInfo),
    minDateField: fieldInfo.options.min_date_field,
    maxDateField: fieldInfo.options.max_date_field,
});

const origDtFieldDeps = dateTimeField.fieldDependencies;
dateTimeField.fieldDependencies = (fieldNode) => {
    const deps = origDtFieldDeps ? origDtFieldDeps(fieldNode) : [];
    const { options, type } = fieldNode;
    if (options.min_date_field) {
        deps.push({ name: options.min_date_field, type, readonly: true });
    }
    if (options.max_date_field) {
        deps.push({ name: options.max_date_field, type, readonly: true });
    }
    return deps;
};
