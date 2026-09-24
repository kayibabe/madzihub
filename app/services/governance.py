from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Record


@dataclass
class KPIRegistryItem:
    key: str
    title: str
    formula: str
    unit: str
    owner: str
    benchmark_type: str
    benchmark_value: str | None
    chart_guidance: str
    required_fields: list[str]
    currently_supported: bool
    notes: str


KPI_REGISTRY: list[KPIRegistryItem] = [
    KPIRegistryItem(
        key="pct_nrw",
        title="Non-Revenue Water",
        formula="NRW % = (non-revenue water ÷ volume produced) × 100",
        unit="%",
        owner="Operations / Commercial",
        benchmark_type="Target line allowed",
        benchmark_value="SRWB target 27%; international good practice 20%",
        chart_guidance="Use target lines on time-series and zone-comparison charts.",
        required_fields=["vol_produced", "nrw", "pct_nrw"],
        currently_supported=True,
        notes="Core operational loss metric already represented in the current data model.",
    ),
    KPIRegistryItem(
        key="collection_rate",
        title="Collection Rate",
        formula="Collection rate = cash collected ÷ amount billed × 100",
        unit="%",
        owner="Finance / Commercial",
        benchmark_type="Target line allowed",
        benchmark_value="95% benchmark",
        chart_guidance="Use benchmark context or target line where the chart is explicitly about collection efficiency.",
        required_fields=["cash_collected", "amt_billed", "collection_rate"],
        currently_supported=True,
        notes="Financial sustainability metric suitable for KPI cards and trend charts.",
    ),
    KPIRegistryItem(
        key="supply_hours",
        title="Continuity of Supply",
        formula="Continuity = average normal supply hours per day / period",
        unit="hours",
        owner="Operations",
        benchmark_type="Context note preferred",
        benchmark_value="Local operating standard to be confirmed",
        chart_guidance="Avoid a universal target line unless a board-approved service standard exists.",
        required_fields=["supply_hours", "power_fail_hours"],
        currently_supported=True,
        notes="Useful for compliance context, but benchmark should be policy-led, not implied.",
    ),
    KPIRegistryItem(
        key="chlorine_dose_proxy",
        title="Treatment Chemical Dosing Proxy",
        formula="Proxy only: chlorine kg and chemical cost reviewed alongside production",
        unit="proxy",
        owner="Water Quality",
        benchmark_type="Context note only",
        benchmark_value=None,
        chart_guidance="Do not draw compliance lines; current data does not contain sample-result compliance values.",
        required_fields=["chlorine_kg", "chem_cost", "vol_produced"],
        currently_supported=True,
        notes="Operational proxy, not a regulatory compliance result.",
    ),
    KPIRegistryItem(
        key="residual_chlorine_compliance",
        title="Residual Chlorine Compliance",
        formula="Compliant samples ÷ total samples × 100",
        unit="%",
        owner="Water Quality Laboratory",
        benchmark_type="Target line allowed once data exists",
        benchmark_value="Board / regulator standard",
        chart_guidance="Use formal compliance line only when sample-result dataset exists.",
        required_fields=["residual_chlorine_min", "residual_chlorine_max", "samples_total", "samples_compliant"],
        currently_supported=False,
        notes="Not yet represented in the current RawData schema.",
    ),
    KPIRegistryItem(
        key="turbidity_compliance",
        title="Turbidity Compliance",
        formula="Compliant turbidity samples ÷ total turbidity samples × 100",
        unit="%",
        owner="Water Quality Laboratory",
        benchmark_type="Target line allowed once data exists",
        benchmark_value="Permit / drinking-water standard",
        chart_guidance="Use formal compliance line only when laboratory result data exists.",
        required_fields=["turbidity_ntu", "samples_total", "samples_compliant"],
        currently_supported=False,
        notes="Not yet represented in the current RawData schema.",
    ),
    KPIRegistryItem(
        key="bacteriological_compliance",
        title="Bacteriological Compliance",
        formula="Bacteriologically compliant samples ÷ total microbiological samples × 100",
        unit="%",
        owner="Water Quality Laboratory",
        benchmark_type="Target line allowed once data exists",
        benchmark_value="Permit / public-health standard",
        chart_guidance="Only use explicit compliance thresholds with actual microbiological sample results.",
        required_fields=["ecoli_present", "total_coliform_present", "samples_total", "samples_compliant"],
        currently_supported=False,
        notes="Critical compliance metric still missing from the operational upload schema.",
    ),
]


KPI_UI_ALIASES: dict[str, list[str]] = {
    "pct_nrw": ["NRW Rate", "NRW %", "Corporate NRW %", "Non-Revenue Water", "NRW"],
    "collection_rate": ["Collection Rate", "Collection Efficiency", "Collections"],
    "supply_hours": ["Supply Hours", "Continuity of Supply", "Supply Continuity"],
    "chlorine_dose_proxy": ["Chlorine Dose Proxy", "Treatment Chemical Dosing Proxy", "Operational Proxy Data"],
    "residual_chlorine_compliance": ["Residual Chlorine Compliance"],
    "turbidity_compliance": ["Turbidity Compliance"],
    "bacteriological_compliance": ["Bacteriological Compliance"],
}

EXPORT_GOVERNANCE_PAGES: list[str] = [
    "overview",
    "production",
    "wt-ei",
    "customers",
    "connections",
    "stuck",
    "connectivity",
    "breakdowns",
    "pipelines",
    "billed",
    "collections",
    "charges",
    "expenses",
    "debtors",
    "budget",
    "compliance",
]


PAGE_TITLE_REGISTRY: dict[str, str] = {
    "overview": "Executive Dashboard",
    "production": "Production & Non-Revenue Water",
    "wt-ei": "Water Treatment & Energy",
    "customers": "Customer Accounts",
    "connections": "New Water Connections",
    "stuck": "Stuck Meters",
    "connectivity": "Service Connectivity",
    "breakdowns": "Infrastructure Breakdowns",
    "pipelines": "Pipeline Extensions",
    "billed": "Billed Amounts",
    "collections": "Billing & Collections",
    "charges": "Service Charges & Meter Rental",
    "expenses": "Operating Expenses",
    "debtors": "Outstanding Debtors",
    "budget": "Budget Health & Performance",
    "compliance": "Water Quality & Regulatory Compliance",
}


@dataclass
class EvidenceLadderItem:
    key: str
    title: str
    description: str
    allowed_visual_treatment: str
    governance_position: str


EVIDENCE_LADDER: list[EvidenceLadderItem] = [
    EvidenceLadderItem(
        key="statutory",
        title="Statutory / Permit Evidence",
        description="Use only when governed laboratory or regulatory-result data exists, has been validated, and directly supports the compliance claim being shown.",
        allowed_visual_treatment="Literal compliance line or pass/fail treatment may be shown.",
        governance_position="Highest evidential weight. Never implied by proxy indicators.",
    ),
    EvidenceLadderItem(
        key="approved_kpi",
        title="Board-Approved KPI Comparator",
        description="Use where the utility has a clearly approved internal target or widely accepted sector comparator for the KPI being charted.",
        allowed_visual_treatment="Literal target line allowed on purpose-built KPI charts.",
        governance_position="Strong managerial evidence, but not a substitute for statutory compliance evidence.",
    ),
    EvidenceLadderItem(
        key="control_band",
        title="Threshold / Control Envelope",
        description="Use when interpretation depends on operating limits, warning limits, or control-chart logic rather than a single target line.",
        allowed_visual_treatment="Threshold band, control limit, or warning/action line treatment.",
        governance_position="Analytically legitimate where process-control logic exists.",
    ),
    EvidenceLadderItem(
        key="context",
        title="Operational Context / Proxy",
        description="Use when the data is operationally useful but does not justify a literal statutory or board-level compliance comparator.",
        allowed_visual_treatment="Interpretation note or contextual commentary only.",
        governance_position="Descriptive evidence only. Avoid overstating benchmark legitimacy.",
    ),
    EvidenceLadderItem(
        key="missing",
        title="Source Data Not Yet Onboarded",
        description="Use where the intended KPI or compliance claim needs fields that are not yet present in the governed upload schema.",
        allowed_visual_treatment="No benchmark line. Show evidence caveat or data-gap note instead.",
        governance_position="Do not infer compliance or target attainment.",
    ),
]


@dataclass
class ChartGovernanceItem:
    page_key: str
    title: str
    benchmark_mode: str
    benchmark_label: str
    note: str
    rationale: str
    legend_style: str
    print_priority: str


@dataclass
class PageVisualStandard:
    page_key: str
    title: str
    benchmark_rule: str
    legend_rule: str
    note_rule: str
    print_rule: str


PAGE_VISUAL_STANDARDS: list[PageVisualStandard] = [
    PageVisualStandard(
        page_key="overview",
        title="Executive Dashboard",
        benchmark_rule="Use literal target lines only on charts with a board-approved KPI benchmark such as NRW or collection efficiency.",
        legend_rule="Keep legends compact and executive. Prefer pill legends or top legends with short labels.",
        note_rule="Every chart must carry a concise interpretation note when a literal target line is not analytically legitimate.",
        print_rule="Prioritise the KPI row and first trend row together in board-pack output.",
    ),
    PageVisualStandard(
        page_key="production",
        title="Production & Non-Revenue Water",
        benchmark_rule="NRW charts may use target lines. Volume charts should use contextual notes unless paired with an explicitly benchmarked efficiency indicator.",
        legend_rule="Use compact legends with NRW benchmark labels kept visible and consistent across trend and zone views.",
        note_rule="Explain whether the chart is showing a literal benchmark or descriptive operating context.",
        print_rule="Keep the main water-balance chart and the primary zone comparison on the first board-pack spread.",
    ),
    PageVisualStandard(
        page_key="wt-ei",
        title="Water Treatment & Energy",
        benchmark_rule="Do not force target lines on raw cost charts. Use threshold bands only where the indicator has an accepted operating limit or control envelope.",
        legend_rule="Legends should separate treatment-input series from operating-cost series and stay visually quiet.",
        note_rule="Use operational context notes for chemical and power cost charts unless a formal standard exists.",
        print_rule="Show treatment and energy trend cards before detailed cost tables in print output.",
    ),
    PageVisualStandard(
        page_key="connectivity",
        title="Service Connectivity",
        benchmark_rule="Turnaround-time charts may use explicit benchmark lines where the service standard is clear; volume charts remain contextual.",
        legend_rule="Use compact legends with the service-standard series labelled as the benchmark.",
        note_rule="Notes should clarify whether the chart is measuring turnaround compliance or simple delivery volume.",
        print_rule="Keep turnaround KPIs and the main service-standard chart together in print.",
    ),
    PageVisualStandard(
        page_key="collections",
        title="Billing & Collections",
        benchmark_rule="Collection-efficiency charts may use target lines. Revenue-volume charts should use benchmark context rather than synthetic lines.",
        legend_rule="Legend wording should distinguish billed, collected, and benchmark series clearly.",
        note_rule="Interpretation notes should explain cash-conversion context where billing and collections are shown together.",
        print_rule="Preserve collection-rate visuals and the receivables table on the same board-pack section where possible.",
    ),
    PageVisualStandard(
        page_key="budget",
        title="Budget Health & Performance",
        benchmark_rule="Budget charts may use target or plan lines where the comparator is the approved budget. Analytical decomposition charts should use interpretation notes instead.",
        legend_rule="Legends should distinguish actual, budget, and forecast cleanly and avoid decorative series names.",
        note_rule="Any variance or waterfall chart should carry an explanatory note rather than a false benchmark line.",
        print_rule="Budget summary, drivers, and variance charts should export with executive notes visible.",
    ),
    PageVisualStandard(
        page_key="compliance",
        title="Water Quality & Regulatory Compliance",
        benchmark_rule="Do not assert statutory target lines until laboratory-result fields are onboarded and governed. Use evidence-status notes and proxy labels instead.",
        legend_rule="Legends must distinguish statutory evidence from operational proxies, with no implied compliance line where evidence is missing.",
        note_rule="Narrative notes must explain why a chart uses a context note, threshold band, or no literal benchmark at all.",
        print_rule="Compliance pages should print with evidence caveats fully visible and never collapse them into visual shorthand.",
    ),
]


CHART_GOVERNANCE_REGISTRY: list[ChartGovernanceItem] = [
    ChartGovernanceItem(
        page_key="overview",
        title="NRW Rate — Monthly Trend",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: SRWB target 27%; IWA good-practice benchmark 20%. Dashed benchmark lines should remain visible in trend interpretation.",
        rationale="The chart measures an explicitly benchmarked efficiency KPI with a literal corporate target and sector comparison point.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="overview",
        title="NRW Rate by Zone — Current Period (%)",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: compare every zone against the 27% corporate NRW target and the 20% good-practice benchmark.",
        rationale="Zone comparison is valid because each bar is the same KPI measured against the same benchmark rule.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="production",
        title="Volume Produced (m³) & NRW Rate — Monthly",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: track NRW against the 27% SRWB target and 20% IWA benchmark while reading production in parallel.",
        rationale="The chart contains a benchmarkable NRW series alongside production; only the NRW component legitimately receives a target line.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="production",
        title="NRW Rate by Zone (%)",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: compare each zone against the 27% target and 20% international good-practice benchmark.",
        rationale="Like-for-like zone benchmarking is analytically legitimate for NRW percentage comparisons.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="collections",
        title="Billing vs Collections — Monthly (MWK)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: chart supports collection-efficiency review; read together with the IBNET collection-rate benchmark of 95% shown in KPI cards.",
        rationale="Billing and collections volumes are descriptive series, so the benchmark belongs in interpretation rather than as a literal line on the chart.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="collections",
        title="Collection Rate by Zone (%)",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: benchmark line set at 95% collection efficiency in line with common IBNET-style performance review.",
        rationale="Collection rate is a standard efficiency KPI that supports a literal benchmark line by zone.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="collections",
        title="Billed vs Collected — Monthly (MWK)",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: billed and collected values are paired with the monthly collection-rate line and the IBNET 95% benchmark, so cash conversion can be read directly against the approved efficiency threshold.",
        rationale="Because the chart now includes the KPI efficiency line, the benchmark is a legitimate comparator on the same visual rather than a decorative reference.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="connectivity",
        title="Days to Quotation & Days to Connect",
        benchmark_mode="band",
        benchmark_label="Threshold band",
        note="Benchmark context: quotation turnaround should trend toward 7 days and connection completion toward 30 days or better.",
        rationale="Turnaround-time charts are better read against service-standard thresholds than against a single decorative target line.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="wt-ei",
        title="Supply Hours vs Power Failure Hours",
        benchmark_mode="band",
        benchmark_label="Threshold band",
        note="Benchmark context: continuity charts are strongest when supply hours trend upward and outage hours approach zero.",
        rationale="Continuity and outage indicators should use threshold interpretation rather than implying one universal line for all schemes and periods.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Monthly Revenue: Actual vs Budget (MWK)",
        benchmark_mode="line",
        benchmark_label="Budget line",
        note="Benchmark context: review actual water sales against the prorated annual budget and read collections as cash-conversion support rather than budget basis.",
        rationale="The approved budget is the legitimate comparator, so a literal plan line is appropriate.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Volume Produced: Actual vs Budget (m³)",
        benchmark_mode="line",
        benchmark_label="Budget line",
        note="Benchmark context: production should track or exceed prorated budget where service demand and capacity assumptions hold.",
        rationale="Budget-versus-actual production is a valid plan-comparison chart with an explicit comparator.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="New Connections — Cumulative YTD vs Budget",
        benchmark_mode="line",
        benchmark_label="Budget line",
        note="Benchmark context: the cumulative line should stay close to or above the prorated target to protect future revenue growth.",
        rationale="A cumulative delivery curve against budget is a legitimate plan-performance comparison.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Revenue Decomposition — Volume Effect Waterfall (MWK)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Interpretation note: with tariff held constant, the waterfall isolates how much of the revenue gap is attributable to water-volume underperformance and cash conversion effects.",
        rationale="Waterfall decomposition explains drivers and should not receive a synthetic target line.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Budget Performance Index — Revenue by Zone",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: a BPI above 1.0 means the zone is ahead of its proportional revenue budget; below 1.0 signals under-delivery.",
        rationale="The benchmark is the interpretation of the index itself, not an additional graphic threshold line.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Corporate NRW % — Shewhart Control Chart (ISO 7870-2)",
        benchmark_mode="band",
        benchmark_label="Control limits",
        note="Control note: points outside warning and action limits indicate special-cause variation requiring management attention beyond routine target monitoring.",
        rationale="Control charts require warning and action bands rather than simple target lines.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="NRW % by Zone vs 27% Target",
        benchmark_mode="line",
        benchmark_label="Target line",
        note="Benchmark context: 27% is the internal management target; the most material operational priority is the largest-producing zone with persistent excess NRW.",
        rationale="This is a direct target-comparison chart using a single corporate threshold.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="NRW % Monthly Trend by Zone",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: sustained movement toward or below 27% matters more than isolated monthly swings.",
        rationale="Multi-zone trend spaghetti plots are more credible with interpretation notes than with stacked reference lines.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Revenue Water vs NRW Volume — Monthly (m³)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Interpretation note: growth in NRW volume without matching revenue-water growth indicates treatment effort that is not translating into billable output.",
        rationale="The chart explains operational relationship rather than compliance against a single numeric benchmark.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="wt-ei",
        title="Chemical Costs — Actual vs Budget (MWK/month)",
        benchmark_mode="line",
        benchmark_label="Budget line",
        note="Benchmark context: recurring monthly overruns indicate a structural cost issue, not just a timing issue, especially late in the financial year.",
        rationale="This chart has a legitimate approved-budget comparator.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="wt-ei",
        title="Power / Electricity — Actual vs Budget (MWK/month)",
        benchmark_mode="line",
        benchmark_label="Budget line",
        note="Benchmark context: read this as field electricity only; under-budget results do not capture uncoded head-office or zonal electricity spend.",
        rationale="Approved-budget comparison is legitimate, but the note must explain scope limitations.",
        legend_style="compact-top",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="wt-ei",
        title="Chemical & Power Cost per m³ by Zone (MWK)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: highest-cost zones warrant joint review of treatment efficiency, pump efficiency, and NRW performance.",
        rationale="Unit-cost ranking is comparative analysis, not a universal compliance-threshold chart.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Zone Performance Radar — 5 Dimensions (normalised 0–100)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Interpretation note: use the radar as a synthesis view only; confirm any weak axis against the detailed tables below before actioning.",
        rationale="Composite radar charts are synthesis visuals and should not imply literal threshold compliance.",
        legend_style="compact-top",
        print_priority="low",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Revenue Variance by Zone (MWK)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: compare actual sales with proportional budget by zone and use variance/BPI details to isolate the weakest commercial segment.",
        rationale="Variance charts are diagnostic by nature and are better explained through notes than synthetic lines.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Revenue vs Budget by Zone (MWK)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Benchmark context: compare actual sales with proportional budget by zone and use variance/BPI details to isolate the weakest commercial segment.",
        rationale="Grouped zone comparisons are descriptive plan-performance visuals rather than literal threshold charts.",
        legend_style="compact-top",
        print_priority="medium",
    ),
    ChartGovernanceItem(
        page_key="budget",
        title="Zone Performance by Dimension (score 0–100)",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Interpretation note: use the score view as a synthesis summary only; confirm any weak dimension against the zone tables before management action.",
        rationale="Synthetic score summaries should remain interpretive rather than visually over-claimed with benchmark lines.",
        legend_style="compact-top",
        print_priority="low",
    ),
    ChartGovernanceItem(
        page_key="compliance",
        title="Statutory Compliance Status",
        benchmark_mode="none",
        benchmark_label="",
        note="Evidence rule: no literal target line is allowed until regulated laboratory-result fields exist in the governed schema.",
        rationale="The current compliance page reports evidence status rather than numeric statutory compliance performance.",
        legend_style="none",
        print_priority="high",
    ),
    ChartGovernanceItem(
        page_key="compliance",
        title="Operational Proxy Context",
        benchmark_mode="context",
        benchmark_label="Read note",
        note="Operational indicators are useful for monitoring context but must not be presented as statutory compliance evidence.",
        rationale="Proxy indicators support management awareness but do not warrant literal regulatory benchmark lines.",
        legend_style="none",
        print_priority="high",
    ),
]


def _normalise_lookup_key(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(value or "")).split())


def _kpi_evidence_class(item: KPIRegistryItem) -> str:
    if not item.currently_supported:
        return "missing"
    benchmark = item.benchmark_type.lower()
    if "target line allowed" in benchmark:
        return "approved"
    if "context note preferred" in benchmark:
        return "context"
    if "context note only" in benchmark or "proxy" in item.unit.lower():
        return "proxy"
    return "context"


def _kpi_evidence_status(item: KPIRegistryItem) -> str:
    match _kpi_evidence_class(item):
        case "approved":
            return "Approved comparator available"
        case "context":
            return "Operational context only"
        case "proxy":
            return "Operational proxy only"
        case _:
            return "Source data not yet onboarded"


def _kpi_visual_treatment(item: KPIRegistryItem) -> str:
    match _kpi_evidence_class(item):
        case "approved":
            return "Literal target line allowed on purpose-built KPI charts."
        case "context":
            return "Use interpretation note rather than a universal target line."
        case "proxy":
            return "Use proxy label and context note; do not imply statutory compliance."
        case _:
            return "Show an evidence caveat only until source fields are onboarded."


def _kpi_aliases(item: KPIRegistryItem) -> list[str]:
    aliases = [item.title, item.key.replace("_", " ")]
    aliases.extend(KPI_UI_ALIASES.get(item.key, []))
    # Deduplicate while preserving order
    seen = set()
    out = []
    for alias in aliases:
        norm = _normalise_lookup_key(alias)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(alias)
    return out


def _kpi_payload(item: KPIRegistryItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["aliases"] = _kpi_aliases(item)
    payload["evidence_class"] = _kpi_evidence_class(item)
    payload["evidence_status"] = _kpi_evidence_status(item)
    payload["visual_treatment"] = _kpi_visual_treatment(item)
    payload["support_status"] = "Live" if item.currently_supported else "Needs governed source data"
    payload["tooltip"] = (
        f"{item.formula} Owner: {item.owner}. "
        f"{_kpi_evidence_status(item)}. {_kpi_visual_treatment(item)}"
    )
    payload["evidence_short"] = {
        "approved": "Target",
        "context": "Context",
        "proxy": "Proxy",
        "missing": "Data gap",
    }.get(payload["evidence_class"], "Info")
    return payload


def build_chart_governance_registry() -> dict[str, Any]:
    items = [asdict(item) for item in CHART_GOVERNANCE_REGISTRY]
    summary = Counter(item.benchmark_mode for item in CHART_GOVERNANCE_REGISTRY)
    return {
        "summary": {
            "total": len(CHART_GOVERNANCE_REGISTRY),
            "line": summary.get("line", 0),
            "band": summary.get("band", 0),
            "context": summary.get("context", 0),
            "none": summary.get("none", 0),
        },
        "items": items,
        "by_title": {item["title"]: item for item in items},
    }


def build_page_visual_standards() -> dict[str, Any]:
    items = [asdict(item) for item in PAGE_VISUAL_STANDARDS]
    return {
        "summary": {"total_pages": len(PAGE_VISUAL_STANDARDS)},
        "items": items,
        "by_page": {item["page_key"]: item for item in items},
    }


def build_evidence_ladder() -> dict[str, Any]:
    items = [asdict(item) for item in EVIDENCE_LADDER]
    return {
        "summary": {"steps": len(items)},
        "items": items,
        "by_key": {item["key"]: item for item in items},
    }


def build_governance_bundle() -> dict[str, Any]:
    return {
        "pages": build_page_visual_standards(),
        "charts": build_chart_governance_registry(),
        "kpis": build_kpi_governance_status(),
        "evidence_ladder": build_evidence_ladder(),
        "institutional_rule": "Target lines appear only where the charted KPI has a legitimate approved comparator or accepted sector benchmark. Otherwise the dashboard uses a threshold band, control limit, or interpretation note.",
    }


def _page_title(page_key: str) -> str:
    return PAGE_TITLE_REGISTRY.get(page_key, page_key.replace("-", " ").replace("_", " ").title())


def _data_quality_tone(status: str) -> str:
    return {"good": "good", "watch": "amber", "poor": "danger", "no_data": "danger"}.get(status, "neutral")


def _data_quality_label(status: str) -> str:
    return {
        "good": "Data quality strong",
        "watch": "Data quality watch",
        "poor": "Data quality risk",
        "no_data": "No governed data",
    }.get(status, "Data quality pending")


def _data_quality_detail(payload: dict[str, Any]) -> str:
    if payload.get("status") == "no_data":
        return "No governed records are currently loaded, so export evidence should be treated as unavailable."
    summary = payload.get("summary") or {}
    return (
        f"{summary.get('good', 0)} monitored fields are strong, "
        f"{summary.get('watch', 0)} are on watch, and {summary.get('poor', 0)} are poor "
        f"across {payload.get('records', 0)} governed records."
    )


def _page_evidence_profile(page_key: str) -> dict[str, str]:
    page_modes = Counter(item.benchmark_mode for item in CHART_GOVERNANCE_REGISTRY if item.page_key == page_key)
    standards = build_page_visual_standards().get("by_page", {})
    page_std = standards.get(page_key)

    if page_key == "compliance":
        return {
            "status": "proxy_only",
            "label": "Statutory evidence gap",
            "tone": "danger",
            "detail": "Operational proxy indicators are live, but regulated laboratory-result fields are not yet onboarded into the governed schema.",
        }
    if page_key == "budget":
        return {
            "status": "budget_comparator",
            "label": "Approved budget comparator",
            "tone": "good",
            "detail": "This page uses approved budget or target comparators where literal lines appear, with diagnostic charts remaining interpretation-led.",
        }
    if page_modes.get("line", 0) > 0 and page_key in {"overview", "production", "collections"}:
        return {
            "status": "approved_comparator",
            "label": "Approved KPI comparator",
            "tone": "good",
            "detail": "This page contains a governed KPI comparator that supports literal target or benchmark-line treatment where appropriate.",
        }
    if page_modes.get("band", 0) >= max(page_modes.get("line", 0), page_modes.get("context", 0), 1):
        return {
            "status": "threshold_led",
            "label": "Threshold-led evidence",
            "tone": "amber",
            "detail": "This page is governed primarily through thresholds or control bands rather than literal target lines.",
        }
    if page_std and "context" in page_std.get("benchmark_rule", "").lower():
        return {
            "status": "context_led",
            "label": "Context-led evidence",
            "tone": "neutral",
            "detail": "Interpret this page through governed narrative and contextual evidence rather than a universal literal target line.",
        }
    if page_modes.get("context", 0) > 0 or not page_modes:
        return {
            "status": "context_led",
            "label": "Context-led evidence",
            "tone": "neutral",
            "detail": "This page is descriptive and should be read through governed context notes and supporting tables.",
        }
    return {
        "status": "mixed",
        "label": "Mixed evidence treatment",
        "tone": "blue",
        "detail": "This page mixes comparator, threshold, and contextual treatments under the governance register.",
    }


def build_page_export_governance(db: Session, page_key: str | None = None) -> dict[str, Any]:
    data_quality = build_data_quality_status(db)
    dq_status = str(data_quality.get("status") or "watch")
    dq_label = _data_quality_label(dq_status)
    dq_tone = _data_quality_tone(dq_status)
    dq_detail = _data_quality_detail(data_quality)
    standards = build_page_visual_standards().get("by_page", {})

    selected_pages = [page_key] if page_key else EXPORT_GOVERNANCE_PAGES
    items: list[dict[str, Any]] = []
    for key in selected_pages:
        evidence = _page_evidence_profile(key)
        page_std = standards.get(key)
        export_note = " ".join(
            part
            for part in [
                dq_label + ".",
                evidence["label"] + ".",
                page_std.get("print_rule") if page_std else "Keep governance chips visible in board-pack output.",
            ]
            if part
        )
        chips = [
            {
                "key": "data_quality",
                "label": dq_label,
                "tone": dq_tone,
                "detail": dq_detail,
            },
            {
                "key": "evidence",
                "label": evidence["label"],
                "tone": evidence["tone"],
                "detail": evidence["detail"],
            },
            {
                "key": "board_pack",
                "label": "Board-pack governed",
                "tone": "neutral",
                "detail": page_std.get("print_rule") if page_std else "Keep data-quality and evidence cues visible in report exports and print output.",
            },
        ]
        items.append(
            {
                "page_key": key,
                "title": _page_title(key),
                "data_quality_status": dq_status,
                "data_quality_label": dq_label,
                "data_quality_tone": dq_tone,
                "data_quality_detail": dq_detail,
                "evidence_status": evidence["status"],
                "evidence_label": evidence["label"],
                "evidence_tone": evidence["tone"],
                "evidence_detail": evidence["detail"],
                "benchmark_rule": page_std.get("benchmark_rule", "") if page_std else "Use the governance register before showing literal target lines.",
                "legend_rule": page_std.get("legend_rule") if page_std else "Keep legends compact and non-decorative in exports.",
                "print_rule": page_std.get("print_rule") if page_std else "Keep data-quality and evidence cues visible in board-pack output.",
                "export_note": export_note,
                "chips": chips,
            }
        )

    summary = Counter(item["evidence_status"] for item in items)
    return {
        "summary": {
            "pages": len(items),
            "data_quality_status": dq_status,
            "approved_comparator": summary.get("approved_comparator", 0) + summary.get("budget_comparator", 0),
            "threshold_led": summary.get("threshold_led", 0),
            "context_led": summary.get("context_led", 0),
            "proxy_only": summary.get("proxy_only", 0),
            "mixed": summary.get("mixed", 0),
        },
        "data_quality": data_quality,
        "items": items,
        "by_page": {item["page_key"]: item for item in items},
    }

def _safe_pct(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    try:
        return round((float(numerator) / float(denominator)) * 100.0, 2)
    except Exception:
        return None


def build_data_quality_status(db: Session) -> dict[str, Any]:
    total_records = db.query(func.count(Record.id)).scalar() or 0
    if total_records == 0:
        return {
            "records": 0,
            "status": "no_data",
            "completeness": [],
            "summary": {"good": 0, "watch": 0, "poor": 0},
        }

    monitored_fields = [
        ("zone", Record.zone),
        ("scheme", Record.scheme),
        ("year", Record.year),
        ("month_no", Record.month_no),
        ("vol_produced", Record.vol_produced),
        ("pct_nrw", Record.pct_nrw),
        ("active_customers", Record.active_customers),
        ("amt_billed", Record.amt_billed),
        ("cash_collected", Record.cash_collected),
        ("collection_rate", Record.collection_rate),
        ("chlorine_kg", Record.chlorine_kg),
        ("supply_hours", Record.supply_hours),
    ]
    completeness: list[dict[str, Any]] = []
    summary = Counter()
    for name, column in monitored_fields:
        present = db.query(func.count()).filter(column.is_not(None)).filter(column != "").scalar() or 0
        pct = round((present / total_records) * 100.0, 1)
        if pct >= 98:
            state = "good"
        elif pct >= 80:
            state = "watch"
        else:
            state = "poor"
        summary[state] += 1
        completeness.append({"field": name, "present": int(present), "total": int(total_records), "pct": pct, "status": state})

    system_status = "good" if summary["poor"] == 0 else "watch" if summary["poor"] <= 2 else "poor"
    return {
        "records": int(total_records),
        "status": system_status,
        "completeness": completeness,
        "summary": {"good": summary["good"], "watch": summary["watch"], "poor": summary["poor"]},
    }


def build_kpi_governance_status() -> dict[str, Any]:
    items = [_kpi_payload(item) for item in KPI_REGISTRY]
    supported = sum(1 for item in items if item["currently_supported"])
    unsupported = len(items) - supported
    evidence_summary = Counter(item["evidence_class"] for item in items)
    by_label: dict[str, dict[str, Any]] = {}
    for item in items:
        for alias in item["aliases"]:
            by_label[_normalise_lookup_key(alias)] = item
    return {
        "summary": {
            "total_kpis": len(items),
            "supported_now": supported,
            "requires_new_data": unsupported,
            "approved": evidence_summary.get("approved", 0),
            "context": evidence_summary.get("context", 0),
            "proxy": evidence_summary.get("proxy", 0),
            "missing": evidence_summary.get("missing", 0),
        },
        "items": items,
        "by_label": by_label,
    }


def build_compliance_overview(db: Session) -> dict[str, Any]:
    total_records = db.query(func.count(Record.id)).scalar() or 0
    distinct_zones = db.query(func.count(func.distinct(Record.zone))).scalar() or 0
    avg_supply_hours = db.query(func.avg(Record.supply_hours)).scalar() or 0.0
    avg_power_fail_hours = db.query(func.avg(Record.power_fail_hours)).scalar() or 0.0
    avg_nrw = db.query(func.avg(Record.pct_nrw)).scalar() or 0.0

    chemical_rows = db.query(Record).filter(Record.vol_produced > 0).all()
    chlorine_proxy_values = []
    for row in chemical_rows:
        try:
            chlorine_proxy_values.append((float(row.chlorine_kg or 0.0) / float(row.vol_produced)) * 1000.0)
        except Exception:
            continue
    avg_chlorine_proxy = round(sum(chlorine_proxy_values) / len(chlorine_proxy_values), 3) if chlorine_proxy_values else None

    missing_modules = [item.title for item in KPI_REGISTRY if not item.currently_supported]
    return {
        "coverage": {
            "records": int(total_records),
            "zones": int(distinct_zones),
        },
        "operational_proxies": {
            "avg_supply_hours": round(float(avg_supply_hours or 0.0), 2),
            "avg_power_failure_hours": round(float(avg_power_fail_hours or 0.0), 2),
            "avg_nrw_pct": round(float(avg_nrw or 0.0), 2),
            "avg_chlorine_dose_proxy_kg_per_1000m3": avg_chlorine_proxy,
        },
        "compliance_position": {
            "status": "partial",
            "message": "Operational and treatment proxies are available, but formal laboratory compliance indicators are not yet in the current upload schema.",
            "missing_regulated_datasets": missing_modules,
        },
    }


def build_water_quality_module(db: Session) -> dict[str, Any]:
    rows = db.query(Record).all()
    total_rows = len(rows)
    treated_rows = [r for r in rows if (r.vol_produced or 0) > 0]
    chlorine_present = sum(1 for r in rows if (r.chlorine_kg or 0) > 0)
    chem_cost_present = sum(1 for r in rows if (r.chem_cost or 0) > 0)

    proxies = []
    for r in treated_rows:
        vol = float(r.vol_produced or 0)
        if vol <= 0:
            continue
        chlorine = float(r.chlorine_kg or 0)
        alum = float(r.alum_kg or 0)
        proxies.append({
            "zone": r.zone,
            "scheme": r.scheme,
            "month": r.month,
            "year": r.year,
            "chlorine_kg_per_1000m3": round((chlorine / vol) * 1000.0, 3),
            "alum_kg_per_1000m3": round((alum / vol) * 1000.0, 3),
            "chem_cost_per_m3": round(float(r.chem_cost_per_m3 or 0.0), 4),
        })

    # Real water-quality compliance — live once monthly samples are entered.
    def _wq_sum(field):
        return sum(int(getattr(r, field, 0) or 0) for r in rows)
    def _wq_rate(s_field, c_field):
        s = _wq_sum(s_field); c = _wq_sum(c_field)
        return {"samples": s, "compliant": c, "pct": round(c / s * 100, 1) if s else None}
    compliance = {
        "samples_taken": _wq_sum("wq_samples_taken"),
        "chlorine":        _wq_rate("wq_cl_samples", "wq_cl_compliant"),
        "turbidity":       _wq_rate("wq_turbidity_samples", "wq_turbidity_compliant"),
        "bacteriological": _wq_rate("wq_bact_samples", "wq_bact_compliant"),
        "ph":              _wq_rate("wq_ph_samples", "wq_ph_compliant"),
    }
    _params = ("chlorine", "turbidity", "bacteriological", "ph")
    _tot_s = sum(compliance[p]["samples"] for p in _params)
    _tot_c = sum(compliance[p]["compliant"] for p in _params)
    compliance["overall_pct"] = round(_tot_c / _tot_s * 100, 1) if _tot_s else None
    has_wq = _tot_s > 0

    return {
        "module_status": "live" if has_wq else "partial",
        "compliance": compliance,
        "available_now": [
            "chlorine dosing proxy",
            "alum dosing proxy",
            "chemical cost per m³",
            "supply continuity context",
        ],
        "not_yet_available": [
            "residual chlorine sample compliance",
            "turbidity compliance",
            "bacteriological compliance",
            "regulatory permit exceedance log",
            "sampling-plan completion rate",
        ],
        "coverage": {
            "rows_with_production": len(treated_rows),
            "rows_with_chlorine": chlorine_present,
            "rows_with_chemical_cost": chem_cost_present,
            "total_rows": total_rows,
        },
        "latest_proxies": proxies[-12:],
        "governance_note": "These indicators are operational proxies only. They must not be labelled as statutory compliance results until lab-result fields are added to the governed schema.",
    }
