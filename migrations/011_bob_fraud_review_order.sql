-- Add a recent, otherwise eligible Bob order whose risk signals alone require
-- manager review. Stable UUIDs and UPSERT make this demo fixture rerunnable.

USE product_returns;

BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

UPSERT INTO orders (
    order_id, order_number, customer_id, order_status, currency,
    subtotal_amount, tax_amount, shipping_amount, total_amount,
    ordered_at, created_at, updated_at
) VALUES (
    '30000000-0000-4000-8000-000000000007',
    'DEMO-1007',
    '10000000-0000-4000-8000-000000000003',
    'delivered', 'USD', 129.99, 10.40, 0.00, 140.39,
    now() - INTERVAL '6 days', now(), now()
) RETURNING NOTHING;

UPSERT INTO order_items (
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

INSERT INTO return_item_capacity (
    order_item_id, purchased_quantity, reserved_quantity,
    refunded_quantity, updated_at
) VALUES (
    '40000000-0000-4000-8000-000000000007', 1, 0, 0, now()
)
ON CONFLICT (order_item_id) DO UPDATE SET
    purchased_quantity = excluded.purchased_quantity,
    updated_at = now()
RETURNING NOTHING;

COMMIT;

SELECT o.order_number, c.external_customer_id, c.account_status,
       oi.product_name, oi.quantity, o.total_amount, o.ordered_at
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE o.order_number = 'DEMO-1007';
