# RawData Dashboard Coverage Audit

- Source workbook: `/D:/WebApps/OpsApp/uploads/RawData.xlsx`
- Authoritative sheet: `DataEntry`
- Total `DataEntry` headers audited: 222
- Parser-mapped headers: 222 / 222
- Unmapped headers: `0`
- Dimension-only fields surfaced through filter/meta instead of report tables: `Fiscal Year`, `Month No.`

## Field Coverage

| Section | Workbook Header | DB Field | Dashboard Destination |
|---|---|---|---|
| RECORD DIMENSIONS | Zone | `zone` | Global filter bar / page meta |
| RECORD DIMENSIONS | Scheme | `scheme` | Global filter bar / page meta |
| RECORD DIMENSIONS | Fiscal Year | `fiscal_year` | Global filter bar / page meta |
| RECORD DIMENSIONS | Year | `year` | Global filter bar / page meta |
| RECORD DIMENSIONS | Month No. | `month_no` | Global filter bar / page meta |
| RECORD DIMENSIONS | Month | `month` | Global filter bar / page meta |
| RECORD DIMENSIONS | Quarter | `quarter` | Global filter bar / page meta |
| WATER PRODUCTION & NRW | Volume Produced (m³) | `vol_produced` | Production |
| WATER PRODUCTION & NRW | Vol Billed Individual Postpaid | `vol_billed_indiv_pp` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed CWP Postpaid | `vol_billed_cwp_pp` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed Institutions Postpaid | `vol_billed_inst_pp` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed Commercial Postpaid | `vol_billed_comm_pp` | Customer Accounts |
| WATER PRODUCTION & NRW | TOTAL Vol Billed Postpaid | `total_vol_billed_pp` | Covered in an existing summary/detail report |
| WATER PRODUCTION & NRW | Vol Billed Individual Prepaid | `vol_billed_indiv_prepaid` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed CWP Prepaid | `vol_billed_cwp_prepaid` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed Institutions Prepaid | `vol_billed_inst_prepaid` | Customer Accounts |
| WATER PRODUCTION & NRW | Vol Billed Commercial Prepaid | `vol_billed_comm_prepaid` | Customer Accounts |
| WATER PRODUCTION & NRW | TOTAL Vol Billed Prepaid | `total_vol_billed_prepaid` | Covered in an existing summary/detail report |
| WATER PRODUCTION & NRW | TOTAL Revenue Water m³ | `revenue_water` | Covered in an existing summary/detail report |
| WATER PRODUCTION & NRW | Non-Revenue Water m³ | `nrw` | Production |
| WATER PRODUCTION & NRW | % NRW | `pct_nrw` | Production |
| TREATMENT CHEMICALS | Chlorine kg | `chlorine_kg` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Chlorine kg per m³ | `chlorine_kg_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Alum Sulphate kg | `alum_kg` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Alum Sulphate kg per m³ | `alum_kg_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Soda Ash kg | `soda_ash_kg` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Soda Ash kg per m³ | `soda_ash_kg_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Algae Floc litres | `algae_floc_litres` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Algae Floc per m³ | `algae_floc_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Sud Floc litres | `sud_floc_litres` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Sud Floc per m³ | `sud_floc_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Potassium Permanganate kg | `kmno4_kg` | Water Treatment & Energy |
| TREATMENT CHEMICALS | KMnO4 per m³ | `kmno4_per_m3` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Cost of Chemicals MWK | `chem_cost` | Water Treatment & Energy |
| TREATMENT CHEMICALS | Chem Cost per m³ | `chem_cost_per_m3` | Water Treatment & Energy |
| POWER | Power Usage kWh | `power_kwh` | Water Treatment & Energy |
| POWER | Power per m³ | `power_kwh_per_m3` | Water Treatment & Energy |
| POWER | Cost of Power MWK | `power_cost` | Water Treatment & Energy |
| POWER | Power Cost per m³ | `power_cost_per_m3` | Water Treatment & Energy |
| TRANSPORT & OPERATIONS | Distances Covered km | `distances_km` | Workforce & Fleet Efficiency |
| TRANSPORT & OPERATIONS | Fuel Used litres | `fuel_used_litres` | Workforce & Fleet Efficiency |
| TRANSPORT & OPERATIONS | Cost of Fuel MWK | `fuel_cost` | Workforce & Fleet Efficiency |
| TRANSPORT & OPERATIONS | Maintenance MWK | `maintenance` | Workforce & Fleet Efficiency |
| TRANSPORT & OPERATIONS | Staff Costs MWK | `staff_costs` | Operating Expenses |
| TRANSPORT & OPERATIONS | Wages MWK | `wages` | Operating Expenses |
| TRANSPORT & OPERATIONS | Other Overhead MWK | `other_overhead` | Operating Expenses |
| TRANSPORT & OPERATIONS | TOTAL Operating Costs MWK | `op_cost` | Operating Expenses |
| TRANSPORT & OPERATIONS | OpCost per m³ Produced | `op_cost_per_m3_produced` | Operating Expenses |
| TRANSPORT & OPERATIONS | OpCost per m³ Billed | `op_cost_per_m3_billed` | Operating Expenses |
| STAFFING | Permanent Staff | `perm_staff` | Workforce & Fleet Efficiency |
| STAFFING | Staff per 1000m³ 12h | `staff_per_1000m3_12h` | Workforce & Fleet Efficiency |
| STAFFING | Temporary Staff | `temp_staff` | Workforce & Fleet Efficiency |
| CONNECTIONS — INDIVIDUAL | Indiv Conn BroughtFwd | `conn_indiv_bfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — INDIVIDUAL | Indiv Conn Applied PP | `conn_indiv_applied_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — INDIVIDUAL | Indiv Conn Done PP | `conn_indiv_done_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — INDIVIDUAL | Indiv Conn Done Prepaid | `conn_indiv_done_prepaid` | Connection Pipeline by Customer Class |
| CONNECTIONS — INDIVIDUAL | Indiv Conn TOTAL Done | `conn_indiv_total_done` | Connection Pipeline by Customer Class |
| CONNECTIONS — INDIVIDUAL | Indiv Conn CarriedFwd | `conn_indiv_cfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn BroughtFwd | `conn_inst_bfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn Applied PP | `conn_inst_applied_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn Done PP | `conn_inst_done_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn Done Prepaid | `conn_inst_done_prepaid` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn TOTAL Done | `conn_inst_total_done` | Connection Pipeline by Customer Class |
| CONNECTIONS — INSTITUTIONAL | Inst Conn CarriedFwd | `conn_inst_cfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn BroughtFwd | `conn_comm_bfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn Applied PP | `conn_comm_applied_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn Done PP | `conn_comm_done_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn Done Prepaid | `conn_comm_done_prepaid` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn TOTAL Done | `conn_comm_total_done` | Connection Pipeline by Customer Class |
| CONNECTIONS — COMMERCIAL | Comm Conn CarriedFwd | `conn_comm_cfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn BroughtFwd | `conn_cwp_bfwd` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn Applied PP | `conn_cwp_applied_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn Done PP | `conn_cwp_done_pp` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn Done Prepaid | `conn_cwp_done_prepaid` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn TOTAL Done | `conn_cwp_total_done` | Connection Pipeline by Customer Class |
| CONNECTIONS — CWP | CWP Conn CarriedFwd | `conn_cwp_cfwd` | Connection Pipeline by Customer Class |
| AGGREGATED CONNECTIONS | ALL Conn BroughtFwd | `all_conn_bfwd` | New Water Connections |
| AGGREGATED CONNECTIONS | ALL Conn Applied | `all_conn_applied` | New Water Connections |
| AGGREGATED CONNECTIONS | ALL Conn TOTAL Done | `new_connections` | Covered in an existing summary/detail report |
| AGGREGATED CONNECTIONS | ALL Conn CarriedFwd | `all_conn_cfwd` | New Water Connections |
| METERS & DISCONNECTIONS | Prepaid Meters Installed | `prepaid_meters_installed` | Covered in an existing summary/detail report |
| METERS & DISCONNECTIONS | Disconnected Individual | `disconnected_individual` | Customer Accounts |
| METERS & DISCONNECTIONS | Disconnected Institutional | `disconnected_inst` | Customer Accounts |
| METERS & DISCONNECTIONS | Disconnected Commercial | `disconnected_commercial` | Customer Accounts |
| METERS & DISCONNECTIONS | Disconnected CWP | `disconnected_cwp` | Customer Accounts |
| METERS & DISCONNECTIONS | TOTAL Disconnected | `total_disconnected` | Customer Accounts |
| ACTIVE CONSUMERS | Active Postpaid Individual | `active_post_individual` | Customer Accounts |
| ACTIVE CONSUMERS | Active Postpaid Institutional | `active_post_inst` | Customer Accounts |
| ACTIVE CONSUMERS | Active Postpaid Commercial | `active_post_commercial` | Customer Accounts |
| ACTIVE CONSUMERS | Active Postpaid CWP | `active_post_cwp` | Customer Accounts |
| ACTIVE CONSUMERS | TOTAL Active Postpaid | `active_postpaid` | Customer Accounts |
| ACTIVE CONSUMERS | Active Prepaid Individual | `active_prep_individual` | Customer Accounts |
| ACTIVE CONSUMERS | Active Prepaid Institutional | `active_prep_inst` | Customer Accounts |
| ACTIVE CONSUMERS | Active Prepaid Commercial | `active_prep_commercial` | Customer Accounts |
| ACTIVE CONSUMERS | Active Prepaid CWP | `active_prep_cwp` | Customer Accounts |
| ACTIVE CONSUMERS | TOTAL Active Prepaid | `active_prepaid` | Customer Accounts |
| ACTIVE CONSUMERS | TOTAL Active Customers | `active_customers` | Customer Accounts |
| ACTIVE CONSUMERS | Total Metered Consumers | `total_metered` | Customer Accounts |
| POPULATION | Population Supply Area | `pop_supply_area` | Customer Accounts |
| POPULATION | Population Supplied | `pop_supplied` | Customer Accounts |
| POPULATION | Pct Population Supplied | `pct_pop_supplied` | Customer Accounts |
| STUCK METERS — INSTITUTIONAL | Inst StuckM BroughtFwd | `stuck_inst_bfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — INSTITUTIONAL | Inst StuckM New | `stuck_inst_new` | Meter Exceptions by Customer Class |
| STUCK METERS — INSTITUTIONAL | Inst StuckM Repaired | `stuck_inst_repaired` | Meter Exceptions by Customer Class |
| STUCK METERS — INSTITUTIONAL | Inst StuckM Replaced | `stuck_inst_replaced` | Meter Exceptions by Customer Class |
| STUCK METERS — INSTITUTIONAL | Inst StuckM CarriedFwd | `stuck_inst_cfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — COMMERCIAL | Comm StuckM BroughtFwd | `stuck_comm_bfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — COMMERCIAL | Comm StuckM New | `stuck_comm_new` | Meter Exceptions by Customer Class |
| STUCK METERS — COMMERCIAL | Comm StuckM Repaired | `stuck_comm_repaired` | Meter Exceptions by Customer Class |
| STUCK METERS — COMMERCIAL | Comm StuckM Replaced | `stuck_comm_replaced` | Meter Exceptions by Customer Class |
| STUCK METERS — COMMERCIAL | Comm StuckM CarriedFwd | `stuck_comm_cfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — CWP | CWP StuckM BroughtFwd | `stuck_cwp_bfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — CWP | CWP StuckM New | `stuck_cwp_new` | Meter Exceptions by Customer Class |
| STUCK METERS — CWP | CWP StuckM Repaired | `stuck_cwp_repaired` | Meter Exceptions by Customer Class |
| STUCK METERS — CWP | CWP StuckM Replaced | `stuck_cwp_replaced` | Meter Exceptions by Customer Class |
| STUCK METERS — CWP | CWP StuckM CarriedFwd | `stuck_cwp_cfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — INDIVIDUAL | Indiv StuckM BroughtFwd | `stuck_indiv_bfwd` | Meter Exceptions by Customer Class |
| STUCK METERS — INDIVIDUAL | Indiv StuckM New | `stuck_indiv_new` | Meter Exceptions by Customer Class |
| STUCK METERS — INDIVIDUAL | Indiv StuckM Repaired | `stuck_indiv_repaired` | Meter Exceptions by Customer Class |
| STUCK METERS — INDIVIDUAL | Indiv StuckM Replaced | `stuck_indiv_replaced` | Meter Exceptions by Customer Class |
| STUCK METERS — INDIVIDUAL | Indiv StuckM CarriedFwd | `stuck_indiv_cfwd` | Meter Exceptions by Customer Class |
| AGGREGATED STUCK METERS | ALL StuckM BroughtFwd | `stuck_meters` | Meter Exceptions |
| AGGREGATED STUCK METERS | ALL StuckM New | `stuck_new` | Meter Exceptions |
| AGGREGATED STUCK METERS | ALL StuckM Repaired | `stuck_repaired` | Meter Exceptions |
| AGGREGATED STUCK METERS | ALL StuckM Replaced | `stuck_replaced` | Meter Exceptions |
| AGGREGATED STUCK METERS | ALL StuckM CarriedFwd | `all_stuck_cfwd` | Meter Exceptions |
| PIPE BREAKDOWNS — PVC | PVC 20mm | `pvc_20mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 25mm | `pvc_25mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 32mm | `pvc_32mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 40mm | `pvc_40mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 50mm | `pvc_50mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 63mm | `pvc_63mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 75mm | `pvc_75mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 90mm | `pvc_90mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 110mm | `pvc_110mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 160mm | `pvc_160mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 200mm | `pvc_200mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 250mm | `pvc_250mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — PVC | PVC 315mm | `pvc_315mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 15mm | `gi_15mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 20mm | `gi_20mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 25mm | `gi_25mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 40mm | `gi_40mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 50mm | `gi_50mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 75mm | `gi_75mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 100mm | `gi_100mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 150mm | `gi_150mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — GI | GI 200mm | `gi_200mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 150mm | `di_150mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 200mm | `di_200mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 250mm | `di_250mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 300mm | `di_300mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 350mm | `di_350mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — DI | DI 525mm | `di_525mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | HDPE 20mm | `hdpe_20mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | HDPE 25mm | `hdpe_25mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | HDPE 32mm | `hdpe_32mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | HDPE 50mm | `hdpe_50mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | AC 50mm | `ac_50mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | AC 75mm | `ac_75mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | AC 100mm | `ac_100mm` | Pipe Failure by Material and Size |
| PIPE BREAKDOWNS — HDPE & AC | AC 150mm | `ac_150mm` | Pipe Failure by Material and Size |
| TOTAL BREAKDOWNS | TOTAL Pipe Breakdowns | `pipe_breakdowns` | Pipe Failure by Material and Size |
| PUMPS & SUPPLY HOURS | Pump Breakdowns | `pump_breakdowns` | Production |
| PUMPS & SUPPLY HOURS | Pump Hours Lost | `pump_hours_lost` | Production |
| PUMPS & SUPPLY HOURS | Normal Supply Hours | `supply_hours` | Production |
| PUMPS & SUPPLY HOURS | Power Failure Hours | `power_fail_hours` | Water Treatment & Energy |
| DEVELOPMENT LINES | DevLines 32mm | `dev_lines_32mm` | Covered in an existing summary/detail report |
| DEVELOPMENT LINES | DevLines 50mm | `dev_lines_50mm` | Covered in an existing summary/detail report |
| DEVELOPMENT LINES | DevLines 63mm | `dev_lines_63mm` | Covered in an existing summary/detail report |
| DEVELOPMENT LINES | DevLines 90mm | `dev_lines_90mm` | Covered in an existing summary/detail report |
| DEVELOPMENT LINES | DevLines 110mm | `dev_lines_110mm` | Covered in an existing summary/detail report |
| DEVELOPMENT LINES | TOTAL Dev Lines Done | `dev_lines_total` | Covered in an existing summary/detail report |
| CASH COLLECTED | Cash Coll Indiv PP | `cash_coll_indiv_pp` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll CWP PP | `cash_coll_cwp_pp` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll Comm PP | `cash_coll_comm_pp` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll Inst PP | `cash_coll_inst_pp` | Customer Segment Revenue |
| CASH COLLECTED | TOTAL Cash Coll PP | `cash_coll_pp` | Collections |
| CASH COLLECTED | Cash Coll Indiv Prepaid | `cash_coll_indiv_prepaid` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll CWP Prepaid | `cash_coll_cwp_prepaid` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll Comm Prepaid | `cash_coll_comm_prepaid` | Customer Segment Revenue |
| CASH COLLECTED | Cash Coll Inst Prepaid | `cash_coll_inst_prepaid` | Customer Segment Revenue |
| CASH COLLECTED | TOTAL Cash Coll Prepaid | `cash_coll_prepaid` | Collections |
| CASH COLLECTED | TOTAL Cash Collected | `cash_collected` | Collections |
| AMOUNTS BILLED | Amt Billed Indiv PP | `amt_billed_indiv_pp` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed CWP PP | `amt_billed_cwp_pp` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed Inst PP | `amt_billed_inst_pp` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed Comm PP | `amt_billed_comm_pp` | Customer Segment Revenue |
| AMOUNTS BILLED | TOTAL Amt Billed PP | `amt_billed_pp` | Revenue Billing |
| AMOUNTS BILLED | Amt Billed Indiv Prepaid | `amt_billed_indiv_prepaid` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed CWP Prepaid | `amt_billed_cwp_prepaid` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed Inst Prepaid | `amt_billed_inst_prepaid` | Customer Segment Revenue |
| AMOUNTS BILLED | Amt Billed Comm Prepaid | `amt_billed_comm_prepaid` | Customer Segment Revenue |
| AMOUNTS BILLED | TOTAL Amt Billed Prepaid | `amt_billed_prepaid` | Revenue Billing |
| AMOUNTS BILLED | TOTAL Amount Billed | `amt_billed` | Revenue Billing |
| SERVICE CHARGES | Svc Charge Individual | `service_charge_individual` | Customer Segment Revenue |
| SERVICE CHARGES | Svc Charge CWP | `service_charge_cwp` | Customer Segment Revenue |
| SERVICE CHARGES | Svc Charge Institutions | `service_charge_institutions` | Customer Segment Revenue |
| SERVICE CHARGES | Svc Charge Commercial | `service_charge_commercial` | Customer Segment Revenue |
| SERVICE CHARGES | TOTAL Service Charge | `service_charge` | Ancillary Charges |
| METER RENTAL | Meter Rental Individual | `meter_rental_individual` | Customer Segment Revenue |
| METER RENTAL | Meter Rental CWP | `meter_rental_cwp` | Customer Segment Revenue |
| METER RENTAL | Meter Rental Institutions | `meter_rental_institutions` | Customer Segment Revenue |
| METER RENTAL | Meter Rental Commercial | `meter_rental_commercial` | Customer Segment Revenue |
| METER RENTAL | TOTAL Meter Rental | `meter_rental` | Ancillary Charges |
| FINANCIAL KPIs | TOTAL Sales MWK | `total_sales` | Ancillary Charges |
| FINANCIAL KPIs | Private Debtors MWK | `private_debtors` | Debtors |
| FINANCIAL KPIs | Public Debtors MWK | `public_debtors` | Debtors |
| FINANCIAL KPIs | TOTAL Debtors MWK | `total_debtors` | Debtors |
| FINANCIAL KPIs | OpCost per Sales | `op_cost_per_sales` | Operating Expenses |
| FINANCIAL KPIs | Cash Collection Rate | `collection_rate` | Covered in an existing summary/detail report |
| FINANCIAL KPIs | Collection per Total Sales | `collection_per_sales` | Collections |
| CONNECTION PERFORMANCE | Cust Applied Connection | `conn_applied` | Service Connectivity |
| CONNECTION PERFORMANCE | Days to Quotation | `days_to_quotation` | Service Connectivity |
| CONNECTION PERFORMANCE | Cust Fully Paid | `conn_fully_paid` | Service Connectivity |
| CONNECTION PERFORMANCE | Paid-up Applicants | `paid_up_applicants` | Service Connectivity |
| CONNECTION PERFORMANCE | Days to Connect | `days_to_connect` | Service Connectivity |
| CONNECTION PERFORMANCE | Connection Days | `connection_days` | Service Connectivity |
| CONNECTION PERFORMANCE | Connectivity Rate | `connectivity_rate` | Service Connectivity |
| QUERY PERFORMANCE | Queries Received | `queries_received` | Service Connectivity |
| QUERY PERFORMANCE | Time to Resolve Queries | `time_to_resolve` | Service Connectivity |
| QUERY PERFORMANCE | Response Time avg | `response_time_avg` | Service Connectivity |