/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";

export class ApprovalSystray extends Component {
    static template = "ae_approval_matrix.ApprovalSystray";
    static components = { Dropdown };
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.busService = this.env.services.bus_service;
        this.state = useState({
            count: 0,
            reviews: [],
        });

        if (this.busService) {
            this.busService.subscribe("approval_matrix/updated", () => {
                this.fetchData();
            });
        }

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        try {
            const data = await this.orm.call(
                "res.users",
                "get_pending_approval_reviews",
                [],
                { limit: 10 }
            );
            this.state.count = data.count || 0;
            this.state.reviews = data.reviews || [];
        } catch {
            this.state.count = 0;
            this.state.reviews = [];
        }
    }

    async onBeforeOpen() {
        await this.fetchData();
    }

    openReview(review) {
        document.body.click();
        if (review.res_model && review.res_id) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: review.res_model,
                res_id: review.res_id,
                views: [[false, "form"]],
                target: "current",
            });
        } else {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "approval.review",
                res_id: review.id,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    openMyApprovals() {
        document.body.click();
        this.action.doAction("ae_approval_matrix.action_my_approval_review");
    }
}

registry.category("systray").add("ae_approval_matrix.ApprovalSystray", {
    Component: ApprovalSystray,
    sequence: 25,
});
