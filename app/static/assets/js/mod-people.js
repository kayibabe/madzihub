/* ══════════════════════════════════════════════════════════════════════════
   People (mod-people.js) — performance contracts and staff appraisal
   Off until an HR officer records the approved HR policy. Private: each record is visible only to
   the people named on it and HR officers (never implied by the administrator role).
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
Object.assign(MZ.entityPages, {staff_appraisal: 'people', performance_contract: 'people'});
const P = {tab: 'appraisals', sel: null};
const A_LABEL = {agree: 'Agree objectives', self_assess: 'Self-assess', appraise: 'Appraise', acknowledge: 'Acknowledge', appeal: 'Appeal', decide: 'Decide appeal', correct: 'Correct (HR)'};
const C_LABEL = {sign: 'Sign', countersign: 'Countersign', evaluate: 'Evaluate', accept: 'Accept evaluation', appeal: 'Appeal', decide: 'Decide appeal'};

MZ.page('people', async root => {
  const pending = MZ.takePending('people');
  if(pending){ P.sel = pending.id; P.tab = pending.type === 'performance_contract' ? 'contracts' : 'appraisals'; }
  const g = await MZ.api('/api/people/gate');
  const gateRow = (key, label) => `<li><strong>${E(label)}:</strong> ${g[key].enabled ? `${MZ.badge('active')} under policy “${E(g[key].policy_ref)}” (recorded by ${E(g[key].confirmed_by)})` : g[key].switched_off_in_config ? MZ.badge('off', 'danger', 'Switched off in configuration') : MZ.badge('pending', 'warn', 'Waiting for the approved HR policy')}</li>`;
  MZ.html(root, `${MZ.header('People: contracts and appraisals', `Private HR records. Each is visible only to the people named on it and to HR officers. Ratings run ${E(g.rating_scale)}; appeals are decided by an HR officer who is not party to the record, and every correction is kept.`,
      g.is_hr_officer ? '<button class="mz-btn ghost" data-mz="policy">Record HR policy</button>' : '')}
    <div class="mz-notice"><ul style="margin:0">${gateRow('staff_appraisal', 'Staff appraisal')}${gateRow('performance_contracts', 'Performance contracts')}</ul></div>
    <div id="pp-tabs"></div><div id="pp-body" style="margin-top:12px"></div>`);
  MZ.onAct(root.querySelector('.mz-hdr'), {policy: async () => {
    const ok = await MZ.form({title: 'Record the approved HR policy', intro: 'Only record a policy the organisation has formally approved. The module becomes usable under it.', fields: [
      {name: 'module', label: 'Module', type: 'select', options: [{value: 'staff_appraisal', label: 'Staff appraisal'}, {value: 'performance_contracts', label: 'Performance contracts'}]},
      {name: 'policy_ref', label: 'Policy reference (document, clause, approval)', required: true, full: true}, {name: 'summary', label: 'Summary', type: 'textarea'}],
      onSubmit: v => MZ.api('/api/people/gate', {method: 'POST', body: v})});
    if(ok) MZ.refresh('people');
  }});
  const render = () => {
    MZ.tabs(MZ.$('pp-tabs'), [{key: 'appraisals', label: 'Appraisals'}, {key: 'contracts', label: 'Performance contracts'}], P.tab, k => { P.tab = k; P.sel = null; render(); });
    const key = P.tab === 'appraisals' ? 'staff_appraisal' : 'performance_contracts';
    if(!g[key].enabled){ MZ.html(MZ.$('pp-body'), '<div class="mz-empty">This module is not in use yet.</div>'); return; }
    (P.tab === 'appraisals' ? appraisals : contracts)(MZ.$('pp-body'), g).catch(e => MZ.html(MZ.$('pp-body'), `<div class="mz-notice danger">${E(e.message)}</div>`));
  };
  render();
});

async function appraisals(body, g){
  const rows = await MZ.api('/api/people/appraisals');
  MZ.html(body, `${g.is_hr_officer || MZ.canAnywhere('reviewer') ? '<div class="mz-btn-row" style="margin-bottom:10px"><button class="mz-btn primary" data-mz="new">New appraisal</button></div>' : ''}
    <div class="mz-split"><div id="pp-list">${MZ.table({rows, rowId: a => a.id, selected: P.sel, empty: 'No appraisals involving you.', columns: [
      {label: 'Appraisal', render: a => `<span class="mz-strong">${E(a.employee)}</span> <span class="mz-meta">appraised by ${E(a.appraiser)}</span><div class="mz-meta">${E(a.period_label)}</div>`},
      {label: 'Overall', num: true, render: a => E(MZ.num(a.overall_rating))}, {label: 'Status', render: a => MZ.badge(a.status)}]})}</div>
    <section class="mz-card" id="pp-detail"><div class="mz-empty">Select an appraisal.</div></section></div>`);
  MZ.onAct(body.querySelector('.mz-btn-row') || body, {new: async () => {
    const ok = await MZ.form({title: 'New appraisal', wide: true, fields: [{name: 'employee', label: 'Employee (username)', required: true}, {name: 'appraiser', label: 'Appraiser (username)', required: true, value: MZ.me.username},
      {name: 'period_label', label: 'Period', required: true, placeholder: 'FY2026/27'},
      {name: 'objectives', label: 'Objectives (one per line: weight | title | measure)', type: 'textarea', rows: 6, required: true, help: 'Weights must add up to 100.'}],
      onSubmit: v => MZ.api('/api/people/appraisals', {method: 'POST', body: {...v, objectives: v.objectives.split('\n').map(s => s.trim()).filter(Boolean).map(s => { const [w, t, m] = s.split('|').map(x => (x || '').trim()); return {weight: Number(w), title: t, measure: m}; })}})});
    if(ok){ P.sel = ok.id; appraisals(body, g); }
  }});
  MZ.onRow(MZ.$('pp-list'), id => { P.sel = id; appraisal().catch(MZ.fail); });
  if(P.sel) appraisal().catch(() => { P.sel = null; });
}

async function appraisal(){
  const a = await MZ.api(`/api/people/appraisals/${P.sel}`);
  const host = MZ.$('pp-detail');
  const r = (x, i) => x && x.ratings ? E(x.ratings[String(i)] ?? '—') : '—';
  MZ.html(host, `<div class="mz-hdr"><h3>${E(a.employee)} · ${E(a.period_label)}</h3>${MZ.badge(a.status)}</div>
    <p class="mz-meta">Appraiser ${E(a.appraiser)} · scale ${E(a.rating_scale)}</p>
    ${MZ.table({rows: a.objectives.map((o, i) => ({...o, i})), columns: [{label: 'Objective', render: o => `${E(o.title)}${o.measure ? `<div class="mz-meta">${E(o.measure)}</div>` : ''}`},
      {label: 'Weight', num: true, render: o => E(o.weight) + '%'}, {label: 'Self', num: true, render: o => r(a.self_assessment, o.i)}, {label: 'Appraiser', num: true, render: o => r(a.appraiser_assessment, o.i)}]})}
    <dl class="mz-kv" style="margin-top:10px"><dt>Overall</dt><dd>${E(MZ.num(a.overall_rating))}</dd>
      ${a.self_assessment && a.self_assessment.comment ? `<dt>Employee</dt><dd>${E(a.self_assessment.comment)}</dd>` : ''}${a.appraiser_assessment && a.appraiser_assessment.comment ? `<dt>Appraiser</dt><dd>${E(a.appraiser_assessment.comment)}</dd>` : ''}
      ${a.appeal_reason ? `<dt>Appeal</dt><dd>${E(a.appeal_reason)}</dd>` : ''}${a.appeal_decision ? `<dt>Decision</dt><dd>${E(a.appeal_decision)}</dd>` : ''}</dl>
    <div class="mz-btn-row" style="margin:12px 0">${a.allowed.map(t => `<button class="mz-btn ${t === 'appeal' || t === 'correct' ? 'danger' : 'primary'}" data-mz="tr" data-name="${t}">${E(A_LABEL[t])}</button>`).join('')}</div>
    <h4>History (kept in full)</h4>${MZ.historyHtml(a.history)}`);
  MZ.onAct(host, {tr: async d => {
    let body = {name: d.name};
    if(d.name === 'self_assess' || d.name === 'appraise'){
      const f = await MZ.form({title: A_LABEL[d.name], fields: [...a.objectives.map((o, i) => ({name: `r${i}`, label: `${o.title} (1–5)`, type: 'number', min: 1, max: 5, step: '0.5', required: true})),
        {name: 'comment', label: 'Comment', type: 'textarea'}], onSubmit: v => v});
      if(!f) return; body.ratings = Object.fromEntries(a.objectives.map((o, i) => [String(i), f[`r${i}`]])); body.comment = f.comment;
    }else if(['appeal', 'decide', 'correct'].includes(d.name)){
      const f = await MZ.form({title: A_LABEL[d.name], fields: [{name: 'reason', label: 'Reason', type: 'textarea', required: true},
        ...(d.name !== 'appeal' ? [{name: 'overall', label: 'Overall rating (leave blank to keep)', type: 'number', min: 1, max: 5, step: '0.1'}] : [])], onSubmit: v => v});
      if(!f) return; body.reason = f.reason; if(f.overall != null) body.overall = f.overall;
    }else if(d.name === 'acknowledge'){
      const f = await MZ.form({title: 'Acknowledge appraisal', fields: [{name: 'comment', label: 'Your comment (optional)', type: 'textarea'}], onSubmit: v => v}); if(!f) return; body.comment = f.comment;
    }
    await MZ.api(`/api/people/appraisals/${a.id}/transition`, {method: 'POST', body}); appraisal();
  }});
}

async function contracts(body, g){
  const rows = await MZ.api('/api/people/contracts');
  MZ.html(body, `${g.is_hr_officer ? '<div class="mz-btn-row" style="margin-bottom:10px"><button class="mz-btn primary" data-mz="new">New contract</button></div>' : ''}
    <div class="mz-split"><div id="pp-list">${MZ.table({rows, rowId: c => c.id, selected: P.sel, empty: 'No contracts involving you.', columns: [
      {label: 'Contract', render: c => `<span class="mz-strong">${E(c.holder)}</span> <span class="mz-meta">supervisor ${E(c.supervisor)}</span><div class="mz-meta">${E(MZ.unitName(c.org_unit_code))} · ${E(c.period)}</div>`},
      {label: 'Rating', num: true, render: c => E(MZ.num(c.final_rating))}, {label: 'Status', render: c => MZ.badge(c.status)}]})}</div>
    <section class="mz-card" id="pp-detail"><div class="mz-empty">Select a contract.</div></section></div>`);
  MZ.onAct(body.querySelector('.mz-btn-row') || body, {new: async () => {
    const [plans, periods] = await Promise.all([MZ.api('/api/strategy/plans'), MZ.api('/api/platform/periods?period_type=year')]);
    const plan = plans.find(p => p.status === 'active') || plans[0];
    if(!plan){ MZ.toast('Set up a plan first.', 'danger'); return; }
    const detail = await MZ.api(`/api/strategy/plans/${plan.id}`);
    const ok = await MZ.form({title: 'New performance contract', wide: true, intro: `Plan ${E(plan.code)}. List indicators and weights (adding up to 100).`, fields: [
      {name: 'period_id', label: 'Year', type: 'select', options: periods.map(p => ({value: p.id, label: p.label}))},
      {name: 'org_unit_code', label: 'Unit', type: 'select', options: MZ.unitOptions('viewer')},
      {name: 'holder', label: 'Holder (username)', required: true}, {name: 'supervisor', label: 'Supervisor (username)', required: true},
      {name: 'items', label: `Items (one per line: weight | indicator code). Codes: ${detail.indicators.map(i => i.code).join(', ')}`, type: 'textarea', rows: 5, required: true}],
      onSubmit: v => MZ.api('/api/people/contracts', {method: 'POST', body: {plan_id: plan.id, period_id: Number(v.period_id), org_unit_code: v.org_unit_code, holder: v.holder, supervisor: v.supervisor,
        items: v.items.split('\n').map(s => s.trim()).filter(Boolean).map(s => { const [w, code] = s.split('|').map(x => x.trim()); const ind = detail.indicators.find(i => i.code === code); if(!ind) throw new Error(`Unknown indicator code ${code}.`); return {indicator_id: ind.id, weight: Number(w)}; })}})});
    if(ok){ P.sel = ok.id; contracts(body, g); }
  }});
  MZ.onRow(MZ.$('pp-list'), id => { P.sel = id; contract().catch(MZ.fail); });
  if(P.sel) contract().catch(() => { P.sel = null; });
}

async function contract(){
  const c = await MZ.api(`/api/people/contracts/${P.sel}`);
  const host = MZ.$('pp-detail');
  const ev = c.evaluation;
  MZ.html(host, `<div class="mz-hdr"><h3>${E(c.holder)} · ${E(c.period)}</h3>${MZ.badge(c.status)}</div>
    <p class="mz-meta">${E(MZ.unitName(c.org_unit_code))} · supervisor ${E(c.supervisor)}</p>
    ${ev ? MZ.table({rows: ev.items, caption: `Evaluated on ${ev.scheme} (engine ${ev.engine_version}): ${MZ.num(ev.rating)} ${ev.rating_label || ''} — ${ev.method}`, columns: [
        {label: 'Indicator', key: 'indicator'}, {label: 'Weight', num: true, render: i => E(i.weight) + '%'}, {label: 'Actual', num: true, render: i => E(MZ.num(i.actual))},
        {label: 'Target', num: true, render: i => E(MZ.num(i.target))}, {label: 'Achievement', num: true, render: i => i.achievement == null ? '—' : E(MZ.num(i.achievement, 1)) + '%'},
        {label: 'Rating', render: i => E(i.rating_label || i.note || '—')}]})
      : MZ.table({rows: c.items, columns: [{label: 'Indicator', key: 'indicator'}, {label: 'Weight', num: true, render: i => E(i.weight) + '%'}]})}
    <dl class="mz-kv" style="margin-top:10px"><dt>Final rating</dt><dd>${E(MZ.num(c.final_rating))} ${E(c.final_label || '')}</dd>
      ${c.appeal_reason ? `<dt>Appeal</dt><dd>${E(c.appeal_reason)}</dd>` : ''}${c.appeal_decision ? `<dt>Decision</dt><dd>${E(c.appeal_decision)}</dd>` : ''}</dl>
    <div class="mz-btn-row" style="margin:12px 0">${c.allowed.map(t => `<button class="mz-btn ${t === 'appeal' ? 'danger' : 'primary'}" data-mz="tr" data-name="${t}">${E(C_LABEL[t])}</button>`).join('')}</div>`);
  MZ.onAct(host, {tr: async d => {
    const body = {name: d.name};
    if(d.name === 'appeal' || d.name === 'decide'){
      const f = await MZ.form({title: C_LABEL[d.name], fields: [{name: 'reason', label: 'Reason', type: 'textarea', required: true},
        ...(d.name === 'decide' ? [{name: 'adjusted_rating', label: 'Adjusted rating (blank = unchanged)', type: 'number', step: '0.1'}] : [])], onSubmit: v => v});
      if(!f) return; body.reason = f.reason; if(f.adjusted_rating != null) body.adjusted_rating = f.adjusted_rating;
    }
    await MZ.api(`/api/people/contracts/${c.id}/transition`, {method: 'POST', body}); contract();
  }});
}

})();
