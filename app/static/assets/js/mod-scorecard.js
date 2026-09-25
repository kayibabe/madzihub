/* ══════════════════════════════════════════════════════════════════════════
   Scorecard (mod-scorecard.js) — builds on window.MZ
   · Scorecard:     tree grid (performance, completeness and data quality in separate columns),
                    calculation detail, snapshots, overrides, approval, weights editor
   · Strategy Map:  SVG map of pillars, objectives and the initiatives that serve them
   · Scoring Schemes: versioned schemes, five explicit bands, sign-off
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
MZ.entityPages.score_snapshot = 'scorecard';

const SC = {planId: null, periodId: null, unit: 'org', snapId: null, tab: 'scorecard', open: new Set(), selected: null, data: null};
const pct = v => v === null || v === undefined ? '—' : `${MZ.num(v, 1)}%`;
const ratingText = (r, label) => r === null || r === undefined ? '—' : `${MZ.num(r, 2)}${label ? ' · ' + label : ''}`;

function ratingTone(rating, scheme){
  if(rating === null || rating === undefined || !scheme) return '';
  const rs = scheme.bands.map(b => b.rating);
  const best = scheme.rating_order === 'lower_is_better' ? Math.min(...rs) : Math.max(...rs);
  const worst = scheme.rating_order === 'lower_is_better' ? Math.max(...rs) : Math.min(...rs);
  const pos = (rating - worst) / ((best - worst) || 1);      // 0 worst … 1 best
  return pos >= 0.7 ? 'ok' : pos >= 0.45 ? 'info' : pos >= 0.25 ? 'warn' : 'danger';
}
const ratingBadge = (item, scheme) => item.rating === null || item.rating === undefined
  ? MZ.badge(item.status || item.state || 'unscored', '', MZ.label(item.status === 'incomplete' ? 'incomplete' : (item.state || item.status || 'unscored')))
  : `<span class="mz-badge ${ratingTone(item.rating, scheme)}">${E(ratingText(item.rating, item.rating_label))}</span>${item.override ? ' <span class="mz-badge purple" title="Overridden">override</span>' : ''}`;

async function selectors(){
  const [plans, periods] = await Promise.all([MZ.api('/api/strategy/plans'), MZ.api('/api/platform/periods')]);
  if(!plans.some(p => String(p.id) === String(SC.planId))) SC.planId = (plans.find(p => p.status === 'active') || plans[0] || {}).id;
  const today = MZ.today();
  if(!periods.some(p => String(p.id) === String(SC.periodId))){
    SC.periodId = (periods.find(p => p.period_type === 'quarter' && p.start_date <= today && today <= p.end_date) || periods[0] || {}).id;
  }
  if(!MZ.roleOn(SC.unit)) SC.unit = (MZ.units[0] || {}).code || 'org';
  return {plans, periods};
}
function selectorHtml(plans, periods, idp){
  return `<div class="mz-toolbar">
    <div class="adm-field"><label class="adm-label" for="${idp}-plan">Plan</label><select class="adm-select" id="${idp}-plan">${plans.map(p => `<option value="${p.id}"${String(p.id) === String(SC.planId) ? ' selected' : ''}>${E(p.code)} — ${E(p.title)}</option>`).join('')}</select></div>
    <div class="adm-field"><label class="adm-label" for="${idp}-period">Period</label><select class="adm-select" id="${idp}-period">${periods.map(p => `<option value="${p.id}"${String(p.id) === String(SC.periodId) ? ' selected' : ''}>${E(p.label)}${p.status === 'locked' ? ' (locked)' : ''}</option>`).join('')}</select></div>
    <div class="adm-field"><label class="adm-label" for="${idp}-unit">Unit</label><select class="adm-select" id="${idp}-unit">${MZ.unitOptions('viewer').map(o => `<option value="${E(o.value)}"${o.value === SC.unit ? ' selected' : ''}>${E(o.label)}</option>`).join('')}</select></div>
  </div>`;
}
function bindSelectors(idp, reload){
  const on = (id, key) => MZ.$(`${idp}-${id}`)?.addEventListener('change', e => { SC[key] = e.target.value; SC.snapId = null; SC.selected = null; reload(); });
  on('plan', 'planId'); on('period', 'periodId'); on('unit', 'unit');
}

/* ═══════════════════════════════ Scorecard ═════════════════════════════ */
MZ.page('scorecard', async root => {
  const pending = MZ.takePending('scorecard');
  if(pending && pending.type === 'score_snapshot') SC.snapId = pending.id;
  const {plans, periods} = await selectors();
  if(!plans.length){ MZ.html(root, `${MZ.header('Scorecard', 'Set up a plan on Plans & Indicators first.')}`); return; }
  MZ.html(root, `${MZ.header('Scorecard', 'Achievement against target (polarity-aware, capped for rating, uncapped value kept), rated on the signed-off scheme and combined by weight. Performance, completeness and data quality are shown separately; an item with too little data is “incomplete”, never scored as zero.')}
    ${selectorHtml(plans, periods, 'sc')}<div id="sc-tabs"></div><div id="sc-body"></div>`);
  bindSelectors('sc', () => MZ.refresh('scorecard'));
  const render = () => {
    MZ.tabs(MZ.$('sc-tabs'), [{key: 'scorecard', label: 'Scorecard'}, {key: 'weights', label: 'Weights'}], SC.tab, k => { SC.tab = k; render(); });
    (SC.tab === 'weights' ? renderWeights : renderScorecard)(MZ.$('sc-body')).catch(e => MZ.html(MZ.$('sc-body'), `<div class="mz-notice danger">${E(e.message)}</div>`));
  };
  render();
});

async function renderScorecard(body){
  const snaps = await MZ.api(`/api/scorecard/snapshots?plan_id=${SC.planId}&period_id=${SC.periodId}&org_unit=${encodeURIComponent(SC.unit)}`);
  let view, snap = null;
  if(SC.snapId){ snap = await MZ.api(`/api/scorecard/snapshots/${SC.snapId}`); view = {tree: snap.tree, scheme: snap.scheme, inputs: snap.inputs}; }
  else { view = await MZ.api(`/api/scorecard/preview?plan_id=${SC.planId}&period_id=${SC.periodId}&org_unit=${encodeURIComponent(SC.unit)}`); }
  SC.data = {view, snap};
  const canSnap = !MZ.me.read_only && (MZ.hasFunction('strategy_manager') || MZ.can(SC.unit, 'reviewer'));
  const rootItem = view.tree.root;
  const scheme = view.scheme;
  const dqFails = view.inputs.indicators.reduce((a, i) => a + ((i.dq || {}).fails || 0), 0);
  const dqWarns = view.inputs.indicators.reduce((a, i) => a + ((i.dq || {}).warns || 0), 0);
  const counted = view.inputs.indicators.filter(i => !['not_applicable', 'not_due', 'not_reported'].includes(i.state));
  MZ.html(body, `<div class="mz-grid-2" style="margin-top:12px">
    <section class="mz-card"><h3>${snap ? `Snapshot #${E(snap.id)} ${MZ.badge(snap.status)}` : 'Live calculation (not stored)'}</h3>
      ${(snap ? snap.provisional : view.provisional) ? '<div class="mz-notice warn">Scheme not signed off yet: this score is provisional and cannot be approved.</div>' : ''}
      <div class="mz-stats" style="margin-top:8px">
        <div class="mz-stat ${ratingTone(rootItem.rating, scheme)}"><span class="mz-stat-val">${E(rootItem.rating == null ? '—' : MZ.num(rootItem.rating, 2))}</span><span class="mz-stat-lbl">Rating ${rootItem.rating_label ? '· ' + E(rootItem.rating_label) : ''}</span></div>
        <div class="mz-stat"><span class="mz-stat-val">${E(pct(rootItem.achievement))}</span><span class="mz-stat-lbl">Weighted achievement</span></div>
        <div class="mz-stat ${rootItem.status === 'complete' ? 'ok' : 'warn'}"><span class="mz-stat-val">${counted.length ? E(counted.filter(i => i.state === 'measured').length + '/' + counted.length) : '—'}</span><span class="mz-stat-lbl">Indicators with data</span></div>
        <div class="mz-stat ${dqFails ? 'danger' : dqWarns ? 'warn' : 'ok'}"><span class="mz-stat-val">${dqFails}/${dqWarns}</span><span class="mz-stat-lbl">DQ fails / warnings</span></div>
      </div>
      <p class="mz-meta" style="margin-top:8px">Status: ${MZ.badge(rootItem.status)} · ${E(rootItem.method || '')}</p>
      <p class="mz-meta">Scheme ${E(scheme.code)} v${E(scheme.version)} (${E(MZ.label(scheme.status))}) · ratings ${scheme.rating_order === 'higher_is_better' ? 'higher is better' : 'lower is better'} · cap ${E(scheme.cap_pct)}% · coverage gate ${E(scheme.coverage_gate_pct)}%${snap ? ` · engine ${E(snap.engine_version)} · inputs <span class="mz-mono" title="${E(snap.inputs_hash)}">${E(snap.inputs_hash.slice(0, 12))}…</span>` : ''}</p>
      <div class="mz-btn-row">${snap ? '<button class="mz-btn ghost" data-mz="live">Show live calculation</button>' : ''}
        ${canSnap ? '<button class="mz-btn primary" data-mz="snap">Take snapshot</button>' : ''}
        ${snap && snap.can_approve ? '<button class="mz-btn primary" data-mz="approve">Approve snapshot</button>' : ''}</div>
      ${snap && snap.approval_blocker ? `<p class="mz-meta" role="status"><strong>Cannot be signed off yet:</strong> ${E(snap.approval_blocker)}</p>` : ''}
    </section>
    <section class="mz-card"><h3>Snapshots for this plan, period and unit</h3>${MZ.table({rows: snaps, rowId: s => s.id, selected: SC.snapId, empty: 'No snapshots yet.', columns: [
      {label: '#', render: s => `<span class="mz-mono">${E(s.id)}</span>`}, {label: 'Rating', render: s => E(ratingText(s.rating, s.rating_label))},
      {label: 'Status', render: s => MZ.badge(s.status) + (s.provisional ? ' ' + MZ.badge('provisional') : '')},
      {label: 'Taken', render: s => `${E(s.created_by)}<div class="mz-meta">${E(MZ.dateTime(s.created_at))}</div>`},
      {label: 'Approved', render: s => s.approved_by ? `${E(s.approved_by)}<div class="mz-meta">${E(MZ.dateTime(s.approved_at))}</div>` : '—'}]})}</section>
  </div>
  <section class="mz-card"><h3>Scorecard</h3><div id="sc-grid"></div></section>
  <section class="mz-card" id="sc-detail" hidden></section>`);
  const snapHost = body.querySelectorAll('.mz-card')[1];
  MZ.onRow(snapHost, id => { SC.snapId = id; SC.selected = null; renderScorecard(body); });
  renderGrid();
  MZ.onAct(body.querySelector('.mz-card'), {
    live: () => { SC.snapId = null; renderScorecard(body); },
    snap: async () => {
      const r = await MZ.reason({title: 'Take a score snapshot', label: 'Note (optional)', required: false, submitLabel: 'Take snapshot',
        intro: 'The snapshot freezes the values, targets, weights, scheme and engine version it was calculated from. Recalculating later makes a new snapshot; approved ones are never rewritten.'});
      if(!r) return;
      const s = await MZ.api('/api/scorecard/snapshots', {method: 'POST', body: {plan_id: Number(SC.planId), period_id: Number(SC.periodId), org_unit_code: SC.unit, note: r.reason || null}});
      SC.snapId = s.id; MZ.toast(`Snapshot #${s.id} taken.`, 'ok'); renderScorecard(body);
    },
    approve: async () => {
      const r = await MZ.reason({title: `Approve snapshot #${snap.id}`, label: 'Note (optional)', required: false, submitLabel: 'Approve',
        intro: 'Approving supersedes any earlier approved snapshot for this plan, period and unit.'});
      if(!r) return;
      await MZ.api(`/api/scorecard/snapshots/${snap.id}/approve`, {method: 'POST', body: {note: r.reason || null}});
      MZ.toast('Snapshot approved.', 'ok'); renderScorecard(body);
    },
  });
}

function renderGrid(){
  const {view} = SC.data;
  const items = view.tree.items;
  const scheme = view.scheme;
  const rows = [];
  const walk = (key, depth) => {
    const it = items[key];
    if(!it) return;
    rows.push({it, depth});
    if(it.type === 'node' && SC.open.has(key)) it.children.forEach(k => walk(k, depth + 1));
  };
  if(!SC.open.size) view.tree.root.children.forEach(k => SC.open.add(k));
  view.tree.root.children.forEach(k => walk(k, 0));
  const dq = it => it.type !== 'indicator' ? '' : !it.dq ? '<span class="mz-meta">no cycle</span>'
    : `${it.dq.fails ? MZ.badge('fail', 'danger', `${it.dq.fails} fail`) : ''}${it.dq.warns ? ' ' + MZ.badge('warn', 'warn', `${it.dq.warns} warn`) : ''}${!it.dq.fails && !it.dq.warns ? MZ.badge('pass', 'ok', it.dq.revision ? 'Pass' : 'No submission') : ''}`;
  const html = `<div class="mz-table-wrap"><table class="mz-table" role="treegrid" aria-label="Scorecard">
    <thead><tr><th scope="col">Item</th><th scope="col" class="num">Weight</th><th scope="col" class="num">Actual</th><th scope="col" class="num">Target</th>
      <th scope="col" class="num">Achievement</th><th scope="col">Rating</th><th scope="col">Completeness</th><th scope="col">Data quality</th></tr></thead>
    <tbody>${rows.map(({it, depth}) => {
      const isNode = it.type === 'node';
      const toggle = isNode && it.children.length ? `<button class="mz-link" data-mz="toggle" data-key="${E(it.key)}" aria-expanded="${SC.open.has(it.key)}" aria-label="${SC.open.has(it.key) ? 'Collapse' : 'Expand'} ${E(it.code)}">${SC.open.has(it.key) ? '▾' : '▸'}</button> ` : '';
      const completeness = isNode ? `${MZ.badge(it.status)}<div class="mz-meta">${it.coverage_pct != null ? E(MZ.num(it.coverage_pct, 1)) + '% of weight' : ''}${it.weighting === 'equal' ? ' · equal weights' : ''}</div>`
        : MZ.badge(it.state, it.state === 'scored' ? 'ok' : ['not_applicable', 'not_due', 'not_reported'].includes(it.state) ? '' : 'warn');
      return `<tr class="mz-click${SC.selected === it.key ? ' mz-selected' : ''}" data-row-id="${E(it.key)}" tabindex="0" role="row" aria-level="${depth + 1}">
        <td style="padding-left:${12 + depth * 20}px">${toggle}${isNode ? `<span class="mz-badge">${E(MZ.label(it.node_type))}</span> ` : ''}<span class="mz-mono">${E(it.code)}</span> ${E(isNode ? it.title : it.name)}</td>
        <td class="num">${it.weight != null ? E(MZ.num(it.weight, 1)) + '%' : '<span class="mz-meta">—</span>'}</td>
        <td class="num">${isNode ? '' : E(MZ.num(it.actual))}</td><td class="num">${isNode ? '' : E(MZ.num(it.target))}</td>
        <td class="num">${E(pct(it.achievement))}${it.achievement_uncapped != null && it.achievement_uncapped !== it.achievement ? `<div class="mz-meta">uncapped ${E(pct(it.achievement_uncapped))}</div>` : ''}</td>
        <td>${ratingBadge(it, scheme)}</td><td>${completeness}</td><td>${dq(it)}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  const host = MZ.$('sc-grid');
  MZ.html(host, html);
  MZ.onRow(host, key => { SC.selected = key; renderGrid(); itemDetail(key); });
  MZ.onAct(host, {toggle: d => { SC.open.has(d.key) ? SC.open.delete(d.key) : SC.open.add(d.key); renderGrid(); }});
}

function itemDetail(key){
  const {view, snap} = SC.data;
  const it = view.tree.items[key];
  const host = MZ.$('sc-detail');
  host.hidden = false;
  const scheme = view.scheme;
  let calc;
  if(it.type === 'indicator'){
    calc = `<dl class="mz-kv"><dt>Polarity</dt><dd>${E(MZ.label(it.polarity))}</dd><dt>Actual</dt><dd>${E(MZ.num(it.actual))} ${E(it.unit || '')} <span class="mz-meta">${E(it.source || '')}</span></dd>
      <dt>Target</dt><dd>${E(MZ.num(it.target))}${it.lower != null ? ` (range ${E(MZ.num(it.lower))}–${E(MZ.num(it.upper))})` : ''}</dd>
      <dt>Formula</dt><dd>${E(it.rule || '—')}</dd><dt>Achievement</dt><dd>${E(pct(it.achievement_uncapped))} uncapped → ${E(pct(it.achievement))} rated</dd>
      <dt>Rating</dt><dd>${ratingBadge(it, scheme)}${it.calculated_rating != null ? ` <span class="mz-meta">(calculated ${E(ratingText(it.calculated_rating, it.calculated_label))})</span>` : ''}</dd>
      ${it.note ? `<dt>Note</dt><dd>${E(it.note)}</dd>` : ''}
      <dt>Source rows</dt><dd class="mz-mono">values ${E((it.value_refs || []).join(', ') || '—')} · target ${E(it.target_id || '—')}</dd>
      <dt>Submission</dt><dd>${it.assignment_status ? MZ.badge(it.assignment_status) : '—'}${it.dq && it.dq.revision ? ` revision ${E(it.dq.revision)}` : ''}</dd></dl>`;
  }else{
    calc = `<p class="mz-meta">${E(it.method || '')}</p>${MZ.table({rows: it.contributions || [], empty: 'Nothing scored at this level.', columns: [
        {label: 'Item', render: c => E(c.label)}, {label: 'Weight', num: true, render: c => E(MZ.num(c.weight, 1)) + '%'},
        {label: 'Achievement', num: true, render: c => E(pct(c.achievement))}, {label: 'Rating', num: true, render: c => E(MZ.num(c.rating, 2))},
        {label: 'Adds to score', num: true, render: c => E(pct(c.share_of_score))}, {label: 'Adds to rating', num: true, render: c => E(MZ.num(c.share_of_rating, 2))}]})}
      ${(it.missing || []).length ? `<h4>Missing</h4><ul>${it.missing.map(m => `<li>${E(m.label)} (${E(MZ.num(m.weight, 1))}%)${m.note ? ' — ' + E(m.note) : ''}</li>`).join('')}</ul>` : ''}
      ${(it.excluded || []).length ? `<h4>Excluded from the weights</h4><ul>${it.excluded.map(m => `<li>${E(m.label)}: ${E(MZ.label(m.state))}</li>`).join('')}</ul>` : ''}`;
  }
  MZ.html(host, `<div class="mz-hdr"><h3>${E(it.code)} · ${E(it.title || it.name)}</h3><div class="mz-btn-row">
      ${snap && snap.can_override ? `<button class="mz-btn" data-mz="override" data-key="${E(key)}">${it.override ? 'Change override' : 'Override rating'}</button>` : ''}</div></div>
    ${it.override ? `<div class="mz-notice warn">Overridden to ${E(ratingText(it.rating, it.rating_label))} by ${E(it.override.by)}: “${E(it.override.reason)}”</div>` : ''}
    <h4>Calculation</h4>${calc}`);
  host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  MZ.onAct(host, {override: async d => {
    const r = await MZ.form({title: `Override the rating of ${it.code}`, intro: 'The calculated value stays visible next to the override. The reason is kept in the snapshot and the audit trail.', fields: [
      {name: 'rating', label: 'Rating', type: 'select', options: [{value: '', label: '(remove override)'}, ...scheme.bands.map(b => ({value: b.rating, label: `${b.rating} · ${b.label}`}))], value: it.override ? it.override.rating : ''},
      {name: 'reason', label: 'Reason', type: 'textarea', required: true}],
      onSubmit: v => MZ.api(`/api/scorecard/snapshots/${snap.id}/override`, {method: 'POST', body: {key: d.key, rating: v.rating === '' || v.rating === null ? null : Number(v.rating), reason: v.reason}})});
    if(r){ MZ.toast('Override saved.', 'ok'); renderScorecard(MZ.$('sc-body')); }
  }});
}

async function renderWeights(body){
  const groups = await MZ.api(`/api/scorecard/plans/${SC.planId}/weights`);
  const manager = MZ.hasFunction('strategy_manager') && !MZ.me.read_only;
  MZ.html(body, `<section class="mz-card" style="margin-top:12px"><h3>Weights</h3>
    <p class="mz-sub">At each level the weights add up to 100, or are all left blank (equal shares, shown as such). The totals update as you type; saving is refused while any level is unbalanced.</p>
    <form id="sc-wform">${groups.map((g, gi) => `<fieldset class="mz-card" style="margin:10px 0;padding:12px"><legend class="mz-strong">${E(g.parent)}</legend>
      <div class="mz-table-wrap"><table class="mz-table"><thead><tr><th scope="col">Item</th><th scope="col" class="num">Weight (%)</th></tr></thead><tbody>
      ${g.items.map(it => `<tr><td>${it.type === 'indicator' ? '<span class="mz-badge info">Indicator</span>' : `<span class="mz-badge">${E(MZ.label(it.node_type))}</span>`} <span class="mz-mono">${E(it.code)}</span> ${E(it.label)}</td>
        <td class="num"><input class="adm-input" style="max-width:110px;text-align:right" type="number" min="0" max="100" step="any" name="w:${it.type}:${it.id}" data-group="${gi}" value="${it.weight ?? ''}" aria-label="Weight of ${E(it.code)}" ${manager ? '' : 'disabled'}></td></tr>`).join('')}
      </tbody></table></div><p class="mz-meta" id="sc-wsum-${gi}" aria-live="polite"></p></fieldset>`).join('')}
    ${manager ? `<div class="adm-field"><label class="adm-label" for="sc-wreason">Reason for the change</label><input class="adm-input" id="sc-wreason"></div><div class="mz-btn-row"><button class="mz-btn primary" type="submit">Save weights</button></div>` : ''}</form></section>`);
  const form = MZ.$('sc-wform');
  const sums = () => groups.forEach((g, gi) => {
    const vals = [...form.querySelectorAll(`input[data-group="${gi}"]`)].map(i => i.value === '' ? null : Number(i.value));
    const set = vals.filter(v => v !== null);
    const el = MZ.$(`sc-wsum-${gi}`);
    const total = set.reduce((a, b) => a + b, 0);
    if(!set.length){ el.textContent = 'No weights: equal shares.'; el.style.color = ''; }
    else if(set.length !== vals.length){ el.textContent = `Total ${total} — fill every weight or clear them all.`; el.style.color = '#991b1b'; }
    else { el.textContent = `Total ${MZ.num(total)}%${Math.abs(total - 100) < 1e-6 ? ' ✓' : ' — must be 100'}`; el.style.color = Math.abs(total - 100) < 1e-6 ? '#166534' : '#991b1b'; }
  });
  form.addEventListener('input', sums); sums();
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const items = [...form.querySelectorAll('input[name^="w:"]')].map(i => { const [, type, id] = i.name.split(':'); return {type, id: Number(id), weight: i.value === '' ? null : Number(i.value)}; });
    try{ await MZ.api(`/api/scorecard/plans/${SC.planId}/weights`, {method: 'PUT', body: {items, reason: MZ.$('sc-wreason').value || null}}); MZ.toast('Weights saved.', 'ok'); renderWeights(body); }
    catch(err){ MZ.fail(err); }
  });
}

/* ═══════════════════════════════ Strategy map ══════════════════════════ */
MZ.page('strategy-map', async root => {
  const {plans, periods} = await selectors();
  if(!plans.length){ MZ.html(root, MZ.header('Strategy map', 'Set up a plan first.')); return; }
  const m = await MZ.api(`/api/scorecard/plans/${SC.planId}/map?period_id=${SC.periodId}&org_unit=${encodeURIComponent(SC.unit)}`);
  const pillars = m.nodes.filter(n => n.node_type === 'pillar');
  const byParent = {};
  m.nodes.forEach(n => { (byParent[n.parent_id] = byParent[n.parent_id] || []).push(n); });
  // Programmes and initiatives always; activities and milestones only when linked to a result.
  const delivery = m.nodes.filter(n => ['programme', 'initiative'].includes(n.node_type)
    || (['activity', 'milestone'].includes(n.node_type) && m.links.some(l => l.from === n.id)));
  const colW = 230, boxW = 206, boxH = 54, gap = 14, top = 64;
  const results = {};
  let maxRows = 0;
  pillars.forEach((p, ci) => {
    const kids = (byParent[p.id] || []).filter(n => ['objective', 'outcome', 'output'].includes(n.node_type));
    results[p.id] = {x: 12 + ci * colW, y: top, n: p};
    kids.forEach((k, ri) => { results[k.id] = {x: 12 + ci * colW, y: top + (ri + 1) * (boxH + gap), n: k}; });
    maxRows = Math.max(maxRows, kids.length + 1);
  });
  const dy = top + maxRows * (boxH + gap) + 50;
  const dels = {};
  delivery.forEach((d, i) => { dels[d.id] = {x: 12 + (i % Math.max(1, pillars.length)) * colW, y: dy + Math.floor(i / Math.max(1, pillars.length)) * (boxH + gap), n: d}; });
  const width = Math.max(1, pillars.length) * colW + 24;
  const height = (Object.values(dels).reduce((a, b) => Math.max(a, b.y), dy) + boxH + 20);
  const tone = n => ratingTone(n.rating, m.scheme);
  const fill = {ok: '#F0FDF4', info: '#ECFBFA', warn: '#FFFBEB', danger: '#FEF2F2', '': '#F8FAFC'};
  const stroke = {ok: '#16a34a', info: '#0E7C7B', warn: '#d97706', danger: '#dc2626', '': '#94a3b8'};
  const wrap = (t, n) => { const words = String(t).split(/\s+/); const lines = ['']; words.forEach(w => { if((lines[lines.length - 1] + ' ' + w).trim().length > n) lines.push(w); else lines[lines.length - 1] = (lines[lines.length - 1] + ' ' + w).trim(); }); return lines.slice(0, 2); };
  const box = (b, kind) => {
    const n = b.n, t = kind === 'delivery' ? '' : tone(n);
    const lines = wrap(`${n.code} ${n.title}`, 30);
    const status = kind === 'delivery' ? MZ.label(n.status) : (n.rating != null ? `${MZ.num(n.rating, 1)} · ${n.rating_label}` : MZ.label(n.score_status || 'no score'));
    return `<g><title>${E(n.code)} ${E(n.title)}: ${E(status)}</title>
      <rect x="${b.x}" y="${b.y}" width="${boxW}" height="${boxH}" rx="10" fill="${kind === 'delivery' ? '#fff' : fill[t]}" stroke="${kind === 'delivery' ? '#94a3b8' : stroke[t]}" stroke-width="${n.node_type === 'pillar' ? 2.2 : 1.4}" ${kind === 'delivery' ? 'stroke-dasharray="4 3"' : ''}/>
      ${lines.map((l, i) => `<text x="${b.x + 10}" y="${b.y + 18 + i * 14}" font-size="11.5" font-weight="${n.node_type === 'pillar' ? 800 : 600}" fill="#111827">${E(l)}</text>`).join('')}
      <text x="${b.x + 10}" y="${b.y + boxH - 8}" font-size="10.5" fill="#374151">${E(status)}</text></g>`;
  };
  const lines = m.links.filter(l => dels[l.from] && results[l.to]).map(l => {
    const a = dels[l.from], b = results[l.to];
    return `<path d="M${a.x + boxW / 2},${a.y} C${a.x + boxW / 2},${a.y - 40} ${b.x + boxW / 2},${b.y + boxH + 40} ${b.x + boxW / 2},${b.y + boxH}" fill="none" stroke="#0E7C7B" stroke-width="1.2" opacity=".55" marker-end="url(#mz-arrow)"/>`;
  }).join('');
  const svg = `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-labelledby="sm-title sm-desc" style="min-width:${Math.min(width, 700)}px;background:#fff">
    <title id="sm-title">Strategy map</title><desc id="sm-desc">Pillars with their objectives, coloured by rating, and the delivery work linked to them. The table below lists the same information.</desc>
    <defs><marker id="mz-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0E7C7B"/></marker></defs>
    <text x="12" y="30" font-size="13" font-weight="800" fill="#374151">RESULTS</text>
    <text x="12" y="${dy - 16}" font-size="13" font-weight="800" fill="#374151">DELIVERY (dashed; arrows show what each serves)</text>
    ${lines}${Object.values(results).map(b => box(b, 'result')).join('')}${Object.values(dels).map(b => box(b, 'delivery')).join('')}</svg>`;
  MZ.html(root, `${MZ.header('Strategy map', `Results coloured by rating, with the delivery work that serves them. Ratings come from ${m.source.kind === 'approved_snapshot' ? `approved snapshot #${m.source.id}` : 'a live calculation (not yet approved)'}.`)}
    ${selectorHtml(plans, periods, 'sm')}
    <section class="mz-card" style="overflow:auto">${pillars.length ? svg : '<div class="mz-empty">No pillars yet.</div>'}</section>
    <section class="mz-card"><h3>Legend and text version</h3><div class="mz-pill-list" style="margin-bottom:10px">${m.scheme.bands.map(b => `<span class="mz-badge ${ratingTone(b.rating, m.scheme)}">${E(b.rating)} · ${E(b.label)}</span>`).join('')}<span class="mz-badge">No score</span></div>
      ${MZ.table({rows: m.nodes, columns: [{label: 'Item', render: n => `<span class="mz-badge">${E(MZ.label(n.node_type))}</span> <span class="mz-mono">${E(n.code)}</span> ${E(n.title)}`},
        {label: 'Rating / status', render: n => ['programme', 'initiative', 'activity', 'milestone'].includes(n.node_type) ? MZ.badge(n.status) : (n.rating != null ? `<span class="mz-badge ${ratingTone(n.rating, m.scheme)}">${E(MZ.num(n.rating, 2))} · ${E(n.rating_label)}</span>` : MZ.badge(n.score_status || 'no score'))},
        {label: 'Serves', render: n => m.links.filter(l => l.from === n.id).map(l => E((m.nodes.find(x => x.id === l.to) || {}).code || '')).join(', ')}]})}</section>`);
  bindSelectors('sm', () => MZ.refresh('strategy-map'));
});

/* ═══════════════════════════════ Schemes ═══════════════════════════════ */
MZ.page('schemes', async root => {
  const rows = await MZ.api('/api/scorecard/schemes');
  const manager = MZ.hasFunction('strategy_manager') && !MZ.me.read_only;
  MZ.html(root, `${MZ.header('Scoring schemes', 'How achievement becomes a rating. Each scheme is versioned; only a draft can be edited, and a scheme must be signed off by someone other than its author before any score calculated with it can be approved. The default is MadziHub’s proposal, not a regulator’s or government method.')}
    ${rows.map(s => `<section class="mz-card"><div class="mz-hdr"><h3>${E(s.name)} <span class="mz-meta mz-mono">${E(s.code)} v${E(s.version)}</span></h3>
      <div class="mz-btn-row">${MZ.badge(s.status)}${s.can_edit ? `<button class="mz-btn ghost" data-mz="edit" data-id="${s.id}">Edit draft</button>` : ''}
        ${s.can_approve ? `<button class="mz-btn primary" data-mz="approve" data-id="${s.id}">Sign off</button>` : ''}
        ${manager && s.status !== 'draft' ? `<button class="mz-btn" data-mz="version" data-id="${s.id}">New version</button>` : ''}
        ${manager && s.status === 'approved' ? `<button class="mz-btn danger" data-mz="retire" data-id="${s.id}">Retire</button>` : ''}</div></div>
      <p class="mz-sub">${E(s.description || '')}</p>
      <dl class="mz-kv"><dt>Rating order</dt><dd>${s.rating_order === 'higher_is_better' ? 'Higher numbers are better (5 = best)' : 'Lower numbers are better (1 = best)'}</dd>
        <dt>Cap for rating</dt><dd>${E(s.cap_pct)}% (uncapped achievement is kept and shown)</dd>
        <dt>Lower-is-better formula</dt><dd>${s.lower_method === 'linear_deviation' ? '(2 − actual ÷ target) × 100' : 'target ÷ actual × 100'}</dd>
        <dt>Zero targets</dt><dd>${s.zero_target_rule === 'unscored' ? 'Left unscored (shown as missing)' : 'Binary: met = 100 %, not met = 0 %'}</dd>
        <dt>Missing data</dt><dd>${s.missing_policy === 'coverage_gate' ? `Coverage gate ${E(s.coverage_gate_pct)}%: below it the result is “incomplete”; above it the score is weighted over the covered weight and says so` : 'Missing items count as 0 % (explicit scheme rule)'}</dd>
        <dt>Effective</dt><dd>${E(MZ.date(s.effective_from))} – ${s.effective_to ? E(MZ.date(s.effective_to)) : 'open'}</dd>
        <dt>Signed off</dt><dd>${s.approved_by ? `${E(s.approved_by)}, ${E(MZ.date(s.approved_at))}` : 'Not yet'} · author ${E(s.created_by)}</dd></dl>
      <h4>Bands</h4>${MZ.table({rows: s.bands, columns: [{label: 'Rating', render: b => `<span class="mz-strong">${E(b.rating)}</span>`}, {label: 'Label', key: 'label'},
        {label: 'Achievement', render: b => `${E(b.min_achievement)}% ${b.max_achievement != null ? '≤ a < ' + E(b.max_achievement) + '%' : 'and above'}`}]})}</section>`).join('')}`);
  MZ.onAct(root, {
    approve: async d => { const r = await MZ.reason({title: 'Sign off scheme', label: 'Note (optional)', required: false, submitLabel: 'Sign off', intro: 'Signing off makes this scheme usable for approved scores. It cannot be edited afterwards; changes need a new version.'}); if(!r) return;
      await MZ.api(`/api/scorecard/schemes/${d.id}/transition`, {method: 'POST', body: {name: 'approve', reason: r.reason || null}}); MZ.toast('Scheme signed off.', 'ok'); MZ.refresh('schemes'); },
    retire: async d => { const r = await MZ.reason({title: 'Retire scheme'}); if(!r) return;
      await MZ.api(`/api/scorecard/schemes/${d.id}/transition`, {method: 'POST', body: {name: 'retire', reason: r.reason}}); MZ.refresh('schemes'); },
    version: async d => { await MZ.api('/api/scorecard/schemes', {method: 'POST', body: {from_scheme_id: Number(d.id)}}); MZ.toast('New draft version created.', 'ok'); MZ.refresh('schemes'); },
    edit: async d => {
      const s = rows.find(x => String(x.id) === d.id);
      const bands = [...s.bands].sort((a, b) => b.min_achievement - a.min_achievement);
      const ok = await MZ.form({title: `Edit ${s.code} v${s.version}`, wide: true, intro: 'Five contiguous bands starting at 0 %. The top band must reach above the cap (or be open-ended).', fields: [
        {name: 'name', label: 'Name', value: s.name, required: true},
        {name: 'rating_order', label: 'Rating order', type: 'select', value: s.rating_order, options: [{value: 'higher_is_better', label: 'Higher is better (5 best)'}, {value: 'lower_is_better', label: 'Lower is better (1 best)'}]},
        {name: 'cap_pct', label: 'Cap (%)', type: 'number', step: 'any', value: s.cap_pct},
        {name: 'coverage_gate_pct', label: 'Coverage gate (%)', type: 'number', step: 'any', value: s.coverage_gate_pct},
        {name: 'lower_method', label: 'Lower-is-better formula', type: 'select', value: s.lower_method, options: [{value: 'linear_deviation', label: '(2 − actual ÷ target) × 100'}, {value: 'ratio_inverse', label: 'target ÷ actual × 100'}]},
        {name: 'zero_target_rule', label: 'Zero targets', type: 'select', value: s.zero_target_rule, options: [{value: 'unscored', label: 'Leave unscored'}, {value: 'binary', label: 'Binary (met / not met)'}]},
        {name: 'missing_policy', label: 'Missing data', type: 'select', value: s.missing_policy, options: [{value: 'coverage_gate', label: 'Coverage gate'}, {value: 'count_as_zero', label: 'Count missing as 0 % (explicit)'}]},
        {name: 'effective_from', label: 'Effective from', type: 'date', value: s.effective_from || ''},
        {name: 'description', label: 'Description', type: 'textarea', value: s.description || ''},
        ...bands.flatMap((b, i) => [
          {name: `b${i}_rating`, label: `Band ${i + 1}: rating`, type: 'number', value: b.rating},
          {name: `b${i}_label`, label: `Band ${i + 1}: label`, value: b.label},
          {name: `b${i}_min`, label: `Band ${i + 1}: from (%)`, type: 'number', step: 'any', value: b.min_achievement},
          {name: `b${i}_max`, label: `Band ${i + 1}: below (%) — blank = no limit`, type: 'number', step: 'any', value: b.max_achievement ?? ''}])],
        onSubmit: v => MZ.api(`/api/scorecard/schemes/${s.id}`, {method: 'PUT', body: {
          name: v.name, rating_order: v.rating_order, cap_pct: v.cap_pct, coverage_gate_pct: v.coverage_gate_pct, lower_method: v.lower_method,
          zero_target_rule: v.zero_target_rule, missing_policy: v.missing_policy, effective_from: v.effective_from || null, description: v.description,
          bands: bands.map((b, i) => ({rating: v[`b${i}_rating`], label: v[`b${i}_label`], min_achievement: v[`b${i}_min`], max_achievement: v[`b${i}_max`]}))}})});
      if(ok){ MZ.toast('Draft saved.', 'ok'); MZ.refresh('schemes'); }
    },
  });
});

})();
