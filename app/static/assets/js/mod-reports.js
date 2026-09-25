/* ══════════════════════════════════════════════════════════════════════════
   Reporting hub (mod-reports.js) — builds on window.MZ
   Templates → draft reports with frozen data → review → approval → publication.
   Previews are rendered by the server from the frozen data and shown in a
   sandboxed frame (no scripts); downloads are logged.
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
MZ.entityPages.report_instance = 'reports-hub';

const R = {status: '', selected: null};
const STATUS_TABS = [['', 'All'], ['draft', 'Drafts'], ['in_review', 'In review'], ['approved', 'Approved'], ['published', 'Published'], ['withdrawn', 'Withdrawn']];

MZ.page('reports-hub', async root => {
  const pending = MZ.takePending('reports-hub');
  if(pending) R.selected = pending.id;
  const [templates, rows] = await Promise.all([MZ.api('/api/reports-hub/templates'), MZ.api('/api/reports-hub/instances' + (R.status ? `?status=${R.status}` : ''))]);
  const canCreate = !MZ.me.read_only && (MZ.hasFunction('report_manager') || MZ.canAnywhere('reviewer'));
  MZ.html(root, `${MZ.header('Reporting hub', 'Board packs, scorecard reports, submission and data-quality reports, and exception reports. Each report freezes its data when drafted; approval fixes its content, and every approved output is stored with a fingerprint. Nothing is sent by e-mail: reports are downloaded, and every download is logged.',
      canCreate ? '<button class="mz-btn primary" data-mz="new">New report</button>' : '')}
    <div id="rh-tabs"></div>
    <div class="mz-split" style="margin-top:12px"><div id="rh-list">${MZ.table({rows, rowId: r => r.id, selected: R.selected, empty: 'No reports here.', columns: [
      {label: 'Report', render: r => `<span class="mz-strong">${E(r.title)}</span><div class="mz-meta">${E(r.template.name)} v${E(r.template.version)} · ${E(MZ.label(r.audience))}</div>`},
      {label: 'Period', render: r => E(r.period)},
      {label: 'Status', render: r => MZ.badge(r.status) + (r.needs_approved_score && !r.score_approved ? ' ' + MZ.badge('score_unapproved', 'warn', 'Score not approved') : '')},
      {label: 'Author', render: r => `${E(r.created_by)}<div class="mz-meta">${E(MZ.date(r.created_at))}</div>`}]})}</div>
      <section class="mz-card" id="rh-detail" aria-live="polite"><div class="mz-empty">Select a report.</div></section></div>`);
  MZ.tabs(MZ.$('rh-tabs'), STATUS_TABS.map(([k, l]) => ({key: k, label: l})), R.status, k => { R.status = k; R.selected = null; MZ.refresh('reports-hub'); });
  MZ.onRow(MZ.$('rh-list'), id => { R.selected = id; detail().catch(MZ.fail); });
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => {
    const [plans, periods] = await Promise.all([MZ.api('/api/strategy/plans'), MZ.api('/api/platform/periods')]);
    const units = MZ.unitOptions('reviewer');
    const r = await MZ.form({title: 'New report', intro: `The report’s data is captured (frozen) now. You can refresh it until you submit it for review. ${MZ.periodsIntro(periods)}`, onChange: MZ.bindPeriodsLink, fields: [
      {name: 'template_id', label: 'Template', type: 'select', required: true, options: templates.map(t => ({value: t.id, label: `${t.name} — ${t.description}`}))},
      {name: 'plan_id', label: 'Plan', type: 'select', options: [{value: '', label: '(none)'}, ...plans.map(p => ({value: p.id, label: `${p.code} ${p.title}`}))], value: (plans.find(p => p.status === 'active') || {}).id || ''},
      {name: 'period_id', label: 'Period', type: 'select', required: true, options: periods.map(p => ({value: p.id, label: p.label}))},
      {name: 'org_unit_code', label: 'Unit', type: 'select', required: true, options: MZ.hasFunction('report_manager') ? MZ.unitOptions('viewer') : units},
      {name: 'audience', label: 'Audience', type: 'select', options: ['board', 'management', 'regulator', 'internal', 'public'].map(a => ({value: a, label: MZ.label(a)})), value: 'management'},
      {name: 'title', label: 'Title (optional)', full: true}],
      onSubmit: v => MZ.api('/api/reports-hub/instances', {method: 'POST', body: {...v, template_id: Number(v.template_id), period_id: Number(v.period_id), plan_id: v.plan_id ? Number(v.plan_id) : null, title: v.title || null}})});
    if(r){ R.selected = r.id; R.status = ''; MZ.toast('Draft created and data frozen.', 'ok'); MZ.refresh('reports-hub'); }
  }});
  if(R.selected) detail().catch(() => { R.selected = null; });
});

async function detail(){
  document.querySelectorAll('#rh-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(R.selected)));
  const r = await MZ.api(`/api/reports-hub/instances/${R.selected}`);
  const host = MZ.$('rh-detail');
  const labels = {submit: 'Submit for review', return: 'Return to author', approve: 'Approve', publish: 'Publish', withdraw: 'Withdraw'};
  MZ.html(host, `<div class="mz-hdr"><h3>${E(r.title)}</h3>${MZ.badge(r.status)}</div>
    ${r.needs_approved_score && !r.score_approved ? '<div class="mz-notice warn">The score in this report is a live, unapproved calculation. Approve the score snapshot, then refresh the data, before this report can be approved.</div>' : ''}
    <dl class="mz-kv"><dt>Template</dt><dd>${E(r.template.name)} v${E(r.template.version)}</dd><dt>Period</dt><dd>${E(r.period)}</dd>
      <dt>Unit</dt><dd>${E(MZ.unitName(r.org_unit_code))}</dd><dt>Audience</dt><dd>${E(MZ.label(r.audience))}</dd>
      <dt>Data frozen</dt><dd>${E(MZ.dateTime(r.frozen_at))} · version ${E(r.data_version)} · <span class="mz-mono" title="${E(r.data_hash || '')}">${E((r.data_hash || '').slice(0, 16))}</span></dd>
      ${r.content_hash ? `<dt>Approved content</dt><dd class="mz-mono" title="${E(r.content_hash)}">${E(r.content_hash.slice(0, 16))}</dd>` : ''}
      ${r.approved_by ? `<dt>Approved</dt><dd>${E(r.approved_by)}, ${E(MZ.dateTime(r.approved_at))}</dd>` : ''}
      ${r.published_by ? `<dt>Published</dt><dd>${E(r.published_by)}, ${E(MZ.dateTime(r.published_at))}</dd>` : ''}</dl>
    <div class="mz-btn-row" style="margin:12px 0">${r.can_edit ? '<button class="mz-btn ghost" data-mz="freeze">Refresh data</button>' : ''}
      ${r.allowed.map(t => `<button class="mz-btn ${t === 'approve' || t === 'publish' ? 'primary' : t === 'withdraw' || t === 'return' ? 'danger' : ''}" data-mz="tr" data-name="${t}">${E(labels[t] || t)}</button>`).join('')}</div>
    <h4>Outputs</h4><div class="mz-btn-row"><button class="mz-btn" data-mz="dl" data-fmt="pdf">Download PDF</button><button class="mz-btn" data-mz="dl" data-fmt="xlsx">Download Excel</button><button class="mz-btn ghost" data-mz="dl" data-fmt="html">Download HTML</button></div>
    ${r.outputs.length ? `<p class="mz-meta">Stored outputs: ${r.outputs.map(o => `${E(o.format.toUpperCase())} <span class="mz-mono">${E(o.sha256.slice(0, 12))}</span>`).join(' · ')}</p>` : '<p class="mz-meta">Drafts are rendered on request and marked “not approved”; outputs are stored at approval.</p>'}
    ${r.commentary_sections.length ? `<h4>Commentary</h4><form id="rh-comm">${r.commentary_sections.map(s => `<div class="adm-field"><label class="adm-label" for="rh-c-${E(s.key)}">${E(s.title)}</label><textarea class="adm-input" id="rh-c-${E(s.key)}" data-key="${E(s.key)}" rows="4" ${r.can_edit ? '' : 'readonly'}>${E(r.commentary[s.key] || '')}</textarea></div>`).join('')}${r.can_edit ? '<button class="mz-btn" type="submit">Save commentary</button>' : ''}</form>` : ''}
    <h4>Preview</h4><div id="rh-preview" class="mz-table-wrap" style="height:520px"></div>
    <h4>Decisions</h4>${r.approvals.length ? `<ol class="mz-timeline">${r.approvals.map(s => `<li><strong>${E(MZ.label(s.step))}</strong> by ${E(s.actor)} <span class="mz-when">${E(MZ.dateTime(s.at))}</span>${s.comment ? `<div class="mz-reason">“${E(s.comment)}”</div>` : ''}</li>`).join('')}</ol>` : '<div class="mz-empty">None yet.</div>'}
    <h4>Access log</h4>${MZ.table({rows: r.access_log, empty: 'Nothing logged.', columns: [{label: 'When', render: l => E(MZ.dateTime(l.at))}, {label: 'Who', key: 'actor'}, {label: 'What', render: l => E(MZ.label(l.action))}, {label: 'Detail', render: l => `<span class="mz-meta">${E(l.detail || '')}</span>`}]})}
    <div id="rh-extras" style="margin-top:12px"></div>`);
  // The preview runs in an iframe with an empty sandbox: no scripts, no navigation, no same-origin access.
  try{
    const res = await MZ.api(`/api/reports-hub/instances/${r.id}/output/html`, {raw: true});
    const frame = document.createElement('iframe');
    frame.setAttribute('sandbox', '');
    frame.setAttribute('title', `Preview of ${r.title}`);
    frame.style.cssText = 'width:100%;height:100%;border:0;background:#fff';
    frame.srcdoc = await res.text();
    MZ.$('rh-preview').appendChild(frame);
  }catch(e){ MZ.html(MZ.$('rh-preview'), `<div class="mz-notice danger">${E(e.message)}</div>`); }
  await MZ.extras(MZ.$('rh-extras'), 'report_instance', r.id);
  MZ.$('rh-comm')?.addEventListener('submit', async e => {
    e.preventDefault();
    const commentary = Object.fromEntries([...e.target.querySelectorAll('textarea[data-key]')].map(t => [t.dataset.key, t.value]));
    try{ await MZ.api(`/api/reports-hub/instances/${r.id}/commentary`, {method: 'PUT', body: {commentary}}); MZ.toast('Commentary saved.', 'ok'); detail(); }catch(err){ MZ.fail(err); }
  });
  MZ.onAct(host, {
    freeze: async () => { await MZ.api(`/api/reports-hub/instances/${r.id}/freeze`, {method: 'POST'}); MZ.toast('Data refreshed.', 'ok'); detail(); },
    tr: async d => {
      let reason = null;
      if(d.name === 'return' || d.name === 'withdraw'){ const x = await MZ.reason({title: labels[d.name]}); if(!x) return; reason = x.reason; }
      await MZ.api(`/api/reports-hub/instances/${r.id}/transition`, {method: 'POST', body: {name: d.name, reason}});
      MZ.toast(d.name === 'approve' ? 'Approved: outputs rendered and stored.' : 'Done.', 'ok'); MZ.refreshUnread(); MZ.refresh('reports-hub');
    },
    dl: d => MZ.download(`/api/reports-hub/instances/${r.id}/output/${d.fmt}?download=true`, `report-${r.id}.${d.fmt}`),
  });
}

/* ─── My Work: reports waiting for this person's approval ───────────────── */
MZ.myWorkSections.push(data => {
  const rows = data.reports_to_approve || [];
  if(!rows.length) return '';
  return `<section class="mz-card" aria-label="Reports to approve"><h3>Reports to approve <span class="mz-badge warn">${rows.length}</span></h3>
    <div class="mz-mw-section" data-open-page="reports-hub" data-open-type="report_instance">${MZ.table({rows, rowId: r => r.id, empty: '', columns: [
      {label: 'Report', render: r => `<span class="mz-strong">${E(r.title)}</span><div class="mz-meta">${E(r.template.name)}</div>`},
      {label: 'Unit', render: r => E(MZ.unitName(r.org_unit_code))}, {label: 'Period', render: r => E(r.period)},
      {label: 'Author', render: r => E(r.created_by)}, {label: 'Status', render: r => MZ.badge(r.status)}]})}</div></section>`;
});

})();
