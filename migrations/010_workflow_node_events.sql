-- Durable, customer-safe node progress for the ReturnFlow presentation.
--
-- Tempo and Loki remain the detailed operator observability systems. This
-- existing node_attempts table gives the customer/API a durable projection of
-- attempts, inputs, outputs, failures, and timing without scraping operator
-- observability tools.

USE product_returns;

ALTER TABLE node_attempts
    ADD COLUMN IF NOT EXISTS input_state JSONB NULL;

ALTER TABLE node_attempts
    ADD COLUMN IF NOT EXISTS duration_ms INT8 NULL;

SELECT count(*) AS node_attempt_count
FROM node_attempts;
