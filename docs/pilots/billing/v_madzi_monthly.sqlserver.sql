-- MadziHub billing view: SQL Server. ILLUSTRATIVE: placeholder table and column names.
-- Contract: one row per branch per month; see docs/pilots/BILLING_PILOT.md §3.
CREATE OR ALTER VIEW dbo.v_madzi_monthly AS
WITH months AS (
  SELECT branch_code, DATEFROMPARTS(YEAR(bill_date), MONTH(bill_date), 1) AS period_month FROM dbo.bills
  UNION SELECT branch_code, DATEFROMPARTS(YEAR(receipt_date), MONTH(receipt_date), 1) FROM dbo.receipts
),
billed AS (
  SELECT branch_code, DATEFROMPARTS(YEAR(bill_date), MONTH(bill_date), 1) AS period_month,
         SUM(consumption_m3) AS billed_volume_m3, SUM(amount) AS billed_amount, MAX(updated_at) AS updated_at
  FROM dbo.bills WHERE status <> 'CANCELLED'
  GROUP BY branch_code, DATEFROMPARTS(YEAR(bill_date), MONTH(bill_date), 1)
),
paid AS (
  SELECT branch_code, DATEFROMPARTS(YEAR(receipt_date), MONTH(receipt_date), 1) AS period_month,
         SUM(amount) AS cash_collected, MAX(updated_at) AS updated_at
  FROM dbo.receipts WHERE status <> 'REVERSED'
  GROUP BY branch_code, DATEFROMPARTS(YEAR(receipt_date), MONTH(receipt_date), 1)
),
accounts AS (
  SELECT m.branch_code, m.period_month,
         SUM(CASE WHEN a.connected_on < DATEADD(month, 1, m.period_month)
                   AND (a.disconnected_on IS NULL OR a.disconnected_on >= DATEADD(month, 1, m.period_month)) THEN 1 ELSE 0 END) AS active_accounts,
         SUM(CASE WHEN DATEFROMPARTS(YEAR(a.connected_on), MONTH(a.connected_on), 1) = m.period_month THEN 1 ELSE 0 END) AS new_connections,
         SUM(CASE WHEN a.disconnected_on IS NOT NULL AND DATEFROMPARTS(YEAR(a.disconnected_on), MONTH(a.disconnected_on), 1) = m.period_month THEN 1 ELSE 0 END) AS disconnections,
         MAX(a.updated_at) AS updated_at
  FROM months m JOIN dbo.accounts a ON a.branch_code = m.branch_code
  GROUP BY m.branch_code, m.period_month
)
SELECT m.branch_code, m.period_month, b.billed_volume_m3, b.billed_amount, p.cash_collected,
       ac.active_accounts, ac.new_connections, ac.disconnections,
       (SELECT MAX(v) FROM (VALUES (b.updated_at), (p.updated_at), (ac.updated_at)) AS t(v)) AS updated_at
FROM months m
LEFT JOIN billed b   ON b.branch_code = m.branch_code AND b.period_month = m.period_month
LEFT JOIN paid p     ON p.branch_code = m.branch_code AND p.period_month = m.period_month
LEFT JOIN accounts ac ON ac.branch_code = m.branch_code AND ac.period_month = m.period_month;

-- CREATE LOGIN madzihub_reader WITH PASSWORD = '<set by DBA>';
-- CREATE USER madzihub_reader FOR LOGIN madzihub_reader;
-- GRANT SELECT ON dbo.v_madzi_monthly TO madzihub_reader;
