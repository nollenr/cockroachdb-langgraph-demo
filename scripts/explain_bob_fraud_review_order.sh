#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN UPSERT INTO orders (
    order_id, order_number, customer_id, order_status, currency,
    subtotal_amount, tax_amount, shipping_amount, total_amount,
    ordered_at, created_at, updated_at
) VALUES (
    '30000000-0000-4000-8000-000000000007', 'DEMO-1007',
    '10000000-0000-4000-8000-000000000003', 'delivered', 'USD',
    129.99, 10.40, 0.00, 140.39, now() - INTERVAL '6 days', now(), now()
) RETURNING NOTHING;

EXPLAIN UPSERT INTO order_items (
    order_item_id, order_id, product_id, sku, product_name,
    product_category, quantity, unit_price, tax_amount, line_total,
    activated_at, created_at
) VALUES (
    '40000000-0000-4000-8000-000000000007',
    '30000000-0000-4000-8000-000000000007',
    '20000000-0000-4000-8000-000000000002',
    'COFFEE-12C', '12-Cup Coffee Maker', 'small_appliance',
    1, 129.99, 10.40, 140.39, NULL, now()
) RETURNING NOTHING;

EXPLAIN INSERT INTO return_item_capacity (
    order_item_id, purchased_quantity, reserved_quantity,
    refunded_quantity, updated_at
) VALUES (
    '40000000-0000-4000-8000-000000000007', 1, 0, 0, now()
)
ON CONFLICT (order_item_id) DO UPDATE SET
    purchased_quantity = excluded.purchased_quantity,
    updated_at = now()
RETURNING NOTHING;
SQL
