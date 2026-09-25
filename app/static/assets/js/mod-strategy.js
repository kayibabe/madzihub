/* ══════════════════════════════════════════════════════════════════════════
   Strategy & M&E (mod-strategy.js) — builds on window.MZ (mod-platform.js)
   · Plans & Indicators: results/delivery structure, level labels, reference sheets, targets
   · Reporting Cycles:   cycle set-up, assignment generation, open/close
   · Progress Updates:   my updates, verification and approval queues, immutable revisions, DQA
   · Evaluations:        findings, management responses and follow-up actions
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;

Object.assign(MZ.entityPages, {plan: 'strategy', plan_node: 'strategy', indicator: 'strategy',
  cycle_assignment: 'updates', evaluation: 'evaluations', management_response: 'evaluations'});

const S = {plans: [], planId: null, plan: null, tab: 'structure', indicatorId: null};
const POLARITY_LABELS = {higher: 'Higher is better', lower: 'Lower is better', range: 'Within a range',
  milestone: 'Milestone (% complete)', yes_no: 'Yes / no', kri: 'Key risk indicator'};
const RESULT_TYPES = ['pillar', 'objective', 'outcome', 'output'];
const DELIVERY_TYPES = ['programme', 'initiative', 'activity', 'milestone'];

async function loadPlans(){
  S.plans = await MZ.api('/api/strategy/plans');
  if(!S.plans.some(p => String(p.id) === String(S.planId))) S.planId = (S.plans.find(p => p.status === 'active') || S.plans[0] || {}).id || null;
  return S.plans;
}
function planSelect(id, onChange){
  return `<div class="adm-field"><label class="adm-label" for="${id}">Plan</label><select class="adm-select" id="${id}">${S.plans.map(p =>
    `<option value="${p.id}"${String(p.id) === String(S.planId) ? ' selected' : ''}>${E(p.code)} — ${E(p.title)} (${E(MZ.label(p.status))})</option>`).join('')}</select></div>`;
}
function bindPlanSelect(id, after){
  MZ.$(id)?.addEventListener('change', e => { S.planId = e.target.value; S.indicatorId = null; after(); });
}
const lvl = (type, plural) => { const l = S.plan?.levels?.[type]; return l ? (plural ? l.plural : l.label) : MZ.label(type); };
const valueText = (v, unit) => v === null || v === undefined ? '—' : `${MZ.num(v)}${unit ? (unit === '%' ? '%' : ' ' + unit) : ''}`;

/* ══════════════════════════ Plans & Indicators ══════════════════════════ */
MZ.page('strategy', async root => {
  await loadPlans();
  const pending = MZ.takePending('strategy');
  if(pending && pending.type === 'indicator'){ S.indicatorId = pending.id; S.tab = 'indicators'; }
  if(pending && pending.type === 'plan'){ S.planId = pending.id; }
  const manager = MZ.hasFunction('strategy_manager') && !MZ.me.read_only;
  if(!S.plans.length){
    MZ.html(root, `${MZ.header('Plans & indicators', 'No strategic plan yet.')}
      <div class="mz-card"><p>Start from the plan in the installation's configuration, or create a new plan.</p>
      ${manager ? '<div class="mz-btn-row"><button class="mz-btn primary" data-mz="import">Import the configured plan</button><button class="mz-btn" data-mz="new-plan">New plan</button></div>' : '<p class="mz-meta">A strategy manager sets plans up.</p>'}</div>`);
    MZ.onAct(root, {import: importPlan, 'new-plan': newPlan});
    return;
  }
  S.plan = S.planId ? await MZ.api(`/api/strategy/plans/${S.planId}`) : null;
  if(pending && pending.type === 'plan_node') S.tab = 'structure';
  const p = S.plan;
  const trBtns = (p.allowed || []).map(t => `<button class="mz-btn ${t === 'archive' ? 'danger' : ''}" data-mz="plan-tr" data-name="${t}">${E(MZ.label(t))}</button>`).join('');
  MZ.html(root, `${MZ.header('Plans & indicators', 'The results structure (what we want to achieve) and the delivery structure (the work that gets us there) are separate trees joined by links. Every indicator has a controlled reference sheet; changing its definition needs a reason and creates a new version.',
      manager ? `<button class="mz-btn" data-mz="new-plan">New plan</button>${S.plans.some(x => x.code === 'tenant-plan') ? '' : '<button class="mz-btn ghost" data-mz="import">Import configured plan</button>'}` : '')}
    <div class="mz-toolbar">${planSelect('sp-plan')}<div class="mz-btn-row">${MZ.badge(p.status)} <span class="mz-meta">Fiscal years ending ${E(p.start_fy)}–${E(p.end_fy)}${p.approved_by ? ` · activated by ${E(p.approved_by)}` : ''}</span>${trBtns}${manager ? '<button class="mz-btn ghost" data-mz="edit-plan">Edit plan</button>' : ''}</div></div>
    <div id="sp-tabs"></div><div id="sp-body"></div>`);
  bindPlanSelect('sp-plan', () => MZ.refresh('strategy'));
  MZ.onAct(root.querySelector('.mz-hdr'), {import: importPlan, 'new-plan': newPlan});
  MZ.onAct(root.querySelector('.mz-toolbar'), {
    'plan-tr': async d => {
      let reason = null;
      if(d.name !== 'activate'){ const r = await MZ.reason({title: `${MZ.label(d.name)} plan`}); if(!r) return; reason = r.reason; }
      await MZ.api(`/api/strategy/plans/${p.id}/transition`, {method: 'POST', body: {name: d.name, reason}});
      MZ.toast(`Plan ${d.name === 'activate' ? 'activated' : d.name + 'd'}.`, 'ok'); MZ.refresh('strategy');
    },
    'edit-plan': async () => {
      const ok = await MZ.form({title: `Edit ${p.code}`, fields: [
        {name: 'title', label: 'Title', value: p.title, required: true, full: true},
        {name: 'start_fy', label: 'First fiscal year (ending)', type: 'number', value: p.start_fy, required: true},
        {name: 'end_fy', label: 'Last fiscal year (ending)', type: 'number', value: p.end_fy, required: true},
        {name: 'description', label: 'Description', type: 'textarea', value: p.description || ''}],
        onSubmit: v => MZ.api(`/api/strategy/plans/${p.id}`, {method: 'PUT', body: v})});
      if(ok) MZ.refresh('strategy');
    },
  });
  const tabs = [{key: 'structure', label: 'Structure', count: p.nodes.length}, {key: 'indicators', label: 'Indicators', count: p.indicators.length},
                {key: 'levels', label: 'Level labels'}];
  const render = () => {
    MZ.tabs(MZ.$('sp-tabs'), tabs, S.tab, k => { S.tab = k; render(); });
    const body = MZ.$('sp-body');
    if(S.tab === 'structure') renderStructure(body, manager, pending);
    else if(S.tab === 'indicators') renderIndicators(body, manager);
    else renderLevels(body, manager);
  };
  render();
});

async function importPlan(){
  const r = await MZ.api('/api/strategy/plans/import-tenant', {method: 'POST'});
  MZ.toast(r.created ? `Imported ${r.indicators} indicators under ${r.pillars} pillars (draft).` : r.reason, r.created ? 'ok' : '');
  if(r.plan_id) S.planId = r.plan_id;
  MZ.refresh('strategy');
}
async function newPlan(){
  const fy = new Date().getFullYear() + 1;
  const p = await MZ.form({title: 'New strategic plan', fields: [
    {name: 'code', label: 'Code', required: true, help: 'Short identifier, e.g. SP2027.'},
    {name: 'title', label: 'Title', required: true},
    {name: 'start_fy', label: 'First fiscal year (ending)', type: 'number', value: fy, required: true},
    {name: 'end_fy', label: 'Last fiscal year (ending)', type: 'number', value: fy + 4, required: true},
    {name: 'description', label: 'Description', type: 'textarea'}],
    onSubmit: v => MZ.api('/api/strategy/plans', {method: 'POST', body: v})});
  if(p){ S.planId = p.id; MZ.refresh('strategy'); }
}

function treeHtml(nodes, types, manager){
  const kids = {};
  nodes.filter(n => types.includes(n.node_type)).forEach(n => { (kids[n.parent_id || 0] = kids[n.parent_id || 0] || []).push(n); });
  const indCount = id => S.plan.indicators.filter(i => i.node_id === id).length;
  const contrib = id => S.plan.contributes.filter(c => c.from === id).map(c => S.plan.nodes.find(n => n.id === c.to)).filter(Boolean);
  const walk = (pid, depth) => (kids[pid] || []).map(n => `
    <li style="margin-left:${depth * 18}px" class="${n.context_only ? 'mz-meta' : ''}">
      <div class="mz-hdr" style="gap:8px;padding:6px 0;border-bottom:1px solid #eef2f7">
        <div><span class="mz-badge">${E(lvl(n.node_type))}</span> <strong class="mz-mono">${E(n.code)}</strong> ${E(n.title)}
          ${n.context_only ? ' <span class="mz-meta">(context)</span>' : `${n.retired ? ' ' + MZ.badge('retired', 'danger') : ''}
          <div class="mz-meta">${E(MZ.unitName(n.org_unit_code))}${n.owner ? ' · owner ' + E(n.owner) : ''}${n.weight != null ? ' · weight ' + E(n.weight) + '%' : ''}${indCount(n.id) ? ` · ${indCount(n.id)} indicator(s)` : ''}${n.end_date ? ' · due ' + E(MZ.date(n.end_date)) : ''}</div>
          ${contrib(n.id).length ? `<div class="mz-meta">Contributes to: ${contrib(n.id).map(c => E(c.code + ' ' + c.title)).join('; ')}</div>` : ''}`}
        </div>
        ${n.context_only ? '' : `<div class="mz-btn-row">${DELIVERY_TYPES.includes(n.node_type) ? MZ.badge(n.status) : ''}
          <button class="mz-btn ghost" data-mz="node" data-id="${n.id}" aria-label="Open ${E(n.code)}">Open</button></div>`}
      </div></li>${walk(n.id, depth + 1)}`).join('');
  const html = walk(0, 0);
  return html ? `<ul style="list-style:none;margin:0;padding:0">${html}</ul>` : '<div class="mz-empty">Nothing here yet.</div>';
}
function renderStructure(body, manager, pending){
  MZ.html(body, `<div class="mz-grid-2" style="margin-top:14px">
    <section class="mz-card" aria-labelledby="sp-res"><div class="mz-hdr"><h3 id="sp-res">Results</h3>${manager ? '<button class="mz-btn" data-mz="add-node" data-structure="results">Add result item</button>' : ''}</div>${treeHtml(S.plan.nodes, RESULT_TYPES, manager)}</section>
    <section class="mz-card" aria-labelledby="sp-del"><div class="mz-hdr"><h3 id="sp-del">Delivery</h3>${manager ? '<button class="mz-btn" data-mz="add-node" data-structure="delivery">Add delivery item</button>' : ''}</div>${treeHtml(S.plan.nodes, DELIVERY_TYPES, manager)}</section>
  </div><section class="mz-card" id="sp-node" hidden></section>`);
  MZ.onAct(body, {'add-node': d => nodeForm(null, d.structure), node: d => nodeDetail(d.id, manager)});
  if(pending && pending.type === 'plan_node') nodeDetail(pending.id, manager);
}
async function nodeDetail(id, manager){
  const n = S.plan.nodes.find(x => String(x.id) === String(id));
  const host = MZ.$('sp-node');
  if(!n || !host) return;
  host.hidden = false;
  const isDelivery = DELIVERY_TYPES.includes(n.node_type);
  const mayStatus = isDelivery && !MZ.me.read_only && (manager || n.owner === MZ.me.username || MZ.can(n.org_unit_code, 'approver'));
  MZ.html(host, `<div class="mz-hdr"><h3>${E(lvl(n.node_type))} ${E(n.code)} · ${E(n.title)}</h3><div class="mz-btn-row">
      ${manager ? `<button class="mz-btn ghost" data-mz="edit" data-id="${n.id}">Edit</button>` : ''}
      ${mayStatus && !manager ? `<button class="mz-btn" data-mz="status" data-id="${n.id}">Report status</button>` : ''}
      ${manager && isDelivery ? `<button class="mz-btn" data-mz="contrib" data-id="${n.id}">Link to a result</button>` : ''}
      ${MZ.canAnywhere('contributor') ? `<button class="mz-btn ghost" data-mz="action" data-id="${n.id}">Raise action</button>` : ''}</div></div>
    <dl class="mz-kv"><dt>Unit</dt><dd>${E(MZ.unitName(n.org_unit_code))}</dd><dt>Owner</dt><dd>${E(n.owner || '—')}</dd>
      ${isDelivery ? `<dt>Status</dt><dd>${MZ.badge(n.status)}</dd><dt>Dates</dt><dd>${E(MZ.date(n.start_date))} – ${E(MZ.date(n.end_date))}</dd><dt>Budget</dt><dd>${E(MZ.num(n.budget))}</dd>` : ''}
      <dt>Weight</dt><dd>${n.weight != null ? E(n.weight) + '%' : '—'}</dd>${n.description ? `<dt>Description</dt><dd style="white-space:pre-wrap">${E(n.description)}</dd>` : ''}</dl>
    <div id="sp-node-extras" style="margin-top:12px"></div>`);
  host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  await MZ.extras(MZ.$('sp-node-extras'), 'plan_node', n.id);
  MZ.onAct(host, {
    edit: () => nodeForm(n, isDelivery ? 'delivery' : 'results'),
    status: async () => {
      const ok = await MZ.form({title: `Status of ${n.code}`, fields: [
        {name: 'status', label: 'Status', type: 'select', value: n.status, options: ['not_started', 'on_track', 'at_risk', 'off_track', 'completed', 'cancelled'].map(s => ({value: s, label: MZ.label(s)}))},
        {name: 'description', label: 'Progress note', type: 'textarea', value: n.description || ''}],
        onSubmit: v => MZ.api(`/api/strategy/nodes/${n.id}`, {method: 'PUT', body: v})});
      if(ok) MZ.refresh('strategy');
    },
    contrib: async () => {
      const results = S.plan.nodes.filter(x => RESULT_TYPES.includes(x.node_type) && !x.context_only);
      const ok = await MZ.form({title: `${n.code} contributes to…`, fields: [
        {name: 'result_node_id', label: 'Result', type: 'select', required: true, options: results.map(r => ({value: r.id, label: `${lvl(r.node_type)} ${r.code} ${r.title}`}))},
        {name: 'note', label: 'How it contributes', type: 'textarea', rows: 2}],
        onSubmit: v => MZ.api(`/api/strategy/nodes/${n.id}/contributes`, {method: 'POST', body: {result_node_id: Number(v.result_node_id), note: v.note}})});
      if(ok) MZ.refresh('strategy');
    },
    action: async () => { const a = await MZ.actionForm({unit: n.org_unit_code, sourceType: 'plan_node', sourceId: n.id, title: `${n.code}: `}); if(a) MZ.toast(`${a.ref} raised.`, 'ok'); },
  });
}
async function nodeForm(n, structure){
  const types = structure === 'delivery' ? DELIVERY_TYPES : RESULT_TYPES;
  const enabled = types.filter(t => S.plan.levels[t]?.enabled !== false);
  const parents = S.plan.nodes.filter(x => types.includes(x.node_type) && !x.context_only && (!n || x.id !== n.id));
  const fields = [
    ...(n ? [] : [{name: 'node_type', label: 'Level', type: 'select', required: true, options: enabled.map(t => ({value: t, label: lvl(t)}))},
                  {name: 'code', label: 'Code', required: true, help: 'e.g. O1.2'}]),
    {name: 'title', label: 'Title', value: n?.title || '', required: true, full: true},
    {name: 'parent_id', label: 'Sits under', type: 'select', value: n?.parent_id || '', options: [{value: '', label: '(top level)'}, ...parents.map(x => ({value: x.id, label: `${lvl(x.node_type)} ${x.code} ${x.title}`}))]},
    {name: 'org_unit_code', label: 'Responsible unit', type: 'select', value: n?.org_unit_code || 'org', options: MZ.unitOptions('viewer')},
    {name: 'owner', label: 'Owner (username)', value: n?.owner || ''},
    {name: 'weight', label: 'Weight among its siblings (%)', type: 'number', step: 'any', min: 0, max: 100, value: n?.weight ?? '', help: 'Used by the scorecard; weights at each level must add up to 100.'},
    ...(structure === 'delivery' ? [
      {name: 'status', label: 'Status', type: 'select', value: n?.status || 'not_started', options: ['not_started', 'on_track', 'at_risk', 'off_track', 'completed', 'cancelled'].map(s => ({value: s, label: MZ.label(s)}))},
      {name: 'start_date', label: 'Start', type: 'date', value: n?.start_date || ''},
      {name: 'end_date', label: 'Finish', type: 'date', value: n?.end_date || ''},
      {name: 'budget', label: 'Budget', type: 'number', step: 'any', value: n?.budget ?? ''}] : []),
    {name: 'description', label: 'Description', type: 'textarea', value: n?.description || ''},
    ...(n ? [{name: 'retired', label: 'Retired (no longer part of the plan)', type: 'checkbox', value: n.retired},
             {name: 'reason', label: 'Reason (needed to retire)', type: 'textarea', rows: 2}] : [])];
  const ok = await MZ.form({title: n ? `Edit ${n.code}` : `Add ${structure} item`, fields,
    onSubmit: v => {
      const body = {...v, parent_id: v.parent_id ? Number(v.parent_id) : null, owner: v.owner || null};
      if(n) return MZ.api(`/api/strategy/nodes/${n.id}`, {method: 'PUT', body});
      return MZ.api(`/api/strategy/plans/${S.plan.id}/nodes`, {method: 'POST', body});
    }});
  if(ok){ MZ.toast('Saved.', 'ok'); MZ.refresh('strategy'); }
}

function renderIndicators(body, manager){
  const inds = S.plan.indicators;
  MZ.html(body, `<div class="mz-hdr" style="margin-top:14px"><p class="mz-sub" style="margin:0">Select an indicator to open its reference sheet, targets and published values.</p>${manager ? '<button class="mz-btn primary" data-mz="new-ind">New indicator</button>' : ''}</div>
    <div class="mz-split" style="margin-top:10px"><div id="sp-ind-table">${MZ.table({rows: inds, rowId: i => i.id, selected: S.indicatorId, empty: 'No indicators yet.', columns: [
      {label: 'Code', render: i => `<span class="mz-mono mz-strong">${E(i.code)}</span>`},
      {label: 'Indicator', render: i => `${E(i.name)}<div class="mz-meta">${E(POLARITY_LABELS[i.polarity] || i.polarity)}${i.unit ? ' · ' + E(i.unit) : ''}</div>`},
      {label: 'Frequency', render: i => E(MZ.label(i.frequency))},
      {label: 'Collection', render: i => MZ.badge(i.collection, i.collection === 'automatic' ? 'info' : '')},
      {label: 'Version', render: i => `v${E(i.version)}`},
      {label: 'Status', render: i => MZ.badge(i.status)}]})}</div>
    <section class="mz-card" id="sp-ind-detail"><div class="mz-empty">Select an indicator.</div></section></div>`);
  MZ.onRow(MZ.$('sp-ind-table'), id => { S.indicatorId = id; indicatorDetail(manager).catch(MZ.fail); });
  MZ.onAct(body.querySelector('.mz-hdr'), {'new-ind': () => indicatorForm(null)});
  if(S.indicatorId) indicatorDetail(manager).catch(MZ.fail);
}
async function indicatorDetail(manager){
  const host = MZ.$('sp-ind-detail');
  document.querySelectorAll('#sp-ind-table tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(S.indicatorId)));
  const i = await MZ.api(`/api/strategy/indicators/${S.indicatorId}`);
  const units = i.reporting_units.filter(u => MZ.roleOn(u));
  const unit = units[0] || i.org_unit_code;
  const series = MZ.roleOn(unit) ? await MZ.api(`/api/strategy/indicators/${i.id}/series?org_unit=${encodeURIComponent(unit)}`).catch(() => ({series: []})) : {series: []};
  const node = S.plan.nodes.find(n => n.id === i.node_id);
  MZ.html(host, `<div class="mz-hdr"><h3>${E(i.code)} · ${E(i.name)}</h3><div class="mz-btn-row">${MZ.badge(i.status)} <span class="mz-badge info">v${E(i.version)}</span>
      ${manager ? '<button class="mz-btn ghost" data-mz="edit">Edit reference sheet</button><button class="mz-btn ghost" data-mz="targets">Targets</button>' : ''}</div></div>
    <h4>Reference sheet</h4>
    <dl class="mz-kv">
      <dt>Definition</dt><dd style="white-space:pre-wrap">${E(i.definition || '—')}</dd>
      <dt>Measures</dt><dd>${node ? E(`${lvl(node.node_type)} ${node.code} ${node.title}`) : '—'}</dd>
      <dt>Polarity</dt><dd>${E(POLARITY_LABELS[i.polarity] || i.polarity)}</dd><dt>Unit</dt><dd>${E(i.unit || '—')}</dd>
      <dt>Formula</dt><dd>${E(i.formula_text || '—')}</dd><dt>Aggregation</dt><dd>${E(MZ.label(i.aggregation))}</dd>
      <dt>Frequency</dt><dd>${E(MZ.label(i.frequency))}</dd><dt>Collection</dt><dd>${E(MZ.label(i.collection))} <span class="mz-meta mz-mono">${E(i.metric_code)}</span></dd>
      <dt>Source</dt><dd>${E(i.source || '—')}</dd><dt>Owner</dt><dd>${E(i.owner || '—')}</dd>
      <dt>Responsible unit</dt><dd>${E(MZ.unitName(i.org_unit_code))}</dd><dt>Reporting units</dt><dd>${i.reporting_units.map(u => E(MZ.unitName(u))).join(', ')}</dd>
      <dt>Baseline</dt><dd>${E(valueText(i.baseline_value, i.unit))}${i.baseline_date ? ' (' + E(MZ.date(i.baseline_date)) + ')' : ''}</dd>
      <dt>Target basis</dt><dd>${E(i.target_basis || '—')}</dd>
      <dt>Evidence</dt><dd>${i.evidence_required ? 'Required with every submission' : 'Optional'}</dd>
      <dt>Valid range</dt><dd>${i.valid_min != null || i.valid_max != null ? `${E(MZ.num(i.valid_min))} to ${E(MZ.num(i.valid_max))}` : '—'}</dd>
      <dt>Data-quality notes</dt><dd style="white-space:pre-wrap">${E(i.dq_notes || '—')}</dd>
    </dl>
    <h4>Targets</h4>${MZ.table({rows: i.targets, empty: 'No targets set.', columns: [
      {label: 'Period', render: t => E(t.label)}, {label: 'Unit', render: t => E(MZ.unitName(t.org_unit_code))},
      {label: 'Target', num: true, render: t => E(valueText(t.value, i.unit))},
      {label: 'Range', render: t => t.lower != null ? `${E(MZ.num(t.lower))} – ${E(MZ.num(t.upper))}` : ''}]})}
    <h4>Published values · ${E(MZ.unitName(unit))}</h4>${MZ.table({rows: (series.series || []).slice(-12).reverse(), empty: 'No approved or loaded values yet.', columns: [
      {label: 'Period', render: s => E(s.period)}, {label: 'Value', num: true, render: s => E(valueText(s.value, i.unit))},
      {label: 'Source', render: s => `<span class="mz-meta">${E(s.source || '')}</span>`}]})}
    <div id="sp-ind-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('sp-ind-extras'), 'indicator', i.id);
  MZ.onAct(host, {edit: () => indicatorForm(i), targets: () => targetsForm(i)});
}
function indicatorFields(i){
  const results = S.plan.nodes.filter(n => RESULT_TYPES.includes(n.node_type) && !n.context_only);
  return [
    ...(i ? [] : [{name: 'code', label: 'Code', required: true}]),
    {name: 'name', label: 'Name', value: i?.name || '', required: true, full: !!i},
    {name: 'definition', label: 'Definition (plain language)', type: 'textarea', value: i?.definition || ''},
    {name: 'node_id', label: 'Measures result', type: 'select', value: i?.node_id || '', options: [{value: '', label: '(none)'}, ...results.map(n => ({value: n.id, label: `${lvl(n.node_type)} ${n.code} ${n.title}`}))]},
    {name: 'polarity', label: 'Polarity', type: 'select', value: i?.polarity || 'higher', options: Object.entries(POLARITY_LABELS).map(([v, l]) => ({value: v, label: l}))},
    {name: 'unit', label: 'Unit of measure', value: i?.unit || '', placeholder: '%, m³, days …'},
    {name: 'aggregation', label: 'Aggregation over time', type: 'select', value: i?.aggregation || 'sum', options: ['sum', 'avg', 'last', 'max', 'min'].map(v => ({value: v, label: MZ.label(v)}))},
    {name: 'frequency', label: 'Reporting frequency', type: 'select', value: i?.frequency || 'quarter', options: ['month', 'quarter', 'year'].map(v => ({value: v, label: MZ.label(v)}))},
    {name: 'collection', label: 'Collection', type: 'select', value: i?.collection || 'manual', options: [{value: 'manual', label: 'Manual (submitted in cycles)'}, {value: 'automatic', label: 'Automatic (from connected systems)'}]},
    {name: 'metric_code', label: 'Catalogue measure (automatic only)', value: i?.metric_code || '', help: 'Leave blank for manual indicators; a measure is created for them.'},
    {name: 'formula_text', label: 'Formula (as written)', value: i?.formula_text || ''},
    {name: 'source', label: 'Source of data', value: i?.source || ''},
    {name: 'owner', label: 'Owner (username)', value: i?.owner || ''},
    {name: 'org_unit_code', label: 'Responsible unit', type: 'select', value: i?.org_unit_code || 'org', options: MZ.unitOptions('viewer')},
    {name: 'reporting_units', label: 'Reporting units', type: 'checkboxes', value: i?.reporting_units || [], options: MZ.unitOptions('viewer').map(o => ({value: o.value, label: o.label.trim()})), help: 'Each unit ticked reports separately in every cycle. None ticked: the responsible unit reports.'},
    {name: 'baseline_value', label: 'Baseline value', type: 'number', step: 'any', value: i?.baseline_value ?? ''},
    {name: 'baseline_date', label: 'Baseline date', type: 'date', value: i?.baseline_date || ''},
    {name: 'target_basis', label: 'Target basis', value: i?.target_basis || '', help: 'Where the targets come from (plan, budget, regulator).'},
    {name: 'valid_min', label: 'Valid minimum', type: 'number', step: 'any', value: i?.valid_min ?? ''},
    {name: 'valid_max', label: 'Valid maximum', type: 'number', step: 'any', value: i?.valid_max ?? ''},
    {name: 'evidence_required', label: 'Evidence required with each submission', type: 'checkbox', value: i?.evidence_required},
    {name: 'dq_notes', label: 'Data-quality notes', type: 'textarea', value: i?.dq_notes || ''},
    ...(i ? [{name: 'status', label: 'Status', type: 'select', value: i.status, options: [{value: 'active', label: 'Active'}, {value: 'retired', label: 'Retired'}]},
             {name: 'reason', label: 'Reason for the change', type: 'textarea', rows: 2, help: 'Required when the definition changes; a new version is created.'}] : [])];
}
async function indicatorForm(i){
  const ok = await MZ.form({title: i ? `Edit ${i.code} (v${i.version})` : 'New indicator', wide: true, fields: indicatorFields(i),
    onSubmit: v => {
      const body = {...v, node_id: v.node_id ? Number(v.node_id) : null, owner: v.owner || null, metric_code: v.metric_code || null,
                    reporting_units: v.reporting_units.length ? v.reporting_units : null};
      if(!i){ if(!body.metric_code) delete body.metric_code; return MZ.api(`/api/strategy/plans/${S.plan.id}/indicators`, {method: 'POST', body}); }
      if(!body.metric_code) delete body.metric_code;
      return MZ.api(`/api/strategy/indicators/${i.id}`, {method: 'PUT', body});
    }});
  if(ok){ S.indicatorId = ok.id; MZ.toast('Reference sheet saved.', 'ok'); MZ.refresh('strategy'); }
}
async function targetsForm(i){
  const periods = await MZ.api(`/api/platform/periods?period_type=${i.frequency === 'month' ? 'month' : i.frequency}`);
  const years = await MZ.api('/api/platform/periods?period_type=year');
  const opts = [...years.map(p => ({value: `year|${p.start_date}`, label: p.label})),
                ...(i.frequency !== 'year' ? periods.map(p => ({value: `${p.period_type}|${p.start_date}`, label: p.label})) : [])];
  const ok = await MZ.form({title: `Set a target for ${i.code}`, intro: 'Changing an agreed target needs a reason. Missing fiscal years can be added on Reporting Periods.', fields: [
    {name: 'period', label: 'Period', type: 'select', required: true, options: opts},
    {name: 'org_unit_code', label: 'Unit', type: 'select', value: i.org_unit_code, options: MZ.unitOptions('viewer').filter(o => [i.org_unit_code, ...i.reporting_units].includes(o.value))},
    {name: 'value', label: 'Target value', type: 'number', step: 'any', required: true},
    ...(i.polarity === 'range' ? [{name: 'lower', label: 'Lower bound', type: 'number', step: 'any', required: true}, {name: 'upper', label: 'Upper bound', type: 'number', step: 'any', required: true}] : []),
    {name: 'reason', label: 'Reason (when changing an existing target)', type: 'textarea', rows: 2}],
    onSubmit: v => {
      const [period_type, period_start] = v.period.split('|');
      return MZ.api(`/api/strategy/indicators/${i.id}/targets`, {method: 'PUT', body: {targets: [{period_type, period_start, value: v.value, lower: v.lower ?? null, upper: v.upper ?? null, org_unit_code: v.org_unit_code}], reason: v.reason}});
    }});
  if(ok){ MZ.toast('Target saved.', 'ok'); indicatorDetail(true); }
}
function renderLevels(body, manager){
  const types = [...RESULT_TYPES, ...DELIVERY_TYPES];
  MZ.html(body, `<section class="mz-card" style="margin-top:14px"><h3>Level labels</h3>
    <p class="mz-sub">Each plan can use its own words for its levels (e.g. "Focus area" instead of "Strategic pillar"). The underlying types stay fixed so reports and permissions stay consistent.</p>
    <form id="sp-levels"><div class="mz-table-wrap"><table class="mz-table"><thead><tr><th scope="col">Type</th><th scope="col">Label</th><th scope="col">Plural</th><th scope="col">In use</th></tr></thead><tbody>
    ${types.map(t => { const l = S.plan.levels[t] || {}; return `<tr><td>${E(MZ.label(t))} <span class="mz-meta">(${RESULT_TYPES.includes(t) ? 'results' : 'delivery'})</span></td>
      <td><input class="adm-input" name="label:${t}" aria-label="Label for ${E(t)}" value="${E(l.label || '')}" ${manager ? '' : 'disabled'}></td>
      <td><input class="adm-input" name="plural:${t}" aria-label="Plural for ${E(t)}" value="${E(l.plural || '')}" ${manager ? '' : 'disabled'}></td>
      <td><input type="checkbox" name="enabled:${t}" aria-label="${E(t)} enabled" ${l.enabled !== false ? 'checked' : ''} ${manager ? '' : 'disabled'}></td></tr>`; }).join('')}
    </tbody></table></div>${manager ? '<div class="mz-btn-row" style="margin-top:10px"><button class="mz-btn primary" type="submit">Save labels</button></div>' : ''}</form></section>`);
  MZ.$('sp-levels')?.addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target;
    const levels = types.map(t => ({node_type: t, label: f.elements[`label:${t}`].value, plural: f.elements[`plural:${t}`].value, enabled: f.elements[`enabled:${t}`].checked}));
    try{ await MZ.api(`/api/strategy/plans/${S.plan.id}/levels`, {method: 'PUT', body: levels}); MZ.toast('Labels saved.', 'ok'); MZ.refresh('strategy'); }catch(err){ MZ.fail(err); }
  });
}

/* ═══════════════════════════ Reporting Cycles ═══════════════════════════ */
const C = {cycleId: null};
MZ.page('cycles', async root => {
  await loadPlans();
  const manager = MZ.hasFunction('strategy_manager') && !MZ.me.read_only;
  if(!S.planId){ MZ.html(root, `${MZ.header('Reporting cycles', 'Set up a plan first.')}`); return; }
  const cycles = await MZ.api(`/api/strategy/plans/${S.planId}/cycles`);
  const plan = S.plans.find(p => String(p.id) === String(S.planId));
  MZ.html(root, `${MZ.header('Reporting cycles', 'A cycle asks each indicator’s reporting units for their figure, narrative, variance reason, corrective action and evidence for one period. Generate the assignments, name who submits, verifies and approves, then open the cycle.',
      manager && plan.status === 'active' ? '<button class="mz-btn primary" data-mz="new">New cycle</button>' : '')}
    <div class="mz-toolbar">${planSelect('cy-plan')}</div>
    ${plan.status !== 'active' ? '<div class="mz-notice warn">Cycles run on an active plan. Activate the plan on Plans &amp; indicators.</div>' : ''}
    <div id="cy-list">${MZ.table({rows: cycles, rowId: c => c.id, selected: C.cycleId, empty: 'No cycles yet.', columns: [
      {label: 'Cycle', render: c => `<span class="mz-strong">${E(c.name)}</span><div class="mz-meta">${E(c.period)}${c.require_verification ? ' · with verification' : ''}</div>`},
      {label: 'Due', render: c => E(MZ.date(c.due_on))},
      {label: 'Progress', render: c => { const done = c.counts.approved || 0; const pct = c.total ? Math.round(done / c.total * 100) : 0;
        return `<div class="mz-bar" role="img" aria-label="${done} of ${c.total} approved"><span style="width:${pct}%"></span></div><div class="mz-meta">${done} of ${c.total} approved · ${c.counts.submitted || 0} submitted · ${(c.counts.not_submitted || 0) + (c.counts.returned || 0)} outstanding</div>`; }},
      {label: 'Status', render: c => MZ.badge(c.status) + (c.period_status === 'locked' ? ' ' + MZ.badge('locked') : '')}]})}</div>
    <section class="mz-card" id="cy-detail" hidden></section>`);
  bindPlanSelect('cy-plan', () => { C.cycleId = null; MZ.refresh('cycles'); });
  MZ.onRow(MZ.$('cy-list'), id => { C.cycleId = id; cycleDetail(manager).catch(MZ.fail); });
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => {
    const periods = (await MZ.api('/api/platform/periods')).filter(p => p.status === 'open');
    const c = await MZ.form({title: 'New reporting cycle', fields: [
      {name: 'period_id', label: 'Period', type: 'select', required: true, options: periods.map(p => ({value: p.id, label: `${p.label} (${MZ.label(p.period_type)})`}))},
      {name: 'name', label: 'Name', help: 'Defaults to "<period> progress".'},
      {name: 'opens_on', label: 'Opens on', type: 'date'}, {name: 'due_on', label: 'Due on', type: 'date', help: 'Defaults to 15 days after the period ends.'},
      {name: 'require_verification', label: 'Verify before approval', type: 'checkbox', value: true}],
      onSubmit: v => MZ.api(`/api/strategy/plans/${S.planId}/cycles`, {method: 'POST', body: {...v, period_id: Number(v.period_id)}})});
    if(c){ C.cycleId = c.id; MZ.refresh('cycles'); }
  }});
  if(C.cycleId) cycleDetail(manager).catch(() => { C.cycleId = null; });
});
async function cycleDetail(manager){
  const host = MZ.$('cy-detail');
  const c = await MZ.api(`/api/strategy/cycles/${C.cycleId}`);
  host.hidden = false;
  MZ.html(host, `<div class="mz-hdr"><h3>${E(c.name)} · ${E(c.period)}</h3><div class="mz-btn-row">${MZ.badge(c.status)}
      ${manager && c.status !== 'closed' ? '<button class="mz-btn" data-mz="gen">Generate assignments</button>' : ''}
      ${(c.allowed || []).map(t => `<button class="mz-btn ${t === 'open' ? 'primary' : ''}" data-mz="tr" data-name="${t}">${E(MZ.label(t))} cycle</button>`).join('')}</div></div>
    ${MZ.table({rows: c.assignments, rowId: a => a.id, empty: 'No assignments yet: generate them from the plan’s indicators.', columns: [
      {label: 'Indicator', render: a => `<span class="mz-mono">${E(a.indicator.code)}</span> ${E(a.indicator.name)}`},
      {label: 'Unit', render: a => E(MZ.unitName(a.org_unit_code))},
      {label: 'Submits', render: a => E(a.contributor || 'Any contributor')},
      {label: 'Verifies', render: a => E(a.reviewer || (c.require_verification ? 'Any reviewer' : '—'))},
      {label: 'Approves', render: a => E(a.approver || 'Any approver')},
      {label: 'Latest', num: true, render: a => a.latest ? (a.latest.value_state === 'reported' ? E(MZ.num(a.latest.value)) : MZ.badge(a.latest.value_state)) : '—'},
      {label: 'Status', render: a => MZ.badge(a.status) + (a.overdue ? ' ' + MZ.badge('overdue') : '')},
      {label: '', render: a => manager ? `<button class="mz-btn ghost" data-mz="assign" data-id="${a.id}" data-unit="${E(a.org_unit_code)}">People</button>` : ''}]})}`);
  MZ.onRow(host, id => MZ.open('updates', 'cycle_assignment', id));
  MZ.onAct(host, {
    gen: async () => { const r = await MZ.api(`/api/strategy/cycles/${c.id}/generate`, {method: 'POST'}); MZ.toast(`${r.created} assignment(s) created.`, 'ok'); MZ.refresh('cycles'); },
    tr: async d => {
      let reason = null;
      if(d.name === 'reopen'){ const r = await MZ.reason({title: 'Reopen cycle'}); if(!r) return; reason = r.reason; }
      await MZ.api(`/api/strategy/cycles/${c.id}/transition`, {method: 'POST', body: {name: d.name, reason}});
      MZ.toast(`Cycle ${d.name === 'open' ? 'opened; contributors have been notified' : d.name + 'd'}.`, 'ok'); MZ.refresh('cycles');
    },
    assign: async d => {
      const a = c.assignments.find(x => String(x.id) === d.id);
      const people = await MZ.api(`/api/platform/assignable-users?unit=${encodeURIComponent(d.unit)}`);
      const opts = role => [{value: '', label: `(any ${role})`}, ...people.map(p => ({value: p.username, label: `${p.full_name || p.username} (${p.role})`}))];
      const ok = await MZ.form({title: `People for ${a.indicator.code} · ${MZ.unitName(a.org_unit_code)}`, fields: [
        {name: 'contributor', label: 'Submits', type: 'select', value: a.contributor || '', options: opts('contributor')},
        {name: 'reviewer', label: 'Verifies', type: 'select', value: a.reviewer || '', options: opts('reviewer')},
        {name: 'approver', label: 'Approves', type: 'select', value: a.approver || '', options: opts('approver')}],
        onSubmit: v => MZ.api(`/api/strategy/assignments/${a.id}`, {method: 'PUT', body: {contributor: v.contributor || null, reviewer: v.reviewer || null, approver: v.approver || null}})});
      if(ok) cycleDetail(manager);
    },
  });
}

/* ═══════════════════════════ Progress Updates ═══════════════════════════ */
const U = {queue: 'submit', selected: null};
const QUEUES = [['submit', 'To submit'], ['verify', 'To verify'], ['approve', 'To approve'], ['overdue', 'Overdue'], ['all', 'All in my scope']];
MZ.page('updates', async root => {
  const pending = MZ.takePending('updates');
  if(pending){ U.selected = pending.id; U.queue = 'all'; }
  const counts = await Promise.all(QUEUES.slice(0, 4).map(([q]) => MZ.api(`/api/strategy/assignments?queue=${q}`).then(r => r.length).catch(() => 0)));
  MZ.html(root, `${MZ.header('Progress updates', 'Submit figures with their narrative and evidence; reviewers verify, approvers approve. Each submission is kept as a numbered revision that cannot be edited. “Pending”, “not applicable” and zero are different answers.')}
    <div id="up-tabs"></div><div class="mz-split" style="margin-top:12px"><div id="up-list"></div><section class="mz-card" id="up-detail" aria-live="polite"><div class="mz-empty">Select an update.</div></section></div>`);
  const tabs = QUEUES.map(([k, l], i) => ({key: k, label: l, count: i < 4 ? counts[i] : undefined}));
  const load = async () => {
    MZ.tabs(MZ.$('up-tabs'), tabs, U.queue, k => { U.queue = k; U.selected = null; load(); });
    const rows = await MZ.api(`/api/strategy/assignments?queue=${U.queue}`);
    MZ.html(MZ.$('up-list'), MZ.table({rows, rowId: a => a.id, selected: U.selected, empty: 'Nothing in this queue.', columns: [
      {label: 'Indicator', render: a => `<span class="mz-mono">${E(a.indicator.code)}</span> ${E(a.indicator.name)}<div class="mz-meta">${E(a.cycle_name)}</div>`},
      {label: 'Unit', render: a => E(MZ.unitName(a.org_unit_code))},
      {label: 'Due', render: a => E(MZ.date(a.due_on)) + (a.overdue ? ' ' + MZ.badge('overdue') : '')},
      {label: 'Latest', num: true, render: a => a.latest ? (a.latest.value_state === 'reported' ? E(valueText(a.latest.value, a.indicator.unit)) : MZ.badge(a.latest.value_state)) : MZ.badge('not_submitted', '', 'No submission')},
      {label: 'Status', render: a => MZ.badge(a.status)}]}));
    if(U.selected) detail().catch(MZ.fail);
  };
  const detail = async () => {
    document.querySelectorAll('#up-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(U.selected)));
    const a = await MZ.api(`/api/strategy/assignments/${U.selected}`);
    const i = a.indicator;
    const latest = a.latest;
    const dqaBadge = r => MZ.badge(r.result, r.result === 'pass' ? 'ok' : r.result === 'warn' ? 'warn' : 'danger', `${MZ.label(r.check)}: ${r.result}`);
    MZ.html(MZ.$('up-detail'), `<div class="mz-hdr"><h3>${E(i.code)} · ${E(i.name)}</h3>${MZ.badge(a.status)}</div>
      <p class="mz-meta">${E(MZ.unitName(a.org_unit_code))} · ${E(a.period)} · due ${E(MZ.date(a.due_on))}${a.period_status === 'locked' ? ' · ' + MZ.badge('locked') : ''} · reference sheet v${E(i.version)}</p>
      <dl class="mz-kv"><dt>Definition</dt><dd>${E(i.definition || '—')}</dd>
        <dt>Target</dt><dd>${a.target ? E(valueText(a.target.value, i.unit)) + (a.target.lower != null ? ` (range ${E(MZ.num(a.target.lower))}–${E(MZ.num(a.target.upper))})` : '') : 'No target for this period'}</dd>
        <dt>Previous period</dt><dd>${a.previous ? `${E(valueText(a.previous.value, i.unit))} <span class="mz-meta">(${E(a.previous.period)})</span>` : '—'}</dd>
        <dt>Baseline</dt><dd>${E(valueText(i.baseline_value, i.unit))}</dd>
        <dt>Collection</dt><dd>${i.collection === 'automatic' ? `Automatic — published value ${E(valueText(a.published, i.unit))}` : 'Manual'}</dd>
        ${i.evidence_required ? '<dt>Evidence</dt><dd>Required</dd>' : ''}${i.valid_min != null || i.valid_max != null ? `<dt>Valid range</dt><dd>${E(MZ.num(i.valid_min))} to ${E(MZ.num(i.valid_max))}</dd>` : ''}</dl>
      <div class="mz-btn-row" style="margin:12px 0">${a.allowed.map(t => `<button class="mz-btn ${t === 'approve' || t === 'submit' ? 'primary' : t === 'return' || t === 'reopen' ? 'danger' : ''}" data-mz="${t === 'submit' ? 'submit' : 'tr'}" data-name="${t}">${E(t === 'submit' && latest ? 'Submit a new revision' : MZ.label(t))}</button>`).join('')}
        ${MZ.can(a.org_unit_code, 'reviewer') && latest ? '<button class="mz-btn ghost" data-mz="dqa">Record a data-quality check</button>' : ''}
        ${MZ.can(a.org_unit_code, 'contributor') ? '<button class="mz-btn ghost" data-mz="action">Raise action</button>' : ''}</div>
      <h4>Revisions</h4>
      ${a.revisions.length ? `<ol class="mz-timeline">${a.revisions.map(r => `<li><div><strong>Revision ${E(r.revision)}</strong>: ${r.value_state === 'reported' ? E(valueText(r.value, i.unit)) : MZ.badge(r.value_state)} by ${E(r.submitted_by)} <span class="mz-when">${E(MZ.dateTime(r.submitted_at))}${r.late ? ' · late' : ''}</span></div>
        ${r.forecast != null ? `<div class="mz-meta">Forecast: ${E(valueText(r.forecast, i.unit))}</div>` : ''}
        ${r.narrative ? `<div><strong>Narrative:</strong> ${E(r.narrative)}</div>` : ''}${r.variance_reason ? `<div><strong>Variance:</strong> ${E(r.variance_reason)}</div>` : ''}
        ${r.corrective_action ? `<div><strong>Corrective action:</strong> ${E(r.corrective_action)}</div>` : ''}${r.evidence_note ? `<div><strong>Evidence:</strong> ${E(r.evidence_note)}</div>` : ''}
        <div class="mz-pill-list" style="margin-top:4px">${(r.dqa || []).map(dqaBadge).join('')}</div>
        ${(r.dqa || []).filter(d => d.result !== 'pass').map(d => `<div class="mz-meta">${E(MZ.label(d.check))} (${E(d.assessed_by)}): ${E(d.reason)}</div>`).join('')}</li>`).join('')}</ol>` : '<div class="mz-empty">No submission yet.</div>'}
      <h4>Decisions</h4>${a.approvals.length ? `<ol class="mz-timeline">${a.approvals.map(s => `<li><strong>${E(MZ.label(s.step))}</strong> · ${E(MZ.label(s.decision))} by ${E(s.actor)} <span class="mz-when">${E(MZ.dateTime(s.at))}</span>${s.comment ? `<div class="mz-reason">“${E(s.comment)}”</div>` : ''}</li>`).join('')}</ol>` : '<div class="mz-empty">None yet.</div>'}
      <div id="up-extras" style="margin-top:12px"></div>`);
    await MZ.extras(MZ.$('up-extras'), 'cycle_assignment', a.id);
    MZ.onAct(MZ.$('up-detail'), {
      submit: async () => {
        const auto = i.collection === 'automatic';
        const ok = await MZ.form({title: `Submit ${i.code} for ${MZ.unitName(a.org_unit_code)}`, wide: true,
          intro: auto ? 'This indicator takes its value from connected systems; your submission adds the explanation.' : 'Leave the value blank only if it is pending or not applicable; a blank is never treated as zero.',
          fields: [
            {name: 'value_state', label: 'Answer', type: 'select', value: latest?.value_state || 'reported', options: [
              {value: 'reported', label: auto ? 'Use the published value' : 'A figure'}, {value: 'pending', label: 'Pending (figure not available yet)'}, {value: 'not_applicable', label: 'Not applicable this period'}]},
            ...(auto ? [] : [{name: 'value', label: `Value${i.unit ? ' (' + i.unit + ')' : ''}${i.polarity === 'yes_no' ? ' — 1 yes / 0 no' : ''}`, type: 'number', step: 'any', value: latest?.value ?? ''}]),
            {name: 'forecast', label: 'Forecast for the period end', type: 'number', step: 'any', value: latest?.forecast ?? ''},
            {name: 'narrative', label: 'Narrative', type: 'textarea', value: latest?.narrative || ''},
            {name: 'variance_reason', label: 'Reason for any variance from target', type: 'textarea', value: latest?.variance_reason || ''},
            {name: 'corrective_action', label: 'Corrective action', type: 'textarea', value: latest?.corrective_action || ''},
            {name: 'evidence_note', label: `Evidence${i.evidence_required ? ' (required)' : ''}`, type: 'textarea', rows: 2, value: latest?.evidence_note || '', help: 'Where the supporting evidence is. Documents can also be linked as evidence.'}],
          onSubmit: v => MZ.api(`/api/strategy/assignments/${a.id}/submit`, {method: 'POST', body: v})});
        if(ok){ MZ.toast(`Revision ${ok.submitted_revision} submitted.`, 'ok'); load(); }
      },
      tr: async d => {
        let reason = null;
        if(d.name === 'return' || d.name === 'reopen'){ const r = await MZ.reason({title: `${MZ.label(d.name)} update`, label: d.name === 'return' ? 'What needs correcting' : 'Reason for reopening an approved figure'}); if(!r) return; reason = r.reason; }
        await MZ.api(`/api/strategy/assignments/${a.id}/transition`, {method: 'POST', body: {name: d.name, reason}});
        MZ.toast(d.name === 'approve' ? 'Approved and published.' : 'Done.', 'ok'); load();
      },
      dqa: async () => {
        const ok = await MZ.form({title: 'Data-quality assessment', intro: 'Recorded against the latest revision. It never changes the submitted value.', fields: [
          {name: 'check', label: 'Check', type: 'select', value: 'reviewer', options: ['validity', 'range', 'completeness', 'timeliness', 'consistency', 'evidence', 'reviewer'].map(v => ({value: v, label: MZ.label(v)}))},
          {name: 'result', label: 'Result', type: 'select', options: ['pass', 'warn', 'fail'].map(v => ({value: v, label: MZ.label(v)}))},
          {name: 'reason', label: 'Reason', type: 'textarea', required: true}],
          onSubmit: v => MZ.api(`/api/strategy/assignments/${a.id}/dqa`, {method: 'POST', body: v})});
        if(ok) detail();
      },
      action: async () => { const x = await MZ.actionForm({unit: a.org_unit_code, sourceType: 'cycle_assignment', sourceId: a.id, title: `${i.code} ${a.period}: `}); if(x) MZ.toast(`${x.ref} raised.`, 'ok'); },
    });
  };
  MZ.onRow(MZ.$('up-list'), id => { U.selected = id; detail().catch(MZ.fail); });
  await load();
});

/* ═══════════════════════════════ Evaluations ═══════════════════════════ */
const EV = {selected: null};
MZ.page('evaluations', async root => {
  await loadPlans();
  const pending = MZ.takePending('evaluations');
  if(pending && pending.type === 'evaluation') EV.selected = pending.id;
  const manager = MZ.hasFunction('strategy_manager') && !MZ.me.read_only;
  const rows = await MZ.api('/api/strategy/evaluations');
  MZ.html(root, `${MZ.header('Evaluations', 'Mid-term, end-term and thematic evaluations with their method, findings and limitations. Every finding gets a management response; accepted recommendations become owned, dated actions.',
      manager && S.planId ? '<button class="mz-btn primary" data-mz="new">New evaluation</button>' : '')}
    <div class="mz-split"><div id="ev-list">${MZ.table({rows, rowId: e => e.id, selected: EV.selected, empty: 'No evaluations yet.', columns: [
      {label: 'Evaluation', render: e => `<span class="mz-strong">${E(e.title)}</span><div class="mz-meta">${E(MZ.label(e.kind))} · ${E(MZ.unitName(e.org_unit_code))}</div>`},
      {label: 'Lead', render: e => E(e.lead || '—')},
      {label: 'Findings', num: true, render: e => `${e.responses.filter(r => r.response).length}/${e.responses.length}`},
      {label: 'Status', render: e => MZ.badge(e.status)}]})}</div><section class="mz-card" id="ev-detail"><div class="mz-empty">Select an evaluation.</div></section></div>`);
  MZ.onRow(MZ.$('ev-list'), id => { EV.selected = id; evDetail().catch(MZ.fail); });
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => {
    const e = await MZ.form({title: 'New evaluation', wide: true, fields: [
      {name: 'title', label: 'Title', required: true, full: true},
      {name: 'kind', label: 'Kind', type: 'select', options: ['mid_term', 'end_term', 'thematic', 'other'].map(v => ({value: v, label: MZ.label(v)}))},
      {name: 'org_unit_code', label: 'Unit evaluated', type: 'select', options: MZ.unitOptions('viewer')},
      {name: 'lead', label: 'Lead (username)'}, {name: 'start_date', label: 'Start', type: 'date'}, {name: 'end_date', label: 'End', type: 'date'},
      {name: 'scope', label: 'Scope', type: 'textarea'}, {name: 'method', label: 'Method', type: 'textarea'},
      {name: 'criteria', label: 'Criteria (optional; OECD DAC shown as a template)', type: 'checkboxes', options: ['relevance', 'coherence', 'effectiveness', 'efficiency', 'impact', 'sustainability'].map(v => ({value: v, label: MZ.label(v)}))}],
      onSubmit: v => MZ.api(`/api/strategy/plans/${S.planId}/evaluations`, {method: 'POST', body: {...v, lead: v.lead || null}})});
    if(e){ EV.selected = e.id; MZ.refresh('evaluations'); }
  }});
  if(EV.selected) evDetail().catch(() => { EV.selected = null; });
});
async function evDetail(){
  const e = await MZ.api(`/api/strategy/evaluations/${EV.selected}`);
  document.querySelectorAll('#ev-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(e.id)));
  const host = MZ.$('ev-detail');
  MZ.html(host, `<div class="mz-hdr"><h3>${E(e.title)}</h3><div class="mz-btn-row">${MZ.badge(e.status)}${e.allowed.map(t => `<button class="mz-btn" data-mz="tr" data-name="${t}">${E(MZ.label(t))}</button>`).join('')}${e.can_edit ? '<button class="mz-btn ghost" data-mz="edit">Edit</button>' : ''}</div></div>
    <dl class="mz-kv"><dt>Kind</dt><dd>${E(MZ.label(e.kind))}</dd><dt>Unit</dt><dd>${E(MZ.unitName(e.org_unit_code))}</dd><dt>Lead</dt><dd>${E(e.lead || '—')}</dd>
      <dt>Dates</dt><dd>${E(MZ.date(e.start_date))} – ${E(MZ.date(e.end_date))}</dd><dt>Criteria</dt><dd>${e.criteria.length ? e.criteria.map(c => E(MZ.label(c))).join(', ') : '—'}</dd>
      <dt>Scope</dt><dd style="white-space:pre-wrap">${E(e.scope || '—')}</dd><dt>Method</dt><dd style="white-space:pre-wrap">${E(e.method || '—')}</dd>
      <dt>Findings summary</dt><dd style="white-space:pre-wrap">${E(e.findings_summary || '—')}</dd><dt>Limitations</dt><dd style="white-space:pre-wrap">${E(e.limitations || '—')}</dd></dl>
    <div class="mz-hdr" style="margin-top:14px"><h4 style="margin:0">Findings and management responses</h4>${e.can_edit ? '<button class="mz-btn" data-mz="finding">Add finding</button>' : ''}</div>
    ${MZ.table({rows: e.responses, empty: 'No findings recorded.', columns: [
      {label: 'Finding', render: r => `${E(r.finding)}${r.recommendation ? `<div class="mz-meta">Recommendation: ${E(r.recommendation)}</div>` : ''}`},
      {label: 'Response', render: r => r.response ? `${MZ.badge(r.response)}<div class="mz-meta">${E(r.response_text)}</div><div class="mz-meta">by ${E(r.responded_by)}</div>` : (e.can_respond ? `<button class="mz-btn" data-mz="respond" data-id="${r.id}">Respond</button>` : MZ.badge('pending', '', 'Awaiting response'))},
      {label: 'Action', render: r => r.action_id ? `<button class="mz-link" data-mz="open-action" data-id="${r.action_id}">Open action</button><div class="mz-meta">${E(r.owner || '')}${r.due_date ? ' · due ' + E(MZ.date(r.due_date)) : ''}</div>` : '—'}]})}
    <div id="ev-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('ev-extras'), 'evaluation', e.id);
  MZ.onAct(host, {
    tr: async d => { let reason = null; if(d.name === 'reopen'){ const r = await MZ.reason({title: 'Reopen evaluation'}); if(!r) return; reason = r.reason; }
      await MZ.api(`/api/strategy/evaluations/${e.id}/transition`, {method: 'POST', body: {name: d.name, reason}}); MZ.refresh('evaluations'); },
    edit: async () => { const ok = await MZ.form({title: `Edit ${e.title}`, wide: true, fields: [
        {name: 'title', label: 'Title', value: e.title, required: true, full: true}, {name: 'lead', label: 'Lead (username)', value: e.lead || ''},
        {name: 'start_date', label: 'Start', type: 'date', value: e.start_date || ''}, {name: 'end_date', label: 'End', type: 'date', value: e.end_date || ''},
        {name: 'scope', label: 'Scope', type: 'textarea', value: e.scope || ''}, {name: 'method', label: 'Method', type: 'textarea', value: e.method || ''},
        {name: 'findings_summary', label: 'Findings summary', type: 'textarea', value: e.findings_summary || ''}, {name: 'limitations', label: 'Limitations', type: 'textarea', value: e.limitations || ''}],
        onSubmit: v => MZ.api(`/api/strategy/evaluations/${e.id}`, {method: 'PUT', body: {...v, lead: v.lead || null}})});
      if(ok) evDetail(); },
    finding: async () => { const ok = await MZ.form({title: 'Add finding', fields: [{name: 'finding', label: 'Finding', type: 'textarea', required: true}, {name: 'recommendation', label: 'Recommendation', type: 'textarea'}],
        onSubmit: v => MZ.api(`/api/strategy/evaluations/${e.id}/findings`, {method: 'POST', body: v})}); if(ok) evDetail(); },
    respond: async d => {
      const people = await MZ.api(`/api/platform/assignable-users?unit=${encodeURIComponent(e.org_unit_code)}`).catch(() => []);
      const ok = await MZ.form({title: 'Management response', intro: 'Accepted and partially accepted recommendations create an action for the owner.', fields: [
        {name: 'response', label: 'Response', type: 'select', options: [{value: 'accepted', label: 'Accepted'}, {value: 'partially_accepted', label: 'Partially accepted'}, {value: 'rejected', label: 'Rejected'}]},
        {name: 'response_text', label: 'Explanation', type: 'textarea', required: true},
        {name: 'owner', label: 'Action owner', type: 'select', options: [{value: '', label: '(none — rejected)'}, ...people.map(p => ({value: p.username, label: p.full_name || p.username}))]},
        {name: 'due_date', label: 'Action due', type: 'date'}],
        onSubmit: v => MZ.api(`/api/strategy/responses/${d.id}`, {method: 'POST', body: {...v, owner: v.owner || null}})});
      if(ok){ MZ.toast('Response recorded.', 'ok'); evDetail(); }
    },
    'open-action': d => MZ.open('actions', 'action', d.id),
  });
}

/* ─── My Work sections ───────────────────────────────────────────────────── */
MZ.myWorkSections.push(data => {
  const block = (key, title, empty) => {
    const rows = data[key] || [];
    if(!rows.length) return '';
    return `<section class="mz-card" aria-label="${E(title)}"><h3>${E(title)} <span class="mz-badge warn">${rows.length}</span></h3>
      <div class="mz-mw-section" data-open-page="updates" data-open-type="cycle_assignment">${MZ.table({rows, rowId: a => a.id, empty, columns: [
        {label: 'Indicator', render: a => `<span class="mz-mono">${E(a.indicator.code)}</span> ${E(a.indicator.name)}`},
        {label: 'Unit', render: a => E(MZ.unitName(a.org_unit_code))}, {label: 'Period', render: a => E(a.period)},
        {label: 'Due', render: a => E(MZ.date(a.due_on)) + (a.overdue ? ' ' + MZ.badge('overdue') : '')}, {label: 'Status', render: a => MZ.badge(a.status)}]})}</div></section>`;
  };
  return block('updates_to_submit', 'Progress updates to submit', '') + block('updates_to_verify', 'Updates to verify', '') + block('updates_to_approve', 'Updates to approve', '');
});

})();
