/* ══════════════════════════════════════════════════════════════════════════
   Governance & Risk (mod-governance.js) — builds on window.MZ
   · Meetings & Resolutions (board secretary)
   · Audit Findings (auditor and management roles kept apart)
   · Risk Register (organisation-defined criteria, any matrix size, heat map, controls, treatments)
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
Object.assign(MZ.entityPages, {meeting: 'meetings', resolution: 'meetings', audit_finding: 'audit-findings', risk: 'risks'});

/* ═══════════════════════════ Meetings & resolutions ════════════════════ */
const MT = {selected: null};
MZ.page('meetings', async root => {
  const pending = MZ.takePending('meetings');
  if(pending && pending.type === 'meeting') MT.selected = pending.id;
  const rows = await MZ.api('/api/governance/meetings');
  if(pending && pending.type === 'resolution') MT.selected = (rows.find(m => m.resolutions.some(r => String(r.id) === pending.id)) || {}).id || null;
  const sec = MZ.hasFunction('board_secretary') && !MZ.me.read_only;
  MZ.html(root, `${MZ.header('Meetings & resolutions', 'Board and committee meetings, their minutes and resolutions. A resolution with an owner becomes an owned, dated action; the owner reports implementation and the board secretary closes it.',
      sec ? '<button class="mz-btn primary" data-mz="new">New meeting</button>' : '')}
    <div class="mz-split"><div id="mt-list">${MZ.table({rows, rowId: m => m.id, selected: MT.selected, empty: 'No meetings recorded.', columns: [
      {label: 'Meeting', render: m => `<span class="mz-strong">${E(m.body)}</span> ${E(m.title)}`}, {label: 'Date', render: m => E(MZ.date(m.meeting_date))},
      {label: 'Resolutions', num: true, render: m => `${m.resolutions.filter(r => r.status === 'closed').length}/${m.resolutions.length} closed`},
      {label: 'Status', render: m => MZ.badge(m.status)}]})}</div><section class="mz-card" id="mt-detail"><div class="mz-empty">Select a meeting.</div></section></div>`);
  MZ.onRow(MZ.$('mt-list'), id => { MT.selected = id; detail().catch(MZ.fail); });
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => {
    const m = await MZ.form({title: 'New meeting', fields: [{name: 'body', label: 'Body', required: true, placeholder: 'Board, Audit Committee …'},
      {name: 'title', label: 'Title', required: true}, {name: 'meeting_date', label: 'Date', type: 'date', required: true, value: MZ.today()},
      {name: 'org_unit_code', label: 'Unit', type: 'select', options: MZ.unitOptions('viewer')}],
      onSubmit: v => MZ.api('/api/governance/meetings', {method: 'POST', body: v})});
    if(m){ MT.selected = m.id; MZ.refresh('meetings'); }
  }});
  if(MT.selected) detail().catch(() => { MT.selected = null; });
});
async function detail(){
  const m = await MZ.api(`/api/governance/meetings/${MT.selected}`);
  document.querySelectorAll('#mt-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(m.id)));
  const host = MZ.$('mt-detail');
  const RL = {implement: 'Report implemented', close: 'Close', reopen: 'Reopen', cancel: 'Cancel'};
  MZ.html(host, `<div class="mz-hdr"><h3>${E(m.body)} · ${E(m.title)}</h3><div class="mz-btn-row">${MZ.badge(m.status)}${m.allowed.map(t => `<button class="mz-btn" data-mz="mtr" data-name="${t}">${E(t === 'hold' ? 'Mark as held' : 'Approve minutes')}</button>`).join('')}
      ${m.can_add_resolution ? '<button class="mz-btn primary" data-mz="res">Record resolution</button>' : ''}</div></div>
    <p class="mz-meta">${E(MZ.date(m.meeting_date))} · ${E(MZ.unitName(m.org_unit_code))} · secretary ${E(m.secretary || '—')}${m.minutes_document_id ? ` · <button class="mz-link" data-mz="doc" data-id="${m.minutes_document_id}">Minutes</button>` : ''}</p>
    <h4>Resolutions</h4>${MZ.table({rows: m.resolutions, empty: 'No resolutions.', columns: [
      {label: 'Number', render: r => `<span class="mz-mono mz-strong">${E(r.number)}</span>`},
      {label: 'Resolution', render: r => `${E(r.text)}${r.implementation_note ? `<div class="mz-meta">Implementation: ${E(r.implementation_note)}</div>` : ''}`},
      {label: 'Owner / due', render: r => `${E(r.owner || '—')}<div class="mz-meta">${E(MZ.date(r.due_date))}</div>${r.action_id ? `<button class="mz-link" data-mz="act" data-id="${r.action_id}">Action</button>` : ''}`},
      {label: 'Status', render: r => MZ.badge(r.status)},
      {label: '', render: r => `<div class="mz-btn-row">${r.allowed.map(t => `<button class="mz-btn ${t === 'close' ? 'primary' : t === 'cancel' ? 'danger' : 'ghost'}" data-mz="rtr" data-id="${r.id}" data-name="${t}">${E(RL[t])}</button>`).join('')}</div>`}]})}
    <div id="mt-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('mt-extras'), 'meeting', m.id);
  MZ.onAct(host, {
    mtr: async d => {
      let doc = null;
      if(d.name === 'approve_minutes'){
        const docs = (await MZ.api('/api/documents')).filter(x => x.type.code === 'minutes' || x.type.code === 'report');
        const r = await MZ.form({title: 'Approve minutes', intro: 'Choose the minutes document (upload it on Documents first, type “Minutes”).', fields: [
          {name: 'doc', label: 'Minutes document', type: 'select', required: true, options: docs.map(x => ({value: x.id, label: x.title}))}], onSubmit: v => v});
        if(!r) return; doc = Number(r.doc);
      }
      await MZ.api(`/api/governance/meetings/${m.id}/transition`, {method: 'POST', body: {name: d.name, minutes_document_id: doc}}); detail();
    },
    res: async () => {
      const ok = await MZ.form({title: 'Record resolution', fields: [{name: 'text', label: 'Resolution', type: 'textarea', required: true},
        {name: 'number', label: 'Number (blank = next in sequence)'}, {name: 'org_unit_code', label: 'Unit responsible', type: 'select', options: MZ.unitOptions('viewer'), value: m.org_unit_code},
        {name: 'owner', label: 'Owner (username; creates an action)'}, {name: 'due_date', label: 'Due', type: 'date'}],
        onSubmit: v => MZ.api(`/api/governance/meetings/${m.id}/resolutions`, {method: 'POST', body: {...v, owner: v.owner || null, number: v.number || null}})});
      if(ok) detail();
    },
    rtr: async d => {
      let reason = null;
      if(d.name !== 'close'){ const r = await MZ.reason({title: RL[d.name], label: d.name === 'implement' ? 'What was done' : 'Reason'}); if(!r) return; reason = r.reason; }
      await MZ.api(`/api/governance/resolutions/${d.id}/transition`, {method: 'POST', body: {name: d.name, reason}}); detail();
    },
    act: d => MZ.open('actions', 'action', d.id), doc: d => MZ.open('documents', 'document', d.id),
  });
}

/* ═══════════════════════════════ Audit findings ════════════════════════ */
const AF = {selected: null};
const AF_LABEL = {respond: 'Submit management response', accept: 'Accept response', reject_response: 'Reject response', request_closure: 'Request closure',
  validate: 'Validate and close', reject_closure: 'Reject closure', reopen: 'Reopen'};
MZ.page('audit-findings', async root => {
  const pending = MZ.takePending('audit-findings');
  if(pending) AF.selected = pending.id;
  const data = await MZ.api('/api/governance/findings');
  MZ.html(root, `${MZ.header('Audit findings', 'Findings from internal and external audit and regulators. Auditors raise, rate and validate; management responds, agrees a date and asks for closure. Neither can do the other’s part, and an auditor cannot close a finding while its follow-up actions are open.',
      data.can_raise ? '<button class="mz-btn primary" data-mz="new">Raise finding</button>' : '')}
    <div class="mz-split"><div id="af-list">${MZ.table({rows: data.findings, rowId: f => f.id, selected: AF.selected, empty: 'No findings.', columns: [
      {label: 'Finding', render: f => `<span class="mz-mono mz-strong">${E(f.ref)}</span> ${E(f.title)}<div class="mz-meta">${E(f.audit_name)} · ${E(MZ.unitName(f.org_unit_code))}</div>`},
      {label: 'Rating', render: f => MZ.badge(f.rating)}, {label: 'Owner', key: 'owner'},
      {label: 'Due', render: f => E(MZ.date(f.agreed_due_date)) + (f.overdue ? ' ' + MZ.badge('overdue') : '')},
      {label: 'Status', render: f => MZ.badge(f.status)}]})}</div><section class="mz-card" id="af-detail"><div class="mz-empty">Select a finding.</div></section></div>`);
  MZ.onRow(MZ.$('af-list'), id => { AF.selected = id; afDetail().catch(MZ.fail); });
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => {
    const f = await MZ.form({title: 'Raise audit finding', wide: true, fields: [
      {name: 'audit_name', label: 'Audit', required: true}, {name: 'source', label: 'Source', type: 'select', options: data.sources.map(s => ({value: s, label: MZ.label(s)}))},
      {name: 'title', label: 'Finding', required: true, full: true}, {name: 'rating', label: 'Rating', type: 'select', options: data.ratings.map(r => ({value: r, label: MZ.label(r)}))},
      {name: 'org_unit_code', label: 'Unit', type: 'select', options: MZ.unitOptions('viewer')},
      {name: 'owner', label: 'Management owner (username)', required: true},
      {name: 'description', label: 'Condition and criteria', type: 'textarea'}, {name: 'recommendation', label: 'Recommendation', type: 'textarea'}],
      onSubmit: v => MZ.api('/api/governance/findings', {method: 'POST', body: v})});
    if(f){ AF.selected = f.id; MZ.refresh('audit-findings'); }
  }});
  if(AF.selected) afDetail().catch(() => { AF.selected = null; });
});
async function afDetail(){
  const f = await MZ.api(`/api/governance/findings/${AF.selected}`);
  document.querySelectorAll('#af-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(f.id)));
  const host = MZ.$('af-detail');
  MZ.html(host, `<div class="mz-hdr"><h3>${E(f.ref)} · ${E(f.title)}</h3><div class="mz-btn-row">${MZ.badge(f.rating)} ${MZ.badge(f.status)}</div></div>
    <dl class="mz-kv"><dt>Audit</dt><dd>${E(f.audit_name)} (${E(MZ.label(f.source))})</dd><dt>Unit</dt><dd>${E(MZ.unitName(f.org_unit_code))}</dd>
      <dt>Auditor</dt><dd>${E(f.auditor)}</dd><dt>Management owner</dt><dd>${E(f.owner)}</dd>
      <dt>Condition</dt><dd style="white-space:pre-wrap">${E(f.description || '—')}</dd><dt>Recommendation</dt><dd style="white-space:pre-wrap">${E(f.recommendation || '—')}</dd>
      <dt>Management response</dt><dd style="white-space:pre-wrap">${E(f.management_response || 'Not yet submitted')}${f.responded_by ? ` <span class="mz-meta">(${E(f.responded_by)})</span>` : ''}</dd>
      <dt>Agreed date</dt><dd>${E(MZ.date(f.agreed_due_date))}</dd>${f.closure_note ? `<dt>Closure note</dt><dd>${E(f.closure_note)}</dd>` : ''}${f.validated_by ? `<dt>Validated by</dt><dd>${E(f.validated_by)}</dd>` : ''}</dl>
    <div class="mz-btn-row" style="margin:12px 0">${f.allowed.map(t => `<button class="mz-btn ${['accept', 'validate'].includes(t) ? 'primary' : t.startsWith('reject') ? 'danger' : ''}" data-mz="tr" data-name="${t}">${E(AF_LABEL[t])}</button>`).join('')}
      ${f.can_edit ? '<button class="mz-btn ghost" data-mz="edit">Edit (auditor)</button>' : ''}</div>
    <h4>Follow-up actions</h4>${MZ.table({rows: f.actions, rowId: a => a.id, empty: 'None yet: accepting the management response creates one.', columns: [
      {label: 'Action', render: a => `${E(a.ref)} ${E(a.title)}`}, {label: 'Due', render: a => E(MZ.date(a.due_date))}, {label: 'Status', render: a => MZ.badge(a.status)}]})}
    <h4>Decisions</h4>${f.decisions.length ? `<ol class="mz-timeline">${f.decisions.map(s => `<li><strong>${E(MZ.label(s.step))}</strong> by ${E(s.actor)} <span class="mz-when">${E(MZ.dateTime(s.at))}</span>${s.comment ? `<div class="mz-reason">“${E(s.comment)}”</div>` : ''}</li>`).join('')}</ol>` : '<div class="mz-empty">None yet.</div>'}
    <div id="af-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('af-extras'), 'audit_finding', f.id);
  MZ.onRow(host.querySelectorAll('.mz-table-wrap')[0], id => MZ.open('actions', 'action', id));
  MZ.onAct(host, {
    tr: async d => {
      let body = {name: d.name};
      if(d.name === 'respond'){
        const r = await MZ.form({title: 'Management response', fields: [{name: 'response', label: 'Response and planned action', type: 'textarea', required: true},
          {name: 'agreed_due_date', label: 'To be implemented by', type: 'date', required: true}], onSubmit: v => v});
        if(!r) return; body = {...body, ...r};
      }else if(['reject_response', 'reject_closure', 'reopen', 'request_closure'].includes(d.name)){
        const r = await MZ.reason({title: AF_LABEL[d.name], label: d.name === 'request_closure' ? 'What was done, and where is the evidence' : 'Reason'});
        if(!r) return; body.reason = r.reason;
      }
      await MZ.api(`/api/governance/findings/${f.id}/transition`, {method: 'POST', body}); MZ.toast('Done.', 'ok'); MZ.refresh('audit-findings');
    },
    edit: async () => {
      const ok = await MZ.form({title: `Edit ${f.ref}`, wide: true, fields: [{name: 'title', label: 'Finding', value: f.title, required: true, full: true},
        {name: 'rating', label: 'Rating', type: 'select', value: f.rating, options: ['critical', 'high', 'medium', 'low'].map(r => ({value: r, label: MZ.label(r)}))},
        {name: 'owner', label: 'Management owner', value: f.owner}, {name: 'description', label: 'Condition and criteria', type: 'textarea', value: f.description || ''},
        {name: 'recommendation', label: 'Recommendation', type: 'textarea', value: f.recommendation || ''}],
        onSubmit: v => MZ.api(`/api/governance/findings/${f.id}`, {method: 'PUT', body: v})});
      if(ok) afDetail();
    },
  });
}

/* ═══════════════════════════════ Risk register ═════════════════════════ */
const RK = {selected: null, kind: 'residual', tab: 'register'};
const APPETITE_TONE = {within: 'ok', tolerance: 'warn', outside: 'danger'};
const bandBadge = b => b ? `<span class="mz-badge ${APPETITE_TONE[b.appetite] || ''}">${E(b.score)} · ${E(b.label)}</span>` : '<span class="mz-meta">not rated</span>';

MZ.page('risks', async root => {
  const pending = MZ.takePending('risks');
  if(pending){ RK.selected = pending.id; RK.tab = 'register'; }
  MZ.html(root, `${MZ.header('Risk register', 'Risks rated on the organisation’s own criteria (likelihood × impact scales of any size, score bands and appetite). Ratings keep their history; controls, treatments (actions) and the objectives each risk affects are recorded with it.')}
    <div id="rk-tabs"></div><div id="rk-body" style="margin-top:12px"></div>`);
  const render = () => {
    MZ.tabs(MZ.$('rk-tabs'), [{key: 'register', label: 'Register'}, {key: 'heatmap', label: 'Heat map'}, {key: 'criteria', label: 'Risk criteria'}], RK.tab, k => { RK.tab = k; render(); });
    ({register: renderRegister, heatmap: renderHeat, criteria: renderCriteria})[RK.tab](MZ.$('rk-body')).catch(MZ.fail);
  };
  render();
});

async function renderRegister(body){
  const data = await MZ.api('/api/governance/risks');
  const canAdd = MZ.canAnywhere('contributor') && data.matrix;
  MZ.html(body, `${!data.matrix ? '<div class="mz-notice warn">No risk criteria are active. A risk manager sets them up on the Risk criteria tab.</div>' : ''}
    <div class="mz-btn-row" style="margin-bottom:10px">${canAdd ? '<button class="mz-btn primary" data-mz="new">Add risk</button>' : ''}</div>
    <div class="mz-split"><div id="rk-list">${MZ.table({rows: data.risks, rowId: r => r.id, selected: RK.selected, empty: 'No open risks.', columns: [
      {label: 'Risk', render: r => `<span class="mz-mono mz-strong">${E(r.code)}</span> ${E(r.title)}<div class="mz-meta">${E(r.category || '')} · ${E(MZ.unitName(r.org_unit_code))} · ${E(r.owner)}</div>`},
      {label: 'Inherent', render: r => bandBadge(r.inherent)}, {label: 'Residual', render: r => bandBadge(r.residual) + (r.residual_above_inherent ? ' ' + MZ.badge('check', 'warn', 'Above inherent') : '')},
      {label: 'Review', render: r => E(MZ.date(r.review_date)) + (r.review_overdue ? ' ' + MZ.badge('overdue') : '')}]})}</div>
    <section class="mz-card" id="rk-detail"><div class="mz-empty">Select a risk.</div></section></div>`);
  MZ.onRow(MZ.$('rk-list'), id => { RK.selected = id; riskDetail().catch(MZ.fail); });
  MZ.onAct(body.querySelector('.mz-btn-row'), {new: async () => {
    const m = data.matrix;
    const lv = [{value: '', label: '(not rated)'}, ...m.likelihood_levels.map(x => ({value: x.value, label: `${x.value} · ${x.label}`}))];
    const iv = [{value: '', label: '(not rated)'}, ...m.impact_levels.map(x => ({value: x.value, label: `${x.value} · ${x.label}`}))];
    const r = await MZ.form({title: 'Add risk', wide: true, fields: [{name: 'title', label: 'Risk', required: true, full: true},
      {name: 'org_unit_code', label: 'Unit', type: 'select', options: MZ.unitOptions('contributor')}, {name: 'category', label: 'Category'},
      {name: 'owner', label: 'Owner (username, default you)'}, {name: 'review_date', label: 'Next review', type: 'date'},
      {name: 'cause', label: 'Cause', type: 'textarea', rows: 2}, {name: 'consequence', label: 'Consequence', type: 'textarea', rows: 2},
      {name: 'inherent_l', label: 'Inherent likelihood', type: 'select', options: lv}, {name: 'inherent_i', label: 'Inherent impact', type: 'select', options: iv},
      {name: 'residual_l', label: 'Residual likelihood', type: 'select', options: lv}, {name: 'residual_i', label: 'Residual impact', type: 'select', options: iv}],
      onSubmit: v => { const b = {...v, owner: v.owner || null}; for(const k of ['inherent_l', 'inherent_i', 'residual_l', 'residual_i']) b[k] = v[k] ? Number(v[k]) : null; return MZ.api('/api/governance/risks', {method: 'POST', body: b}); }});
    if(r){ RK.selected = r.id; renderRegister(body); }
  }});
  if(RK.selected) riskDetail().catch(() => { RK.selected = null; });
}

async function riskDetail(){
  const r = await MZ.api(`/api/governance/risks/${RK.selected}`);
  document.querySelectorAll('#rk-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(r.id)));
  const host = MZ.$('rk-detail');
  const m = r.matrix;
  MZ.html(host, `<div class="mz-hdr"><h3>${E(r.code)} · ${E(r.title)}</h3>${MZ.badge(r.status)}</div>
    <dl class="mz-kv"><dt>Owner</dt><dd>${E(r.owner)}</dd><dt>Unit</dt><dd>${E(MZ.unitName(r.org_unit_code))}</dd><dt>Category</dt><dd>${E(r.category || '—')}</dd>
      <dt>Cause</dt><dd>${E(r.cause || '—')}</dd><dt>Consequence</dt><dd>${E(r.consequence || '—')}</dd>
      <dt>Inherent</dt><dd>${bandBadge(r.inherent)}${r.inherent ? ` <span class="mz-meta">L${E(r.inherent_l)} × I${E(r.inherent_i)}</span>` : ''}</dd>
      <dt>Residual</dt><dd>${bandBadge(r.residual)}${r.residual ? ` <span class="mz-meta">L${E(r.residual_l)} × I${E(r.residual_i)}; appetite: ${E(MZ.label(r.residual.appetite))}</span>` : ''}</dd>
      <dt>Next review</dt><dd>${E(MZ.date(r.review_date))}${r.review_overdue ? ' ' + MZ.badge('overdue') : ''}</dd></dl>
    <div class="mz-btn-row" style="margin:12px 0">${r.can_edit ? '<button class="mz-btn primary" data-mz="assess">Re-rate</button><button class="mz-btn" data-mz="control">Add control</button><button class="mz-btn" data-mz="treat">Add treatment</button><button class="mz-btn ghost" data-mz="link">Link an objective</button><button class="mz-btn ghost" data-mz="edit">Edit</button>' : ''}
      ${r.can_close ? `<button class="mz-btn ${r.status === 'open' ? 'danger' : ''}" data-mz="tr" data-name="${r.status === 'open' ? 'close' : 'reopen'}">${r.status === 'open' ? 'Close risk' : 'Reopen'}</button>` : ''}</div>
    <h4>Controls</h4>${MZ.table({rows: r.controls, empty: 'No controls recorded.', columns: [{label: 'Control', render: c => `${E(c.description)}<div class="mz-meta">${E(MZ.label(c.control_type))}${c.owner ? ' · ' + E(c.owner) : ''}</div>`},
      {label: 'Effectiveness', render: c => MZ.badge(c.effectiveness, {effective: 'ok', partly: 'warn', ineffective: 'danger'}[c.effectiveness] || '')}, {label: 'Last tested', render: c => E(MZ.date(c.last_tested))}]})}
    <h4>Treatments</h4>${MZ.table({rows: r.treatments, empty: 'No treatment actions.', columns: [{label: 'Action', render: a => `${E(a.ref)} ${E(a.title)}`}, {label: 'Owner', key: 'owner'}, {label: 'Due', render: a => E(MZ.date(a.due_date))}, {label: 'Status', render: a => MZ.badge(a.status)}]})}
    <h4>Rating history</h4>${MZ.table({rows: r.assessments, empty: 'Not rated yet.', columns: [{label: 'When', render: a => E(MZ.dateTime(a.assessed_at))}, {label: 'Kind', render: a => E(MZ.label(a.kind))},
      {label: 'L × I', render: a => `${E(a.likelihood)} × ${E(a.impact)} = ${E(a.score)} ${E(a.band || '')}`}, {label: 'By', key: 'assessed_by'}, {label: 'Note', render: a => E(a.note || '')}]})}
    <div id="rk-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('rk-extras'), 'risk', r.id);
  const lv = m.likelihood_levels.map(x => ({value: x.value, label: `${x.value} · ${x.label}`}));
  const iv = m.impact_levels.map(x => ({value: x.value, label: `${x.value} · ${x.label}`}));
  MZ.onAct(host, {
    assess: async () => { const ok = await MZ.form({title: `Re-rate ${r.code}`, fields: [{name: 'kind', label: 'Rating', type: 'select', options: [{value: 'residual', label: 'Residual (after controls)'}, {value: 'inherent', label: 'Inherent (before controls)'}]},
        {name: 'likelihood', label: 'Likelihood', type: 'select', options: lv}, {name: 'impact', label: 'Impact', type: 'select', options: iv}, {name: 'note', label: 'Why the rating changed', type: 'textarea', required: true}],
        onSubmit: v => MZ.api(`/api/governance/risks/${r.id}/assess`, {method: 'POST', body: {...v, likelihood: Number(v.likelihood), impact: Number(v.impact)}})}); if(ok) riskDetail(); },
    control: async () => { const ok = await MZ.form({title: 'Add control', fields: [{name: 'description', label: 'Control', type: 'textarea', required: true},
        {name: 'control_type', label: 'Type', type: 'select', options: ['preventive', 'detective', 'corrective'].map(x => ({value: x, label: MZ.label(x)}))},
        {name: 'effectiveness', label: 'Effectiveness', type: 'select', options: ['not_tested', 'effective', 'partly', 'ineffective'].map(x => ({value: x, label: MZ.label(x)}))},
        {name: 'owner', label: 'Owner (username)'}, {name: 'last_tested', label: 'Last tested', type: 'date'}],
        onSubmit: v => MZ.api(`/api/governance/risks/${r.id}/controls`, {method: 'POST', body: {...v, owner: v.owner || null, last_tested: v.last_tested || null}})}); if(ok) riskDetail(); },
    treat: async () => { const a = await MZ.actionForm({unit: r.org_unit_code, sourceType: 'risk', sourceId: r.id, title: `Treat ${r.code}: `}); if(a) riskDetail(); },
    link: async () => {
      const plans = await MZ.api('/api/strategy/plans');
      const active = plans.find(p => p.status === 'active');
      if(!active){ MZ.toast('No active plan to link to.', 'danger'); return; }
      const plan = await MZ.api(`/api/strategy/plans/${active.id}`);
      const ok = await MZ.form({title: 'Objective affected by this risk', fields: [{name: 'node', label: 'Plan item', type: 'select', required: true,
        options: plan.nodes.filter(n => !n.context_only && ['pillar', 'objective', 'outcome'].includes(n.node_type)).map(n => ({value: n.id, label: `${n.code} ${n.title}`}))}],
        onSubmit: v => MZ.api('/api/platform/links', {method: 'POST', body: {from_type: 'risk', from_id: String(r.id), to_type: 'plan_node', to_id: String(v.node), relation: 'affects'}})});
      if(ok){ MZ.toast('Linked.', 'ok'); riskDetail(); }
    },
    edit: async () => { const ok = await MZ.form({title: `Edit ${r.code}`, fields: [{name: 'title', label: 'Risk', value: r.title, required: true, full: true}, {name: 'category', label: 'Category', value: r.category || ''},
        {name: 'owner', label: 'Owner', value: r.owner}, {name: 'review_date', label: 'Next review', type: 'date', value: r.review_date || ''},
        {name: 'cause', label: 'Cause', type: 'textarea', value: r.cause || ''}, {name: 'consequence', label: 'Consequence', type: 'textarea', value: r.consequence || ''}],
        onSubmit: v => MZ.api(`/api/governance/risks/${r.id}`, {method: 'PUT', body: {...v, review_date: v.review_date || null}})}); if(ok) riskDetail(); },
    tr: async d => { const x = await MZ.reason({title: d.name === 'close' ? 'Close risk' : 'Reopen risk'}); if(!x) return;
      await MZ.api(`/api/governance/risks/${r.id}/transition`, {method: 'POST', body: {name: d.name, reason: x.reason}}); renderRegister(MZ.$('rk-body')); },
  });
}

async function renderHeat(body){
  const h = await MZ.api(`/api/governance/risk-heatmap?kind=${RK.kind}`);
  if(!h.matrix){ MZ.html(body, '<div class="mz-notice warn">No risk criteria are active yet.</div>'); return; }
  const m = h.matrix;
  const cell = (l, i) => h.cells.find(c => c.likelihood === l && c.impact === i);
  const bandOf = s => m.bands.find(b => b.min <= s && s <= b.max) || {};
  const fill = {within: '#DCFCE7', tolerance: '#FEF3C7', outside: '#FEE2E2'};
  const rows = [...m.likelihood_levels].reverse();
  MZ.html(body, `<div class="mz-toolbar"><div class="adm-field"><label class="adm-label" for="rk-kind">Rating</label><select class="adm-select" id="rk-kind"><option value="residual"${RK.kind === 'residual' ? ' selected' : ''}>Residual</option><option value="inherent"${RK.kind === 'inherent' ? ' selected' : ''}>Inherent</option></select></div></div>
    <section class="mz-card"><h3>${E(m.name)}: open risks by ${E(RK.kind)} rating</h3><div class="mz-table-wrap"><table class="mz-table" style="table-layout:fixed">
      <caption>Rows: likelihood (highest first). Columns: impact. Each cell shows its score band and the risks in it.</caption>
      <thead><tr><th scope="col">Likelihood \\ Impact</th>${m.impact_levels.map(x => `<th scope="col">${E(x.value)} · ${E(x.label)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(l => `<tr><th scope="row">${E(l.value)} · ${E(l.label)}</th>${m.impact_levels.map(i => { const s = l.value * i.value; const b = bandOf(s); const c = cell(l.value, i.value);
        return `<td style="background:${fill[b.appetite] || '#fff'}"><div class="mz-meta">${E(s)} · ${E(b.label || '')}</div>${c ? `<strong>${E(c.count)}</strong> <span class="mz-meta">${E(c.risks.join(', '))}</span>` : ''}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="mz-pill-list" style="margin-top:10px">${m.bands.map(b => `<span class="mz-badge ${APPETITE_TONE[b.appetite]}">${E(b.min)}–${E(b.max)} ${E(b.label)} (${E(MZ.label(b.appetite))} appetite)</span>`).join('')}</div></section>`);
  MZ.$('rk-kind').addEventListener('change', e => { RK.kind = e.target.value; renderHeat(body); });
}

async function renderCriteria(body){
  const data = await MZ.api('/api/governance/risk-matrices');
  MZ.html(body, `<div class="mz-notice">Each organisation sets its own scales and bands; MadziHub assumes no particular grid size or appetite and makes no ISO certification claim. A matrix with rated risks cannot be changed: create a new one and activate it.</div>
    ${data.can_manage ? '<div class="mz-btn-row" style="margin:10px 0"><button class="mz-btn primary" data-mz="new">New matrix</button></div>' : ''}
    ${data.matrices.map(m => `<section class="mz-card"><div class="mz-hdr"><h3>${E(m.name)} <span class="mz-meta">${m.likelihood_levels.length} × ${m.impact_levels.length}</span></h3><div class="mz-btn-row">${m.active ? MZ.badge('active') : ''}${data.can_manage && !m.active ? `<button class="mz-btn" data-mz="activate" data-id="${m.id}">Activate</button>` : ''}</div></div>
      <div class="mz-grid-2"><div><h4>Likelihood</h4><ol>${m.likelihood_levels.map(x => `<li>${E(x.label)}</li>`).join('')}</ol></div><div><h4>Impact</h4><ol>${m.impact_levels.map(x => `<li>${E(x.label)}</li>`).join('')}</ol></div></div>
      <h4>Bands</h4><div class="mz-pill-list">${m.bands.map(b => `<span class="mz-badge ${APPETITE_TONE[b.appetite]}">${E(b.min)}–${E(b.max)} ${E(b.label)} · ${E(MZ.label(b.appetite))}</span>`).join('')}</div></section>`).join('') || '<div class="mz-empty">No matrices yet.</div>'}`);
  MZ.onAct(body, {
    activate: async d => { await MZ.api(`/api/governance/risk-matrices/${d.id}/activate`, {method: 'POST'}); MZ.toast('Matrix active.', 'ok'); renderCriteria(body); },
    new: async () => {
      const size = await MZ.form({title: 'New risk matrix', intro: 'Choose the scale sizes; you then name every level and set the bands.', fields: [
        {name: 'l', label: 'Likelihood levels', type: 'number', min: 2, max: 10, value: 5, required: true}, {name: 'i', label: 'Impact levels', type: 'number', min: 2, max: 10, value: 5, required: true}], onSubmit: v => v});
      if(!size) return;
      const t = await MZ.api(`/api/governance/risk-matrices/template?likelihood=${size.l}&impact=${size.i}`);
      const ok = await MZ.form({title: 'Define the matrix', wide: true, fields: [
        {name: 'name', label: 'Name', value: t.name.replace(' (edit before use)', ''), required: true, full: true},
        ...t.likelihood_levels.map(x => ({name: `l${x.value}`, label: `Likelihood ${x.value}`, value: '', required: true, placeholder: 'e.g. Rare / Possible / Almost certain'})),
        ...t.impact_levels.map(x => ({name: `i${x.value}`, label: `Impact ${x.value}`, value: '', required: true, placeholder: 'e.g. Minor / Major'})),
        {name: 'bands', label: 'Bands (one per line: min-max label appetite)', type: 'textarea', rows: 5, required: true, value: t.bands.map(b => `${b.min}-${b.max} ${b.label} ${b.appetite}`).join('\n'),
         help: `Scores run from 1 to ${size.l * size.i}. Appetite is within, tolerance or outside.`}],
        onSubmit: v => {
          const bands = v.bands.split('\n').map(s => s.trim()).filter(Boolean).map(s => { const m = s.match(/^(\d+)\s*-\s*(\d+)\s+(.+)\s+(within|tolerance|outside)$/i); if(!m) throw new Error(`Cannot read band “${s}”.`); return {min: Number(m[1]), max: Number(m[2]), label: m[3].trim(), appetite: m[4].toLowerCase()}; });
          return MZ.api('/api/governance/risk-matrices', {method: 'POST', body: {name: v.name,
            likelihood_levels: t.likelihood_levels.map(x => ({value: x.value, label: v[`l${x.value}`]})), impact_levels: t.impact_levels.map(x => ({value: x.value, label: v[`i${x.value}`]})), bands}});
        }});
      if(ok){ MZ.toast('Matrix saved; activate it to use it.', 'ok'); renderCriteria(body); }
    },
  });
}

})();
