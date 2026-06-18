import { expect, test } from "@odoo/hoot";
import { click, edit } from "@odoo/hoot-dom";
import { animationFrame, mockTimeZone } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { getPickerCell } from "@web/../tests/core/datetime/datetime_test_helpers";
import {
    dateField,
    dateTimeField,
} from "@web/views/fields/datetime/datetime_field";
import "@ae_datepicker_limit/js/datetime_field_limit";

class Demo extends models.Model {
    date_start = fields.Date({ string: "Start date", searchable: true });
    date_end = fields.Date({ string: "End date", searchable: true });
    datetime_start = fields.Datetime({ string: "Start datetime", searchable: true });
    datetime_end = fields.Datetime({ string: "End datetime", searchable: true });

    _records = [
        {
            id: 1,
            date_start: "2017-02-20",
            date_end: "2017-02-25",
            datetime_start: "2017-02-20 10:00:00",
            datetime_end: "2017-02-25 10:00:00",
        },
    ];
}

defineModels([Demo]);

test("dateField forwards min/max_date_field options", () => {
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

    expect(props.minDateField).toBe("date_start");
    expect(props.maxDateField).toBe("date_end");
});

test("dateTimeField forwards min/max_date_field options", () => {
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

    expect(props.minDateField).toBe("start_datetime");
    expect(props.maxDateField).toBe("end_datetime");
});

test("dateField registers referenced fields as dependencies", () => {
    const deps = dateField.fieldDependencies({
        attrs: {},
        options: {
            min_date_field: "date_start",
            max_date_field: "date_end",
        },
        type: "date",
    });

    expect(deps).toEqual([
        { name: "date_start", type: "date", readonly: true },
        { name: "date_end", type: "date", readonly: true },
    ]);
});

test("dateTimeField registers referenced fields as dependencies", () => {
    const deps = dateTimeField.fieldDependencies({
        attrs: {},
        options: {
            min_date_field: "start_datetime",
            max_date_field: "end_datetime",
        },
        type: "datetime",
    });

    expect(deps).toEqual([
        { name: "start_datetime", type: "datetime", readonly: true },
        { name: "end_datetime", type: "datetime", readonly: true },
    ]);
});

test("date field uses min_date_field reactively", async () => {
    mockTimeZone(0);

    await mountView({
        type: "form",
        resModel: "demo",
        resId: 1,
        arch: `
            <form>
                <field name="date_start"/>
                <field name="date_end" options="{'min_date_field': 'date_start'}"/>
            </form>`,
    });

    await click(".o_field_widget[name='date_end'] input");
    await animationFrame();

    expect(".o_datetime_picker").toHaveCount(1);
    expect(getPickerCell("19")).toHaveAttribute("disabled", { message: "days before the minimum should be disabled" });
    expect(getPickerCell("20")).not.toHaveAttribute("disabled", { message: "the minimum day should remain selectable" });

    await click(".o_field_widget[name='date_start'] input");
    await animationFrame();
    await edit("02/22/2017", { confirm: "Enter" });
    await animationFrame();

    await click(".o_field_widget[name='date_end'] input");
    await animationFrame();

    expect(getPickerCell("21")).toHaveAttribute("disabled", { message: "datepicker should refresh when the referenced field changes" });
    expect(getPickerCell("22")).not.toHaveAttribute("disabled", { message: "the new minimum day should remain selectable" });
});

test("datetime field uses min_date_field reactively", async () => {
    mockTimeZone(0);

    await mountView({
        type: "form",
        resModel: "demo",
        resId: 1,
        arch: `
            <form>
                <field name="datetime_start"/>
                <field name="datetime_end" options="{'min_date_field': 'datetime_start'}"/>
            </form>`,
    });

    await click(".o_field_widget[name='datetime_end'] input");
    await animationFrame();

    expect(".o_datetime_picker").toHaveCount(1);
    expect(getPickerCell("19")).toHaveAttribute("disabled", { message: "days before the minimum should be disabled" });
    expect(getPickerCell("20")).not.toHaveAttribute("disabled", { message: "the minimum day should remain selectable" });

    await click(".o_field_widget[name='datetime_start'] input");
    await animationFrame();
    await edit("02/22/2017 10:00:00", { confirm: "Enter" });
    await animationFrame();

    await click(".o_field_widget[name='datetime_end'] input");
    await animationFrame();

    expect(getPickerCell("21")).toHaveAttribute("disabled", { message: "datetime picker should refresh when the referenced field changes" });
    expect(getPickerCell("22")).not.toHaveAttribute("disabled", { message: "the new minimum day should remain selectable" });
});
