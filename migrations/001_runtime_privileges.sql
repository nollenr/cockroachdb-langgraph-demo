-- Runtime privilege policy for the product_returns application.
--
-- Run this migration while connected to CockroachDB as `ron`.
-- It is safe to run before the application tables exist: the default
-- privileges cover future tables, and the ALL TABLES grant covers any tables
-- that already exist when the migration is rerun.

USE product_returns;

-- Do not let every SQL user connect to this project database merely through
-- membership in CockroachDB's built-in `public` role. Grant access explicitly
-- to the application identity instead.
REVOKE CONNECT ON DATABASE product_returns FROM public;
GRANT CONNECT ON DATABASE product_returns TO product_returns_app;

-- A user needs USAGE to resolve objects in a schema. USAGE does not grant
-- permission to create objects or read/write table data.
GRANT USAGE ON SCHEMA public TO product_returns_app;

-- Prevent arbitrary SQL users from creating objects in the public schema.
-- `ron`, as the database/schema owner, retains the ability to run migrations.
REVOKE CREATE ON SCHEMA public FROM public;

-- Automatically grant runtime access when `ron` creates new tables, including
-- the LangGraph checkpoint tables created during the deployment-time setup.
ALTER DEFAULT PRIVILEGES FOR USER ron IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLES TO product_returns_app;

-- Apply the same runtime permissions to tables that already exist. This makes
-- the migration safe to rerun after adding application or checkpoint tables.
GRANT SELECT, INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA public
TO product_returns_app;

-- Verification: inspect direct and inherited database/schema privileges,
-- future-object defaults, and current table privileges.
SHOW GRANTS ON DATABASE product_returns FOR product_returns_app;
SHOW GRANTS ON SCHEMA public FOR product_returns_app;
SHOW DEFAULT PRIVILEGES FOR USER ron IN SCHEMA public;
SHOW GRANTS ON TABLE product_returns.public.* FOR product_returns_app;
