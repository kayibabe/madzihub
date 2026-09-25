/* ══════════════════════════════════════════════════════════════════════════
   Documents (mod-documents.js) — builds on window.MZ
   · Master list of controlled documents (number, revision, status, effective and review dates)
   · All documents the user may see, and full-text search (scope- and classification-limited)
   · Detail: versions with fingerprints, upload, approve / make effective / withdraw, revise
   · MZ.attachEvidence(type, id): used by every record's "Linked records" panel
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
MZ.entityPages.document = 'documents';

const D = {tab: 'master', selected: null, q: '', types: null};
const size = n => n > 1048576 ? `${MZ.num(n / 1048576, 1)} MB` : n > 1024 ? `${MZ.num(n / 1024, 0)} KB` : `${n} B`;
const TR_LABEL = {approve: 'Approve', make_effective: 'Make effective', withdraw: 'Withdraw'};

async function types(){ D.types = D.types || await MZ.api('/api/documents/types'); return D.types; }

MZ.attachEvidence = async function(entityType, entityId, unitLabel){
  const ok = await MZ.form({title: 'Attach evidence', intro: `The file is stored once with its fingerprint and linked to this record at this exact version${unitLabel ? ` (${E(unitLabel)})` : ''}. Replacing it later adds a new version; the earlier one stays in the history.`,
    fields: [{name: 'file', label: 'File (PDF, Word, Excel, CSV, text or image)', type: 'file', required: true, accept: '.pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg'},
             {name: 'title', label: 'Title (optional)'}, {name: 'note', label: 'Note', type: 'textarea', rows: 2}],
    onSubmit: v => { const f = new FormData(); f.append('entity_type', entityType); f.append('entity_id', String(entityId)); f.append('file', v.file);
      if(v.title) f.append('title', v.title); if(v.note) f.append('note', v.note); return MZ.api('/api/documents/evidence', {method: 'POST', form: f}); }});
  if(ok) MZ.toast('Evidence attached.', 'ok');
  return ok;
};

MZ.page('documents', async root => {
  const pending = MZ.takePending('documents');
  if(pending){ D.selected = pending.id; D.tab = 'all'; }
  const ts = await types();
  const canCreate = !MZ.me.read_only && (MZ.hasFunction('document_controller') || MZ.canAnywhere('contributor'));
  MZ.html(root, `${MZ.header('Documents', 'Controlled documents (policies, procedures, plans, forms) with numbers, revisions, approval and review dates, and the evidence attached to records. Files are kept outside the web root, never overwritten, and checked against their fingerprint on every download.',
      canCreate ? '<button class="mz-btn primary" data-mz="new">New document</button>' : '')}
    <div id="dc-tabs"></div><div id="dc-body" style="margin-top:12px"></div>`);
  MZ.onAct(root.querySelector('.mz-hdr'), {new: () => newDoc(ts)});
  const render = () => {
    MZ.tabs(MZ.$('dc-tabs'), [{key: 'master', label: 'Master list'}, {key: 'all', label: 'All documents'}, {key: 'search', label: 'Search'}], D.tab, k => { D.tab = k; render(); });
    list().catch(MZ.fail);
  };
  render();
});

async function list(){
  const body = MZ.$('dc-body');
  let rows = [];
  if(D.tab === 'search'){
    MZ.html(body, `<form class="mz-toolbar" id="dc-sform" role="search"><div class="adm-field" style="min-width:320px"><label class="adm-label" for="dc-q">Search titles and file contents</label><input class="adm-input" id="dc-q" type="search" value="${E(D.q)}" minlength="2"></div><button class="mz-btn" type="submit">Search</button></form><div class="mz-split" style="margin-top:10px"><div id="dc-list"></div><section class="mz-card" id="dc-detail"><div class="mz-empty">Search, then select a document.</div></section></div>`);
    MZ.$('dc-sform').addEventListener('submit', e => { e.preventDefault(); D.q = MZ.$('dc-q').value.trim(); list().catch(MZ.fail); });
    if(D.q.length >= 2) rows = await MZ.api(`/api/documents/search?q=${encodeURIComponent(D.q)}`);
  }else{
    rows = await MZ.api(`/api/documents${D.tab === 'master' ? '?controlled=true' : ''}`);
    MZ.html(body, `<div class="mz-split"><div id="dc-list"></div><section class="mz-card" id="dc-detail"><div class="mz-empty">Select a document.</div></section></div>`);
  }
  MZ.html(MZ.$('dc-list'), MZ.table({rows, rowId: d => d.id, selected: D.selected, empty: D.tab === 'search' ? (D.q ? 'No matches you can open.' : 'Type at least two characters.') : 'No documents.', columns: [
    {label: 'Document', render: d => `${d.number ? `<span class="mz-mono mz-strong">${E(d.number)} r${E(d.revision)}</span> ` : ''}${E(d.title)}<div class="mz-meta">${E(d.type.name)} · ${E(MZ.unitName(d.org_unit_code))} · ${E(MZ.label(d.classification))}</div>${d.snippet ? `<div class="mz-meta">…${E(d.snippet).replace(/\[/g, '<mark>').replace(/\]/g, '</mark>')}…</div>` : ''}`},
    {label: 'Owner', key: 'owner'},
    {label: 'Effective', render: d => E(MZ.date(d.effective_date))},
    {label: 'Review', render: d => `${E(MZ.date(d.review_date))}${d.review_overdue ? ' ' + MZ.badge('overdue') : ''}`},
    {label: 'Status', render: d => MZ.badge(d.status)}]}));
  MZ.onRow(MZ.$('dc-list'), id => { D.selected = id; detail().catch(MZ.fail); });
  if(D.selected) detail().catch(() => { D.selected = null; });
}

async function detail(){
  document.querySelectorAll('#dc-list tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(D.selected)));
  const d = await MZ.api(`/api/documents/${D.selected}`);
  const host = MZ.$('dc-detail');
  if(!host) return;
  const ext = (D.types.find(t => t.id === d.type.id) || {}).allowed_extensions || [];
  MZ.html(host, `<div class="mz-hdr"><h3>${d.number ? E(`${d.number} r${d.revision} · `) : ''}${E(d.title)}</h3>${MZ.badge(d.status)}</div>
    <dl class="mz-kv"><dt>Type</dt><dd>${E(d.type.name)}${d.type.controlled ? ' (controlled)' : ''}</dd><dt>Unit</dt><dd>${E(MZ.unitName(d.org_unit_code))}</dd>
      <dt>Classification</dt><dd>${E(MZ.label(d.classification))}</dd><dt>Owner</dt><dd>${E(d.owner)}</dd>${d.type.controlled ? `<dt>Approver</dt><dd>${E(d.approver || 'A document controller')}</dd>` : ''}
      ${d.approved_by ? `<dt>Approved</dt><dd>version ${E(d.approved_version)} by ${E(d.approved_by)}</dd>` : ''}
      ${d.type.controlled ? `<dt>Effective</dt><dd>${E(MZ.date(d.effective_date))}</dd><dt>Review due</dt><dd>${E(MZ.date(d.review_date))}${d.review_overdue ? ' ' + MZ.badge('overdue') : ''}</dd>` : ''}
      ${d.tags.length ? `<dt>Tags</dt><dd>${d.tags.map(t => `<span class="mz-badge">${E(t)}</span>`).join(' ')}</dd>` : ''}
      ${d.description ? `<dt>Description</dt><dd style="white-space:pre-wrap">${E(d.description)}</dd>` : ''}
      ${d.evidence_for.length ? `<dt>Evidence for</dt><dd>${d.evidence_for.map(e => `<button class="mz-link" data-mz="open" data-type="${E(e.type)}" data-id="${E(e.id)}">${E(MZ.label(e.type))} #${E(e.id)}</button> (v${E(e.version)})`).join(', ')}</dd>` : ''}</dl>
    <div class="mz-btn-row" style="margin:12px 0">${d.can_edit ? '<button class="mz-btn" data-mz="upload">Upload a new version</button><button class="mz-btn ghost" data-mz="edit">Edit details</button>' : ''}
      ${d.allowed.map(t => `<button class="mz-btn ${t === 'withdraw' ? 'danger' : 'primary'}" data-mz="tr" data-name="${t}">${E(TR_LABEL[t] || t)}</button>`).join('')}
      ${d.can_revise ? '<button class="mz-btn" data-mz="revise">Start revision</button>' : ''}</div>
    <h4>Versions</h4>${MZ.table({rows: d.versions, empty: 'No file yet.', columns: [
      {label: 'Version', render: v => `<span class="mz-strong">v${E(v.version)}</span>${d.approved_version === v.version ? ' ' + MZ.badge('approved') : ''}`},
      {label: 'File', render: v => `${E(v.filename)}<div class="mz-meta">${E(size(v.size))} · <span class="mz-mono" title="SHA-256 ${E(v.sha256)}">${E(v.sha256.slice(0, 12))}</span></div>${v.change_note ? `<div class="mz-meta">${E(v.change_note)}</div>` : ''}`},
      {label: 'Search text', render: v => MZ.badge(v.extraction_status, v.extraction_status === 'ok' ? 'ok' : v.extraction_status === 'failed' ? 'danger' : '', MZ.label(v.extraction_status)) + (v.extraction_error ? `<div class="mz-meta">${E(v.extraction_error)}</div>` : '')},
      {label: 'Uploaded', render: v => `${E(v.uploaded_by)}<div class="mz-meta">${E(MZ.dateTime(v.uploaded_at))}</div>`},
      {label: '', render: v => `<button class="mz-btn ghost" data-mz="dl" data-v="${v.version}" data-name="${E(v.filename)}">Download</button>`}]})}
    <div id="dc-extras" style="margin-top:12px"></div>`);
  await MZ.extras(MZ.$('dc-extras'), 'document', d.id);
  MZ.onAct(host, {
    dl: x => MZ.download(`/api/documents/${d.id}/download?version=${x.v}`, x.name),
    open: x => MZ.open(MZ.entityPages[x.type] || 'actions', x.type, x.id),
    upload: async () => {
      const ok = await MZ.form({title: `New version of ${d.title}`, intro: `Accepted: ${ext.map(x => '.' + x).join(', ')}. The content must match the extension.`,
        fields: [{name: 'file', label: 'File', type: 'file', required: true, accept: ext.map(x => '.' + x).join(',')}, {name: 'change_note', label: 'What changed', type: 'textarea', rows: 2}],
        onSubmit: v => { const f = new FormData(); f.append('file', v.file); if(v.change_note) f.append('change_note', v.change_note); return MZ.api(`/api/documents/${d.id}/versions`, {method: 'POST', form: f}); }});
      if(ok){ MZ.toast('Version uploaded.', 'ok'); detail(); }
    },
    edit: async () => {
      const ok = await MZ.form({title: 'Edit document details', fields: [
        {name: 'title', label: 'Title', value: d.title, required: true, full: true},
        {name: 'classification', label: 'Classification', type: 'select', value: d.classification, options: ['public', 'internal', 'confidential', 'restricted'].map(c => ({value: c, label: MZ.label(c)}))},
        {name: 'owner', label: 'Owner (username)', value: d.owner}, ...(d.type.controlled ? [{name: 'approver', label: 'Approver (username)', value: d.approver || ''}] : []),
        {name: 'tags', label: 'Tags (comma separated)', value: d.tags.join(', ')},
        ...(d.type.controlled ? [{name: 'review_date', label: 'Review date', type: 'date', value: d.review_date || ''}] : []),
        {name: 'description', label: 'Description', type: 'textarea', value: d.description || ''}],
        onSubmit: v => MZ.api(`/api/documents/${d.id}`, {method: 'PUT', body: {...v, approver: v.approver || null, review_date: v.review_date || null, tags: (v.tags || '').split(',').map(t => t.trim()).filter(Boolean)}})});
      if(ok) detail();
    },
    tr: async x => {
      let reason = null;
      if(x.name === 'withdraw'){ const r = await MZ.reason({title: 'Withdraw document'}); if(!r) return; reason = r.reason; }
      await MZ.api(`/api/documents/${d.id}/transition`, {method: 'POST', body: {name: x.name, reason}});
      MZ.toast('Done.', 'ok'); list();
    },
    revise: async () => { const n = await MZ.api(`/api/documents/${d.id}/revise`, {method: 'POST'}); D.selected = n.id; MZ.toast(`Revision ${n.revision} started as a draft.`, 'ok'); list(); },
  });
}

async function newDoc(ts){
  const controllerOrReviewer = MZ.hasFunction('document_controller') || MZ.canAnywhere('reviewer');
  const allowed = ts.filter(t => !t.controlled || controllerOrReviewer);
  const ok = await MZ.form({title: 'New document', intro: 'Controlled documents get the next number for their type and start as drafts; upload the file, then the approver approves it.', fields: [
    {name: 'type_id', label: 'Type', type: 'select', required: true, options: allowed.map(t => ({value: t.id, label: `${t.name}${t.controlled ? ` (controlled, ${t.number_prefix})` : ''}`}))},
    {name: 'title', label: 'Title', required: true},
    {name: 'org_unit_code', label: 'Unit', type: 'select', options: MZ.hasFunction('document_controller') ? MZ.unitOptions('viewer') : MZ.unitOptions('contributor')},
    {name: 'classification', label: 'Classification', type: 'select', value: 'internal', options: ['public', 'internal', 'confidential', 'restricted'].map(c => ({value: c, label: MZ.label(c)}))},
    {name: 'owner', label: 'Owner (username, default you)'}, {name: 'approver', label: 'Approver (controlled documents)'},
    {name: 'tags', label: 'Tags (comma separated)'}, {name: 'description', label: 'Description', type: 'textarea'}],
    onSubmit: v => MZ.api('/api/documents', {method: 'POST', body: {...v, type_id: Number(v.type_id), owner: v.owner || null, approver: v.approver || null, tags: (v.tags || '').split(',').map(t => t.trim()).filter(Boolean)}})});
  if(ok){ D.selected = ok.id; D.tab = ok.type.controlled ? 'master' : 'all'; MZ.refresh('documents'); }
}

})();
