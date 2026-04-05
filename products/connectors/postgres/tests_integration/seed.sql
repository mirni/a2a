-- Seed schema + data for PostgreSQL connector integration tests.
-- Loaded automatically by the postgres:16-alpine container on first start
-- (docker-entrypoint-initdb.d). Idempotent: uses IF NOT EXISTS + ON CONFLICT.
--
-- Contains:
--   public.users (50 rows)
--   public.orders (200 rows, FK -> users)
--   public.products (30 rows)
--   public.big_table (10k rows — for max_rows + timeout tests)
--   public.orders_summary (VIEW — for table_type=VIEW distinction test)
--   test_schema.audit_log (100 rows — for custom-schema tests)

CREATE SCHEMA IF NOT EXISTS test_schema;

-- ---------------------------------------------------------------------------
-- public.users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.users (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    active      BOOLEAN NOT NULL DEFAULT true,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.users (email, name, active, metadata)
SELECT
    'user' || i || '@example.com',
    'User ' || i,
    (i % 7) <> 0,  -- ~86% active
    jsonb_build_object('tier', CASE WHEN i % 3 = 0 THEN 'pro' ELSE 'free' END, 'seq', i)
FROM generate_series(1, 50) AS i
ON CONFLICT (email) DO NOTHING;

-- ---------------------------------------------------------------------------
-- public.products
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.products (
    id      SERIAL PRIMARY KEY,
    sku     TEXT UNIQUE NOT NULL,
    name    TEXT NOT NULL,
    price   NUMERIC(10, 2) NOT NULL
);

INSERT INTO public.products (sku, name, price)
SELECT
    'SKU-' || LPAD(i::TEXT, 4, '0'),
    'Product ' || i,
    ROUND((10 + (i * 3.14))::NUMERIC, 2)
FROM generate_series(1, 30) AS i
ON CONFLICT (sku) DO NOTHING;

-- ---------------------------------------------------------------------------
-- public.orders
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.orders (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    amount      NUMERIC(10, 2) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only insert orders if table is empty (idempotent)
INSERT INTO public.orders (user_id, amount, status)
SELECT
    ((i - 1) % 50) + 1,
    ROUND((5 + i * 1.75)::NUMERIC, 2),
    CASE (i % 4)
        WHEN 0 THEN 'paid'
        WHEN 1 THEN 'pending'
        WHEN 2 THEN 'refunded'
        ELSE 'cancelled'
    END
FROM generate_series(1, 200) AS i
WHERE NOT EXISTS (SELECT 1 FROM public.orders LIMIT 1);

-- ---------------------------------------------------------------------------
-- public.big_table (10k rows — for max_rows + timeout tests)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.big_table (
    id      BIGSERIAL PRIMARY KEY,
    val     INT NOT NULL,
    label   TEXT
);

INSERT INTO public.big_table (val, label)
SELECT i, 'row-' || i
FROM generate_series(1, 10000) AS i
WHERE NOT EXISTS (SELECT 1 FROM public.big_table LIMIT 1);

-- ---------------------------------------------------------------------------
-- public.orders_summary (VIEW for table_type distinction)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.orders_summary AS
SELECT
    u.id AS user_id,
    u.email,
    COUNT(o.id) AS order_count,
    COALESCE(SUM(o.amount), 0) AS total_amount
FROM public.users u
LEFT JOIN public.orders o ON o.user_id = u.id
GROUP BY u.id, u.email;

-- ---------------------------------------------------------------------------
-- test_schema.audit_log (custom schema)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_schema.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event       TEXT NOT NULL,
    payload     JSONB,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO test_schema.audit_log (event, payload)
SELECT
    'event_' || (i % 5),
    jsonb_build_object('seq', i, 'msg', 'audit entry ' || i)
FROM generate_series(1, 100) AS i
WHERE NOT EXISTS (SELECT 1 FROM test_schema.audit_log LIMIT 1);
