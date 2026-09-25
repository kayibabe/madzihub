/* ══════════════════════════════════════════════════════════════════════════
   Performance & Governance — shared toolkit (window.MZ) and platform pages
   · My Work, Actions, Periods, Access & Scope, Audit Trail
   Other modules (mod-strategy.js, mod-scorecard.js ...) build on MZ.
   Relies on app-core.js globals: API, getToken, getUser, navigate, pageCache, DOMPurify.
   The server enforces every permission; the UI only hides what cannot succeed.
   Everything from the server is escaped with MZ.esc before it reaches innerHTML,
   and the markup is sanitised again with DOMPurify.
   ══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';

const MZ = window.MZ = window.MZ || {};
const LOADERS = window.MADZI_PAGE_LOADERS = window.MADZI_PAGE_LOADERS || {};
MZ.pages = new Set();

/* ── basics ─────────────────────────────────────────────────────────────── */
MZ.esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
MZ.$ = id => document.getElementById(id);
MZ.html = (el, html) => { if(typeof el === 'string') el = MZ.$(el); if(el) el.innerHTML = DOMPurify.sanitize(html); return el; };
MZ.label = s => { const t = String(s ?? '').replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
function asDate(iso){
  if(!iso) return null;
  if(/^\d{4}-\d{2}-\d{2}$/.test(iso)) return new Date(iso + 'T00:00:00');
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
}
MZ.date = iso => { const d = asDate(iso); return d ? d.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}) : '—'; };
MZ.dateTime = iso => { const d = asDate(iso); return d ? d.toLocaleString('en-GB', {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'}) : '—'; };
MZ.today = () => new Date().toISOString().slice(0, 10);
MZ.num = (v, dp = 2) => {
  if(v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('en-GB', {maximumFractionDigits: dp});
};

const TONES = {
  ok: ['closed','completed','approved','effective','published','verified','achieved','on_track','active','signed',
       'implemented','complete','validated','accepted','pass','current','ok','low','within_appetite'],
  warn: ['in_progress','submitted','pending','review','in_review','awaiting_verification','at_risk','draft',
         'response_submitted','closure_requested','action_in_progress','midterm_review','medium','warn','provisional',
         'incomplete','planned','partially_accepted','not_started','tolerance'],
  danger: ['overdue','returned','rejected','off_track','cancelled','failed','fail','breach','high','critical',
           'withdrawn','superseded','locked','not_submitted','outside_appetite','appealed'],
  info: ['open','not_applicable','approved_pending','scheduled','under_appeal','in_progress_review'],
};
MZ.tone = s => { const k = String(s || '').toLowerCase(); for(const [t, list] of Object.entries(TONES)) if(list.includes(k)) return t; return ''; };
MZ.badge = (status, tone, text) => `<span class="mz-badge ${tone ?? MZ.tone(status)}">${MZ.esc(text ?? MZ.label(status || '—'))}</span>`;

/* ── API ─────────────────────────────────────────────────────────────────── */
MZ.api = async function(path, {method = 'GET', body, form, raw = false} = {}){
  const headers = {};
  const token = getToken();
  if(token) headers.Authorization = 'Bearer ' + token;
  let payload;
  if(form){ payload = form; }
  else if(body !== undefined){ headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(`${API}${path}`, {method, headers, body: payload});
  if(raw && res.ok) return res;
  const text = await res.text();
  let data = null;
  try{ data = text ? JSON.parse(text) : null; }catch{}
  if(!res.ok){
    let detail = data && data.detail;
    if(Array.isArray(detail)) detail = detail.map(e => `${(e.loc || []).slice(1).join('.') || 'value'}: ${e.msg}`).join('; ');
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
};
MZ.download = async function(path, fallbackName){
  const res = await MZ.api(path, {raw: true});
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = m ? decodeURIComponent(m[1]) : (fallbackName || 'download');
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
};

/* ── toast (announced to screen readers) ─────────────────────────────────── */
MZ.toast = function(msg, tone = ''){
  let host = MZ.$('mz-toast-host');
  if(!host){
    host = document.createElement('div');
    host.id = 'mz-toast-host'; host.className = 'mz-toast-host';
    host.setAttribute('role', 'status'); host.setAttribute('aria-live', 'polite');
    document.body.appendChild(host);
  }
  const t = document.createElement('div');
  t.className = `mz-toast ${tone}`; t.textContent = msg;
  host.appendChild(t);
  setTimeout(() => t.remove(), tone === 'danger' ? 8000 : 4000);
};
MZ.fail = (e) => { console.error(e); MZ.toast(e.message || String(e), 'danger'); };

/* ── who am I, which units ───────────────────────────────────────────────── */
const RANK = {viewer: 0, contributor: 1, reviewer: 2, approver: 3};
MZ.me = null; MZ.units = [];
MZ.loadMe = async function(force = false){
  if(MZ.me && !force) return MZ.me;
  const [me, units] = await Promise.all([MZ.api('/api/platform/me'), MZ.api('/api/platform/org-units')]);
  MZ.me = me; MZ.units = units;
  applyNavVisibility();
  const badge = MZ.$('mz-nav-unread');
  if(badge){ badge.textContent = me.unread_notifications || ''; badge.hidden = !me.unread_notifications; }
  return me;
};
MZ.roleOn = code => {
  if(!MZ.me) return null;
  if(MZ.me.account_role === 'admin') return 'approver';
  const own = (MZ.me.units || {})[code];
  const wide = MZ.me.org_wide_role;
  if(own && (!wide || RANK[own] > RANK[wide])) return own;
  return wide || null;
};
MZ.can = (code, role) => {
  if(!MZ.me || MZ.me.read_only) return false;
  const held = MZ.roleOn(code);
  return !!held && RANK[held] >= RANK[role];
};
MZ.canAnywhere = role => !!MZ.me && !MZ.me.read_only && (MZ.me.account_role === 'admin' || MZ.units.some(u => MZ.can(u.code, role)));
MZ.hasFunction = f => !!MZ.me && (MZ.me.functions || []).includes(f);
MZ.isAdmin = () => !!MZ.me && MZ.me.account_role === 'admin';
MZ.unitName = code => (MZ.units.find(u => u.code === code) || {}).name || code || '—';
MZ.unitOptions = (minRole = 'viewer', {includeBlank = false, blankLabel = 'All units'} = {}) => {
  const depth = {};
  const byCode = Object.fromEntries(MZ.units.map(u => [u.code, u]));
  const d = c => { if(depth[c] !== undefined) return depth[c]; const p = byCode[c]?.parent_code; return depth[c] = p && byCode[p] ? d(p) + 1 : 0; };
  const opts = MZ.units.filter(u => minRole === 'viewer' || MZ.can(u.code, minRole))
    .sort((a, b) => a.code === 'org' ? -1 : b.code === 'org' ? 1 : a.code.localeCompare(b.code))
    .map(u => ({value: u.code, label: `${' '.repeat(d(u.code))}${u.name}`}));
  return includeBlank ? [{value: '', label: blankLabel}, ...opts] : opts;
};

function applyNavVisibility(){
  document.querySelectorAll('[data-mz-requires]').forEach(el => {
    const req = el.getAttribute('data-mz-requires');
    let ok = true;
    for(const part of req.split('|')){
      ok = part === 'admin' ? MZ.isAdmin() : part.startsWith('function:') ? MZ.hasFunction(part.slice(9)) : part === 'any' ? true : false;
      if(ok) break;
    }
    el.hidden = !ok;
  });
}

/* Region-limited users work only in this workspace: land them on My Work. */
window.MADZI_LANDING_OVERRIDE = async function(){
  const me = await MZ.loadMe(true);
  document.body.classList.toggle('mz-scoped', !me.org_wide);
  return me.org_wide ? null : 'my-work';
};

/* ── page registration ───────────────────────────────────────────────────── */
MZ.page = function(key, loader){
  MZ.pages.add(key);
  LOADERS[key] = async function(){
    const root = MZ.$('mz-' + key);
    try{
      await MZ.loadMe();
      await loader(root);
    }catch(e){
      MZ.html(root, `<div class="mz-notice danger">Could not load this page: ${MZ.esc(e.message)}</div>`);
      console.error(key, e);
    }
  };
};
MZ.refresh = key => { if(typeof pageCache !== 'undefined') delete pageCache[key]; return LOADERS[key] && LOADERS[key](); };
/* Module pages always show fresh data: drop the page cache before navigating to them. */
(function wrapNavigate(){
  const install = () => {
    if(typeof window.navigate !== 'function' || window.navigate.__mzWrapped) return false;
    const orig = window.navigate;
    window.navigate = function(page){
      if(MZ.pages.has(page) && typeof pageCache !== 'undefined') delete pageCache[page];
      const out = orig.apply(this, arguments);
      document.body.classList.toggle('mz-module-page', MZ.pages.has(currentPage));
      return out;
    };
    window.navigate.__mzWrapped = true;
    return true;
  };
  if(!install()) document.addEventListener('DOMContentLoaded', install);
})();

MZ.header = (title, sub, actionsHtml = '') =>
  `<div class="mz-hdr"><div><h1 class="mz-title">${MZ.esc(title)}</h1>${sub ? `<p class="mz-sub">${sub}</p>` : ''}</div>
   <div class="mz-btn-row">${actionsHtml}</div></div>`;

/* ── tables ──────────────────────────────────────────────────────────────── */
MZ.table = function({columns, rows, empty = 'Nothing to show.', caption = '', rowId = null, selected = null}){
  if(!rows || !rows.length) return `<div class="mz-table-wrap"><div class="mz-empty">${MZ.esc(empty)}</div></div>`;
  const head = columns.map(c => `<th scope="col" class="${c.num ? 'num' : ''}">${MZ.esc(c.label)}</th>`).join('');
  const body = rows.map(r => {
    const id = rowId ? rowId(r) : null;
    const attrs = id !== null && id !== undefined
      ? ` class="mz-click${String(selected) === String(id) ? ' mz-selected' : ''}" data-row-id="${MZ.esc(id)}" tabindex="0"` : '';
    return `<tr${attrs}>${columns.map(c => `<td class="${c.num ? 'num' : ''} ${c.cls || ''}">${c.render ? c.render(r) : MZ.esc(r[c.key])}</td>`).join('')}</tr>`;
  }).join('');
  return `<div class="mz-table-wrap"><table class="mz-table">${caption ? `<caption>${MZ.esc(caption)}</caption>` : ''}<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};
/* Row selection by click or Enter/Space. */
MZ.onRow = function(host, handler){
  if(!host || host.__mzRow) return;
  host.__mzRow = true;
  host.addEventListener('click', e => {
    if(e.target.closest('button,a,input,select,textarea,label')) return;
    const tr = e.target.closest('tr[data-row-id]');
    if(tr) handler(tr.getAttribute('data-row-id'));
  });
  host.addEventListener('keydown', e => {
    const tr = e.target.closest('tr[data-row-id]');
    if(tr && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); handler(tr.getAttribute('data-row-id')); }
  });
};
/* Delegated buttons: <button data-mz="name" data-id=".."> */
MZ.onAct = function(host, handlers){
  if(!host) return;
  host.__mzHandlers = handlers;
  if(host.__mzAct) return;
  host.__mzAct = true;
  host.addEventListener('click', async e => {
    const btn = e.target.closest('[data-mz]');
    if(!btn || !host.contains(btn) || btn.disabled) return;
    const fn = host.__mzHandlers[btn.getAttribute('data-mz')];
    if(!fn) return;
    e.preventDefault();
    btn.disabled = true;
    try{ await fn(btn.dataset, btn); }catch(err){ MZ.fail(err); }
    finally{ if(btn.isConnected) btn.disabled = false; }
  });
};

/* ── tabs (WAI-ARIA tablist with arrow keys) ─────────────────────────────── */
MZ.tabs = function(host, tabs, active, onSelect){
  const id = host.id || ('mzt' + Math.random().toString(36).slice(2));
  MZ.html(host, `<div class="mz-tabs" role="tablist">${tabs.map(t =>
    `<button type="button" class="mz-tab" role="tab" id="${id}-${MZ.esc(t.key)}" data-tab="${MZ.esc(t.key)}" aria-selected="${t.key === active}" tabindex="${t.key === active ? 0 : -1}">${MZ.esc(t.label)}${t.count !== undefined && t.count !== null ? `<span class="mz-count">${MZ.esc(t.count)}</span>` : ''}</button>`).join('')}</div>`);
  const list = host.querySelector('[role=tablist]');
  const select = key => { onSelect(key); };
  list.addEventListener('click', e => { const b = e.target.closest('[data-tab]'); if(b) select(b.dataset.tab); });
  list.addEventListener('keydown', e => {
    const btns = [...list.querySelectorAll('[role=tab]')];
    const i = btns.indexOf(document.activeElement);
    if(i < 0) return;
    const next = e.key === 'ArrowRight' ? btns[(i + 1) % btns.length] : e.key === 'ArrowLeft' ? btns[(i - 1 + btns.length) % btns.length] : null;
    if(next){ e.preventDefault(); next.focus(); select(next.dataset.tab); }
  });
};

/* ── forms in a native <dialog> (focus handling and Esc come from the browser) ── */
let formSeq = 0;
/* Field names are prefixed: DOMPurify drops name attributes that shadow document or form
   properties (title, body, action ...), so a field called "title" would otherwise vanish. */
const FIELD_PREFIX = 'f_';
function fieldHtml(f, idp){
  const id = `${idp}-${f.name}`;
  const nm = FIELD_PREFIX + f.name;
  const req = f.required ? ' required aria-required="true"' : '';
  const reqMark = f.required ? ' <span class="mz-req" aria-hidden="true">*</span>' : '';
  const help = f.help ? `<div class="mz-help" id="${id}-help">${f.help}</div>` : '';
  const desc = f.help ? ` aria-describedby="${id}-help"` : '';
  const full = f.full || ['textarea', 'checkboxes', 'static', 'file'].includes(f.type) ? ' full' : '';
  const val = f.value ?? '';
  let control;
  switch(f.type){
    case 'textarea':
      control = `<textarea class="adm-input" id="${id}" name="${nm}"${req}${desc} maxlength="${f.maxlength || 5000}" rows="${f.rows || 4}">${MZ.esc(val)}</textarea>`; break;
    case 'select':
      control = `<select class="adm-select" id="${id}" name="${nm}"${req}${desc}>${(f.options || []).map(o =>
        `<option value="${MZ.esc(o.value)}"${String(o.value) === String(val) ? ' selected' : ''}>${MZ.esc(o.label)}</option>`).join('')}</select>`; break;
    case 'checkbox':
      return `<div class="adm-field${full}"><label class="mz-check"><input type="checkbox" id="${id}" name="${nm}"${val ? ' checked' : ''}${desc}> ${MZ.esc(f.label)}</label>${help}</div>`;
    case 'checkboxes':
      return `<fieldset class="adm-field full" style="border:none;padding:0;margin:0 0 14px"><legend class="adm-label">${MZ.esc(f.label)}</legend>${(f.options || []).map((o, i) =>
        `<label class="mz-check"><input type="checkbox" name="${nm}" value="${MZ.esc(o.value)}" id="${id}-${i}"${(val || []).includes(o.value) ? ' checked' : ''}> ${MZ.esc(o.label)}</label>`).join('')}${help}</fieldset>`;
    case 'static':
      return `<div class="adm-field full">${f.label ? `<div class="adm-label">${MZ.esc(f.label)}</div>` : ''}${f.html || ''}</div>`;
    case 'file':
      control = `<input class="adm-input" type="file" id="${id}" name="${nm}"${req}${desc}${f.accept ? ` accept="${MZ.esc(f.accept)}"` : ''}>`; break;
    default:
      control = `<input class="adm-input" type="${f.type || 'text'}" id="${id}" name="${nm}" value="${MZ.esc(val)}"${req}${desc}${f.step ? ` step="${f.step}"` : ''}${f.min !== undefined ? ` min="${f.min}"` : ''}${f.max !== undefined ? ` max="${f.max}"` : ''}${f.maxlength ? ` maxlength="${f.maxlength}"` : ''}${f.placeholder ? ` placeholder="${MZ.esc(f.placeholder)}"` : ''}>`;
  }
  return `<div class="adm-field${full}"><label class="adm-label" for="${id}">${MZ.esc(f.label)}${reqMark}</label>${control}${help}</div>`;
}
function readForm(formEl, fields){
  const out = {};
  for(const f of fields){
    if(f.type === 'static') continue;
    if(f.type === 'checkboxes'){ out[f.name] = [...formEl.querySelectorAll(`input[name="${FIELD_PREFIX}${f.name}"]:checked`)].map(i => i.value); continue; }
    const el = formEl.elements[FIELD_PREFIX + f.name];
    if(!el) continue;
    if(f.type === 'checkbox') out[f.name] = el.checked;
    else if(f.type === 'file') out[f.name] = el.files && el.files[0] || null;
    else if(f.type === 'number') out[f.name] = el.value === '' ? null : Number(el.value);
    else out[f.name] = el.value === '' ? (f.emptyAs !== undefined ? f.emptyAs : null) : el.value;
  }
  return out;
}
/* MZ.form({title, fields, submitLabel, wide, onSubmit(values) -> result, onChange(name, values, dlg)}) */
MZ.form = function({title, intro = '', fields, submitLabel = 'Save', wide = false, onSubmit, onChange}){
  return new Promise(resolve => {
    const idp = `mzf${++formSeq}`;
    const dlg = document.createElement('dialog');
    dlg.className = 'mz-dialog' + (wide ? ' wide' : '');
    dlg.setAttribute('aria-labelledby', `${idp}-title`);
    dlg.innerHTML = DOMPurify.sanitize(`<form method="dialog" novalidate>
      <div class="mz-dialog-hdr"><h2 id="${idp}-title">${MZ.esc(title)}</h2><button type="button" data-close aria-label="Close">×</button></div>
      <div class="mz-dialog-body">${intro ? `<div class="adm-field full mz-help" style="font-size:12.5px">${intro}</div>` : ''}<div class="mz-error" role="alert" hidden></div>${fields.map(f => fieldHtml(f, idp)).join('')}</div>
      <div class="mz-dialog-foot"><button type="button" class="mz-btn ghost" data-close>Cancel</button><button type="submit" class="mz-btn primary">${MZ.esc(submitLabel)}</button></div>
    </form>`);
    document.body.appendChild(dlg);
    const formEl = dlg.querySelector('form');
    const errEl = dlg.querySelector('.mz-error');
    let result = null;
    const close = () => { dlg.close(); };
    dlg.addEventListener('close', () => { dlg.remove(); resolve(result); });
    dlg.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
    if(onChange){
      formEl.addEventListener('change', e => { if(e.target.name) onChange(e.target.name.replace(FIELD_PREFIX, ''), readForm(formEl, fields), dlg); });
    }
    formEl.addEventListener('submit', async e => {
      e.preventDefault();
      errEl.hidden = true;
      const missing = fields.filter(f => f.required && !['checkbox', 'checkboxes', 'static'].includes(f.type))
        .filter(f => { const el = formEl.elements[FIELD_PREFIX + f.name]; return !el || (f.type === 'file' ? !(el.files && el.files.length) : !String(el.value).trim()); });
      if(missing.length){
        errEl.textContent = `Please complete: ${missing.map(f => f.label).join(', ')}.`;
        errEl.hidden = false;
        formEl.elements[FIELD_PREFIX + missing[0].name]?.focus();
        return;
      }
      const submit = formEl.querySelector('[type=submit]');
      submit.disabled = true;
      try{
        result = await onSubmit(readForm(formEl, fields), dlg);
        if(result === undefined) result = true;
        close();
      }catch(err){
        errEl.textContent = err.message || String(err);
        errEl.hidden = false;
        errEl.focus?.();
      }finally{ submit.disabled = false; }
    });
    dlg.showModal();
    const first = formEl.querySelector('.mz-dialog-body input:not([type=hidden]),.mz-dialog-body select,.mz-dialog-body textarea');
    first?.focus();
    if(onChange) onChange(null, readForm(formEl, fields), dlg);
  });
};
MZ.setOptions = (dlg, name, options, value) => {
  const sel = dlg.querySelector(`select[name="${FIELD_PREFIX}${name}"]`);
  if(!sel) return;
  const keep = value ?? sel.value;
  sel.innerHTML = DOMPurify.sanitize(options.map(o => `<option value="${MZ.esc(o.value)}">${MZ.esc(o.label)}</option>`).join(''));
  if(options.some(o => String(o.value) === String(keep))) sel.value = keep;
};
MZ.reason = ({title, label = 'Reason', required = true, submitLabel = 'Confirm', intro = ''}) =>
  MZ.form({title, intro, submitLabel, fields: [{name: 'reason', label, type: 'textarea', required}],
           onSubmit: v => ({reason: v.reason || ''})});

/* ── record extras: comments, links, history ────────────────────────────── */
MZ.historyHtml = function(events){
  if(!events || !events.length) return '<div class="mz-empty">No history yet.</div>';
  const fmt = obj => obj ? Object.entries(obj).map(([k, v]) => `${MZ.label(k)}: ${typeof v === 'object' && v !== null ? JSON.stringify(v) : (v ?? '—')}`).join(' · ') : '';
  return `<ol class="mz-timeline">${events.slice().reverse().map(e => `<li>
    <div><strong>${MZ.esc(MZ.label(String(e.action).split('.').pop()))}</strong> by ${MZ.esc(e.actor)} <span class="mz-when">${MZ.esc(MZ.dateTime(e.at))}</span></div>
    ${e.before || e.after ? `<div class="mz-meta">${e.before ? MZ.esc(fmt(e.before)) + ' → ' : ''}${MZ.esc(fmt(e.after))}</div>` : ''}
    ${e.reason ? `<div class="mz-reason">“${MZ.esc(e.reason)}”</div>` : ''}</li>`).join('')}</ol>`;
};
MZ.extras = async function(host, type, id, {canComment = true} = {}){
  if(!host) return;
  const state = host.__mzExtras = {type, id, tab: (host.__mzExtras && host.__mzExtras.type === type) ? host.__mzExtras.tab : 'comments'};
  const [comments, links, history] = await Promise.all([
    MZ.api(`/api/platform/comments?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`),
    MZ.api(`/api/platform/links?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`),
    MZ.api(`/api/platform/history?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`),
  ]);
  const render = () => {
    MZ.html(host, `<div class="mz-extras-tabs"></div><div class="mz-extras-body" role="tabpanel" style="margin-top:10px"></div>`);
    MZ.tabs(host.querySelector('.mz-extras-tabs'), [
      {key: 'comments', label: 'Comments', count: comments.length},
      {key: 'links', label: 'Linked records', count: links.links.length},
      {key: 'history', label: 'History', count: history.length}], state.tab, k => { state.tab = k; render(); });
    const body = host.querySelector('.mz-extras-body');
    if(state.tab === 'comments'){
      MZ.html(body, `${comments.length ? `<ol class="mz-timeline">${comments.map(c => `<li><div><strong>${MZ.esc(c.author)}</strong> <span class="mz-when">${MZ.esc(MZ.dateTime(c.created_at))}</span></div><div style="white-space:pre-wrap">${MZ.esc(c.body)}</div></li>`).join('')}</ol>` : '<div class="mz-empty">No comments yet.</div>'}
        ${canComment && MZ.me && !MZ.me.read_only ? `<form class="mz-comment-form" style="margin-top:10px"><label class="adm-label" for="${host.id || 'x'}-c">Add a comment</label><textarea class="adm-input" id="${host.id || 'x'}-c" name="comment_text" rows="2" maxlength="5000" required></textarea><div class="mz-btn-row" style="margin-top:6px"><button class="mz-btn" type="submit">Post comment</button></div></form>` : ''}`);
      body.querySelector('.mz-comment-form')?.addEventListener('submit', async e => {
        e.preventDefault();
        const text = e.target.elements.comment_text.value.trim();
        if(!text) return;
        try{ await MZ.api('/api/platform/comments', {method: 'POST', body: {entity_type: type, entity_id: String(id), body: text}});
             MZ.extras(host, type, id, {canComment}); }catch(err){ MZ.fail(err); }
      });
    }else if(state.tab === 'links'){
      MZ.html(body, `${links.links.length ? MZ.table({columns: [
          {label: 'Relation', render: l => MZ.esc(MZ.label(l.relation)) + (l.direction === 'incoming' ? ' <span class="mz-meta">(from)</span>' : '')},
          {label: 'Record', render: l => `${MZ.esc(l.other.type_label)}: ${l.other.page ? `<button class="mz-link" data-mz="open-link" data-page="${MZ.esc(l.other.page)}" data-type="${MZ.esc(l.other.type)}" data-id="${MZ.esc(l.other.id)}">${MZ.esc(l.other.title)}</button>` : MZ.esc(l.other.title)}${l.to_version ? ` <span class="mz-badge info">v${MZ.esc(l.to_version)}</span>` : ''}`},
          {label: 'By', render: l => `${MZ.esc(l.created_by)}<div class="mz-meta">${MZ.esc(MZ.date(l.created_at))}</div>`}],
        rows: links.links}) : '<div class="mz-empty">No linked records.</div>'}
        ${links.hidden ? `<p class="mz-meta">${links.hidden} linked record(s) are outside your access and not shown.</p>` : ''}
        ${MZ.attachEvidence && canComment && MZ.me && !MZ.me.read_only && type !== 'document' ? '<div class="mz-btn-row" style="margin-top:8px"><button class="mz-btn" data-mz="attach">Attach evidence file</button></div>' : ''}`);
      MZ.onAct(body, {'open-link': d => MZ.open(d.page, d.type, d.id),
                      attach: async () => { state.tab = 'links'; if(await MZ.attachEvidence(type, id)) MZ.extras(host, type, id, {canComment}); }});
    }else{
      MZ.html(body, MZ.historyHtml(history));
    }
  };
  render();
};
/* Open a record on its page: pages read MZ.pendingOpen on load. */
MZ.open = function(page, type, id){
  MZ.pendingOpen = {page, type, id: String(id)};
  navigate(page);
};
MZ.takePending = function(page){
  const p = MZ.pendingOpen;
  if(p && p.page === page){ MZ.pendingOpen = null; return p; }
  return null;
};

/* Sidebar items are <div onclick>: make every one reachable and operable from the keyboard. */
function keyboardNav(){
  document.querySelectorAll('#db-nav .nav-item[data-page]').forEach(el => {
    if(!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
    if(!el.hasAttribute('role')) el.setAttribute('role', 'link');
  });
}
document.addEventListener('keydown', e => {
  if(e.key !== 'Enter' && e.key !== ' ') return;
  const el = e.target.closest && e.target.closest('#db-nav .nav-item[data-page], #db-nav .nav-item[role="link"]');
  if(el && e.target === el){ e.preventDefault(); el.click(); }
});
if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', keyboardNav); else keyboardNav();

/* ═══════════════════════════════ My Work ═══════════════════════════════ */
MZ.myWorkSections = [];   // modules push fn(data) -> html
MZ.page('my-work', async root => {
  const data = await MZ.api('/api/platform/my-work');
  await MZ.loadMe(true);
  const sections = MZ.myWorkSections.map(fn => { try{ return fn(data) || ''; }catch(e){ console.error(e); return ''; } }).join('');
  const actionCols = [
    {label: 'Action', render: a => `<span class="mz-strong">${MZ.esc(a.ref)}</span> ${MZ.esc(a.title)}`},
    {label: 'Unit', render: a => MZ.esc(MZ.unitName(a.org_unit_code))},
    {label: 'Due', render: a => `${MZ.esc(MZ.date(a.due_date))}${a.overdue ? ' ' + MZ.badge('overdue') : ''}`},
    {label: 'Status', render: a => MZ.badge(a.status)}];
  MZ.html(root, `${MZ.header(`My work${MZ.me.read_only ? ' (read-only)' : ''}`, `Everything waiting for you, ${MZ.esc(getUser()?.full_name || getUser()?.username || '')}: your actions, items to verify and your notices.${MZ.me.org_wide ? '' : ' Your access covers: ' + MZ.esc(Object.keys(MZ.me.units || {}).map(MZ.unitName).join(', ') || 'no units yet — ask an administrator for access') + '.'}`)}
    <div class="mz-stats">
      <div class="mz-stat"><span class="mz-stat-val">${data.actions.length}</span><span class="mz-stat-lbl">My open actions</span></div>
      <div class="mz-stat ${data.overdue_actions ? 'danger' : 'ok'}"><span class="mz-stat-val">${data.overdue_actions}</span><span class="mz-stat-lbl">Overdue</span></div>
      <div class="mz-stat ${data.actions_to_verify.length ? 'warn' : ''}"><span class="mz-stat-val">${data.actions_to_verify.length}</span><span class="mz-stat-lbl">Actions to verify</span></div>
      <div class="mz-stat"><span class="mz-stat-val">${data.notifications.length}</span><span class="mz-stat-lbl">Unread notices</span></div>
    </div>
    ${sections}
    <div class="mz-grid-2">
      <section class="mz-card" aria-labelledby="mw-a"><h3 id="mw-a">My actions</h3><div id="mw-actions">${MZ.table({columns: actionCols, rows: data.actions, rowId: a => a.id, empty: 'No open actions assigned to you.'})}</div></section>
      <section class="mz-card" aria-labelledby="mw-v"><h3 id="mw-v">Completed actions awaiting your verification</h3><div id="mw-verify">${MZ.table({columns: actionCols, rows: data.actions_to_verify, rowId: a => a.id, empty: 'Nothing to verify.'})}</div></section>
    </div>
    <section class="mz-card" aria-labelledby="mw-n"><div class="mz-hdr"><h3 id="mw-n">Notices</h3>${data.notifications.length ? '<button class="mz-btn ghost" data-mz="read-all">Mark all as read</button>' : ''}</div>
      ${data.notifications.length ? `<ol class="mz-timeline">${data.notifications.map(n => `<li><div><strong>${MZ.esc(n.title)}</strong> <span class="mz-when">${MZ.esc(MZ.dateTime(n.created_at))}</span></div>${n.body ? `<div class="mz-meta">${MZ.esc(n.body)}</div>` : ''}
        <div class="mz-btn-row" style="margin-top:4px">${n.entity_type ? `<button class="mz-link" data-mz="open-note" data-id="${n.id}" data-type="${MZ.esc(n.entity_type)}" data-eid="${MZ.esc(n.entity_id)}">Open</button>` : ''}<button class="mz-link" data-mz="read" data-id="${n.id}">Mark as read</button></div></li>`).join('')}</ol>` : '<div class="mz-empty">No unread notices.</div>'}</section>`);
  const openAction = id => MZ.open('actions', 'action', id);
  MZ.onRow(MZ.$('mw-actions'), openAction);
  MZ.onRow(MZ.$('mw-verify'), openAction);
  root.querySelectorAll('.mz-mw-section[data-open-page]').forEach(host => MZ.onRow(host, id => MZ.open(host.dataset.openPage, host.dataset.openType, id)));
  MZ.onAct(root, {
    'read-all': async () => { await MZ.api('/api/platform/notifications/read-all', {method: 'POST'}); MZ.refresh('my-work'); },
    'read': async d => { await MZ.api(`/api/platform/notifications/${d.id}/read`, {method: 'POST'}); MZ.refresh('my-work'); },
    'open-note': async d => {
      await MZ.api(`/api/platform/notifications/${d.id}/read`, {method: 'POST'});
      const page = MZ.entityPages[d.type];
      if(page) MZ.open(page, d.type, d.eid); else MZ.refresh('my-work');
    },
  });
});
MZ.entityPages = {action: 'actions'};

/* ═══════════════════════════════ Actions ═══════════════════════════════ */
const ACT = {filters: {status: '', unit: '', mine: false, overdue: false, q: ''}, rows: [], selected: null};
const NOTE_PROMPTS = {complete: ['Mark action complete', 'Completion note (what was done, where is the evidence)', true],
                      reopen: ['Reopen action', 'Reason for reopening', true],
                      cancel: ['Cancel action', 'Reason for cancelling', true],
                      close: ['Verify and close', 'Verification note (optional)', false]};

MZ.actionForm = async function({unit = '', sourceType = null, sourceId = null, title = '', description = ''} = {}){
  const units = MZ.unitOptions('contributor');
  if(!units.length){ MZ.toast('You need the contributor role on a unit to raise actions.', 'danger'); return null; }
  return MZ.form({
    title: 'Raise an action', submitLabel: 'Raise action',
    fields: [
      {name: 'title', label: 'Title', required: true, value: title, maxlength: 200, full: true},
      {name: 'org_unit_code', label: 'Unit', type: 'select', options: units, value: unit || units[0].value, required: true},
      {name: 'owner', label: 'Owner', type: 'select', options: [], required: true, help: 'People with access to the unit.'},
      {name: 'due_date', label: 'Due date', type: 'date'},
      {name: 'priority', label: 'Priority', type: 'select', value: 'medium',
       options: ['low', 'medium', 'high', 'critical'].map(p => ({value: p, label: MZ.label(p)}))},
      {name: 'description', label: 'Description', type: 'textarea', value: description}],
    onChange: async (name, v, dlg) => {
      if(name === null || name === 'org_unit_code'){
        try{
          const people = await MZ.api(`/api/platform/assignable-users?unit=${encodeURIComponent(v.org_unit_code)}`);
          MZ.setOptions(dlg, 'owner', people.map(p => ({value: p.username, label: `${p.full_name || p.username} (${p.role})`})), getUser()?.username);
        }catch(e){ MZ.setOptions(dlg, 'owner', []); }
      }
    },
    onSubmit: v => MZ.api('/api/platform/actions', {method: 'POST', body: {...v, source_type: sourceType, source_id: sourceId == null ? null : String(sourceId)}}),
  });
};

async function actLoad(root){
  const f = ACT.filters;
  const qs = new URLSearchParams();
  if(f.status) qs.set('status', f.status);
  if(f.unit) qs.set('org_unit_code', f.unit);
  if(f.mine) qs.set('mine', 'true');
  if(f.overdue) qs.set('overdue', 'true');
  ACT.rows = await MZ.api('/api/platform/actions?' + qs);
  actRender(root);
}
function actRender(root){
  const q = ACT.filters.q.trim().toLowerCase();
  const rows = q ? ACT.rows.filter(a => `${a.ref} ${a.title} ${a.owner} ${a.description || ''}`.toLowerCase().includes(q)) : ACT.rows;
  const count = s => ACT.rows.filter(a => a.status === s).length;
  MZ.html(MZ.$('act-stats'), `
    <div class="mz-stat"><span class="mz-stat-val">${count('open')}</span><span class="mz-stat-lbl">Open</span></div>
    <div class="mz-stat"><span class="mz-stat-val">${count('in_progress')}</span><span class="mz-stat-lbl">In progress</span></div>
    <div class="mz-stat ${ACT.rows.some(a => a.overdue) ? 'danger' : 'ok'}"><span class="mz-stat-val">${ACT.rows.filter(a => a.overdue).length}</span><span class="mz-stat-lbl">Overdue</span></div>
    <div class="mz-stat warn"><span class="mz-stat-val">${count('completed')}</span><span class="mz-stat-lbl">Awaiting verification</span></div>`);
  MZ.html(MZ.$('act-table'), MZ.table({
    caption: `${rows.length} action(s)`, rows, rowId: a => a.id, selected: ACT.selected,
    empty: 'No actions match these filters.',
    columns: [
      {label: 'Ref', render: a => `<span class="mz-strong mz-mono">${MZ.esc(a.ref)}</span>`},
      {label: 'Action', render: a => `${MZ.esc(a.title)}${a.source_type ? `<div class="mz-meta">From ${MZ.esc(MZ.label(a.source_type))}</div>` : ''}`},
      {label: 'Owner', key: 'owner'},
      {label: 'Unit', render: a => MZ.esc(MZ.unitName(a.org_unit_code))},
      {label: 'Due', render: a => `${MZ.esc(MZ.date(a.due_date))}${a.overdue ? '<div>' + MZ.badge('overdue') + '</div>' : ''}`},
      {label: 'Priority', render: a => MZ.badge(a.priority)},
      {label: 'Status', render: a => MZ.badge(a.status)}]}));
}
async function actDetail(root, id){
  ACT.selected = id;
  actRender(root);
  const host = MZ.$('act-detail');
  const a = await MZ.api(`/api/platform/actions/${id}`);
  const btns = (a.allowed || []).map(t => `<button class="mz-btn ${t === 'cancel' ? 'danger' : t === 'close' ? 'primary' : ''}" data-mz="tr" data-name="${t}" data-id="${a.id}">${MZ.esc(MZ.label({close: 'verify and close', complete: 'mark complete'}[t] || t))}</button>`).join('');
  MZ.html(host, `<div class="mz-hdr"><h3 style="margin:0">${MZ.esc(a.ref)} · ${MZ.esc(a.title)}</h3>${MZ.badge(a.status)}</div>
    <dl class="mz-kv" style="margin-top:10px">
      <dt>Owner</dt><dd>${MZ.esc(a.owner)}</dd><dt>Unit</dt><dd>${MZ.esc(MZ.unitName(a.org_unit_code))}</dd>
      <dt>Due</dt><dd>${MZ.esc(MZ.date(a.due_date))} ${a.overdue ? MZ.badge('overdue') : ''}</dd><dt>Priority</dt><dd>${MZ.badge(a.priority)}</dd>
      <dt>Raised by</dt><dd>${MZ.esc(a.created_by)} on ${MZ.esc(MZ.date(a.created_at))}</dd>
      ${a.source_type ? `<dt>Raised from</dt><dd>${MZ.entityPages[a.source_type] ? `<button class="mz-link" data-mz="src" data-type="${MZ.esc(a.source_type)}" data-id="${MZ.esc(a.source_id)}">${MZ.esc(MZ.label(a.source_type))} #${MZ.esc(a.source_id)}</button>` : MZ.esc(MZ.label(a.source_type)) + ' #' + MZ.esc(a.source_id)}</dd>` : ''}
      ${a.description ? `<dt>Description</dt><dd style="white-space:pre-wrap">${MZ.esc(a.description)}</dd>` : ''}
      ${a.progress_note ? `<dt>Progress</dt><dd style="white-space:pre-wrap">${MZ.esc(a.progress_note)}</dd>` : ''}
      ${a.completion_note ? `<dt>Completion note</dt><dd style="white-space:pre-wrap">${MZ.esc(a.completion_note)}</dd>` : ''}
      ${a.closed_by ? `<dt>Verified by</dt><dd>${MZ.esc(a.closed_by)}</dd>` : ''}
    </dl>
    <div class="mz-btn-row" style="margin:12px 0">${btns}${a.can_edit ? `<button class="mz-btn ghost" data-mz="edit" data-id="${a.id}">Edit</button>` : ''}</div>
    <div id="act-extras"></div>`);
  await MZ.extras(MZ.$('act-extras'), 'action', a.id);
  MZ.onAct(host, {
    tr: async d => {
      let note = null;
      const p = NOTE_PROMPTS[d.name];
      if(p){ const r = await MZ.reason({title: p[0], label: p[1], required: p[2]}); if(!r) return; note = r.reason; }
      await MZ.api(`/api/platform/actions/${d.id}/transition`, {method: 'POST', body: {name: d.name, note}});
      MZ.toast(`${a.ref} updated.`, 'ok');
      await actLoad(root); await actDetail(root, d.id);
    },
    edit: async d => {
      const people = await MZ.api(`/api/platform/assignable-users?unit=${encodeURIComponent(a.org_unit_code)}`).catch(() => [{username: a.owner, role: ''}]);
      const saved = await MZ.form({title: `Edit ${a.ref}`, fields: [
        {name: 'title', label: 'Title', value: a.title, required: true, full: true},
        {name: 'owner', label: 'Owner', type: 'select', value: a.owner, options: people.map(p => ({value: p.username, label: p.full_name || p.username}))},
        {name: 'due_date', label: 'Due date', type: 'date', value: a.due_date || ''},
        {name: 'priority', label: 'Priority', type: 'select', value: a.priority, options: ['low', 'medium', 'high', 'critical'].map(p => ({value: p, label: MZ.label(p)}))},
        {name: 'progress_note', label: 'Progress note', type: 'textarea', value: a.progress_note || ''},
        {name: 'description', label: 'Description', type: 'textarea', value: a.description || ''},
        {name: 'reason', label: 'Reason for the change', type: 'textarea', rows: 2, help: 'Required when an agreed due date moves.'}],
        onSubmit: v => {
          const body = {};
          for(const k of ['title', 'owner', 'priority', 'progress_note', 'description']) if((v[k] || '') !== (a[k] || '')) body[k] = v[k];
          if((v.due_date || null) !== (a.due_date || null)) body.due_date = v.due_date || null;
          if(v.reason) body.reason = v.reason;
          return MZ.api(`/api/platform/actions/${d.id}`, {method: 'PUT', body});
        }});
      if(saved){ MZ.toast('Saved.', 'ok'); await actLoad(root); await actDetail(root, d.id); }
    },
    src: d => MZ.open(MZ.entityPages[d.type], d.type, d.id),
  });
}
MZ.page('actions', async root => {
  const pending = MZ.takePending('actions');
  if(pending) ACT.selected = pending.id;
  MZ.html(root, `${MZ.header('Actions', 'Owned, dated follow-up work raised from reviews, evaluations, risks, audit findings and board resolutions. Completing needs a note; a different reviewer verifies and closes; moving an agreed date, cancelling or reopening needs a reason. Everything is kept in the history.',
      MZ.canAnywhere('contributor') ? '<button class="mz-btn primary" data-mz="new">Raise action</button>' : '')}
    <div class="mz-toolbar" role="search">
      <div class="adm-field"><label class="adm-label" for="act-f-status">Status</label><select class="adm-select" id="act-f-status">${[['', 'Any'], ['open', 'Open'], ['in_progress', 'In progress'], ['completed', 'Awaiting verification'], ['closed', 'Closed'], ['cancelled', 'Cancelled']].map(([v, l]) => `<option value="${v}"${ACT.filters.status === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
      <div class="adm-field"><label class="adm-label" for="act-f-unit">Unit</label><select class="adm-select" id="act-f-unit">${MZ.unitOptions('viewer', {includeBlank: true}).map(o => `<option value="${MZ.esc(o.value)}"${ACT.filters.unit === o.value ? ' selected' : ''}>${MZ.esc(o.label)}</option>`).join('')}</select></div>
      <div class="adm-field"><label class="adm-label" for="act-f-q">Search</label><input class="adm-input" id="act-f-q" type="search" value="${MZ.esc(ACT.filters.q)}" placeholder="Ref, title, owner"></div>
      <label class="mz-check"><input type="checkbox" id="act-f-mine"${ACT.filters.mine ? ' checked' : ''}> Mine only</label>
      <label class="mz-check"><input type="checkbox" id="act-f-overdue"${ACT.filters.overdue ? ' checked' : ''}> Overdue only</label>
    </div>
    <div class="mz-stats" id="act-stats"></div>
    <div class="mz-split"><div id="act-table"></div><section class="mz-card" id="act-detail" aria-live="polite"><div class="mz-empty">Select an action to see its detail, comments, links and history.</div></section></div>`);
  const bind = (id, key, prop = 'value') => MZ.$(id).addEventListener(prop === 'value' && id.endsWith('-q') ? 'input' : 'change', e => {
    ACT.filters[key] = e.target[prop];
    if(key === 'q') actRender(root); else actLoad(root);
  });
  bind('act-f-status', 'status'); bind('act-f-unit', 'unit'); bind('act-f-q', 'q');
  bind('act-f-mine', 'mine', 'checked'); bind('act-f-overdue', 'overdue', 'checked');
  MZ.onRow(MZ.$('act-table'), id => actDetail(root, id).catch(MZ.fail));
  MZ.onAct(root.querySelector('.mz-hdr'), {new: async () => { const a = await MZ.actionForm(); if(a){ MZ.toast(`${a.ref} raised.`, 'ok'); await actLoad(root); await actDetail(root, a.id); } }});
  await actLoad(root);
  if(ACT.selected) await actDetail(root, ACT.selected).catch(e => { ACT.selected = null; MZ.fail(e); });
});

/* ═══════════════════════════════ Periods ═══════════════════════════════ */
MZ.page('periods', async root => {
  const rows = await MZ.api('/api/platform/periods');
  const years = [...new Set(rows.map(p => p.fiscal_year))];
  const admin = MZ.isAdmin();
  MZ.html(root, `${MZ.header('Reporting periods', 'Months, quarters and years on the fiscal calendar. A locked period rejects changes in every module; reopening needs a reason and is recorded in the audit trail.',
      admin || MZ.hasFunction('strategy_manager') ? '<button class="mz-btn primary" data-mz="new">Add fiscal year</button>' : '')}
    ${years.map(y => `<section class="mz-card"><h3>${MZ.esc(rows.find(p => p.fiscal_year === y && p.period_type === 'year')?.label || 'FY' + y)}</h3>
      ${MZ.table({rows: rows.filter(p => p.fiscal_year === y), columns: [
        {label: 'Period', render: p => `<span class="mz-strong">${MZ.esc(p.label)}</span>`},
        {label: 'Type', render: p => MZ.esc(MZ.label(p.period_type))},
        {label: 'From', render: p => MZ.esc(MZ.date(p.start_date))}, {label: 'To', render: p => MZ.esc(MZ.date(p.end_date))},
        {label: 'Status', render: p => `${MZ.badge(p.status)}${p.locked_by ? `<div class="mz-meta">by ${MZ.esc(p.locked_by)}, ${MZ.esc(MZ.date(p.locked_at))}</div>` : ''}`},
        {label: '', render: p => admin ? (p.status === 'open' ? `<button class="mz-btn ghost" data-mz="lock" data-id="${p.id}" data-label="${MZ.esc(p.label)}">Lock</button>` : `<button class="mz-btn" data-mz="reopen" data-id="${p.id}" data-label="${MZ.esc(p.label)}">Reopen…</button>`) : ''}]})}</section>`).join('') || '<div class="mz-empty">No periods yet.</div>'}`);
  MZ.onAct(root, {
    new: async () => {
      const r = await MZ.form({title: 'Add fiscal year', fields: [{name: 'fiscal_year', label: 'Fiscal year (year in which it ends)', type: 'number', required: true, min: 1990, max: 2100, value: new Date().getFullYear() + 1}],
        onSubmit: v => MZ.api('/api/platform/periods/fiscal-year', {method: 'POST', body: v})});
      if(r) MZ.refresh('periods');
    },
    lock: async d => {
      const r = await MZ.reason({title: `Lock ${d.label}`, label: 'Note (optional)', required: false, submitLabel: 'Lock period',
        intro: 'Locking stops every module from changing data for this period. Only an administrator can reopen it, with a reason.'});
      if(!r) return;
      await MZ.api(`/api/platform/periods/${d.id}/lock`, {method: 'POST', body: {reason: r.reason}});
      MZ.toast(`${d.label} locked.`, 'ok'); MZ.refresh('periods');
    },
    reopen: async d => {
      const r = await MZ.reason({title: `Reopen ${d.label}`, label: 'Reason for reopening (recorded in the audit trail)', submitLabel: 'Reopen period'});
      if(!r) return;
      await MZ.api(`/api/platform/periods/${d.id}/reopen`, {method: 'POST', body: {reason: r.reason}});
      MZ.toast(`${d.label} reopened.`, 'ok'); MZ.refresh('periods');
    },
  });
});

/* ═══════════════════════════ Access & scope ════════════════════════════ */
const DUTY_HELP = {strategy_manager: 'Plans, indicators, cycles and scoring schemes', report_manager: 'Report templates and instances',
  document_controller: 'Document types and controlled documents', board_secretary: 'Meetings and resolutions',
  auditor: 'Audit findings: ratings, validation and closure', risk_manager: 'Risk criteria and register oversight',
  regulatory_officer: 'Regulator packs and returns', hr_officer: 'Performance contracts and staff appraisals (private; never implied by admin)'};
MZ.page('access', async root => {
  const data = await MZ.api('/api/platform/access/users');
  const units = await MZ.api('/api/platform/org-units');
  MZ.units = units;
  MZ.html(root, `${MZ.header('Access & scope', 'Access is deny-by-default. Grant each person a role on the units they work with; a grant covers the unit and everything below it, and a grant on the whole organisation opens the organisation-wide dashboards. Duties add organisation-wide responsibilities. Every change is audited.',
      '<button class="mz-btn ghost" data-mz="sync">Add configured regions to the tree</button>')}
    <div class="mz-notice">Roles: <strong>viewer</strong> reads · <strong>contributor</strong> submits and raises actions · <strong>reviewer</strong> verifies and closes · <strong>approver</strong> approves and locks. Accounts with the <em>viewer</em> account role stay read-only whatever their grants.</div>
    ${MZ.table({rows: data.users, columns: [
      {label: 'User', render: u => `<span class="mz-strong">${MZ.esc(u.username)}</span>${u.full_name ? `<div class="mz-meta">${MZ.esc(u.full_name)}</div>` : ''}${u.is_active ? '' : MZ.badge('inactive', 'danger')}`},
      {label: 'Account role', render: u => MZ.badge(u.account_role, u.account_role === 'admin' ? 'purple' : 'info')},
      {label: 'Unit grants', render: u => u.account_role === 'admin' ? '<span class="mz-meta">Everything (administrator)</span>' : (u.grants.length ? `<div class="mz-pill-list">${u.grants.map(g => `<span class="mz-badge info">${MZ.esc(g.unit_name)}: ${MZ.esc(g.role)}</span>`).join('')}</div>` : MZ.badge('no access', 'danger', 'No access'))},
      {label: 'Duties', render: u => u.functions.length ? `<div class="mz-pill-list">${u.functions.map(f => `<span class="mz-badge">${MZ.esc(MZ.label(f))}</span>`).join('')}</div>` : '<span class="mz-meta">—</span>'},
      {label: '', render: u => `<button class="mz-btn ghost" data-mz="edit" data-id="${u.id}">Edit access</button>`}]})}`);
  MZ.onAct(root, {
    sync: async () => { const r = await MZ.api('/api/platform/org-units/sync', {method: 'POST'}); MZ.toast(r.created ? `${r.created} unit(s) added.` : 'The tree already has every configured region.', 'ok'); MZ.refresh('access'); },
    edit: async d => {
      const u = data.users.find(x => String(x.id) === d.id);
      const current = Object.fromEntries(u.grants.map(g => [g.org_unit_code, g.role]));
      const unitRows = MZ.unitOptions('viewer').map(o => ({code: o.value, label: o.label}));
      const roleSel = (code) => `<select class="adm-select" name="grant:${MZ.esc(code)}" aria-label="Role on ${MZ.esc(MZ.unitName(code))}">${[['', 'No grant'], ...data.roles.map(r => [r, MZ.label(r)])].map(([v, l]) => `<option value="${v}"${(current[code] || '') === v ? ' selected' : ''}>${l}</option>`).join('')}</select>`;
      const saved = await MZ.form({title: `Access for ${u.username}`, wide: true, submitLabel: 'Save access',
        intro: u.account_role === 'admin' ? 'Administrators already see every unit; grants matter only if the account role changes. The HR officer duty must still be granted explicitly.' : '',
        fields: [
          {type: 'static', name: '_g', label: 'Unit grants', html: `<div class="mz-table-wrap"><table class="mz-table"><thead><tr><th scope="col">Unit</th><th scope="col">Role</th></tr></thead><tbody>${unitRows.map(r => `<tr><td>${MZ.esc(r.label)}</td><td>${roleSel(r.code)}</td></tr>`).join('')}</tbody></table></div>`},
          {name: 'functions', label: 'Duties', type: 'checkboxes', value: u.functions, options: data.functions.map(f => ({value: f, label: `${MZ.label(f)} — ${DUTY_HELP[f] || ''}`}))},
          {name: 'reason', label: 'Reason for the change', type: 'textarea', rows: 2}],
        onSubmit: (v, dlg) => {
          const grants = [...dlg.querySelectorAll('select[name^="grant:"]')].filter(s => s.value).map(s => ({org_unit_code: s.name.slice(6), role: s.value}));
          return MZ.api(`/api/platform/access/users/${u.id}`, {method: 'PUT', body: {grants, functions: v.functions, reason: v.reason}});
        }});
      if(saved){ MZ.toast(`Access for ${u.username} saved.`, 'ok'); MZ.refresh('access'); }
    },
  });
});

/* ═══════════════════════════════ Audit trail ═══════════════════════════ */
const AUD = {entity_type: '', actor: '', since: ''};
MZ.page('audit-trail', async root => {
  const qs = new URLSearchParams({limit: '500'});
  for(const [k, v] of Object.entries(AUD)) if(v) qs.set(k, v);
  const rows = await MZ.api('/api/platform/audit?' + qs);
  const fmt = obj => obj ? Object.entries(obj).map(([k, v]) => `${MZ.label(k)}: ${typeof v === 'object' && v !== null ? JSON.stringify(v) : (v ?? '—')}`).join('; ') : '';
  MZ.html(root, `${MZ.header('Audit trail', 'Append-only record of governed changes: who, what, when, the state before and after, and the reason. The database rejects edits to this trail. Private HR records are excluded here and kept on the records themselves.')}
    <form class="mz-toolbar" id="aud-form" role="search">
      <div class="adm-field"><label class="adm-label" for="aud-type">Record type</label><input class="adm-input" id="aud-type" name="entity_type" value="${MZ.esc(AUD.entity_type)}" placeholder="e.g. action, period"></div>
      <div class="adm-field"><label class="adm-label" for="aud-actor">Actor</label><input class="adm-input" id="aud-actor" name="actor" value="${MZ.esc(AUD.actor)}"></div>
      <div class="adm-field"><label class="adm-label" for="aud-since">Since</label><input class="adm-input" id="aud-since" name="since" type="date" value="${MZ.esc(AUD.since)}"></div>
      <button class="mz-btn" type="submit">Filter</button>
    </form>
    ${MZ.table({caption: `${rows.length} most recent event(s)`, rows, empty: 'No events match.', columns: [
      {label: 'When', render: e => `<span class="mz-mono">${MZ.esc(MZ.dateTime(e.at))}</span>`},
      {label: 'Actor', key: 'actor'},
      {label: 'Action', render: e => `<span class="mz-mono">${MZ.esc(e.action)}</span>`},
      {label: 'Record', render: e => `${MZ.esc(MZ.label(e.entity_type))} #${MZ.esc(e.entity_id)}${e.org_unit_code ? `<div class="mz-meta">${MZ.esc(MZ.unitName(e.org_unit_code))}</div>` : ''}`},
      {label: 'Change', render: e => `<div class="mz-meta">${e.before ? MZ.esc(fmt(e.before)) + ' → ' : ''}${MZ.esc(fmt(e.after))}</div>`},
      {label: 'Reason', render: e => MZ.esc(e.reason || '')}]})}`);
  MZ.$('aud-form').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    for(const k of Object.keys(AUD)) AUD[k] = fd.get(k) || '';
    MZ.refresh('audit-trail');
  });
});

})();
