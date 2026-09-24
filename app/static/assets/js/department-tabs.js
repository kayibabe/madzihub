/* ═══════════════════════════════════════════════════════════════════════
   Department tabs controller
   Top-level switcher: Board View · Operations · Finance · Human Resource &
   Administration · Infrastructure. Each tab swaps in its own sidebar menu.
   - Board / Operations / HR / Infrastructure -> live pages (stub:false)
   - Finance -> filter-aware "coming soon" welcome screen (stub:true)
   Loads after app-core.js so globals (buildCompactFilterSummary, currentPage,
   updatePageMeta, navigate) are available.
   ═══════════════════════════════════════════════════════════════════════ */
(function(){
  'use strict';

  var STORE_KEY = 'srwb.activeDepartment';

  // Small inline SVG helpers (stroke-based, inherit currentColor).
  function ico(paths){
    return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' + paths + '</svg>';
  }
  var ICONS = {
    board:         '<rect x="3" y="3" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="13" y="3" width="8" height="5" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="13" y="10" width="8" height="11" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="3" y="13" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.7"/>',
    operations:    '<path d="M3 13h4l2-7 4 14 2-7h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    finance:       '<path d="M3 20h18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><rect x="5" y="11" width="3" height="6" rx="1" stroke="currentColor" stroke-width="1.7"/><rect x="10.5" y="7" width="3" height="10" rx="1" stroke="currentColor" stroke-width="1.7"/><rect x="16" y="4" width="3" height="13" rx="1" stroke="currentColor" stroke-width="1.7"/>',
    hr:            '<circle cx="9" cy="8" r="3.2" stroke="currentColor" stroke-width="1.7"/><path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M16 4.5a3 3 0 010 6M17.5 14c2.4.3 4 2.3 4 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    infrastructure:'<path d="M4 21V8l8-5 8 5v13" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M9 21v-6h6v6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 21h16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    reports:        '<path d="M6 3h8l5 5v13H6z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
  };

  // Module preview icons.
  var M = {
    chart:   '<path d="M4 19V5M4 19h16M8 16v-4M12 16V9M16 16v-2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    cash:    '<rect x="3" y="6" width="18" height="12" rx="2" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="2.4" stroke="currentColor" stroke-width="1.7"/>',
    shield:  '<path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M9 12l2 2 4-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
    cart:    '<path d="M3 4h2l2 12h11l2-8H6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><circle cx="9" cy="20" r="1.4" stroke="currentColor" stroke-width="1.6"/><circle cx="18" cy="20" r="1.4" stroke="currentColor" stroke-width="1.6"/>',
    building:'<path d="M5 21V4h9v17M14 9h5v12M5 21h16" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M8 8h3M8 12h3M8 16h3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    doc:     '<path d="M6 3h8l5 5v13H6z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    people:  '<circle cx="9" cy="8" r="3" stroke="currentColor" stroke-width="1.7"/><path d="M4 19c0-2.8 2.2-5 5-5s5 2.2 5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M15 5a2.8 2.8 0 010 5.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    wallet:  '<rect x="3" y="6" width="18" height="13" rx="2" stroke="currentColor" stroke-width="1.7"/><path d="M16 12h2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M3 9h13" stroke="currentColor" stroke-width="1.6"/>',
    calendar:'<rect x="4" y="5" width="16" height="16" rx="2" stroke="currentColor" stroke-width="1.7"/><path d="M4 9h16M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    target:  '<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="3.5" stroke="currentColor" stroke-width="1.7"/>',
    cap:     '<path d="M3 8l9-4 9 4-9 4-9-4z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M7 10v5c0 1.5 2.2 3 5 3s5-1.5 5-3v-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    gauge:   '<path d="M5 17a8 8 0 1114 0" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M12 17l4-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    wrench:  '<path d="M15 7a4 4 0 01-5.2 4.7L5 16.5 7.5 19l4.8-4.8A4 4 0 0017 9l-2 2-2-2 2-2z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    truck:   '<rect x="3" y="7" width="11" height="9" rx="1" stroke="currentColor" stroke-width="1.7"/><path d="M14 10h4l3 3v3h-7z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="7" cy="18" r="1.6" stroke="currentColor" stroke-width="1.6"/><circle cx="17" cy="18" r="1.6" stroke="currentColor" stroke-width="1.6"/>',
    map:     '<path d="M9 4L4 6v14l5-2 6 2 5-2V4l-5 2-6-2z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M9 4v14M15 6v14" stroke="currentColor" stroke-width="1.6"/>'
  };

  // Department definitions. `board` and `operations` are live workspaces;
  // the rest are stubs with a curated module roadmap.
  // `landing` (live depts only) navigates to that page on an explicit
  // user switch, giving the tab a distinct entry point.
  var DEPARTMENTS = {
    board:      { label:'Board View', icon:ICONS.board, stub:false, landing:'board' },
    operations: { label:'Operations', icon:ICONS.operations, stub:false },
    finance:        { label:'Finance', icon:ICONS.finance, stub:false, landing:'finance' },
    hr:             { label:'Human Resource & Administration', icon:ICONS.hr, stub:false, landing:'hra' },
    infrastructure: { label:'Infrastructure', icon:ICONS.infrastructure, stub:false, landing:'infrastructure' },
    reports:        { label:'Reports', icon:ICONS.reports, stub:false, landing:'report-centre' }
  };

  var ORDER = ['board','operations','finance','hr','infrastructure','reports'];

  function tabBarHTML(){
    return ORDER.map(function(key){
      var d = DEPARTMENTS[key];
      var soon = d.stub ? '<span class="dept-tab-soon">Soon</span>' : '';
      var aria = d.stub ? ' aria-label="'+d.label+' (coming soon)"' : '';
      return '<button type="button" class="dept-tab" data-dept="'+key+'"'+aria+' '
           + 'onclick="switchDepartment(\''+key+'\')">'
           + '<span class="dept-tab-icon" aria-hidden="true">'+ico(d.icon)+'</span>'
           + '<span>'+d.label+'</span>'+soon+'</button>';
    }).join('');
  }

  function comingSoonHTML(d){
    var cards = d.modules.map(function(m){
      return '<div class="dept-soon-card">'
           + '<span class="dept-soon-card-tag">Planned</span>'
           + '<div class="dept-soon-card-ico">'+ico(m.i)+'</div>'
           + '<h4 class="dept-soon-card-title">'+m.t+'</h4>'
           + '<p class="dept-soon-card-desc">'+m.d+'</p></div>';
    }).join('');

    return '<div class="dept-soon-wrap">'
      + '<div class="dept-soon-hero">'
      +   '<div class="dept-soon-badge-ico">'+ico(d.icon)+'</div>'
      +   '<div class="dept-soon-hero-body">'
      +     '<span class="dept-soon-eyebrow"><span class="pulse-dot"></span>Coming Soon</span>'
      +     '<h2 class="dept-soon-title">'+d.title+'</h2>'
      +     '<p class="dept-soon-tagline">'+d.tagline+'</p>'
      +     '<div class="dept-soon-scope">Current selection: <span id="dept-soon-scope-val"><b>—</b></span></div>'
      +   '</div>'
      + '</div>'
      + '<div class="dept-soon-section-label">Modules on the roadmap</div>'
      + '<div class="dept-soon-grid">'+cards+'</div>'
      + '<div class="dept-soon-foot">'
      +   '<svg viewBox="0 0 24 24" fill="none"><path d="M12 8v5M12 16h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7"/></svg>'
      +   '<div class="dept-soon-foot-txt"><b>This module is under active development.</b> '
      +     'The filters above (financial year, zone and period) are already wired in — '
      +     'as soon as the data feeds are connected, this workspace will respond to them just like Operations does today.</div>'
      +   '<button type="button" onclick="switchDepartment(\'operations\')">Back to Operations</button>'
      + '</div>'
      + '</div>';
  }

  function refreshScope(){
    var el = document.getElementById('dept-soon-scope-val');
    if(!el) return;
    var txt = (typeof window.buildCompactFilterSummary === 'function')
      ? window.buildCompactFilterSummary() : '';
    el.innerHTML = '<b>' + (window.DOMPurify ? DOMPurify.sanitize(txt) : txt) + '</b>';
  }

  function setActiveTab(dept){
    document.querySelectorAll('#dept-tabs .dept-tab').forEach(function(b){
      var on = b.getAttribute('data-dept') === dept;
      b.classList.toggle('active', on);
      if(on){ b.setAttribute('aria-current','page'); } else { b.removeAttribute('aria-current'); }
    });
    // Swap the sidebar to this department's own menu.
    document.querySelectorAll('#db-nav .dept-menu').forEach(function(m){
      m.classList.toggle('is-active', m.getAttribute('data-dept-menu') === dept);
    });
  }

  // Which department owns a given live page — derived from which sidebar
  // menu actually contains that page's nav item, so it always matches the
  // HTML structure (Board owns Consolidated Summary, Executive Dashboard,
  // Benchmarking, Report Centre, Compliance; Operations owns the rest).
  function deptForPage(page){
    var item = document.querySelector('#db-nav .dept-menu .nav-item[data-page="' + page + '"]');
    var menu = item && item.closest('.dept-menu');
    if(menu) return menu.getAttribute('data-dept-menu');
    // Unknown page (e.g. the shared 'soon' placeholder) — keep the current
    // department so a "coming soon" item doesn't bounce the user to Operations.
    var active = document.querySelector('#dept-tabs .dept-tab.active');
    return active ? active.getAttribute('data-dept') : 'operations';
  }

  // Public: open the shared placeholder page for a not-yet-built module,
  // staying within the current department.
  window.openSoon = function(title, msg){
    var set = function(id, txt){ var el = document.getElementById(id); if(el) el.textContent = txt; };
    set('soon-title', title); set('soon-panel-title', title);
    set('soon-panel-msg', msg || 'Awaiting its data feed.');
    set('soon-sub', msg || 'This module is on the delivery roadmap.');
    if(typeof window.navigate === 'function') window.navigate('soon');
    var main = document.getElementById('db-main'); if(main) main.scrollTop = 0;
  };

  // Last Operations page visited, so returning to the Operations tab from
  // another department lands on a real operations page (never a board page).
  var lastLivePage = 'production';

  // Reflect the current live page in the tab strip and clear any stub
  // overlay. Called from the navigate() wrapper so the tabs always track
  // wherever navigation actually landed (sidebar, breadcrumb, post-login).
  function syncTabsToPage(page){
    if(!page) return;
    document.body.classList.remove('dept-stub');
    var dept = deptForPage(page);
    setActiveTab(dept);
    try{ localStorage.setItem(STORE_KEY, dept); }catch(e){}
    if(dept === 'operations') lastLivePage = page;
  }

  // Public: switch the active top-level department.
  window.switchDepartment = function(dept){
    var d = DEPARTMENTS[dept];
    if(!d) dept = 'operations', d = DEPARTMENTS.operations;

    if(d.stub){
      // Stub departments are an overlay, not a page — no navigation.
      setActiveTab(dept);
      try{ localStorage.setItem(STORE_KEY, dept); }catch(e){}
      var soon = document.getElementById('dept-coming-soon');
      if(soon) soon.innerHTML = comingSoonHTML(d);
      document.body.classList.add('dept-stub');
      refreshScope();
      var main = document.getElementById('db-main');
      if(main) main.scrollTop = 0;
      return;
    }

    // Live department → navigate to its landing page (Board→board,
    // HR→hra, Infrastructure→infrastructure). Operations has no landing,
    // so it returns to the last operations page visited. The navigate()
    // wrapper then syncs the tab strip and clears any stub overlay.
    var target = d.landing || lastLivePage;
    if(typeof window.navigate === 'function'){
      window.navigate(target);
    }else{
      setActiveTab(dept);
    }
  };

  // Wrap navigate() so the department tabs follow whatever page is shown.
  function wrapNavigate(){
    if(typeof window.navigate !== 'function' || window.navigate.__deptWrapped) return;
    var orig = window.navigate;
    window.navigate = function(page){
      var r = orig.apply(this, arguments);
      try{ syncTabsToPage(page); }catch(e){}
      return r;
    };
    window.navigate.__deptWrapped = true;
  }

  function init(){
    var rightCol = document.getElementById('db-right-col');
    var topbar = document.getElementById('db-topbar');
    var main = document.getElementById('db-main');
    if(!rightCol || !topbar || !main) return;

    // Build the tab strip and insert it directly beneath the top bar.
    if(!document.getElementById('dept-tabs')){
      var tabs = document.createElement('div');
      tabs.id = 'dept-tabs';
      tabs.setAttribute('role','group');
      tabs.setAttribute('aria-label','Department views');
      tabs.innerHTML = tabBarHTML();
      topbar.insertAdjacentElement('afterend', tabs);
    }

    // The coming-soon host lives inside the scroll pane alongside the pages.
    if(!document.getElementById('dept-coming-soon')){
      var soon = document.createElement('div');
      soon.id = 'dept-coming-soon';
      main.appendChild(soon);
    }

    // Keep the welcome-screen scope echo in sync with the global filter
    // summary updater.
    if(typeof window.updatePageMeta === 'function' && !window.updatePageMeta.__deptWrapped){
      var orig = window.updatePageMeta;
      window.updatePageMeta = function(){
        var r = orig.apply(this, arguments);
        refreshScope();
        return r;
      };
      window.updatePageMeta.__deptWrapped = true;
    }

    // Make the tab strip follow page navigation (sidebar, breadcrumb, and
    // the post-login landing all route through navigate()).
    wrapNavigate();

    // Wire any "Soon" sidebar items that have no explicit handler to the
    // shared placeholder page, deriving the title from their label.
    document.querySelectorAll('#db-nav .nav-item-soon:not([onclick])').forEach(function(it){
      var label = (it.querySelector('.nav-item-label')||{}).textContent || 'Coming soon';
      it.addEventListener('click', function(){ window.openSoon(label, 'This module is on the delivery roadmap, awaiting its data feed.'); });
    });

    // Cosmetic default while the login screen is up; the first real
    // navigate() after sign-in sets the correct tab. If the app already
    // has an active page (e.g. hot reload), reflect it now.
    var active = document.querySelector('#db-main > .db-page.active');
    if(active){
      syncTabsToPage(active.id.replace('page-',''));
    }else{
      setActiveTab('board');
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  }else{
    init();
  }
})();
