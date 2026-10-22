-- Add the covering allocation key to databases where migration 008 had
-- already created its original non-covering UNIQUE constraint.

USE product_returns;

CREATE UNIQUE INDEX IF NOT EXISTS return_allocations_by_request_item
ON return_item_allocations (return_request_id, order_item_id)
STORING (allocated_quantity, allocation_status);
