-- Extend the existing one-shot presenter plan to the provider-success window.
-- The provider ledger and its unique idempotency constraint are unchanged.
USE product_returns;

ALTER TABLE workflow_failure_injections DROP CONSTRAINT check_node_name;
ALTER TABLE workflow_failure_injections DROP CONSTRAINT check_failure_mode;
ALTER TABLE workflow_failure_injections ADD CONSTRAINT check_node_name
    CHECK (node_name IN ('lookup_order', 'retrieve_policy', 'assess_fraud', 'issue_refund'));
ALTER TABLE workflow_failure_injections ADD CONSTRAINT check_failure_mode
    CHECK (
        (node_name = 'issue_refund' AND failure_mode = 'fail_once_after_provider_success')
        OR (node_name IN ('lookup_order', 'retrieve_policy', 'assess_fraud')
            AND failure_mode = 'fail_once_before_node')
    );
