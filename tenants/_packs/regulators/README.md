# Regulator packs

One YAML file per regulator and reporting cycle: `<regulator>/<cycle>.yaml`. A pack describes a
regulator's published method as **data**, tied to the report it comes from. MadziHub imports a
file as a *draft*; nothing is scored until the pack is verified and approved.

## Rules

1. **Cite the source.** `source.title`, `source.url` and `source.accessed` are required. Every
   indicator and group carries `source_ref` (section, table, page).
2. **Verify, don't infer.** Fill a weight, threshold or share only from the cited source, and only
   then set `verified: true`. Never copy numbers from another regulator or another year. When the
   whole pack has been checked, set `verification.source_checked: true`.
3. **Two people.** The officer who imports or last edits a pack cannot approve it. Approval is
   refused while any blocker remains (unverified or missing figures, shares not summing to 100).
4. **One cycle, one pack.** A new cycle or a corrected method is a new file or a new version;
   approving a version retires the previous approved one for that cycle.

## Format

```yaml
regulator: WASREB                       # short name
jurisdiction: Kenya
cycle: "FY2023/24 (IMPACT 17)"
title: "…"
method: weighted_points                 # the only method in engine 1.0.0
source: {title: "…", url: "…", accessed: 2026-09-25}
verification: {source_checked: false, notes: "…"}
groups:                                 # score groups and their share of the total (sum 100)
  - {code: KPI, name: "…", share_pct: 60, verified: false, source_ref: "…"}
indicators:
  - code: NRW
    name: "Non-revenue water"
    group: KPI
    cluster: "Operational Sustainability"      # optional, for display
    unit: "%"
    polarity: lower                            # higher | lower | yes_no
    weight: null                               # number once verified
    in_score: true                             # false = reported but not scored
    verified: false
    source_ref: "Table 3.3, p. 39"
    validation: {min: 0, max: 100}             # checked on every entered value
    madzihub_metric: nrw_pct                   # optional: prefill from the catalogue (fiscal year)
    scoring:                                   # one of:
      type: bands                              #   fixed thresholds
      bands: [{max: 25, points: 10, label: good}, {min: 25, max: 35, points: 5, label: acceptable},
              {min: 35, points: 0, label: not acceptable}]
      # type: peer_interpolation  (min_points / median_points / best_points against peers)
      # type: yes_no              (points for a compliance obligation met)
peer_groups: [{code: size, name: "…", verified: true, source_ref: "…"}]
export_template: {sheet: "Return", columns: [code, name, unit, value, source]}
```

## Shipped drafts (25 September 2026)

| File | What is verified | What is not |
|---|---|---|
| `wasreb/impact17-fy2023-24.yaml` | Nine ranked KPIs in three clusters; the ten indicators described in §3.7; NRW acceptable benchmark < 25 %; peer categories | Which nine are ranked, weights, class thresholds and points (Table 3.3 is not machine-readable) |
| `ewura/fy2023-24.yaml` | Overall score = KPI score + compliance (CRR) score; four KPI scoring components; the 12 KPIs and 7 CRR obligation groups; clusters I–III | Every number: shares (60/40 per the research benchmark, not re-read), weights, boundaries, points. The four-component KPI method also needs an engine extension before approval |

NWASCO and IBNET packs are **not** included: add them only after the jurisdiction's official
schema, current return and scoring method are confirmed from primary sources.
