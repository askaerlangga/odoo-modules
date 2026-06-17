/** @odoo-module **/

import { getPickerCell } from "@web/../tests/core/datetime/datetime_test_helpers";
import { click, editInput, getFixture, patchTimeZone } from "@web/../tests/helpers/utils";
import { makeView, setupViewRegistries } from "@web/../tests/views/helpers";
import "@ae_datepicker_limit/js/datetime_field_limit";
import {
    dateField,
    dateTimeField,
} from "@web/views/fields/datetime/datetime_field";

let target;
let serverData;

QUnit.module("ae_datepicker_limit", (hooks) => {
    hooks.beforeEach(() => {
        target = getFixture();
        serverData = {
            models: {
                demo: {
                    fields: {
                        date_start: { string: "Start date", type: "date", searchable: true },
                        date_end: { string: "End date", type: "date", searchable: true },
                        datetime_start: {
                            string: "Start datetime",
                            type: "datetime",
                            searchable: true,
                        },
                        datetime_end: {
                            string: "End datetime",
                            type: "datetime",
                            searchable: true,
                        },
                    },
                    records: [
                        {
                            id: 1,
                            date_start: "2017-02-20",
                            date_end: "2017-02-25",
                            datetime_start: "2017-02-20 10:00:00",
                            datetime_end: "2017-02-25 10:00:00",
                        },
                    ],
                    onchanges: {},
                },
            },
        };
        setupViewRegistries();
    });

    QUnit.test("dateField forwards min/max_date_field options", (assert) => {
        const props = dateField.extractProps(
            {
                attrs: {},
                options: {
                    min_date_field: "date_start",
                    max_date_field: "date_end",
                },
            },
            { required: false }
        );

        assert.strictEqual(props.minDateField, "date_start");
        assert.strictEqual(props.maxDateField, "date_end");
    });

    QUnit.test("dateTimeField forwards min/max_date_field options", (assert) => {
        const props = dateTimeField.extractProps(
            {
                attrs: {},
                options: {
                    min_date_field: "start_datetime",
                    max_date_field: "end_datetime",
                },
            },
            { required: false }
        );

        assert.strictEqual(props.minDateField, "start_datetime");
        assert.strictEqual(props.maxDateField, "end_datetime");
    });

    QUnit.test("dateField registers referenced fields as dependencies", (assert) => {
        const deps = dateField.fieldDependencies({
            attrs: {},
            options: {
                min_date_field: "date_start",
                max_date_field: "date_end",
            },
            type: "date",
        });

        assert.deepEqual(deps, [
            { name: "date_start", type: "date", readonly: true },
            { name: "date_end", type: "date", readonly: true },
        ]);
    });

    QUnit.test("dateTimeField registers referenced fields as dependencies", (assert) => {
        const deps = dateTimeField.fieldDependencies({
            attrs: {},
            options: {
                min_date_field: "start_datetime",
                max_date_field: "end_datetime",
            },
            type: "datetime",
        });

        assert.deepEqual(deps, [
            { name: "start_datetime", type: "datetime", readonly: true },
            { name: "end_datetime", type: "datetime", readonly: true },
        ]);
    });

    QUnit.test("date field uses min_date_field reactively", async (assert) => {
        patchTimeZone(0);

        await makeView({
            type: "form",
            resModel: "demo",
            resId: 1,
            serverData,
            arch: `
                <form>
                    <field name="date_start"/>
                    <field name="date_end" options="{'min_date_field': 'date_start'}"/>
                </form>`,
        });

        await click(target, ".o_field_widget[name='date_end'] input");
        assert.containsOnce(target, ".o_datetime_picker");
        assert.ok(getPickerCell("19").disabled, "days before the minimum should be disabled");
        assert.notOk(getPickerCell("20").disabled, "the minimum day should remain selectable");

        await editInput(target, ".o_field_widget[name='date_start'] input", "02/22/2017");

        assert.ok(
            getPickerCell("21").disabled,
            "datepicker should refresh when the referenced field changes"
        );
        assert.notOk(getPickerCell("22").disabled, "the new minimum day should remain selectable");
    });

    QUnit.test("datetime field uses min_date_field reactively", async (assert) => {
        patchTimeZone(0);

        await makeView({
            type: "form",
            resModel: "demo",
            resId: 1,
            serverData,
            arch: `
                <form>
                    <field name="datetime_start"/>
                    <field name="datetime_end" options="{'min_date_field': 'datetime_start'}"/>
                </form>`,
        });

        await click(target, ".o_field_widget[name='datetime_end'] input");
        assert.containsOnce(target, ".o_datetime_picker");
        assert.ok(getPickerCell("19").disabled, "days before the minimum should be disabled");
        assert.notOk(getPickerCell("20").disabled, "the minimum day should remain selectable");

        await editInput(target, ".o_field_widget[name='datetime_start'] input", "02/22/2017 10:00:00");

        assert.ok(
            getPickerCell("21").disabled,
            "datetime picker should refresh when the referenced field changes"
        );
        assert.notOk(getPickerCell("22").disabled, "the new minimum day should remain selectable");
    });
});
