-- Deterministic demo fixtures for the Product Returns graph.
--
-- Run as product_returns_app after migrations 001-003 and LangGraph setup.
-- Stable UUIDs and UPSERT make this migration rerunnable. Relative timestamps
-- keep the eligibility scenarios meaningful whenever the demo is rebuilt.

USE product_returns;

BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

UPSERT INTO customers (
    customer_id,
    external_customer_id,
    email,
    account_status,
    created_at,
    updated_at
) VALUES
    ('10000000-0000-4000-8000-000000000001', 'CUST-RON', 'ron@example.com', 'active', now(), now()),
    ('10000000-0000-4000-8000-000000000002', 'CUST-SALLY', 'sally@example.com', 'active', now(), now()),
    ('10000000-0000-4000-8000-000000000003', 'CUST-BOB', 'bob@example.com', 'restricted', now(), now())
RETURNING NOTHING;

UPSERT INTO products (
    product_id,
    sku,
    product_name,
    product_category,
    is_active,
    created_at,
    updated_at
) VALUES
    ('20000000-0000-4000-8000-000000000001', 'TOAST-2SL', 'Two-Slice Toaster', 'small_appliance', true, now(), now()),
    ('20000000-0000-4000-8000-000000000002', 'COFFEE-12C', '12-Cup Coffee Maker', 'small_appliance', true, now(), now()),
    ('20000000-0000-4000-8000-000000000003', 'VAC-PRO-900', 'Pro 900 Vacuum', 'floor_care', true, now(), now()),
    ('20000000-0000-4000-8000-000000000004', 'GIFT-100', '$100 Gift Card', 'gift_card', true, now(), now()),
    ('20000000-0000-4000-8000-000000000005', 'IPHONE-17-256', 'iPhone 17 256GB', 'mobile_phone', true, now(), now())
RETURNING NOTHING;

UPSERT INTO orders (
    order_id,
    order_number,
    customer_id,
    order_status,
    currency,
    subtotal_amount,
    tax_amount,
    shipping_amount,
    total_amount,
    ordered_at,
    created_at,
    updated_at
) VALUES
    ('30000000-0000-4000-8000-000000000001', 'DEMO-1001', '10000000-0000-4000-8000-000000000001', 'delivered', 'USD', 49.99, 4.00, 0.00, 53.99, now() - INTERVAL '10 days', now(), now()),
    ('30000000-0000-4000-8000-000000000002', 'DEMO-1002', '10000000-0000-4000-8000-000000000002', 'delivered', 'USD', 649.00, 51.92, 0.00, 700.92, now() - INTERVAL '8 days', now(), now()),
    ('30000000-0000-4000-8000-000000000003', 'DEMO-1003', '10000000-0000-4000-8000-000000000003', 'delivered', 'USD', 100.00, 0.00, 0.00, 100.00, now() - INTERVAL '5 days', now(), now()),
    ('30000000-0000-4000-8000-000000000004', 'DEMO-1004', '10000000-0000-4000-8000-000000000001', 'delivered', 'USD', 999.00, 79.92, 0.00, 1078.92, now() - INTERVAL '7 days', now(), now()),
    ('30000000-0000-4000-8000-000000000005', 'DEMO-1005', '10000000-0000-4000-8000-000000000002', 'delivered', 'USD', 129.99, 10.40, 0.00, 140.39, now() - INTERVAL '45 days', now(), now()),
    ('30000000-0000-4000-8000-000000000006', 'DEMO-1006', '10000000-0000-4000-8000-000000000003', 'delivered', 'USD', 149.97, 12.00, 0.00, 161.97, now() - INTERVAL '60 days', now(), now())
RETURNING NOTHING;

UPSERT INTO order_items (
    order_item_id,
    order_id,
    product_id,
    sku,
    product_name,
    product_category,
    quantity,
    unit_price,
    tax_amount,
    line_total,
    activated_at,
    created_at
) VALUES
    ('40000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', 'TOAST-2SL', 'Two-Slice Toaster', 'small_appliance', 1, 49.99, 4.00, 53.99, NULL, now()),
    ('40000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000003', 'VAC-PRO-900', 'Pro 900 Vacuum', 'floor_care', 1, 649.00, 51.92, 700.92, NULL, now()),
    ('40000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000003', '20000000-0000-4000-8000-000000000004', 'GIFT-100', '$100 Gift Card', 'gift_card', 1, 100.00, 0.00, 100.00, NULL, now()),
    ('40000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000004', '20000000-0000-4000-8000-000000000005', 'IPHONE-17-256', 'iPhone 17 256GB', 'mobile_phone', 1, 999.00, 79.92, 1078.92, now() - INTERVAL '6 days', now()),
    ('40000000-0000-4000-8000-000000000005', '30000000-0000-4000-8000-000000000005', '20000000-0000-4000-8000-000000000002', 'COFFEE-12C', '12-Cup Coffee Maker', 'small_appliance', 1, 129.99, 10.40, 140.39, NULL, now()),
    ('40000000-0000-4000-8000-000000000006', '30000000-0000-4000-8000-000000000006', '20000000-0000-4000-8000-000000000001', 'TOAST-2SL', 'Two-Slice Toaster', 'small_appliance', 3, 49.99, 12.00, 161.97, NULL, now())
RETURNING NOTHING;

UPSERT INTO return_policies (
    return_policy_id,
    policy_key,
    policy_version,
    title,
    policy_status,
    effective_from,
    effective_until,
    source_uri,
    content_sha256,
    created_at,
    updated_at
) VALUES (
    '50000000-0000-4000-8000-000000000001',
    'standard-returns',
    '1.0',
    'Standard Return and Refund Policy',
    'active',
    '2026-10-16 00:00:00+00',
    NULL,
    'policies/standard-return-policy-v1.md',
    '5ae0ff431a377e15c600ae88472cb305780f42f23f508efe1137c0e459115ee7',
    now(),
    now()
)
RETURNING NOTHING;

UPSERT INTO policy_clauses (
    policy_clause_id,
    return_policy_id,
    clause_key,
    clause_text,
    display_order,
    created_at
) VALUES
    ('51000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000001', 'RET-ELIGIBILITY-001', 'Most products may be returned within 30 calendar days after the original purchase date. The return request must identify the original order and the specific items being returned. Items returned after the 30-day window are not eligible for a refund under the standard policy unless another written warranty or applicable law requires a different result.', 1, now()),
    ('51000000-0000-4000-8000-000000000002', '50000000-0000-4000-8000-000000000001', 'RET-CONDITION-001', 'The product should be returned in substantially the same condition in which it was received. All included parts, accessories, manuals, and packaging should be returned when reasonably possible. We may reduce or deny a refund when an item is damaged through misuse, is missing essential components, or cannot be matched to the original purchase.', 2, now()),
    ('51000000-0000-4000-8000-000000000003', '50000000-0000-4000-8000-000000000001', 'RET-PROOF-001', 'A valid order number or other proof of purchase is required. The purchaser and the item being returned must match our order records.', 3, now()),
    ('51000000-0000-4000-8000-000000000004', '50000000-0000-4000-8000-000000000001', 'RET-EXCEPTION-001', 'Gift cards are final sale and cannot be returned, exchanged, or redeemed for cash except where required by law. Activated mobile phones, including activated iPhones, cannot be returned under the standard return policy. A phone that was delivered defective or damaged may qualify for warranty service or a replacement review instead of a standard refund.', 4, now()),
    ('51000000-0000-4000-8000-000000000005', '50000000-0000-4000-8000-000000000001', 'RET-AMOUNT-001', 'An approved refund is based on the amount actually paid for the eligible items, including applicable item-level taxes. Original shipping charges are not refundable unless the return resulted from our shipping error or the product arrived damaged or defective. Promotional discounts are allocated across the purchased items. The refund cannot exceed the net amount paid for the returned items.', 5, now()),
    ('51000000-0000-4000-8000-000000000006', '50000000-0000-4000-8000-000000000001', 'RET-PAYMENT-001', 'Approved refunds are issued to the original payment method. Processing time after approval depends on the payment provider and the customer''s financial institution. Submitting the same return request more than once does not create an additional refund.', 6, now()),
    ('51000000-0000-4000-8000-000000000007', '50000000-0000-4000-8000-000000000001', 'RET-APPROVAL-001', 'Returns may be sent for manual review when required to confirm eligibility, product condition, account activity, or refund amount. A refund greater than $500.00 requires manager approval before it can be issued.', 7, now()),
    ('51000000-0000-4000-8000-000000000008', '50000000-0000-4000-8000-000000000001', 'RET-RIGHTS-001', 'This policy does not limit rights that cannot legally be excluded. Customers who need help with a return should contact customer support and provide their order number.', 8, now())
RETURNING NOTHING;

-- Historical completed returns provide real evidence for the fraud node. They
-- are deliberately not active graph inputs and have no workflow_runs rows.
UPSERT INTO return_requests (
    return_request_id,
    customer_id,
    order_id,
    request_text,
    classified_intent,
    request_status,
    requested_at,
    updated_at
) VALUES
    ('60000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000006', 'Historical return 1 of 3 for DEMO-1006.', 'refund', 'refunded', now() - INTERVAL '50 days', now() - INTERVAL '50 days'),
    ('60000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000006', 'Historical return 2 of 3 for DEMO-1006.', 'refund', 'refunded', now() - INTERVAL '40 days', now() - INTERVAL '40 days'),
    ('60000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000006', 'Historical return 3 of 3 for DEMO-1006.', 'refund', 'refunded', now() - INTERVAL '30 days', now() - INTERVAL '30 days')
RETURNING NOTHING;

UPSERT INTO return_items (
    return_item_id,
    return_request_id,
    order_item_id,
    requested_quantity,
    return_reason,
    requested_refund_amount,
    created_at
) VALUES
    ('70000000-0000-4000-8000-000000000001', '60000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000006', 1, 'Historical demo return.', 53.99, now() - INTERVAL '50 days'),
    ('70000000-0000-4000-8000-000000000002', '60000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000006', 1, 'Historical demo return.', 53.99, now() - INTERVAL '40 days'),
    ('70000000-0000-4000-8000-000000000003', '60000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000006', 1, 'Historical demo return.', 53.99, now() - INTERVAL '30 days')
RETURNING NOTHING;

COMMIT;

-- Verification summaries.
SELECT 'customers' AS table_name, count(*) AS row_count FROM customers
UNION ALL SELECT 'products', count(*) FROM products
UNION ALL SELECT 'orders', count(*) FROM orders
UNION ALL SELECT 'order_items', count(*) FROM order_items
UNION ALL SELECT 'return_policies', count(*) FROM return_policies
UNION ALL SELECT 'policy_clauses', count(*) FROM policy_clauses
UNION ALL SELECT 'return_requests', count(*) FROM return_requests
UNION ALL SELECT 'return_items', count(*) FROM return_items
ORDER BY table_name;

SELECT
    o.order_number,
    c.external_customer_id,
    c.account_status,
    oi.product_name,
    oi.product_category,
    oi.quantity,
    o.total_amount,
    o.ordered_at,
    oi.activated_at
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE o.order_number LIKE 'DEMO-%'
ORDER BY o.order_number;

SELECT
    rp.policy_key,
    rp.policy_version,
    rp.policy_status,
    rp.source_uri,
    rp.content_sha256,
    count(pc.policy_clause_id) AS clause_count
FROM return_policies AS rp
JOIN policy_clauses AS pc ON pc.return_policy_id = rp.return_policy_id
WHERE rp.policy_key = 'standard-returns'
GROUP BY
    rp.policy_key,
    rp.policy_version,
    rp.policy_status,
    rp.source_uri,
    rp.content_sha256;
