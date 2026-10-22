#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN SELECT o.order_number, o.currency, o.total_amount, o.ordered_at,
       c.external_customer_id, c.email,
       oi.order_item_id, oi.sku, oi.product_name,
       oi.product_category, oi.quantity, oi.line_total
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE o.order_number LIKE 'DEMO-%'
ORDER BY o.order_number, oi.order_item_id;
SQL
