-- Product Returns demo: concurrency-safe per-order-item return quantities.
--
-- A request first reserves quantity. Rejection releases it; successful refund
-- converts it to refunded quantity. The capacity CHECK is the final invariant
-- protecting against returning more units than were purchased.

USE product_returns;

CREATE TABLE IF NOT EXISTS return_item_capacity (
    order_item_id UUID PRIMARY KEY REFERENCES order_items (order_item_id),
    purchased_quantity INT8 NOT NULL CHECK (purchased_quantity > 0),
    reserved_quantity INT8 NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    refunded_quantity INT8 NOT NULL DEFAULT 0 CHECK (refunded_quantity >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reserved_quantity + refunded_quantity <= purchased_quantity)
);

CREATE TABLE IF NOT EXISTS return_item_allocations (
    return_item_allocation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    return_request_id UUID NOT NULL REFERENCES return_requests (return_request_id),
    order_item_id UUID NOT NULL REFERENCES order_items (order_item_id),
    allocated_quantity INT8 NOT NULL CHECK (allocated_quantity > 0),
    allocation_status STRING NOT NULL
        CHECK (allocation_status IN ('reserved', 'refunded', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE INDEX return_allocations_by_request_item (
        return_request_id,
        order_item_id
    ) STORING (allocated_quantity, allocation_status)
);

-- Preserve the meaning of existing return history. Active historical rows
-- reserve quantity, successful rows consume it, and rejected/failed rows do
-- not consume capacity.
INSERT INTO return_item_allocations (
    return_item_allocation_id,
    return_request_id,
    order_item_id,
    allocated_quantity,
    allocation_status,
    created_at,
    updated_at
)
SELECT
    ri.return_item_id,
    ri.return_request_id,
    ri.order_item_id,
    ri.requested_quantity,
    CASE
        WHEN rr.request_status = 'refunded' THEN 'refunded'
        WHEN rr.request_status IN (
            'received', 'classifying', 'gathering_evidence',
            'pending_approval', 'approved', 'refunding'
        ) THEN 'reserved'
        ELSE 'released'
    END,
    ri.created_at,
    rr.updated_at
FROM return_items AS ri
JOIN return_requests AS rr
  ON rr.return_request_id = ri.return_request_id
ON CONFLICT (return_request_id, order_item_id) DO NOTHING;

INSERT INTO return_item_capacity (
    order_item_id,
    purchased_quantity,
    reserved_quantity,
    refunded_quantity
)
SELECT
    oi.order_item_id,
    oi.quantity,
    COALESCE(sum(a.allocated_quantity) FILTER (
        WHERE a.allocation_status = 'reserved'
    ), 0)::INT8,
    COALESCE(sum(a.allocated_quantity) FILTER (
        WHERE a.allocation_status = 'refunded'
    ), 0)::INT8
FROM order_items AS oi
LEFT JOIN return_item_allocations AS a
  ON a.order_item_id = oi.order_item_id
GROUP BY oi.order_item_id, oi.quantity
ON CONFLICT (order_item_id) DO UPDATE SET
    purchased_quantity = excluded.purchased_quantity,
    reserved_quantity = excluded.reserved_quantity,
    refunded_quantity = excluded.refunded_quantity,
    updated_at = now();

SELECT
    count(*) AS capacity_rows,
    sum(purchased_quantity) AS purchased_units,
    sum(reserved_quantity) AS reserved_units,
    sum(refunded_quantity) AS refunded_units
FROM return_item_capacity;
