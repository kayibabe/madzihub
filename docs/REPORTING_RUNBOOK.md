# Reporting Runbook

## Purpose
This runbook defines how operational and executive reports should be produced from the dashboard so that outputs are consistent, auditable, and presentation-ready.

## Standard report outputs
Each report should include:
- report title
- selected financial year
- selected zones, schemes, months, and quarters
- generation timestamp
- user who generated the report where feasible
- source note indicating whether data came from imported `RawData.xlsx`

## Export standards
### Excel
Use Excel when the audience needs:
- raw tabular detail
- downstream manipulation
- reconciliation work

The workbook should contain:
- `Summary` sheet
- `Report Data` sheet
- optional `Validation` sheet for warnings or excluded rows

### Print / PDF
Use print/PDF when the audience needs:
- executive review
- board pack insertion
- formal circulation

The printable output should:
- be one report per print job
- use portrait where the data fits cleanly
- switch to landscape for wider tables
- include a visible filter summary and generation timestamp

## Monthly reporting workflow
1. Validate the source workbook before upload.
2. Import the workbook through the secured upload route.
3. Review validation messages and conflict outcomes.
4. Confirm totals and key KPIs against the source workbook.
5. Generate report exports for circulation.
6. Archive the approved workbook and the final exported reports.

## Reconciliation checklist
Before publishing a report, confirm:
- total production matches the source workbook
- total billed and collected values reconcile
- active customers and disconnected customers reconcile
- NRW percentages are within logical bounds
- quarter and annual values are aggregated correctly

## Executive reporting standards
Executive-facing reports should prioritize:
- exceptions
- trends
- zone and scheme comparisons
- risk signals
- short narrative interpretation

Avoid cluttering executive reports with low-value raw detail when a summary table or KPI card is sufficient.
