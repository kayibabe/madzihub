-- MadziHub billing view: PostgreSQL. ILLUSTRATIVE: table and column names below are
-- placeholders; the utility's DBA maps them to the real billing schema.
-- Contract: one row per branch per month; see docs/pilots/BILLING_PILOT.md §3.
CREATE OR REPLACE VIEW v_madzi_monthly AS
WITH months AS (
  SELECT branch_code, date_trunc('month', bill_date)::date AS period_month FROM bills
  UNION SELECT branch_code, date_trunc('month', receipt_date)::date FROM receipts
),
billed AS (
  SELECT branch_code, date_trunc('month', bill_date)::date AS period_month,
         SUM(consumption_m3) AS billed_volume_m3, SUM(amount) AS billed_amount, MAX(updated_at) AS updated_at
  FROM bills WHERE status <> 'CANCELLED' GROUP BY 1, 2
),
paid AS (
  SELECT branch_code, date_trunc('month', receipt_date)::date AS period_month,
         SUM(amount) AS cash_collected, MAX(updated_at) AS updated_at
  FROM receipts WHERE status <> 'REVERSED' GROUP BY 1, 2
),
accounts AS (
  SELECT m.branch_code, m.period_month,
         COUNT(*) FILTER (WHERE a.connected_on < m.period_month + INTERVAL '1 month'
                          AND (a.disconnected_on IS NULL OR a.disconnected_on >= m.period_month + INTERVAL '1 month')) AS active_accounts,
         COUNT(*) FILTER (WHERE date_trunc('month', a.connected_on) = m.period_month) AS new_connections,
         COUNT(*) FILTER (WHERE date_trunc('month', a.disconnected_on) = m.period_month) AS disconnections,
         MAX(a.updated_at) AS updated_at
  FROM months m JOIN accounts a ON a.branch_code = m.branch_code
  GROUP BY 1, 2
)
SELECT m.branch_code, m.period_month,
       b.billed_volume_m3, b.billed_amount, p.cash_collected,
       ac.active_accounts, ac.new_connections, ac.disconnections,
       GREATEST(b.updated_at, p.updated_at, ac.updated_at) AS updated_at
FROM months m
LEFT JOIN billed b   USING (branch_code, period_month)
LEFT JOIN paid p     USING (branch_code, period_month)
LEFT JOIN accounts ac USING (branch_code, period_month);

-- Read-only account for MadziHub, restricted to this view.
-- CREATE ROLE madzihub_reader LOGIN PASSWORD '<set by DBA>';
-- GRANT USAGE ON SCHEMA public TO madzihub_reader;
-- GRANT SELECT ON v_madzi_monthly TO madzihub_reader;
