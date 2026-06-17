/** @odoo-module **/

import { ActionMenus } from "@web/search/action_menus/action_menus";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { onWillStart, onWillUpdateProps } from "@odoo/owl";

/**
 * Backport of Odoo 18 feature: filter Print menu items based on the
 * 'domain' field of ir.actions.report.
 *
 * When the ActionMenus component mounts or its props change (e.g. user
 * selects different records), we compute which print actions should be
 * visible by calling get_valid_action_reports on the server for any
 * action that carries a 'domain' key.
 *
 * Actions without a domain are always shown.
 * Actions with a domain are shown only if at least one selected record
 * matches the domain.
 * When no records are selected, all actions are shown (safe default).
 */
patch(ActionMenus.prototype, {
    setup() {
        super.setup();
        this._validPrintIds = null;
        onWillStart(async () => {
            this._validPrintIds = await this._computeValidPrintIds(this.props);
        });
        onWillUpdateProps(async (nextProps) => {
            this._validPrintIds = await this._computeValidPrintIds(nextProps);
        });
    },

    async _computeValidPrintIds(props) {
        const printActions = (props.items && props.items.print) || [];
        const actionsWithDomain = [];
        const validIds = [];

        for (const action of printActions) {
            if ("domain" in action) {
                actionsWithDomain.push(action.id);
            } else {
                validIds.push(action.id);
            }
        }

        if (!actionsWithDomain.length) {
            return new Set(validIds);
        }

        let activeIds = props.getActiveIds();

        if (props.isDomainSelected) {
            try {
                activeIds = await this.orm.search(props.resModel, props.domain || [], {
                    limit: session.active_ids_limit,
                    context: props.context,
                });
            } catch {
                activeIds = [];
            }
        }

        if (!activeIds || !activeIds.length) {
            validIds.push(...actionsWithDomain);
            return new Set(validIds);
        }

        try {
            const extra = await this.orm.call(
                "ir.actions.report",
                "get_valid_action_reports",
                [actionsWithDomain, props.resModel, activeIds],
            );
            validIds.push(...extra);
        } catch {
        }

        return new Set(validIds);
    },

    get printItems() {
        const items = super.printItems;
        if (!this._validPrintIds) {
            return items;
        }
        return items.filter((item) => this._validPrintIds.has(item.action.id));
    },
});
