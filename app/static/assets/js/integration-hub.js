/* ══════════════════════════════════════════════════════════════════════════
   Integration hub UI
   · Administration → Data Sources   (admin: sources, runs, rejects, key mappings)
   · Board → Strategic Position      (all users: where we were / are / are going)
   Relies on app-core.js globals: API, getToken, getUser, fetchJsonSafe, DOMPurify, Chart.
   Everything that comes from a source system is escaped with ihEsc() before it
   reaches innerHTML, and the result is sanitised again with DOMPurify.
   ══════════════════════════════════════════════════════════════════════════ */

function ihEsc(v){
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function ihSet(el, html){ if(el) el.innerHTML = DOMPurify.sanitize(html); }
/* <tr> markup must be parsed inside a table or the parser drops the row and cell tags. */
function ihSetRows(tbody, rowsHtml){ if(tbody) tbody.innerHTML = sanitizeRows(rowsHtml); }
async function ihApi(path, {method='GET', body, form, fallback=null}={}){
  const headers = {};
  let payload;
  if(form){ payload = form; }
  else if(body !== undefined){ headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  return fetchJsonSafe(`${API}${path}`, {method, headers, body:payload, label:path, fallback, timeout:120000});
}
function ihAgo(iso){
  if(!iso) return 'never';
  const then = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if(mins < 1) return 'just now';
  if(mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if(h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
function ihNum(v, unit){
  if(v === null || v === undefined || Number.isNaN(v)) return '—';
  const u = unit === 'count' ? '' : (unit || '');
  if(u === '%') return `${v.toLocaleString('en-GB',{maximumFractionDigits:1})}%`;
  const abs = Math.abs(v);
  const opts = abs >= 1e6 ? {notation:'compact', maximumFractionDigits:2}
             : abs >= 100 ? {maximumFractionDigits:0} : {maximumFractionDigits:2};
  const n = v.toLocaleString('en-GB', opts);
  return u ? `${n} ${u}` : n;
}
function ihPeriodLabel(iso, type){
  if(!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  const mon = d.toLocaleString('en-GB',{month:'short'});
  if(type === 'day') return d.toLocaleDateString('en-GB',{day:'numeric', month:'short', year:'numeric'});
  if(type === 'quarter') return `Quarter from ${mon} ${d.getFullYear()}`;
  if(type === 'year') return `Year from ${mon} ${d.getFullYear()}`;
  return `${mon} ${d.getFullYear()}`;
}

/* ─────────────────────────── Data Sources (admin) ─────────────────────────── */

const IH = { sources: [], freshness: [], selected: null, editing: null };

const IH_TEMPLATES = {
  file: {config:{path:'returns/*.csv'},
         mapping:{layout:'wide', metrics:{vol_produced:'Production (m3)'}, period:{field:'Month'}, org_unit:{field:'Scheme'}}},
  sql:  {config:{url_env:'MADZI_SRC_BILLING_DB_URL', watermark_field:'updated_at',
                 query:'SELECT branch, period_month, collected, updated_at FROM v_madzi_monthly WHERE updated_at > :since'},
         mapping:{layout:'wide', metrics:{cash_collected:'collected'}, period:{field:'period_month'}, org_unit:{field:'branch'}}},
  rest: {config:{base_url:'https://system.example/odata', path:'EntitySet',
                 auth:{type:'basic', username_env:'MADZI_SRC_USER', password_env:'MADZI_SRC_PASSWORD'},
                 params:{'$format':'json', '$filter':"Changed gt '{since}'"},
                 records_path:'d.results', next_link_path:'d.__next', watermark_field:'Changed'},
         mapping:{layout:'wide', metrics:{cash_collected:'Amount'}, period:{field:'PostingDate'}, org_unit:{field:'CostCenter'}}},
  push: {config:{},
         mapping:{layout:'long', metric_field:'tag', value_field:'value', ignore_unmapped_metrics:true,
                  period:{field:'timestamp'}, period_type:'day', org_unit:{field:'site'}}},
  legacy_records: {config:{columns:['vol_produced']},
                   mapping:{layout:'wide', metrics:{vol_produced:'vol_produced'}, period:{year_field:'year', month_field:'month_no'},
                            org_unit:{field:'org_unit'}}},
};

function ihStatus(src){
  if(!src.enabled) return {cls:'viewer', label:'Disabled'};
  if(src.last_status === 'failed') return {cls:'danger', label:'Failed'};
  if(src.overdue) return {cls:'warn', label:'Overdue'};
  if(src.last_status === 'partial') return {cls:'warn', label:'Has rejects'};
  if(src.last_status === 'success') return {cls:'ok', label:'Healthy'};
  if(src.last_status === 'running') return {cls:'user', label:'Running'};
  return {cls:'viewer', label:'Never run'};
}

async function ihLoadSources(){
  const tbody = document.getElementById('ih-src-tbody');
  try{
    const [fresh, sources] = await Promise.all([
      ihApi('/api/position/sources/freshness', {fallback:[]}),
      ihApi('/api/integration/sources', {fallback:[]}),
    ]);
    IH.freshness = fresh; IH.sources = sources;
    const bySrc = Object.fromEntries(sources.map(s => [s.code, s]));
    const healthy = fresh.filter(s => ihStatus(s).cls === 'ok').length;
    const attention = fresh.filter(s => ['danger','warn'].includes(ihStatus(s).cls)).length;
    const values = fresh.reduce((a, s) => a + (s.values || 0), 0);
    document.getElementById('ih-stat-total').textContent = fresh.length;
    document.getElementById('ih-stat-healthy').textContent = healthy;
    document.getElementById('ih-stat-attention').textContent = attention;
    document.getElementById('ih-stat-values').textContent = values.toLocaleString('en-GB');
    document.getElementById('ih-empty').style.display = fresh.length ? 'none' : '';
    if(!fresh.length){ ihSetRows(tbody, '<tr><td colspan="7" class="adm-empty">No data sources yet</td></tr>'); return; }
    ihSetRows(tbody, fresh.map(s => {
      const st = ihStatus(s);
      const cfg = bySrc[s.code] || {};
      const push = s.connector === 'push';
      return `<tr class="${IH.selected === s.code ? 'ih-row-selected' : ''}">
        <td><div class="adm-user-name">${ihEsc(s.name)}</div>
            <div class="adm-user-fullname">${ihEsc(s.code)} · ${ihEsc(s.system_type)} · ${ihEsc(s.connector)}${s.owner ? ' · ' + ihEsc(s.owner) : ''}</div></td>
        <td><span class="ih-badge ${st.cls}">${ihEsc(st.label)}</span>
            ${s.last_error ? `<div class="ih-err-line" title="${ihEsc(s.last_error)}">${ihEsc(s.last_error.slice(0, 90))}</div>` : ''}</td>
        <td class="adm-td-meta">${ihEsc(ihAgo(s.last_success_at))}</td>
        <td class="adm-td-meta">${cfg.schedule_minutes ? 'every ' + ihEsc(cfg.schedule_minutes) + ' min' : 'manual'}</td>
        <td class="adm-td-meta" style="text-align:right">${ihEsc(s.priority)}</td>
        <td class="adm-td-meta" style="text-align:right">${(s.values || 0).toLocaleString('en-GB')}</td>
        <td><div class="adm-act-row">
          ${push ? '' : `<button class="adm-act-btn edit" data-ih-act="run" data-code="${ihEsc(s.code)}" ${s.enabled ? '' : 'disabled'}>Run</button>`}
          <button class="adm-act-btn edit" data-ih-act="upload" data-code="${ihEsc(s.code)}" ${s.enabled ? '' : 'disabled'}>Upload</button>
          <button class="adm-act-btn reset" data-ih-act="detail" data-code="${ihEsc(s.code)}">Runs &amp; mappings</button>
          <button class="adm-act-btn reset" data-ih-act="edit" data-code="${ihEsc(s.code)}">Edit</button>
          ${push ? `<button class="adm-act-btn warn" data-ih-act="token" data-code="${ihEsc(s.code)}">New token</button>` : ''}
          ${s.enabled ? `<button class="adm-act-btn danger" data-ih-act="disable" data-code="${ihEsc(s.code)}">Disable</button>` : `<button class="adm-act-btn edit" data-ih-act="enable" data-code="${ihEsc(s.code)}">Enable</button>`}
        </div></td>
      </tr>`;
    }).join(''));
    if(IH.selected) ihLoadDetail(IH.selected);
  }catch(e){
    ihSetRows(tbody, `<tr><td colspan="7" class="adm-err">Failed to load sources: ${ihEsc(e.message)}</td></tr>`);
  }
}

function ihNotice(html, tone='info'){
  const el = document.getElementById('ih-notice');
  if(!el) return;
  el.className = `ih-notice ${tone}`;
  ihSet(el, html);
  el.style.display = html ? '' : 'none';
}

function ihRunSummary(run){
  const tone = run.status === 'failed' ? 'danger' : run.status === 'partial' ? 'warn' : 'ok';
  const parts = [`<strong>${ihEsc(run.status)}</strong>`, `read ${ihEsc(run.rows_read)}`,
                 `loaded ${ihEsc(run.values_loaded)}`, `rejected ${ihEsc(run.rows_rejected)}`];
  if(run.error) parts.push(ihEsc(run.error));
  return {tone, html: parts.join(' · ')};
}

async function ihRun(code){
  ihNotice(`Running <strong>${ihEsc(code)}</strong>…`);
  try{
    const run = await ihApi(`/api/integration/sources/${encodeURIComponent(code)}/run`, {method:'POST'});
    const s = ihRunSummary(run);
    ihNotice(`${ihEsc(code)}: ${s.html}`, s.tone);
    IH.selected = code;
  }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
  ihLoadSources();
}

function ihUpload(code){
  const input = document.getElementById('ih-upload-input');
  input.value = '';
  input.onchange = async () => {
    const file = input.files[0];
    if(!file) return;
    const form = new FormData();
    form.append('file', file);
    ihNotice(`Loading <strong>${ihEsc(file.name)}</strong> into ${ihEsc(code)}…`);
    try{
      const run = await ihApi(`/api/integration/sources/${encodeURIComponent(code)}/upload`, {method:'POST', form});
      const s = ihRunSummary(run);
      ihNotice(`${ihEsc(file.name)}: ${s.html}`, s.tone);
      IH.selected = code;
    }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
    ihLoadSources();
  };
  input.click();
}

async function ihSetEnabled(code, enabled){
  if(!enabled && !confirm(`Disable ${code}? Loaded values are kept; scheduled pulls stop.`)) return;
  try{
    if(enabled) await ihApi(`/api/integration/sources/${encodeURIComponent(code)}`, {method:'PUT', body:{enabled:true}});
    else await ihApi(`/api/integration/sources/${encodeURIComponent(code)}`, {method:'DELETE'});
  }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
  ihLoadSources();
}

async function ihToken(code){
  if(!confirm(`Issue a new push token for ${code}? The current token stops working immediately.`)) return;
  try{
    const r = await ihApi(`/api/integration/sources/${encodeURIComponent(code)}/token`, {method:'POST'});
    ihNotice(`New token for <strong>${ihEsc(code)}</strong>. Copy it now; it is not shown again.
      <code class="ih-token">${ihEsc(r.token)}</code>
      Send rows to <code>POST /api/ingest/${ihEsc(code)}</code> with header <code>X-Madzi-Ingest-Token</code>.`, 'warn');
  }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
}

async function ihBootstrap(){
  ihNotice('Creating the organisation tree, core measures and the monthly-returns source…');
  try{
    const r = await ihApi('/api/integration/bootstrap-legacy', {method:'POST'});
    ihNotice(`Created ${ihEsc(r.org_units)} units, ${ihEsc(r.metrics)} measures and ${ihEsc(r.targets)} plan targets.
      Run <strong>legacy-returns</strong> to publish history.`, 'ok');
  }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
  ihLoadSources();
}

/* Detail panel: recent runs, rejected rows, key mappings */
async function ihLoadDetail(code){
  IH.selected = code;
  const panel = document.getElementById('ih-detail');
  panel.style.display = '';
  document.getElementById('ih-detail-title').textContent = code;
  const runsEl = document.getElementById('ih-runs');
  const mapsEl = document.getElementById('ih-maps');
  ihSet(runsEl, '<div class="adm-empty">Loading…</div>');
  try{
    const [runs, maps] = await Promise.all([
      ihApi(`/api/integration/runs?source=${encodeURIComponent(code)}&limit=10&include_rejects=true`, {fallback:[]}),
      ihApi(`/api/integration/sources/${encodeURIComponent(code)}/key-mappings`, {fallback:[]}),
    ]);
    ihSet(runsEl, runs.length ? runs.map(r => {
      const s = ihRunSummary(r);
      const rejects = (r.rejects || []).slice(0, 25);
      return `<details class="ih-run" ${r === runs[0] ? 'open' : ''}>
        <summary><span class="ih-badge ${s.tone}">${ihEsc(r.status)}</span>
          <span class="adm-td-meta">#${ihEsc(r.id)} · ${ihEsc(ihAgo(r.started_at))} · by ${ihEsc(r.triggered_by)}</span>
          <span>read ${ihEsc(r.rows_read)} · loaded ${ihEsc(r.values_loaded)} · rejected ${ihEsc(r.rows_rejected)}</span></summary>
        ${r.error ? `<div class="adm-err">${ihEsc(r.error)}</div>` : ''}
        ${rejects.length ? `<table class="adm-table ih-rejects"><thead><tr><th style="width:18%">Where</th><th>Why rejected</th><th style="width:34%">Row</th><th style="width:70px"></th></tr></thead><tbody>
          ${rejects.map(x => {
            const m = /unknown (org unit|metric) '([^']*)'/.exec(x.reason || '');
            const kind = m ? (m[1] === 'org unit' ? 'org_unit' : 'metric') : '';
            return `<tr><td class="ih-cell-meta">${ihEsc(x.ref || ('row ' + x.row))}</td><td>${ihEsc(x.reason)}</td>
              <td class="ih-mono">${ihEsc(Object.entries(x.data || {}).map(([k, v]) => `${k}=${v}`).join(', '))}</td>
              <td>${m ? `<button class="adm-act-btn edit" data-ih-act="prefill" data-kind="${kind}" data-key="${ihEsc(m[2])}">Map</button>` : ''}</td></tr>`;
          }).join('')}</tbody></table>
          ${r.rows_rejected > rejects.length ? `<div class="adm-td-meta" style="padding:6px 14px">Showing ${rejects.length} of ${ihEsc(r.rows_rejected)} rejected rows.</div>` : ''}` : ''}
      </details>`;
    }).join('') : '<div class="adm-empty">No runs yet</div>');
    ihSet(mapsEl, maps.length ? `<table class="adm-table"><thead><tr><th>Kind</th><th>Source key</th><th>MadziHub code</th></tr></thead><tbody>
      ${maps.map(m => `<tr><td><span class="ih-badge user">${ihEsc(m.kind === 'org_unit' ? 'unit' : 'measure')}</span></td>
        <td class="ih-mono">${ihEsc(m.external_key)}</td><td class="ih-mono">${ihEsc(m.internal_code)}</td></tr>`).join('')}
      </tbody></table>` : '<div class="adm-empty">No key mappings. Source keys that already equal MadziHub codes need none.</div>');
  }catch(e){ ihSet(runsEl, `<div class="adm-err">${ihEsc(e.message)}</div>`); }
}

function ihPrefillMapping(kind, key){
  document.getElementById('ih-map-kind').value = kind;
  document.getElementById('ih-map-ext').value = key;
  const target = document.getElementById('ih-map-int');
  target.value = '';
  target.focus();
}

async function ihSaveMapping(){
  const kind = document.getElementById('ih-map-kind').value;
  const ext = document.getElementById('ih-map-ext').value.trim();
  const internal = document.getElementById('ih-map-int').value.trim();
  if(!ext || !internal){ ihNotice('Enter both the source key and the MadziHub code.', 'warn'); return; }
  try{
    await ihApi(`/api/integration/sources/${encodeURIComponent(IH.selected)}/key-mappings`,
                {method:'PUT', body:[{kind, external_key:ext, internal_code:internal}]});
    ihNotice(`Mapped <code>${ihEsc(ext)}</code> → <code>${ihEsc(internal)}</code>. Run the source again to load those rows.`, 'ok');
    document.getElementById('ih-map-ext').value = '';
    document.getElementById('ih-map-int').value = '';
    ihLoadDetail(IH.selected);
  }catch(e){ ihNotice(ihEsc(e.message), 'danger'); }
}

/* Source editor modal */
function ihOpenEditor(code){
  const src = code ? IH.sources.find(s => s.code === code) : null;
  IH.editing = src ? src.code : null;
  document.getElementById('ih-modal-title').textContent = src ? `Edit ${src.code}` : 'Add data source';
  const f = id => document.getElementById(id);
  f('ih-f-code').value = src ? src.code : '';
  f('ih-f-code').disabled = !!src;
  f('ih-f-connector').disabled = !!src;
  f('ih-f-name').value = src ? src.name : '';
  f('ih-f-system').value = src ? src.system_type : 'file';
  f('ih-f-connector').value = src ? src.connector : 'file';
  f('ih-f-priority').value = src ? src.priority : 100;
  f('ih-f-schedule').value = src && src.schedule_minutes ? src.schedule_minutes : '';
  f('ih-f-owner').value = src && src.owner ? src.owner : '';
  const tpl = IH_TEMPLATES[src ? src.connector : 'file'];
  f('ih-f-config').value = JSON.stringify(src ? src.config : tpl.config, null, 2);
  f('ih-f-mapping').value = JSON.stringify(src ? src.mapping : tpl.mapping, null, 2);
  f('ih-f-reset').checked = false;
  f('ih-reset-field').style.display = src ? '' : 'none';
  f('ih-modal-err').style.display = 'none';
  document.getElementById('ih-src-modal').classList.add('open');
}
function ihCloseEditor(){ document.getElementById('ih-src-modal').classList.remove('open'); }
function ihConnectorChanged(){
  if(IH.editing) return;
  const tpl = IH_TEMPLATES[document.getElementById('ih-f-connector').value];
  document.getElementById('ih-f-config').value = JSON.stringify(tpl.config, null, 2);
  document.getElementById('ih-f-mapping').value = JSON.stringify(tpl.mapping, null, 2);
}
async function ihSaveEditor(){
  const f = id => document.getElementById(id);
  const err = f('ih-modal-err');
  const fail = msg => { err.textContent = msg; err.style.display = ''; };
  let config, mapping;
  try{ config = JSON.parse(f('ih-f-config').value || '{}'); }catch(e){ return fail('Connection settings are not valid JSON: ' + e.message); }
  try{ mapping = JSON.parse(f('ih-f-mapping').value || '{}'); }catch(e){ return fail('Mapping is not valid JSON: ' + e.message); }
  const schedule = f('ih-f-schedule').value.trim();
  const body = {
    name: f('ih-f-name').value.trim(), system_type: f('ih-f-system').value,
    config, mapping, priority: parseInt(f('ih-f-priority').value || '100', 10),
    owner: f('ih-f-owner').value.trim() || null,
    schedule_minutes: schedule ? parseInt(schedule, 10) : null,
  };
  if(!body.name) return fail('Name is required.');
  try{
    if(IH.editing){
      if(f('ih-f-reset').checked) body.reset_watermark = true;
      await ihApi(`/api/integration/sources/${encodeURIComponent(IH.editing)}`, {method:'PUT', body});
    }else{
      body.code = f('ih-f-code').value.trim();
      body.connector = f('ih-f-connector').value;
      await ihApi('/api/integration/sources', {method:'POST', body});
    }
  }catch(e){ return fail(e.message); }
  ihCloseEditor();
  ihNotice(`Saved <strong>${ihEsc(IH.editing || body.code)}</strong>.`, 'ok');
  ihLoadSources();
}

document.addEventListener('click', ev => {
  const btn = ev.target.closest('[data-ih-act]');
  if(!btn) return;
  const {ihAct:act, code} = btn.dataset;
  if(act === 'run') ihRun(code);
  else if(act === 'upload') ihUpload(code);
  else if(act === 'detail') { ihLoadDetail(code); document.getElementById('ih-detail').scrollIntoView({behavior:'smooth'}); }
  else if(act === 'edit') ihOpenEditor(code);
  else if(act === 'token') ihToken(code);
  else if(act === 'disable') ihSetEnabled(code, false);
  else if(act === 'enable') ihSetEnabled(code, true);
  else if(act === 'prefill') ihPrefillMapping(btn.dataset.kind, btn.dataset.key);
  else if(act === 'position') ihOpenMeasure(btn.dataset.metric);
});

/* ─────────────────────── Strategic Position (all users) ────────────────────── */

const IHP = { units: [], chart: null, data: null };

async function loadPosition(){
  const unitSel = document.getElementById('pos-unit');
  if(!IHP.units.length){
    IHP.units = await ihApi('/api/position/org-units', {fallback:[]});
    const depth = u => { let d = 0, p = u.parent_code; while(p && d < 8){ d++; p = (IHP.units.find(x => x.code === p) || {}).parent_code; } return d; };
    unitSel.replaceChildren(...(IHP.units.length ? IHP.units : [{code:'org', name:'Organisation'}]).map(u => {
      const opt = document.createElement('option');
      opt.value = u.code;
      opt.textContent = '\u00a0\u00a0'.repeat(u.parent_code ? depth(u) : 0) + u.name;  // textContent: no HTML
      return opt;
    }));
    if(IHP.units.some(u => u.code === 'org')) unitSel.value = 'org';
  }
  await ihRenderPosition();
}

function ihPosStatus(m){
  const g = m.gap_to_target;
  if(!m.where_we_are) return {cls:'viewer', icon:'○', label:'No data'};
  if(!g) return {cls:'viewer', icon:'–', label:'No target'};
  if(g.on_track === true) return {cls:'ok', icon:'✓', label:'On track'};
  if(g.on_track === false) return {cls:'danger', icon:'✕', label:'Off track'};
  if(g.period_complete === false) return {cls:'user', icon:'◔', label:'Year to date'};
  return {cls:'viewer', icon:'–', label:'Not assessed'};
}

async function ihRenderPosition(){
  const unit = document.getElementById('pos-unit').value || 'org';
  const ptype = document.getElementById('pos-period').value || 'month';
  const grid = document.getElementById('pos-grid');
  ihSet(grid, '<div class="adm-empty">Loading…</div>');
  try{
    const [data, fresh] = await Promise.all([
      ihApi(`/api/position?org_unit=${encodeURIComponent(unit)}&period_type=${encodeURIComponent(ptype)}`),
      ihApi('/api/position/sources/freshness', {fallback:[]}),
    ]);
    IHP.data = data;
    const stale = fresh.filter(s => s.enabled && (s.overdue || s.last_status === 'failed'));
    ihSet(document.getElementById('pos-fresh'), fresh.length
      ? `<span class="ih-badge ${stale.length ? 'warn' : 'ok'}">${stale.length ? '!' : '✓'} ${stale.length ? `${stale.length} source${stale.length > 1 ? 's' : ''} need attention` : 'All sources current'}</span>
         ${fresh.map(s => `<span class="pos-src" title="${ihEsc(s.name)}">${ihEsc(s.code)}: ${ihEsc(ihAgo(s.last_success_at))}</span>`).join('')}`
      : '');
    const withData = data.measures.filter(m => m.where_we_are);
    if(!withData.length){
      ihSet(grid, `<div class="pos-empty">No measures have data for this unit and period yet.
        ${String((getUser() || {}).role || '').toLowerCase() === 'admin' ? 'Connect sources in <strong>Administration → Data Sources</strong>.' : 'Ask an administrator to connect data sources.'}</div>`);
      ihSet(document.getElementById('pos-summary'), '');
      return;
    }
    const counts = {ok:0, danger:0, other:0};
    withData.forEach(m => { const s = ihPosStatus(m).cls; counts[s === 'ok' ? 'ok' : s === 'danger' ? 'danger' : 'other']++; });
    ihSet(document.getElementById('pos-summary'), `
      <div class="adm-stat-card green"><div class="adm-stat-val">${counts.ok}</div><div class="adm-stat-lbl">✓ On track</div></div>
      <div class="adm-stat-card red"><div class="adm-stat-val">${counts.danger}</div><div class="adm-stat-lbl">✕ Off track</div></div>
      <div class="adm-stat-card"><div class="adm-stat-val">${counts.other}</div><div class="adm-stat-lbl">No verdict yet</div></div>
      <div class="adm-stat-card purple"><div class="adm-stat-val">${withData.length}</div><div class="adm-stat-lbl">Measures reporting</div></div>`);
    const groups = {};
    data.measures.forEach(m => { (groups[m.category || 'Other'] = groups[m.category || 'Other'] || []).push(m); });
    ihSet(grid, Object.entries(groups).map(([cat, ms]) => `
      <div class="pos-cat">${ihEsc(cat)}</div>
      <div class="pos-cards">${ms.map(m => {
        const st = ihPosStatus(m), cur = m.where_we_are, g = m.gap_to_target, t = m.trend;
        const unitLbl = m.metric.unit;
        const trend = t && t.improving !== null && t.improving !== undefined
          ? `<span class="pos-trend ${t.improving ? 'up' : 'down'}">${t.improving ? '▲ improving' : '▼ worsening'}${t.change_pct !== null ? ` (${ihEsc(t.change_pct)}%)` : ''}</span>` : '';
        const extra = [
          m.metric.formula ? 'computed' : '',
          m.rolled_up ? 'rolled up' : '',
          cur && cur.months_reporting ? `${ihEsc(cur.months_reporting)}/${ihEsc(cur.months_expected)} months` : '',
        ].filter(Boolean).join(' · ');
        return `<button class="pos-card" data-ih-act="position" data-metric="${ihEsc(m.metric.code)}" ${cur ? '' : 'disabled'}>
          <div class="pos-card-top"><span class="pos-name">${ihEsc(m.metric.name)}</span><span class="ih-badge ${st.cls}">${st.icon} ${ihEsc(st.label)}</span></div>
          <div class="pos-val">${cur ? ihEsc(ihNum(cur.value, unitLbl)) : '—'}</div>
          <div class="pos-meta">${cur ? ihEsc(ihPeriodLabel(cur.period, data.period_type))
            : (!m.metric.formula && m.metric.aggregation !== 'sum'
               ? 'Not added up across units (a latest or average value); select a single unit'
               : 'no data')}${extra ? ' · ' + extra : ''}</div>
          ${g ? `<div class="pos-target">Target ${ihEsc(ihNum(g.target, unitLbl))} · gap ${ihEsc(ihNum(g.difference, unitLbl))}</div>`
              : (m.next_target ? `<div class="pos-target">Next target ${ihEsc(ihNum(m.next_target.value, unitLbl))} (${ihEsc(ihPeriodLabel(m.next_target.period, m.next_target.period_type))})</div>` : '')}
          ${g && g.note ? `<div class="pos-note">${ihEsc(g.note)}</div>` : ''}
          ${trend}
        </button>`;
      }).join('')}</div>`).join(''));
  }catch(e){ ihSet(grid, `<div class="adm-err">${ihEsc(e.message)}</div>`); }
}

async function ihOpenMeasure(code){
  const unit = document.getElementById('pos-unit').value || 'org';
  const ptype = document.getElementById('pos-period').value || 'month';
  const panel = document.getElementById('pos-detail');
  panel.style.display = '';
  panel.scrollIntoView({behavior:'smooth', block:'start'});
  const body = document.getElementById('pos-detail-body');
  ihSet(body, '<div class="adm-empty">Loading…</div>');
  try{
    const p = await ihApi(`/api/position/${encodeURIComponent(code)}?org_unit=${encodeURIComponent(unit)}&period_type=${encodeURIComponent(ptype)}`);
    const series = [...p.where_we_were, ...(p.where_we_are ? [p.where_we_are] : [])];
    const u = p.metric.unit;
    document.getElementById('pos-detail-title').textContent = p.metric.name;
    const how = p.metric.formula ? `Computed as <code>${ihEsc(p.metric.formula)}</code>${p.rolled_up ? ' from rolled-up components' : ''}.`
              : p.rolled_up ? 'Sum of the units below this one.' : 'Reported directly by the source.';
    ihSet(body, `
      <div class="pos-how">${how} ${p.derived === 'from_month' ? 'Built from monthly values.' : ''}</div>
      <div class="pos-chart-wrap"><canvas id="pos-chart" aria-label="${ihEsc(p.metric.name)} over time with targets" role="img"></canvas></div>
      <div class="pos-cols">
        <div><div class="adm-sys-card-title">Where we were and are</div>
          <div class="adm-table-wrap"><table class="adm-table"><thead><tr><th>Period</th><th style="text-align:right">Value</th><th>Source</th></tr></thead><tbody>
          ${series.slice().reverse().map(s => `<tr><td>${ihEsc(ihPeriodLabel(s.period, p.period_type))}</td>
            <td style="text-align:right" class="ih-mono">${ihEsc(ihNum(s.value, u))}</td>
            <td class="ih-cell-meta" title="${ihEsc(s.source_ref || '')}">${ihEsc(s.source)}${s.inputs ? ' · ' + ihEsc(Object.entries(s.inputs).map(([k, v]) => `${k}=${ihNum(v)}`).join(', ')) : ''}</td></tr>`).join('')}
          </tbody></table></div></div>
        <div><div class="adm-sys-card-title">Where we are going</div>
          ${p.where_we_are_going.length ? `<div class="adm-table-wrap"><table class="adm-table"><thead><tr><th>Period</th><th style="text-align:right">Target</th><th>Basis</th></tr></thead><tbody>
          ${p.where_we_are_going.map(t => `<tr><td>${ihEsc(ihPeriodLabel(t.period, t.period_type))}</td>
            <td style="text-align:right" class="ih-mono">${ihEsc(ihNum(t.value, u))}</td><td class="ih-cell-meta" title="${ihEsc(t.note || '')}">${ihEsc(t.basis.replace('_', ' '))}</td></tr>`).join('')}
          </tbody></table></div>` : '<div class="adm-empty">No future targets set for this unit and period type.</div>'}
        </div>
      </div>`);
    ihDrawChart(p, series);
  }catch(e){ ihSet(body, `<div class="adm-err">${ihEsc(e.message)}</div>`); }
}

function ihDrawChart(p, series){
  if(IHP.chart){ IHP.chart.destroy(); IHP.chart = null; }
  const canvas = document.getElementById('pos-chart');
  if(!canvas || typeof Chart === 'undefined') return;
  const css = getComputedStyle(document.documentElement);
  const tok = (name, fallback) => (css.getPropertyValue(name) || '').trim() || fallback;
  const blue = tok('--ds-blue', '#2563EB'), muted = tok('--ds-text-muted', '#64748b'), border = tok('--ds-border', '#e2e8f0');
  const targets = [...(p.gap_to_target ? [{period:p.gap_to_target.target_period, value:p.gap_to_target.target}] : []),
                   ...p.where_we_are_going].filter(t => t);
  const labels = [...new Set([...series.map(s => s.period), ...targets.map(t => t.period)])].sort();
  const byPeriod = (rows) => labels.map(l => { const r = rows.find(x => x.period === l); return r ? r.value : null; });
  const datasets = [{label:'Actual', data:byPeriod(series), borderColor:blue, backgroundColor:blue,
                     borderWidth:2, pointRadius:4, pointHoverRadius:6, tension:0, spanGaps:true}];
  if(targets.length) datasets.push({label:'Target', data:byPeriod(targets), borderColor:muted, backgroundColor:muted,
                     borderWidth:2, borderDash:[6, 4], pointRadius:4, pointStyle:'rectRot', spanGaps:true});
  IHP.chart = new Chart(canvas, {
    type:'line',
    data:{labels:labels.map(l => ihPeriodLabel(l, p.period_type)), datasets},
    options:{
      responsive:true, maintainAspectRatio:false, animation:false,
      interaction:{mode:'index', intersect:false},
      plugins:{legend:{display:targets.length > 0, position:'top', align:'end', labels:{usePointStyle:true, color:muted, boxWidth:8}},
               tooltip:{callbacks:{label:c => `${c.dataset.label}: ${ihNum(c.parsed.y, p.metric.unit)}`}}},
      scales:{x:{grid:{display:false}, ticks:{color:muted, maxRotation:0, autoSkip:true, maxTicksLimit:8}},
              y:{grid:{color:border}, border:{display:false}, ticks:{color:muted, callback:v => ihNum(v, p.metric.unit)}}},
    },
  });
}

/* ───────────────────── Measures & Targets (admin) ───────────────────── */

const IHM = { metrics: [], units: [], editing: null, checkTimer: null, periods: {} };
const IHM_AGG = {
  sum: 'Added up (volumes, money, counts)', avg: 'Averaged (ratios, rates, levels)',
  last: 'Latest value (customers, stock)', max: 'Highest', min: 'Lowest',
};
const IHM_DIR = { higher: 'Higher is better', lower: 'Lower is better', range: 'Within a band' };
const IHM_BASIS = { strategic_plan: 'Strategic plan', budget: 'Budget', regulator: 'Regulator', internal: 'Internal' };

async function ihmLoad(){
  const tbody = document.getElementById('ihm-tbody');
  try{
    [IHM.metrics, IHM.units] = await Promise.all([
      ihApi('/api/integration/metrics', {fallback:[]}),
      ihApi('/api/integration/org-units', {fallback:[]}),
    ]);
    if(!IHM.metrics.length){
      ihSetRows(tbody, '<tr><td colspan="6" class="adm-empty">No measures yet. Add one, or set up from existing returns in Data Sources.</td></tr>');
    }else{
      ihSetRows(tbody, IHM.metrics.map(m => `<tr>
        <td><div class="adm-user-name">${ihEsc(m.name)}</div><div class="adm-user-fullname">${ihEsc(m.code)}${m.category ? ' · ' + ihEsc(m.category) : ''}${m.unit ? ' · ' + ihEsc(m.unit) : ''}</div></td>
        <td class="ih-cell-meta">${ihEsc(IHM_AGG[m.aggregation] || m.aggregation)}</td>
        <td class="ih-cell-meta">${ihEsc(IHM_DIR[m.direction] || m.direction)}</td>
        <td>${m.formula ? `<code class="ih-mono">${ihEsc(m.formula)}</code>` : '<span class="ih-cell-meta">Loaded from sources</span>'}</td>
        <td>${m.is_active ? '<span class="ih-badge ok">✓ Active</span>' : '<span class="ih-badge viewer">Inactive</span>'}</td>
        <td><div class="adm-act-row">
          <button class="adm-act-btn edit" data-ihm-act="edit" data-code="${ihEsc(m.code)}">Edit</button>
          <button class="adm-act-btn reset" data-ihm-act="targets" data-code="${ihEsc(m.code)}">Targets</button>
          <button class="adm-act-btn ${m.is_active ? 'danger' : 'edit'}" data-ihm-act="toggle" data-code="${ihEsc(m.code)}">${m.is_active ? 'Deactivate' : 'Activate'}</button>
        </div></td></tr>`).join(''));
    }
    ihmFillTargetPickers();
  }catch(e){ ihSetRows(tbody, `<tr><td colspan="6" class="adm-err">${ihEsc(e.message)}</td></tr>`); }
}

function ihmNotice(html, tone='info'){
  const el = document.getElementById('ihm-notice');
  el.className = `ih-notice ${tone}`; ihSet(el, html); el.style.display = html ? '' : 'none';
}

function ihmMetricBody(m){
  return {code:m.code, name:m.name, unit:m.unit || null, category:m.category || null, aggregation:m.aggregation,
          direction:m.direction, formula:m.formula || null, description:m.description || null, is_active:m.is_active};
}

async function ihmToggle(code){
  const m = IHM.metrics.find(x => x.code === code);
  if(!m) return;
  if(m.is_active && !confirm(`Deactivate ${m.name}? It disappears from the Strategic Position page; its data and targets are kept.`)) return;
  try{
    await ihApi('/api/integration/metrics', {method:'POST', body:[{...ihmMetricBody(m), is_active:!m.is_active}]});
    ihmNotice(`${ihEsc(m.name)} ${m.is_active ? 'deactivated' : 'activated'}.`, 'ok');
  }catch(e){ ihmNotice(ihEsc(e.message), 'danger'); }
  ihmLoad();
}

/* Measure editor with live formula check */
function ihmOpenEditor(code){
  const m = code ? IHM.metrics.find(x => x.code === code) : null;
  IHM.editing = m ? m.code : null;
  const f = id => document.getElementById(id);
  f('ihm-modal-title').textContent = m ? `Edit ${m.name}` : 'Add measure';
  f('ihm-f-code').value = m ? m.code : ''; f('ihm-f-code').disabled = !!m;
  f('ihm-f-name').value = m ? m.name : '';
  f('ihm-f-unit').value = m && m.unit ? m.unit : '';
  f('ihm-f-category').value = m && m.category ? m.category : '';
  f('ihm-f-agg').value = m ? m.aggregation : 'sum';
  f('ihm-f-dir').value = m ? m.direction : 'higher';
  f('ihm-f-formula').value = m && m.formula ? m.formula : '';
  f('ihm-f-desc').value = m && m.description ? m.description : '';
  f('ihm-f-active').checked = m ? m.is_active : true;
  f('ihm-modal-err').style.display = 'none';
  ihSet(f('ihm-formula-check'), '');
  ihmRefreshCodes();
  f('ihm-modal').classList.add('open');
  if(f('ihm-f-formula').value) ihmCheckFormula();
}
function ihmCloseEditor(){ document.getElementById('ihm-modal').classList.remove('open'); }
function ihmRefreshCodes(){
  ihSet(document.getElementById('ihm-codes'), IHM.metrics.filter(m => m.code !== IHM.editing).map(m =>
    `<button type="button" class="ih-code-chip" data-ihm-act="insert" data-code="${ihEsc(m.code)}" title="${ihEsc(m.name)}">${ihEsc(m.code)}</button>`).join(''));
}
function ihmInsertCode(code){
  const ta = document.getElementById('ihm-f-formula');
  const at = ta.selectionStart ?? ta.value.length;
  ta.value = ta.value.slice(0, at) + code + ta.value.slice(ta.selectionEnd ?? at);
  ta.focus(); ta.selectionStart = ta.selectionEnd = at + code.length;
  ihmCheckFormulaSoon();
}
function ihmCheckFormulaSoon(){ clearTimeout(IHM.checkTimer); IHM.checkTimer = setTimeout(ihmCheckFormula, 400); }
async function ihmCheckFormula(){
  const out = document.getElementById('ihm-formula-check');
  const formula = document.getElementById('ihm-f-formula').value.trim();
  const code = (document.getElementById('ihm-f-code').value.trim() || '_new_measure').toLowerCase();
  if(!formula){ ihSet(out, '<span class="ih-cell-meta">No formula: values are loaded from data sources.</span>'); return; }
  try{
    const r = await ihApi('/api/integration/metrics/validate-formula', {method:'POST',
      body:{code, formula, aggregation:document.getElementById('ihm-f-agg').value}});
    if(!r.ok){ ihSet(out, `<span class="ih-badge danger">✕ ${ihEsc(r.error)}</span>`); return; }
    const unit = document.getElementById('ihm-f-unit').value.trim();
    const pv = r.preview
      ? ` Organisation, ${ihEsc(ihPeriodLabel(r.preview.period, 'month'))}: <strong>${ihEsc(ihNum(r.preview.value, unit))}</strong>
         <span class="ih-cell-meta">(${ihEsc(Object.entries(r.preview.inputs || {}).map(([k, v]) => `${k} = ${ihNum(v)}`).join(', '))})</span>`
      : ' <span class="ih-cell-meta">No data yet to preview.</span>';
    ihSet(out, `<span class="ih-badge ok">✓ Valid</span> Uses ${r.references.map(c => `<code>${ihEsc(c)}</code>`).join(', ')}.${pv}`);
  }catch(e){ ihSet(out, `<span class="ih-badge danger">✕ ${ihEsc(e.message)}</span>`); }
}
async function ihmSaveEditor(){
  const f = id => document.getElementById(id);
  const err = f('ihm-modal-err');
  const body = {
    code: f('ihm-f-code').value.trim(), name: f('ihm-f-name').value.trim(),
    unit: f('ihm-f-unit').value.trim() || null, category: f('ihm-f-category').value.trim() || null,
    aggregation: f('ihm-f-agg').value, direction: f('ihm-f-dir').value,
    formula: f('ihm-f-formula').value.trim() || null, description: f('ihm-f-desc').value.trim() || null,
    is_active: f('ihm-f-active').checked,
  };
  if(!body.code || !body.name){ err.textContent = 'Code and name are required.'; err.style.display = ''; return; }
  try{ await ihApi('/api/integration/metrics', {method:'POST', body:[body]}); }
  catch(e){ err.textContent = e.message; err.style.display = ''; return; }
  ihmCloseEditor();
  ihmNotice(`Saved <strong>${ihEsc(body.name)}</strong>.`, 'ok');
  ihmLoad();
}

/* Targets */
function ihmFillTargetPickers(){
  const mSel = document.getElementById('ihm-t-metric'), uSel = document.getElementById('ihm-t-unit');
  const keepM = mSel.value, keepU = uSel.value;
  const opt = (value, text) => { const o = document.createElement('option'); o.value = value; o.textContent = text; return o; };
  mSel.replaceChildren(...IHM.metrics.map(m => opt(m.code, `${m.name} (${m.code})`)));
  uSel.replaceChildren(...IHM.units.map(u => opt(u.code, `${u.name} (${u.code})`)));
  if(keepM && IHM.metrics.some(m => m.code === keepM)) mSel.value = keepM;
  if(keepU && IHM.units.some(u => u.code === keepU)) uSel.value = keepU;
  else if(IHM.units.some(u => u.code === 'org')) uSel.value = 'org';
  ihmLoadTargets();
}
async function ihmPeriods(type){
  if(!IHM.periods[type]) IHM.periods[type] = await ihApi(`/api/integration/period-options?period_type=${type}&back=4&forward=8`, {fallback:[]});
  return IHM.periods[type];
}
async function ihmLoadTargets(){
  const metric = document.getElementById('ihm-t-metric').value;
  const unit = document.getElementById('ihm-t-unit').value;
  const ptype = document.getElementById('ihm-t-ptype').value;
  const tbody = document.getElementById('ihm-t-tbody');
  const pSel = document.getElementById('ihm-t-period');
  const periods = await ihmPeriods(ptype);
  pSel.replaceChildren(...periods.map(p => { const o = document.createElement('option'); o.value = p.start; o.textContent = p.label + (p.current ? ' (current)' : ''); return o; }));
  const cur = periods.find(p => p.current); if(cur) pSel.value = cur.start;
  if(!metric){ ihSetRows(tbody, '<tr><td colspan="6" class="adm-empty">Add a measure first.</td></tr>'); return; }
  try{
    const rows = await ihApi(`/api/integration/targets?metric_code=${encodeURIComponent(metric)}&org_unit_code=${encodeURIComponent(unit)}&period_type=${encodeURIComponent(ptype)}`, {fallback:[]});
    const m = IHM.metrics.find(x => x.code === metric) || {};
    ihSetRows(tbody, rows.length ? rows.map(t => `<tr>
      <td>${ihEsc(t.label)}</td><td style="text-align:right" class="ih-mono">${ihEsc(ihNum(t.value, m.unit))}</td>
      <td class="ih-cell-meta">${t.lower != null || t.upper != null ? `${ihEsc(ihNum(t.lower, m.unit))} – ${ihEsc(ihNum(t.upper, m.unit))}` : '—'}</td>
      <td class="ih-cell-meta">${ihEsc(IHM_BASIS[t.basis] || t.basis)}</td><td class="ih-cell-meta">${ihEsc(t.note || '')}</td>
      <td><button class="adm-act-btn danger" data-ihm-act="del-target" data-id="${ihEsc(t.id)}" data-label="${ihEsc(t.label)}">Remove</button></td></tr>`).join('')
      : '<tr><td colspan="6" class="adm-empty">No targets for this measure, unit and period type.</td></tr>');
  }catch(e){ ihSetRows(tbody, `<tr><td colspan="6" class="adm-err">${ihEsc(e.message)}</td></tr>`); }
}
async function ihmSaveTarget(){
  const f = id => document.getElementById(id);
  const num = id => { const v = f(id).value.trim(); return v === '' ? null : Number(v); };
  const value = num('ihm-t-value');
  if(value === null || Number.isNaN(value)){ ihmNotice('Enter a target value.', 'warn'); return; }
  const body = [{metric_code:f('ihm-t-metric').value, org_unit_code:f('ihm-t-unit').value, period_type:f('ihm-t-ptype').value,
                 period_start:f('ihm-t-period').value, value, lower:num('ihm-t-lower'), upper:num('ihm-t-upper'),
                 basis:f('ihm-t-basis').value, note:f('ihm-t-note').value.trim() || null}];
  try{
    await ihApi('/api/integration/targets', {method:'POST', body});
    ihmNotice(`Target saved for ${ihEsc(f('ihm-t-period').selectedOptions[0]?.textContent || '')}. Saving the same period and basis again replaces it.`, 'ok');
    ['ihm-t-value','ihm-t-lower','ihm-t-upper','ihm-t-note'].forEach(id => { f(id).value = ''; });
    ihmLoadTargets();
  }catch(e){ ihmNotice(ihEsc(e.message), 'danger'); }
}
async function ihmDeleteTarget(id, label){
  if(!confirm(`Remove the target for ${label}?`)) return;
  try{ await ihApi(`/api/integration/targets/${encodeURIComponent(id)}`, {method:'DELETE'}); ihmLoadTargets(); }
  catch(e){ ihmNotice(ihEsc(e.message), 'danger'); }
}

document.addEventListener('click', ev => {
  const btn = ev.target.closest('[data-ihm-act]');
  if(!btn) return;
  const {ihmAct:act, code} = btn.dataset;
  if(act === 'edit') ihmOpenEditor(code);
  else if(act === 'toggle') ihmToggle(code);
  else if(act === 'insert') ihmInsertCode(code);
  else if(act === 'del-target') ihmDeleteTarget(btn.dataset.id, btn.dataset.label);
  else if(act === 'targets'){
    document.getElementById('ihm-t-metric').value = code;
    ihmLoadTargets();
    document.getElementById('ihm-targets').scrollIntoView({behavior:'smooth', block:'start'});
  }
});
