(function(){
  let responsiveObserver = null;
  let responsiveBuildScheduled = false;
  let responsiveInitDone = false;
  let responsiveSyncScheduled = false;
  let statusObserver = null;
  let drawerTouch = null;
  const responsiveDirtyWrappers = new Set();

  function isDrawerViewport(){ return window.innerWidth <= 1024; }
  function isNarrowViewport(){ return window.innerWidth <= 768; }

  function textOf(el){
    return ((el?.innerText || el?.textContent || '') + '').replace(/\s+/g, ' ').trim();
  }

  function plainCellText(cell){
    return textOf(cell).replace(/\s+/g, ' ').trim();
  }

  function getHeaderLabels(table){
    const headRows = Array.from(table.querySelectorAll('thead tr'));
    const headerRow = headRows[headRows.length - 1] || table.querySelector('tr');
    if(!headerRow) return [];
    return Array.from(headerRow.children).map(function(cell){ return textOf(cell) || 'Value'; });
  }

  function buildSummary(labels, cells){
    const parts = [];
    for(let i = 1; i < cells.length; i += 1){
      const value = plainCellText(cells[i]);
      if(!value) continue;
      const label = labels[i] || ('Column ' + (i + 1));
      parts.push(label + ': ' + value);
      if(parts.length >= 2) break;
    }
    return parts.join(' • ');
  }

  function ensureMobileNavElements(){
    const topbar = document.getElementById('db-topbar');
    if(topbar && !document.getElementById('tb-mobile-nav-btn')){
      const btn = document.createElement('button');
      btn.id = 'tb-mobile-nav-btn'; btn.type = 'button'; btn.className = 'tb-mobile-nav-btn';
      btn.setAttribute('aria-label', 'Open navigation menu');
      btn.setAttribute('aria-controls', 'db-nav');
      btn.setAttribute('aria-expanded', 'false');
      btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
      btn.addEventListener('click', function(){ toggleMobileNav(); });
      topbar.insertBefore(btn, topbar.firstChild);
    }
    if(!document.getElementById('mobile-nav-overlay')){
      const overlay = document.createElement('div');
      overlay.id = 'mobile-nav-overlay';
      overlay.addEventListener('click', closeMobileNav);
      document.body.appendChild(overlay);
    }
    bindDrawerSwipe();
  }

  function ensureMobileActionBar(){
    if(document.getElementById('mobile-action-bar')) return;
    const bar = document.createElement('div');
    bar.id = 'mobile-action-bar';
    bar.innerHTML = [
      '<button type="button" class="mobile-action-btn" data-action="menu" aria-label="Menu"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>Menu</span></button>',
      '<button type="button" class="mobile-action-btn" data-action="filters" aria-label="Filters"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M1 3h14M3 8h10M6 13h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>Filters</span></button>',
      '<button type="button" class="mobile-action-btn" data-action="refresh" aria-label="Refresh"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13.65 2.35A8 8 0 1014 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M14 2v4h-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Refresh</span></button>',
      '<button type="button" class="mobile-action-btn" data-action="alerts" aria-label="Alerts"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Alerts</span><span class="mobile-action-badge" id="mobile-action-alert-badge"></span></button>',
      '<button type="button" class="mobile-action-btn" data-action="upload" aria-label="Upload data"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 1v9M5 4l3-3 3 3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg><span>Upload</span></button>'
    ].join('');
    bar.addEventListener('click', function(e){
      const btn = e.target.closest('.mobile-action-btn'); if(!btn) return;
      const action = btn.getAttribute('data-action');
      if(action === 'menu'){ toggleMobileNav(); return; }
      if(action === 'filters'){ closeMobileNav(); try{ openFilter(); }catch(e2){} return; }
      if(action === 'refresh'){ closeMobileNav(); try{ reloadPage(currentPage); }catch(e2){} return; }
      if(action === 'alerts'){ closeMobileNav(); try{ toggleAlertDrawer(); }catch(e2){} return; }
      if(action === 'upload'){ closeMobileNav(); try{ openUploadModal(); }catch(e2){} }
    });
    document.body.appendChild(bar);
    syncMobileActionBar();
  }

  function syncMobileActionBar(){
    const bar = document.getElementById('mobile-action-bar'); if(!bar) return;
    const showBar = isNarrowViewport() && document.getElementById('app-view') && getComputedStyle(document.getElementById('app-view')).display !== 'none';
    bar.style.display = showBar ? 'grid' : 'none';
    const uploadDesktopBtn = document.getElementById('tb-upload-btn');
    const uploadActionBtn = bar.querySelector('[data-action="upload"]');
    if(uploadActionBtn){
      const showUpload = !!uploadDesktopBtn && getComputedStyle(uploadDesktopBtn).display !== 'none' && !uploadDesktopBtn.hidden;
      uploadActionBtn.style.display = showUpload ? '' : 'none';
    }
    const alertDesktopBadge = document.getElementById('alert-badge');
    const alertBadge = document.getElementById('mobile-action-alert-badge');
    if(alertBadge){
      alertBadge.textContent = alertDesktopBadge?.textContent || '';
      alertBadge.className = 'mobile-action-badge' + (alertDesktopBadge?.classList.contains('show') ? ' show' : '') + (alertDesktopBadge?.classList.contains('amber') ? ' amber' : '');
    }
  }

  function setMobileNavState(open){
    const body = document.body, btn = document.getElementById('tb-mobile-nav-btn'), overlay = document.getElementById('mobile-nav-overlay'), nav = document.getElementById('db-nav');
    body.classList.toggle('mobile-nav-open', !!open);
    if(btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if(overlay) overlay.classList.toggle('show', !!open);
    if(!open && nav) nav.style.transform = '';
    if(typeof alertDrawerOpen !== 'undefined' && alertDrawerOpen && open){ try{ toggleAlertDrawer(); }catch(e){} }
  }
  window.toggleMobileNav = function(){ if(!isDrawerViewport()) return; setMobileNavState(!document.body.classList.contains('mobile-nav-open')); };
  window.closeMobileNav = function(){ setMobileNavState(false); };

  function bindDrawerSwipe(){
    const nav = document.getElementById('db-nav'); if(!nav || nav.dataset.swipeBound === '1') return; nav.dataset.swipeBound = '1';
    nav.addEventListener('touchstart', function(e){ if(!isDrawerViewport() || !document.body.classList.contains('mobile-nav-open')) return; drawerTouch = { startX:e.touches[0].clientX, currentX:e.touches[0].clientX }; }, { passive:true });
    nav.addEventListener('touchmove', function(e){ if(!drawerTouch || !document.body.classList.contains('mobile-nav-open')) return; drawerTouch.currentX = e.touches[0].clientX; const dx = drawerTouch.currentX - drawerTouch.startX; if(dx < 0){ nav.style.transform = 'translateX(' + Math.max(dx, -nav.offsetWidth) + 'px)'; } }, { passive:true });
    nav.addEventListener('touchend', function(){ if(!drawerTouch) return; const dx = drawerTouch.currentX - drawerTouch.startX; nav.style.transform = ''; if(dx < -60) closeMobileNav(); drawerTouch = null; });
    nav.addEventListener('touchcancel', function(){ if(!drawerTouch) return; nav.style.transform = ''; drawerTouch = null; });
  }

  function setCardCollapsed(card, collapsed){ card.classList.toggle('collapsed', !!collapsed); const toggle = card.querySelector('.mobile-table-card-toggle'); if(toggle){ toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true'); } }
  function removeResponsiveCards(wrapper){ if(!wrapper) return; wrapper.querySelectorAll('.mobile-table-toolbar, .mobile-table-cards').forEach(function(el){ el.remove(); }); }
  function getWrapperResponsiveSignature(wrapper){ const table = wrapper?.querySelector('table'); if(!table) return 'no-table'; const bodyRows = table.tBodies && table.tBodies[0] ? table.tBodies[0].rows.length : 0; const headCols = table.tHead && table.tHead.rows[0] ? table.tHead.rows[0].cells.length : 0; const visible = wrapper.offsetParent === null ? 'hidden' : 'visible'; return [bodyRows, headCols, visible, isNarrowViewport() ? 'narrow' : 'wide'].join('|'); }

  function buildCardsForTable(wrapper, table){
    removeResponsiveCards(wrapper);
    const labels = getHeaderLabels(table);
    const rows = Array.from(table.querySelectorAll('tbody tr')).filter(function(row){ return row.children.length; });
    if(!rows.length) return;
    const caption = textOf(table.querySelector('caption')) || 'Mobile table';
    const toolbar = document.createElement('div');
    toolbar.className = 'mobile-table-toolbar';
    toolbar.innerHTML = '<div class="mobile-table-toolbar-title">' + caption + ' · ' + rows.length + ' rows</div><div class="mobile-table-toolbar-actions"><button type="button" class="mobile-table-toolbar-btn" data-table-action="expand">Expand all</button><button type="button" class="mobile-table-toolbar-btn" data-table-action="collapse">Collapse all</button></div>';
    const cards = document.createElement('div'); cards.className = 'mobile-table-cards';
    rows.forEach(function(row, rowIndex){
      const cells = Array.from(row.children); if(!cells.length) return; const firstCell = cells[0]; const title = plainCellText(firstCell) || labels[0] || ('Record ' + (rowIndex + 1)); const summary = buildSummary(labels, cells);
      const card = document.createElement('section'); card.className = 'mobile-table-card'; if(row.classList.contains('row-section')) card.classList.add('section'); if(row.classList.contains('row-total')) card.classList.add('total');
      const head = document.createElement('div'); head.className = 'mobile-table-card-head';
      const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'mobile-table-card-toggle'; toggle.setAttribute('aria-expanded', 'true');
      toggle.innerHTML = '<span class="mobile-table-card-title-wrap"><span class="mobile-table-card-title"></span><span class="mobile-table-card-summary"></span></span><span class="mobile-table-card-chevron" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span>';
      toggle.querySelector('.mobile-table-card-title').textContent = title; toggle.querySelector('.mobile-table-card-summary').textContent = summary || 'Tap to collapse'; toggle.addEventListener('click', function(){ setCardCollapsed(card, !card.classList.contains('collapsed')); });
      head.appendChild(toggle); card.appendChild(head);
      const body = document.createElement('div'); body.className = 'mobile-table-card-body';
      if(cells.length === 1 || firstCell.colSpan >= labels.length){ const only = document.createElement('div'); only.className = 'mobile-table-empty'; only.innerHTML = firstCell.innerHTML || '&nbsp;'; body.appendChild(only); }
      else { for(let i = 1; i < cells.length; i += 1){ const valueCell = cells[i], label = labels[i] || ('Column ' + (i + 1)), text = plainCellText(valueCell); const rowEl = document.createElement('div'); rowEl.className = 'mobile-table-row'; const labelEl = document.createElement('div'); labelEl.className = 'mobile-table-label'; labelEl.textContent = label; const valueEl = document.createElement('div'); valueEl.className = 'mobile-table-value'; valueEl.innerHTML = valueCell.innerHTML && valueCell.innerHTML.trim() ? valueCell.innerHTML : (text || '—'); rowEl.appendChild(labelEl); rowEl.appendChild(valueEl); body.appendChild(rowEl);} }
      if(!body.children.length){ const empty = document.createElement('div'); empty.className = 'mobile-table-empty'; empty.textContent = 'No visible values'; body.appendChild(empty); }
      card.appendChild(body); cards.appendChild(card);
    });
    toolbar.addEventListener('click', function(e){ const btn = e.target.closest('[data-table-action]'); if(!btn) return; const collapse = btn.getAttribute('data-table-action') === 'collapse'; cards.querySelectorAll('.mobile-table-card').forEach(function(card){ setCardCollapsed(card, collapse); }); });
    wrapper.appendChild(toolbar); wrapper.appendChild(cards);
  }

  function buildResponsiveCardsForWrapper(wrapper){ if(!wrapper) return; if(!isNarrowViewport()){ removeResponsiveCards(wrapper); wrapper.dataset.responsiveSig = ''; return; } const table = wrapper.querySelector('table'); if(!table){ removeResponsiveCards(wrapper); wrapper.dataset.responsiveSig = 'no-table'; return; } const nextSig = getWrapperResponsiveSignature(wrapper); if(wrapper.dataset.responsiveSig === nextSig) return; wrapper.dataset.responsiveSig = nextSig; buildCardsForTable(wrapper, table); }
  function markResponsiveWrapperDirty(wrapper){ if(!wrapper) return; responsiveDirtyWrappers.add(wrapper); scheduleResponsiveBuild(); }
  function flushResponsiveBuilds(){ const wrappers = Array.from(responsiveDirtyWrappers); responsiveDirtyWrappers.clear(); wrappers.forEach(function(wrapper){ try{ buildResponsiveCardsForWrapper(wrapper); }catch(err){ console.warn('Responsive wrapper rebuild failed', err); } }); syncMobileActionBar(); }
  function scheduleResponsiveBuild(){ if(responsiveBuildScheduled) return; responsiveBuildScheduled = true; requestAnimationFrame(function(){ responsiveBuildScheduled = false; flushResponsiveBuilds(); }); }
  function buildResponsiveCardTables(root){ const scope = root || document; const wrappers = scope.querySelectorAll('.rpt-wrap, .zs-wrap, .adm-table-wrap'); wrappers.forEach(function(wrapper){ markResponsiveWrapperDirty(wrapper); }); }
  window.buildResponsiveCardTables = buildResponsiveCardTables;
  function queueResponsiveBuild(target){ if(target){ if(target.matches && target.matches('.rpt-wrap, .zs-wrap, .adm-table-wrap')){ markResponsiveWrapperDirty(target); return; } const wrapper = target.closest ? target.closest('.rpt-wrap, .zs-wrap, .adm-table-wrap') : null; if(wrapper){ markResponsiveWrapperDirty(wrapper); return; } } buildResponsiveCardTables(document); }

  function ensureResponsiveObserver(){
    const main = document.getElementById('db-main'); if(responsiveObserver || !main) return;
    responsiveObserver = new MutationObserver(function(mutations){
      const dirty = new Set();
      mutations.forEach(function(m){
        let node = null; if(m.target && m.target.nodeType === 1){ node = m.target; } else if(m.target && m.target.parentElement){ node = m.target.parentElement; } if(!node) return;
        const wrapper = node.closest ? node.closest('.rpt-wrap, .zs-wrap, .adm-table-wrap') : null; if(wrapper) dirty.add(wrapper);
        if(m.type === 'childList'){ Array.from(m.addedNodes || []).forEach(function(added){ if(added.nodeType !== 1) return; if(added.matches && added.matches('.rpt-wrap, .zs-wrap, .adm-table-wrap')) dirty.add(added); const nested = added.querySelectorAll ? added.querySelectorAll('.rpt-wrap, .zs-wrap, .adm-table-wrap') : []; nested.forEach(function(w){ dirty.add(w); }); }); }
      });
      if(!dirty.size && isNarrowViewport()){ buildResponsiveCardTables(document); return; }
      dirty.forEach(function(wrapper){ markResponsiveWrapperDirty(wrapper); });
    });
    responsiveObserver.observe(main, { subtree:true, childList:true, characterData:false, attributes:true, attributeFilter:['class','style'] });
  }

  function ensureStatusObserver(){
    if(statusObserver) return;
    const targets = [document.getElementById('filter-context'), document.getElementById('filter-context-text'), document.getElementById('alert-badge'), document.getElementById('tb-upload-btn'), document.getElementById('app-view')].filter(Boolean);
    if(!targets.length) return;
    statusObserver = new MutationObserver(function(){ syncMobileActionBar(); });
    targets.forEach(function(node){ statusObserver.observe(node, { subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class','style','hidden'] }); });
  }

  function syncResponsiveLayout(){ ensureMobileNavElements(); ensureMobileActionBar(); ensureResponsiveObserver(); ensureStatusObserver(); if(!isDrawerViewport()) closeMobileNav(); queueResponsiveBuild(); syncMobileActionBar(); }
  window.syncResponsiveLayout = syncResponsiveLayout;
  function scheduleResponsiveSync(){ if(responsiveSyncScheduled) return; responsiveSyncScheduled = true; requestAnimationFrame(function(){ responsiveSyncScheduled = false; syncResponsiveLayout(); }); }

  function initResponsiveEnhancements(){
    if(responsiveInitDone) return; responsiveInitDone = true;
    syncResponsiveLayout();
    window.addEventListener('resize', scheduleResponsiveSync, { passive:true });
    window.addEventListener('orientationchange', function(){ scheduleResponsiveSync(); setTimeout(scheduleResponsiveSync, 180); }, { passive:true });
    document.addEventListener('keydown', function(e){ if(e.key === 'Escape') closeMobileNav(); });
    document.addEventListener('click', function(e){ if(!isDrawerViewport()) return; const nav = document.getElementById('db-nav'); const btn = document.getElementById('tb-mobile-nav-btn'); if(!document.body.classList.contains('mobile-nav-open')) return; if(nav && nav.contains(e.target)) return; if(btn && btn.contains(e.target)) return; closeMobileNav(); });
    document.addEventListener('click', function(e){ const navItem = e.target.closest('.nav-item, .nav-admin-link, .btn-logout'); if(navItem && isDrawerViewport()) setTimeout(closeMobileNav, 60); });
    window.addEventListener('beforeprint', function(){ closeMobileNav(); });
  }
  window.initResponsiveEnhancements = initResponsiveEnhancements;

  const _showApp = window.showApp; if(typeof _showApp === 'function'){ window.showApp = function(user){ const result = _showApp(user); setTimeout(function(){ initResponsiveEnhancements(); queueResponsiveBuild(); }, 30); return result; }; }
  const _navigate = window.navigate; if(typeof _navigate === 'function'){ window.navigate = function(page){ closeMobileNav(); const result = _navigate(page); setTimeout(queueResponsiveBuild, 80); return result; }; }
  const _loadPage = window.loadPage; if(typeof _loadPage === 'function'){ window.loadPage = async function(page){ const result = await _loadPage(page); queueResponsiveBuild(); return result; }; }
  const _openFilter = window.openFilter; if(typeof _openFilter === 'function'){ window.openFilter = function(){ closeMobileNav(); const result = _openFilter(); syncMobileActionBar(); return result; }; }
  const _toggleAlertDrawer = window.toggleAlertDrawer; if(typeof _toggleAlertDrawer === 'function'){ window.toggleAlertDrawer = function(){ closeMobileNav(); const result = _toggleAlertDrawer(); setTimeout(syncMobileActionBar, 30); return result; }; }
  const _reloadPage = window.reloadPage; if(typeof _reloadPage === 'function'){ window.reloadPage = function(page){ const result = _reloadPage(page); setTimeout(queueResponsiveBuild, 80); return result; }; }
  initResponsiveEnhancements(); if(document.getElementById('app-view')?.style.display !== 'none') queueResponsiveBuild();
})();
