/** @odoo-module */

import { ListController } from "@web/views/list/list_controller";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { patch } from "@web/core/utils/patch";
import { rpcBus } from "@web/core/network/rpc";

const UPDATE_METHODS = ["create", "write", "unlink"];

// Invalidate web client disk cache for get_views only on actual record mutations
rpcBus.addEventListener("RPC:RESPONSE", (ev) => {
    const params = ev.detail?.data?.params;
    if (params?.model === "approval.matrix" && UPDATE_METHODS.includes(params?.method)) {
        rpcBus.trigger("CLEAR-CACHES", "get_views");
    }
});

patch(ListController.prototype, {
    evalViewModifier(modifier) {
        if (!modifier) {
            return false;
        }
        const evalContext = Object.assign({}, this.model.root.evalContext);
        const selection = this.model.root.selection || [];
        if (selection.length > 0) {
            evalContext.id = selection[0].resId;
            evalContext.approval_need_validation = selection.some(
                (r) => r.data && r.data.approval_need_validation
            );
            const allApproved = selection.every(
                (r) => r.data && r.data.approval_state === "approved"
            );
            evalContext.approval_state = allApproved ? "approved" : "draft";
        } else {
            evalContext.id = 0;
            evalContext.approval_need_validation = false;
            evalContext.approval_state = false;
        }
        try {
            return evaluateBooleanExpr(modifier, evalContext);
        } catch {
            return super.evalViewModifier(modifier);
        }
    },
});
