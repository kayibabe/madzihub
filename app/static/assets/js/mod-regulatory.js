/* ══════════════════════════════════════════════════════════════════════════
   Regulatory (mod-regulatory.js) — builds on window.MZ
   · Packs: import source-cited drafts, see what is unverified, edit (with reason), approve (second officer)
   · Returns: raw values (append-only), prefill from the catalogue, submit, export
   · League tables: saved runs with peer values; clearly not an official ranking
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';
const MZ = window.MZ;
const E = MZ.esc;
const RG = {tab: 'packs', pack: null, ret: null};

MZ.page('regulatory', async root => {
  MZ.html(root, `${MZ.header('Regulatory', 'Regulator methods are versioned, source-cited packs. A pack is usable only after every figure has been checked against the cited report and a second regulatory officer approves it. Scores calculated here are MadziHub comparisons, never an official regulator ranking.')}
    <div id="rg-tabs"></div><div id="rg-body" style="margin-top:12px"></div>`);
  const render = () => {
    MZ.tabs(MZ.$('rg-tabs'), [{key: 'packs', label: 'Packs'}, {key: 'returns', label: 'Returns'}, {key: 'league', label: 'League tables'}], RG.tab, k => { RG.tab = k; render(); });
    ({packs, returns, league})[RG.tab](MZ.$('rg-body')).catch(e => MZ.html(MZ.$('rg-body'), `<div class="mz-notice danger">${E(e.message)}</div>`));
  };
  render();
});

async function packs(body){
  const [files, rows] = await Promise.all([MZ.api('/api/regulatory/pack-files'), MZ.api('/api/regulatory/packs')]);
  const officer = MZ.hasFunction('regulatory_officer') && !MZ.me.read_only;
  MZ.html(body, `${officer ? `<section class="mz-card"><h3>Pack files shipped with this installation</h3>${MZ.table({rows: files, empty: 'No pack files.', columns: [
      {label: 'File', render: f => `<span class="mz-mono">${E(f.file)}</span>`}, {label: 'Regulator', key: 'regulator'}, {label: 'Cycle', key: 'cycle'},
      {label: '', render: f => f.error ? `<span class="mz-meta">${E(f.error)}</span>` : `<button class="mz-btn" data-mz="import" data-file="${E(f.file)}">Import as draft</button>`}]})}</section>` : ''}
    <div class="mz-split"><div id="rg-packs">${MZ.table({rows, rowId: p => p.id, selected: RG.pack, empty: 'No packs imported.', columns: [
      {label: 'Pack', render: p => `<span class="mz-strong">${E(p.regulator)}</span> ${E(p.cycle)} <span class="mz-meta">v${E(p.version)}</span>`},
      {label: 'Verified', render: p => `${E(p.verified_count)}/${E(p.indicator_count)}`},
      {label: 'Status', render: p => MZ.badge(p.status) + (p.status === 'draft' && p.blockers.length ? ' ' + MZ.badge('blocked', 'warn', `${p.blockers.length} open item(s)`) : '')}]})}</div>
    <section class="mz-card" id="rg-pack"><div class="mz-empty">Select a pack.</div></section></div>`);
  MZ.onAct(body, {import: async d => { const p = await MZ.api('/api/regulatory/packs/import', {method: 'POST', body: {file: d.file}}); RG.pack = p.id; MZ.toast('Imported as a draft.', 'ok'); packs(body); }});
  MZ.onRow(MZ.$('rg-packs'), id => { RG.pack = id; packDetail().catch(MZ.fail); });
  if(RG.pack) packDetail().catch(() => { RG.pack = null; });
}

async function packDetail(){
  const p = await MZ.api(`/api/regulatory/packs/${RG.pack}`);
  document.querySelectorAll('#rg-packs tr[data-row-id]').forEach(tr => tr.classList.toggle('mz-selected', tr.dataset.rowId === String(p.id)));
  const host = MZ.$('rg-pack');
  const officer = MZ.hasFunction('regulatory_officer') && !MZ.me.read_only;
  const c = p.content;
  MZ.html(host, `<div class="mz-hdr"><h3>${E(p.title)}</h3>${MZ.badge(p.status)}</div>
    <dl class="mz-kv"><dt>Regulator</dt><dd>${E(p.regulator)} (${E(p.jurisdiction)})</dd><dt>Cycle</dt><dd>${E(p.cycle)} · version ${E(p.version)}</dd>
      <dt>Source</dt><dd>${E(p.source_title)}${p.source_url ? `<div class="mz-meta mz-mono" style="white-space:normal;overflow-wrap:anywhere">${E(p.source_url)}</div>` : ''}${p.source_accessed ? `<div class="mz-meta">accessed ${E(MZ.date(p.source_accessed))}</div>` : ''}</dd>
      <dt>Verification</dt><dd>${E((c.verification || {}).notes || '')}</dd><dt>Fingerprint</dt><dd class="mz-mono">${E(p.content_hash.slice(0, 16))}</dd>
      ${p.approved_by ? `<dt>Approved</dt><dd>${E(p.approved_by)}, ${E(MZ.dateTime(p.approved_at))}</dd>` : ''}</dl>
    ${p.blockers.length ? `<div class="mz-notice warn"><strong>Not usable yet (${p.blockers.length}):</strong><ul>${p.blockers.slice(0, 12).map(b => `<li>${E(b)}</li>`).join('')}${p.blockers.length > 12 ? `<li>… and ${p.blockers.length - 12} more</li>` : ''}</ul></div>` : ''}
    <div class="mz-btn-row" style="margin:10px 0">${officer && p.status === 'draft' ? '<button class="mz-btn" data-mz="edit">Edit figures (JSON)</button>' : ''}${officer && p.status === 'draft' && !p.blockers.length ? '<button class="mz-btn primary" data-mz="approve">Approve pack</button>' : ''}</div>
    <h4>Groups</h4>${MZ.table({rows: c.groups || [], columns: [{label: 'Group', render: g => `${E(g.code)} ${E(g.name || '')}`}, {label: 'Share', num: true, render: g => g.share_pct == null ? '—' : E(g.share_pct) + '%'}, {label: 'Verified', render: g => MZ.badge(g.verified ? 'verified' : 'unverified', g.verified ? 'ok' : 'warn')}]})}
    <h4>Indicators</h4>${MZ.table({rows: c.indicators || [], columns: [
      {label: 'Code', render: i => `<span class="mz-mono">${E(i.code)}</span>`}, {label: 'Indicator', render: i => `${E(i.name)}<div class="mz-meta">${E(i.cluster || '')}${i.source_ref ? ' · ' + E(i.source_ref) : ''}</div>`},
      {label: 'Unit', render: i => E(i.unit || '')}, {label: 'Better', render: i => E(MZ.label(i.polarity))},
      {label: 'Weight', num: true, render: i => i.weight == null ? '—' : E(i.weight)}, {label: 'Scored', render: i => i.in_score === false ? 'No' : 'Yes'},
      {label: 'Verified', render: i => MZ.badge(i.verified ? 'verified' : 'unverified', i.verified ? 'ok' : 'warn')}]})}
    <h4>Decisions</h4>${p.decisions.length ? `<ol class="mz-timeline">${p.decisions.map(s => `<li>${E(MZ.label(s.step))} by ${E(s.actor)} <span class="mz-when">${E(MZ.dateTime(s.at))}</span></li>`).join('')}</ol>` : '<div class="mz-empty">None.</div>'}`);
  MZ.onAct(host, {
    edit: async () => {
      const ok = await MZ.form({title: `Edit ${p.regulator} ${p.cycle}`, wide: true, intro: 'Fill figures only from the cited source, set <code>verified: true</code> with the page or table in <code>source_ref</code>, and set <code>verification.source_checked</code> when the whole pack has been checked. A different officer approves.', fields: [
        {name: 'content', label: 'Pack content (JSON)', type: 'textarea', rows: 18, value: JSON.stringify(c, null, 2), required: true},
        {name: 'reason', label: 'What changed and where it comes from', type: 'textarea', rows: 2, required: true}],
        onSubmit: v => { let content; try{ content = JSON.parse(v.content); }catch(e){ throw new Error('The JSON is not valid: ' + e.message); }
          return MZ.api(`/api/regulatory/packs/${p.id}`, {method: 'PUT', body: {content, reason: v.reason}}); }});
      if(ok){ MZ.toast('Pack updated.', 'ok'); packDetail(); }
    },
    approve: async () => { const r = await MZ.reason({title: 'Approve pack', label: 'Note', required: false, submitLabel: 'Approve',
        intro: 'You confirm the figures match the cited source. Approving retires any earlier approved version of this cycle.'}); if(!r) return;
      await MZ.api(`/api/regulatory/packs/${p.id}/approve`, {method: 'POST', body: {note: r.reason || null}}); MZ.toast('Pack approved.', 'ok'); packs(MZ.$('rg-body')); },
  });
}

async function returns(body){
  const [rows, pks] = await Promise.all([MZ.api('/api/regulatory/returns'), MZ.api('/api/regulatory/packs')]);
  const officer = MZ.hasFunction('regulatory_officer') && !MZ.me.read_only;
  const usable = pks.filter(p => p.status === 'approved');
  MZ.html(body, `${!usable.length ? '<div class="mz-notice warn">No approved pack yet: returns start once a pack has been verified and approved.</div>' : ''}
    ${officer && usable.length ? '<div class="mz-btn-row" style="margin-bottom:10px"><button class="mz-btn primary" data-mz="new">New return</button></div>' : ''}
    <div class="mz-split"><div id="rg-rets">${MZ.table({rows, rowId: r => r.id, selected: RG.ret, empty: 'No returns.', columns: [
      {label: 'Return', render: r => `${E(r.pack)}<div class="mz-meta">${E(r.period_label)}</div>`}, {label: 'Status', render: r => MZ.badge(r.status)}]})}</div>
    <section class="mz-card" id="rg-ret"><div class="mz-empty">Select a return.</div></section></div>`);
  MZ.onAct(body.querySelector('.mz-btn-row') || body, {new: async () => {
    const r = await MZ.form({title: 'New return', fields: [{name: 'pack_id', label: 'Pack', type: 'select', options: usable.map(p => ({value: p.id, label: `${p.regulator} ${p.cycle} v${p.version}`}))},
      {name: 'period_label', label: 'Period', required: true, placeholder: 'e.g. FY2025/26'}], onSubmit: v => MZ.api('/api/regulatory/returns', {method: 'POST', body: {...v, pack_id: Number(v.pack_id)}})});
    if(r){ RG.ret = r.id; returns(body); }
  }});
  MZ.onRow(MZ.$('rg-rets'), id => { RG.ret = id; retDetail(officer).catch(MZ.fail); });
  if(RG.ret) retDetail(officer).catch(() => { RG.ret = null; });
}

async function retDetail(officer){
  const r = await MZ.api(`/api/regulatory/returns/${RG.ret}`);
  const host = MZ.$('rg-ret');
  const draft = r.status === 'draft' && officer;
  MZ.html(host, `<div class="mz-hdr"><h3>${E(r.pack)} · ${E(r.period_label)}</h3>${MZ.badge(r.status)}</div>
    <p class="mz-meta">Raw values as entered (${E(r.revisions)} entries kept); calculated scores are never written back into a return.</p>
    <form id="rg-vals">${MZ.table({rows: r.values, columns: [
      {label: 'Code', render: v => `<span class="mz-mono">${E(v.code)}</span>`}, {label: 'Indicator', render: v => `${E(v.name)}${v.in_score ? '' : ' <span class="mz-meta">(not scored)</span>'}`},
      {label: 'Value', render: v => draft ? `<input class="adm-input" style="max-width:120px" type="number" step="any" name="v:${E(v.code)}" aria-label="${E(v.name)}" value="${v.value ?? ''}">` : E(MZ.num(v.value))},
      {label: 'Unit', render: v => E(v.unit || '')}, {label: 'Source', render: v => `<span class="mz-meta">${E(v.source || '—')}</span>`}]})}
    <div class="mz-btn-row" style="margin-top:10px">${draft ? '<button class="mz-btn" type="submit">Save values</button><button class="mz-btn ghost" type="button" data-mz="prefill">Fill from the catalogue</button><button class="mz-btn primary" type="button" data-mz="submit">Submit return</button>' : ''}
      <button class="mz-btn ghost" type="button" data-mz="export">Export (Excel)</button></div></form>`);
  MZ.$('rg-vals').addEventListener('submit', async e => {
    e.preventDefault();
    const changes = r.values.map(v => ({code: v.code, raw: e.target.elements[`v:${v.code}`]?.value, old: v.value}))
      .filter(x => x.raw !== undefined && String(x.raw) !== String(x.old ?? '')).map(x => ({code: x.code, value: x.raw === '' ? null : Number(x.raw)}));
    if(!changes.length){ MZ.toast('Nothing changed.'); return; }
    try{ await MZ.api(`/api/regulatory/returns/${r.id}/values`, {method: 'PUT', body: changes}); MZ.toast('Values saved.', 'ok'); retDetail(officer); }catch(err){ MZ.fail(err); }
  });
  MZ.onAct(host, {
    prefill: async () => { const f = await MZ.form({title: 'Fill from the catalogue', fields: [{name: 'fiscal_year', label: 'Fiscal year (ending)', type: 'number', required: true, value: new Date().getFullYear()}],
        onSubmit: v => MZ.api(`/api/regulatory/returns/${r.id}/prefill`, {method: 'POST', body: v})}); if(f){ MZ.toast(`${f.prefilled} value(s) filled.`, 'ok'); retDetail(officer); } },
    submit: async () => { await MZ.api(`/api/regulatory/returns/${r.id}/submit`, {method: 'POST'}); MZ.toast('Return submitted.', 'ok'); returns(MZ.$('rg-body')); },
    export: () => MZ.download(`/api/regulatory/returns/${r.id}/export`, 'return.xlsx'),
  });
}

async function league(body){
  const [runs, pks, rets] = await Promise.all([MZ.api('/api/regulatory/league-runs'), MZ.api('/api/regulatory/packs'), MZ.api('/api/regulatory/returns')]);
  const officer = MZ.hasFunction('regulatory_officer') && !MZ.me.read_only;
  const usable = pks.filter(p => p.status === 'approved');
  MZ.html(body, `<div class="mz-notice">League tables are calculated by MadziHub from an approved pack and the peer values you enter; they are for comparison and are not an official regulator ranking. Each run is saved with its inputs.</div>
    ${officer && usable.length ? '<div class="mz-btn-row" style="margin:10px 0"><button class="mz-btn primary" data-mz="run">New league-table run</button></div>' : ''}
    ${runs.map(run => `<section class="mz-card"><h3>${E(run.label)} <span class="mz-meta">#${E(run.id)} · ${E(MZ.dateTime(run.created_at))} · ${E(run.created_by)}</span></h3>
      ${MZ.table({rows: run.results.entities, columns: [{label: 'Rank', num: true, render: x => E(x.rank)}, {label: 'Utility', render: x => `${x.own ? '<strong>' : ''}${E(x.name)}${x.own ? '</strong> (us)' : ''}`},
        {label: 'Score', num: true, render: x => E(MZ.num(x.total, 2))}, {label: 'Missing', render: x => E((x.missing || []).join(', '))}]})}
      <p class="mz-meta mz-mono">inputs ${E(run.inputs_hash.slice(0, 16))} · pack ${E(run.pack_hash.slice(0, 16))}</p></section>`).join('') || '<div class="mz-empty">No runs yet.</div>'}`);
  MZ.onAct(body, {run: async () => {
    const r = await MZ.form({title: 'New league-table run', wide: true, fields: [
      {name: 'pack_id', label: 'Pack', type: 'select', options: usable.map(p => ({value: p.id, label: `${p.regulator} ${p.cycle} v${p.version}`}))},
      {name: 'return_id', label: 'Our return', type: 'select', options: [{value: '', label: '(none)'}, ...rets.map(x => ({value: x.id, label: `${x.pack} · ${x.period_label} (${x.status})`}))]},
      {name: 'label', label: 'Label'},
      {name: 'peers', label: 'Peer values (JSON)', type: 'textarea', rows: 8, value: '[\n  {"name": "Peer utility A", "values": {"NRW": 40}}\n]', help: 'Values from the regulator’s published report for each peer, by indicator code.'}],
      onSubmit: v => { let peers; try{ peers = JSON.parse(v.peers); }catch(e){ throw new Error('Peer values are not valid JSON.'); }
        return MZ.api('/api/regulatory/league-runs', {method: 'POST', body: {pack_id: Number(v.pack_id), return_id: v.return_id ? Number(v.return_id) : null, label: v.label || null, peers}}); }});
    if(r) league(body);
  }});
}

})();
