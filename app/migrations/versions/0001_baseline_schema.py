"""baseline schema

The schema as it stood when Alembic was adopted (the models at commit 8de1ef9).
Fresh databases are built from this; pre-Alembic databases are checked against
baseline_0001.json and stamped by `python -m app.migrate adopt`, never re-created.

Do not edit this revision to change the schema: add a new revision instead.

Revision ID: 0001
Revises: 
Create Date: 2026-09-24 23:18:15.227285
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('activity_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=60), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('detail', sa.String(length=500), nullable=True),
    sa.Column('ip_address', sa.String(length=60), nullable=True),
    sa.Column('logged_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('activity_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_log_logged_at'), ['logged_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_log_username'), ['username'], unique=False)

    op.create_table('data_sources',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('system_type', sa.String(length=20), nullable=False),
    sa.Column('connector', sa.String(length=20), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('mapping', sa.JSON(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('owner', sa.String(length=120), nullable=True),
    sa.Column('schedule_minutes', sa.Integer(), nullable=True),
    sa.Column('watermark', sa.String(length=64), nullable=True),
    sa.Column('ingest_token_hash', sa.String(length=128), nullable=True),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('data_sources', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_data_sources_code'), ['code'], unique=True)

    op.create_table('fiscal_years',
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=12), nullable=False),
    sa.Column('start_date', sa.String(length=10), nullable=False),
    sa.Column('end_date', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('tariff_per_m3', sa.Float(), nullable=True),
    sa.Column('notes', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('year')
    )
    op.create_table('metric_targets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('metric_code', sa.String(length=80), nullable=False),
    sa.Column('org_unit_code', sa.String(length=80), nullable=False),
    sa.Column('period_type', sa.String(length=10), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('lower', sa.Float(), nullable=True),
    sa.Column('upper', sa.Float(), nullable=True),
    sa.Column('basis', sa.String(length=40), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('metric_code', 'org_unit_code', 'period_type', 'period_start', 'basis', name='uq_metric_target')
    )
    with op.batch_alter_table('metric_targets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_metric_targets_metric_code'), ['metric_code'], unique=False)

    op.create_table('metrics',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('unit', sa.String(length=40), nullable=True),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('aggregation', sa.String(length=10), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('formula', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('metrics', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_metrics_code'), ['code'], unique=True)

    op.create_table('org_profile',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_name', sa.String(length=120), nullable=True),
    sa.Column('short_name', sa.String(length=20), nullable=True),
    sa.Column('registration_no', sa.String(length=60), nullable=True),
    sa.Column('regulator', sa.String(length=120), nullable=True),
    sa.Column('country', sa.String(length=60), nullable=True),
    sa.Column('reporting_currency', sa.String(length=10), nullable=True),
    sa.Column('service_area_km2', sa.Float(), nullable=True),
    sa.Column('population_served', sa.Integer(), nullable=True),
    sa.Column('contact_email', sa.String(length=120), nullable=True),
    sa.Column('contact_phone', sa.String(length=40), nullable=True),
    sa.Column('website', sa.String(length=200), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('org_units',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('unit_type', sa.String(length=40), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['org_units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('org_units', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_org_units_code'), ['code'], unique=True)
        batch_op.create_index(batch_op.f('ix_org_units_parent_id'), ['parent_id'], unique=False)

    op.create_table('records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('zone', sa.String(length=60), nullable=False),
    sa.Column('scheme', sa.String(length=80), nullable=False),
    sa.Column('fiscal_year', sa.String(length=12), nullable=True),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('month_no', sa.Integer(), nullable=False),
    sa.Column('month', sa.String(length=20), nullable=False),
    sa.Column('quarter', sa.String(length=4), nullable=False),
    sa.Column('vol_produced', sa.Float(), nullable=True),
    sa.Column('vol_billed_indiv_pp', sa.Float(), nullable=True),
    sa.Column('vol_billed_cwp_pp', sa.Float(), nullable=True),
    sa.Column('vol_billed_inst_pp', sa.Float(), nullable=True),
    sa.Column('vol_billed_comm_pp', sa.Float(), nullable=True),
    sa.Column('total_vol_billed_pp', sa.Float(), nullable=True),
    sa.Column('vol_billed_indiv_prepaid', sa.Float(), nullable=True),
    sa.Column('vol_billed_cwp_prepaid', sa.Float(), nullable=True),
    sa.Column('vol_billed_inst_prepaid', sa.Float(), nullable=True),
    sa.Column('vol_billed_comm_prepaid', sa.Float(), nullable=True),
    sa.Column('total_vol_billed_prepaid', sa.Float(), nullable=True),
    sa.Column('revenue_water', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('nrw', sa.Float(), nullable=True),
    sa.Column('pct_nrw', sa.Float(), nullable=True),
    sa.Column('chlorine_kg', sa.Float(), nullable=True),
    sa.Column('alum_kg', sa.Float(), nullable=True),
    sa.Column('soda_ash_kg', sa.Float(), nullable=True),
    sa.Column('algae_floc_litres', sa.Float(), nullable=True),
    sa.Column('sud_floc_litres', sa.Float(), nullable=True),
    sa.Column('kmno4_kg', sa.Float(), nullable=True),
    sa.Column('chem_cost', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('chem_cost_per_m3', sa.Float(), nullable=True),
    sa.Column('chlorine_kg_per_m3', sa.Float(), nullable=True),
    sa.Column('alum_kg_per_m3', sa.Float(), nullable=True),
    sa.Column('soda_ash_kg_per_m3', sa.Float(), nullable=True),
    sa.Column('algae_floc_per_m3', sa.Float(), nullable=True),
    sa.Column('sud_floc_per_m3', sa.Float(), nullable=True),
    sa.Column('kmno4_per_m3', sa.Float(), nullable=True),
    sa.Column('wq_samples_taken', sa.Integer(), nullable=True),
    sa.Column('wq_cl_samples', sa.Integer(), nullable=True),
    sa.Column('wq_cl_compliant', sa.Integer(), nullable=True),
    sa.Column('wq_residual_cl_mg_l', sa.Float(), nullable=True),
    sa.Column('wq_turbidity_samples', sa.Integer(), nullable=True),
    sa.Column('wq_turbidity_compliant', sa.Integer(), nullable=True),
    sa.Column('wq_turbidity_ntu', sa.Float(), nullable=True),
    sa.Column('wq_bact_samples', sa.Integer(), nullable=True),
    sa.Column('wq_bact_compliant', sa.Integer(), nullable=True),
    sa.Column('wq_ph_samples', sa.Integer(), nullable=True),
    sa.Column('wq_ph_compliant', sa.Integer(), nullable=True),
    sa.Column('power_kwh', sa.Float(), nullable=True),
    sa.Column('power_cost', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('power_cost_per_m3', sa.Float(), nullable=True),
    sa.Column('power_kwh_per_m3', sa.Float(), nullable=True),
    sa.Column('distances_km', sa.Float(), nullable=True),
    sa.Column('fuel_used_litres', sa.Float(), nullable=True),
    sa.Column('fuel_cost', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('maintenance', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('staff_costs', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('wages', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('other_overhead', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('op_cost', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('op_cost_per_m3_produced', sa.Float(), nullable=True),
    sa.Column('op_cost_per_m3_billed', sa.Float(), nullable=True),
    sa.Column('perm_staff', sa.Float(), nullable=True),
    sa.Column('temp_staff', sa.Float(), nullable=True),
    sa.Column('staff_per_1000m3_12h', sa.Float(), nullable=True),
    sa.Column('all_conn_bfwd', sa.Float(), nullable=True),
    sa.Column('all_conn_applied', sa.Float(), nullable=True),
    sa.Column('new_connections', sa.Float(), nullable=True),
    sa.Column('all_conn_cfwd', sa.Float(), nullable=True),
    sa.Column('prepaid_meters_installed', sa.Float(), nullable=True),
    sa.Column('conn_indiv_bfwd', sa.Float(), nullable=True),
    sa.Column('conn_indiv_applied_pp', sa.Float(), nullable=True),
    sa.Column('conn_indiv_done_pp', sa.Float(), nullable=True),
    sa.Column('conn_indiv_done_prepaid', sa.Float(), nullable=True),
    sa.Column('conn_indiv_total_done', sa.Float(), nullable=True),
    sa.Column('conn_indiv_cfwd', sa.Float(), nullable=True),
    sa.Column('conn_inst_bfwd', sa.Float(), nullable=True),
    sa.Column('conn_inst_applied_pp', sa.Float(), nullable=True),
    sa.Column('conn_inst_done_pp', sa.Float(), nullable=True),
    sa.Column('conn_inst_done_prepaid', sa.Float(), nullable=True),
    sa.Column('conn_inst_total_done', sa.Float(), nullable=True),
    sa.Column('conn_inst_cfwd', sa.Float(), nullable=True),
    sa.Column('conn_comm_bfwd', sa.Float(), nullable=True),
    sa.Column('conn_comm_applied_pp', sa.Float(), nullable=True),
    sa.Column('conn_comm_done_pp', sa.Float(), nullable=True),
    sa.Column('conn_comm_done_prepaid', sa.Float(), nullable=True),
    sa.Column('conn_comm_total_done', sa.Float(), nullable=True),
    sa.Column('conn_comm_cfwd', sa.Float(), nullable=True),
    sa.Column('conn_cwp_bfwd', sa.Float(), nullable=True),
    sa.Column('conn_cwp_applied_pp', sa.Float(), nullable=True),
    sa.Column('conn_cwp_done_pp', sa.Float(), nullable=True),
    sa.Column('conn_cwp_done_prepaid', sa.Float(), nullable=True),
    sa.Column('conn_cwp_total_done', sa.Float(), nullable=True),
    sa.Column('conn_cwp_cfwd', sa.Float(), nullable=True),
    sa.Column('disconnected_individual', sa.Float(), nullable=True),
    sa.Column('disconnected_inst', sa.Float(), nullable=True),
    sa.Column('disconnected_commercial', sa.Float(), nullable=True),
    sa.Column('disconnected_cwp', sa.Float(), nullable=True),
    sa.Column('total_disconnected', sa.Float(), nullable=True),
    sa.Column('active_post_individual', sa.Float(), nullable=True),
    sa.Column('active_post_inst', sa.Float(), nullable=True),
    sa.Column('active_post_commercial', sa.Float(), nullable=True),
    sa.Column('active_post_cwp', sa.Float(), nullable=True),
    sa.Column('active_postpaid', sa.Float(), nullable=True),
    sa.Column('active_prep_individual', sa.Float(), nullable=True),
    sa.Column('active_prep_inst', sa.Float(), nullable=True),
    sa.Column('active_prep_commercial', sa.Float(), nullable=True),
    sa.Column('active_prep_cwp', sa.Float(), nullable=True),
    sa.Column('active_prepaid', sa.Float(), nullable=True),
    sa.Column('active_customers', sa.Float(), nullable=True),
    sa.Column('total_metered', sa.Float(), nullable=True),
    sa.Column('pop_supply_area', sa.Float(), nullable=True),
    sa.Column('pop_supplied', sa.Float(), nullable=True),
    sa.Column('pct_pop_supplied', sa.Float(), nullable=True),
    sa.Column('stuck_meters', sa.Float(), nullable=True),
    sa.Column('stuck_new', sa.Float(), nullable=True),
    sa.Column('stuck_repaired', sa.Float(), nullable=True),
    sa.Column('stuck_replaced', sa.Float(), nullable=True),
    sa.Column('all_stuck_cfwd', sa.Float(), nullable=True),
    sa.Column('stuck_indiv_bfwd', sa.Float(), nullable=True),
    sa.Column('stuck_indiv_new', sa.Float(), nullable=True),
    sa.Column('stuck_indiv_repaired', sa.Float(), nullable=True),
    sa.Column('stuck_indiv_replaced', sa.Float(), nullable=True),
    sa.Column('stuck_indiv_cfwd', sa.Float(), nullable=True),
    sa.Column('stuck_inst_bfwd', sa.Float(), nullable=True),
    sa.Column('stuck_inst_new', sa.Float(), nullable=True),
    sa.Column('stuck_inst_repaired', sa.Float(), nullable=True),
    sa.Column('stuck_inst_replaced', sa.Float(), nullable=True),
    sa.Column('stuck_inst_cfwd', sa.Float(), nullable=True),
    sa.Column('stuck_comm_bfwd', sa.Float(), nullable=True),
    sa.Column('stuck_comm_new', sa.Float(), nullable=True),
    sa.Column('stuck_comm_repaired', sa.Float(), nullable=True),
    sa.Column('stuck_comm_replaced', sa.Float(), nullable=True),
    sa.Column('stuck_comm_cfwd', sa.Float(), nullable=True),
    sa.Column('stuck_cwp_bfwd', sa.Float(), nullable=True),
    sa.Column('stuck_cwp_new', sa.Float(), nullable=True),
    sa.Column('stuck_cwp_repaired', sa.Float(), nullable=True),
    sa.Column('stuck_cwp_replaced', sa.Float(), nullable=True),
    sa.Column('stuck_cwp_cfwd', sa.Float(), nullable=True),
    sa.Column('pipe_pvc', sa.Float(), nullable=True),
    sa.Column('pipe_gi', sa.Float(), nullable=True),
    sa.Column('pipe_di', sa.Float(), nullable=True),
    sa.Column('pipe_hdpe_ac', sa.Float(), nullable=True),
    sa.Column('pipe_breakdowns', sa.Float(), nullable=True),
    sa.Column('pvc_20mm', sa.Float(), nullable=True),
    sa.Column('pvc_25mm', sa.Float(), nullable=True),
    sa.Column('pvc_32mm', sa.Float(), nullable=True),
    sa.Column('pvc_40mm', sa.Float(), nullable=True),
    sa.Column('pvc_50mm', sa.Float(), nullable=True),
    sa.Column('pvc_63mm', sa.Float(), nullable=True),
    sa.Column('pvc_75mm', sa.Float(), nullable=True),
    sa.Column('pvc_90mm', sa.Float(), nullable=True),
    sa.Column('pvc_110mm', sa.Float(), nullable=True),
    sa.Column('pvc_160mm', sa.Float(), nullable=True),
    sa.Column('pvc_200mm', sa.Float(), nullable=True),
    sa.Column('pvc_250mm', sa.Float(), nullable=True),
    sa.Column('pvc_315mm', sa.Float(), nullable=True),
    sa.Column('gi_15mm', sa.Float(), nullable=True),
    sa.Column('gi_20mm', sa.Float(), nullable=True),
    sa.Column('gi_25mm', sa.Float(), nullable=True),
    sa.Column('gi_40mm', sa.Float(), nullable=True),
    sa.Column('gi_50mm', sa.Float(), nullable=True),
    sa.Column('gi_75mm', sa.Float(), nullable=True),
    sa.Column('gi_100mm', sa.Float(), nullable=True),
    sa.Column('gi_150mm', sa.Float(), nullable=True),
    sa.Column('gi_200mm', sa.Float(), nullable=True),
    sa.Column('di_150mm', sa.Float(), nullable=True),
    sa.Column('di_200mm', sa.Float(), nullable=True),
    sa.Column('di_250mm', sa.Float(), nullable=True),
    sa.Column('di_300mm', sa.Float(), nullable=True),
    sa.Column('di_350mm', sa.Float(), nullable=True),
    sa.Column('di_525mm', sa.Float(), nullable=True),
    sa.Column('hdpe_20mm', sa.Float(), nullable=True),
    sa.Column('hdpe_25mm', sa.Float(), nullable=True),
    sa.Column('hdpe_32mm', sa.Float(), nullable=True),
    sa.Column('hdpe_50mm', sa.Float(), nullable=True),
    sa.Column('ac_50mm', sa.Float(), nullable=True),
    sa.Column('ac_75mm', sa.Float(), nullable=True),
    sa.Column('ac_100mm', sa.Float(), nullable=True),
    sa.Column('ac_150mm', sa.Float(), nullable=True),
    sa.Column('pump_breakdowns', sa.Float(), nullable=True),
    sa.Column('pump_hours_lost', sa.Float(), nullable=True),
    sa.Column('supply_hours', sa.Float(), nullable=True),
    sa.Column('power_fail_hours', sa.Float(), nullable=True),
    sa.Column('dev_lines_32mm', sa.Float(), nullable=True),
    sa.Column('dev_lines_50mm', sa.Float(), nullable=True),
    sa.Column('dev_lines_63mm', sa.Float(), nullable=True),
    sa.Column('dev_lines_90mm', sa.Float(), nullable=True),
    sa.Column('dev_lines_110mm', sa.Float(), nullable=True),
    sa.Column('dev_lines_total', sa.Float(), nullable=True),
    sa.Column('cash_coll_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_collected', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_indiv_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_cwp_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_comm_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_inst_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_indiv_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_cwp_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_comm_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('cash_coll_inst_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_indiv_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_cwp_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_inst_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_comm_pp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_indiv_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_cwp_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_inst_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('amt_billed_comm_prepaid', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('service_charge', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('meter_rental', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('total_sales', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('service_charge_individual', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('service_charge_cwp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('service_charge_institutions', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('service_charge_commercial', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('meter_rental_individual', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('meter_rental_cwp', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('meter_rental_institutions', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('meter_rental_commercial', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('private_debtors', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('public_debtors', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('total_debtors', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=True),
    sa.Column('op_cost_per_sales', sa.Float(), nullable=True),
    sa.Column('collection_rate', sa.Float(), nullable=True),
    sa.Column('collection_per_sales', sa.Float(), nullable=True),
    sa.Column('conn_applied', sa.Float(), nullable=True),
    sa.Column('days_to_quotation', sa.Float(), nullable=True),
    sa.Column('conn_fully_paid', sa.Float(), nullable=True),
    sa.Column('paid_up_applicants', sa.Float(), nullable=True),
    sa.Column('days_to_connect', sa.Float(), nullable=True),
    sa.Column('connection_days', sa.Float(), nullable=True),
    sa.Column('connectivity_rate', sa.Float(), nullable=True),
    sa.Column('queries_received', sa.Float(), nullable=True),
    sa.Column('time_to_resolve', sa.Float(), nullable=True),
    sa.Column('response_time_avg', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('zone', 'scheme', 'year', 'month_no', name='uq_zone_scheme_year_monthno')
    )
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.create_index('ix_record_year_month', ['year', 'month_no'], unique=False)
        batch_op.create_index(batch_op.f('ix_records_month'), ['month'], unique=False)
        batch_op.create_index(batch_op.f('ix_records_scheme'), ['scheme'], unique=False)
        batch_op.create_index(batch_op.f('ix_records_zone'), ['zone'], unique=False)
        batch_op.create_index('ix_zone_scheme_year_monthno', ['zone', 'scheme', 'year', 'month_no'], unique=False)

    op.create_table('upload_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('uploaded_by', sa.String(length=60), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=True),
    sa.Column('period', sa.String(length=30), nullable=True),
    sa.Column('rows_inserted', sa.Integer(), nullable=True),
    sa.Column('rows_updated', sa.Integer(), nullable=True),
    sa.Column('rows_skipped', sa.Integer(), nullable=True),
    sa.Column('rows_errored', sa.Integer(), nullable=True),
    sa.Column('logged_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('upload_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_upload_log_logged_at'), ['logged_at'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=60), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=True),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=60), nullable=True),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('budget_lines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('value', sa.Numeric(precision=15, scale=2, asdecimal=False), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['year'], ['fiscal_years.year'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('year', 'category', name='uq_budget_year_category')
    )
    with op.batch_alter_table('budget_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_budget_lines_year'), ['year'], unique=False)

    op.create_table('budget_zone_shares',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('zone', sa.String(length=60), nullable=False),
    sa.Column('rev_share', sa.Float(), nullable=False),
    sa.Column('vol_share', sa.Float(), nullable=False),
    sa.Column('conn_share', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['year'], ['fiscal_years.year'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('year', 'zone', name='uq_zone_share_year_zone')
    )
    with op.batch_alter_table('budget_zone_shares', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_budget_zone_shares_year'), ['year'], unique=False)

    op.create_table('key_mappings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('external_key', sa.String(length=200), nullable=False),
    sa.Column('internal_code', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'kind', 'external_key', name='uq_key_mapping')
    )
    with op.batch_alter_table('key_mappings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_key_mappings_source_id'), ['source_id'], unique=False)

    op.create_table('spc_limits',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=40), nullable=False),
    sa.Column('mean', sa.Float(), nullable=True),
    sa.Column('std', sa.Float(), nullable=True),
    sa.Column('ucl2', sa.Float(), nullable=True),
    sa.Column('lcl2', sa.Float(), nullable=True),
    sa.Column('ucl3', sa.Float(), nullable=True),
    sa.Column('lcl3', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['year'], ['fiscal_years.year'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('year', 'metric', name='uq_spc_year_metric')
    )
    with op.batch_alter_table('spc_limits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_spc_limits_year'), ['year'], unique=False)

    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('triggered_by', sa.String(length=60), nullable=True),
    sa.Column('rows_read', sa.Integer(), nullable=False),
    sa.Column('values_loaded', sa.Integer(), nullable=False),
    sa.Column('rows_rejected', sa.Integer(), nullable=False),
    sa.Column('watermark_before', sa.String(length=64), nullable=True),
    sa.Column('watermark_after', sa.String(length=64), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('rejects', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sync_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sync_runs_source_id'), ['source_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sync_runs_started_at'), ['started_at'], unique=False)

    op.create_table('metric_values',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('metric_code', sa.String(length=80), nullable=False),
    sa.Column('org_unit_code', sa.String(length=80), nullable=False),
    sa.Column('period_type', sa.String(length=10), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('source_ref', sa.String(length=300), nullable=True),
    sa.Column('loaded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['sync_runs.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('metric_code', 'org_unit_code', 'period_type', 'period_start', 'source_id', name='uq_metric_value')
    )
    with op.batch_alter_table('metric_values', schema=None) as batch_op:
        batch_op.create_index('ix_metric_values_lookup', ['metric_code', 'org_unit_code', 'period_type', 'period_start'], unique=False)



def downgrade() -> None:
    # Downgrading the baseline would drop every table and all utility data.
    raise RuntimeError("Refusing to downgrade below the baseline; restore a backup instead.")
