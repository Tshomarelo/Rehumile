/* Rehumile TMW — HQ Shared Sidebar + Custom Drawer System */
(function () {

  // ── 1. Inject CSS ───────────────────────────────────────────────────────────
  var _st = document.createElement('style');
  _st.textContent = [
    /* Drawer panel — slides in from the right, always below the 56px navbar */
    '.hq-drawer{',
      'position:fixed;top:56px;right:0;bottom:0;',
      'width:580px;max-width:100vw;',
      'background:#fff;z-index:1055;',
      'display:flex;flex-direction:column;',
      'transform:translateX(110%);',
      'transition:transform .28s cubic-bezier(.4,0,.2,1);',
      'box-shadow:-6px 0 24px rgba(0,0,0,.18);',
    '}',
    '.hq-drawer.hq-open{transform:translateX(0)}',
    '.hq-drawer.hq-wide{width:780px}',
    /* Drawer sub-sections */
    '.hq-drawer-header{',
      'display:flex;align-items:center;justify-content:space-between;',
      'padding:.85rem 1.25rem;flex-shrink:0;',
      'background:#50181E;color:#fff;',
    '}',
    '.hq-drawer-title{font-size:1rem;font-weight:600;margin:0;color:#fff}',
    '.hq-drawer-body{flex:1;overflow-y:auto;padding:1.25rem}',
    '.hq-drawer-footer{',
      'flex-shrink:0;display:flex;justify-content:flex-end;gap:.5rem;',
      'padding:.85rem 1.25rem;border-top:1px solid #dee2e6;background:#fff;',
    '}',
    /* Backdrop — covers page from below navbar, does NOT cover navbar */
    '.hq-backdrop{',
      'display:none;position:fixed;',
      'top:56px;left:0;right:0;bottom:0;',
      'background:rgba(0,0,0,.45);z-index:1054;',
    '}',
    '.hq-backdrop.hq-open{display:block}',
  ].join('');
  document.head.appendChild(_st);

  // ── 2. Drawer JS API ────────────────────────────────────────────────────────
  window.HQ = {
    showDrawer: function(id) {
      var el = document.getElementById(id);
      var bd = document.getElementById(id + '-bd');
      if (!el) return;
      el.classList.add('hq-open');
      if (bd) bd.classList.add('hq-open');
      el.dispatchEvent(new CustomEvent('hq:show'));
    },
    hideDrawer: function(id) {
      var el = document.getElementById(id);
      var bd = document.getElementById(id + '-bd');
      if (!el) return;
      el.classList.remove('hq-open');
      if (bd) bd.classList.remove('hq-open');
      el.dispatchEvent(new CustomEvent('hq:hide'));
    },
  };

  // Delegated click: data-hq-show="#drawerId" opens, data-hq-hide closes
  document.addEventListener('click', function(e) {
    var show = e.target.closest('[data-hq-show]');
    if (show) { HQ.showDrawer(show.getAttribute('data-hq-show').replace('#','')); return; }
    var hide = e.target.closest('[data-hq-hide]');
    if (hide) { HQ.hideDrawer(hide.getAttribute('data-hq-hide').replace('#','')); return; }
  });

  // ── 3. Track sidebar collapsed state ───────────────────────────────────────
  var _sidebar = document.getElementById('sidebar');
  if (_sidebar) {
    function _syncCollapsed() {
      document.body.classList.toggle('hq-sidebar-collapsed', _sidebar.classList.contains('collapsed'));
    }
    _syncCollapsed();
    new MutationObserver(_syncCollapsed).observe(_sidebar, { attributes: true, attributeFilter: ['class'] });
  }

  // ── 4. Build sidebar nav ────────────────────────────────────────────────────
  var nav = document.querySelector('.sidebar .sidebar-nav');
  if (!nav) return;

  var path = window.location.pathname;

  function isActive(href) {
    try { return new URL(href, location.href).pathname === path; } catch(e) { return false; }
  }
  function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function header(label) { return '<li class="sidebar-header">'+esc(label)+'</li>'; }
  function link(href, icon, label, extra) {
    var a = isActive(href) ? ' active' : '';
    return '<li class="sidebar-item'+a+'"><a class="sidebar-link" href="'+href+'"'+(extra||'')+'>'
      +'<i class="align-middle" data-feather="'+icon+'"></i> <span class="align-middle">'+esc(label)+'</span></a></li>';
  }
  function submenu(id, icon, label, items) {
    var anyActive = items.some(function(i){ return isActive(i[0]); });
    var sub = items.map(function(i){
      var tgt = i[2] ? ' target="'+i[2]+'"' : '';
      var a = isActive(i[0]) ? ' active' : '';
      return '<li class="sidebar-item'+a+'"><a class="sidebar-link" href="'+i[0]+'"'+tgt+'>'+esc(i[1])+'</a></li>';
    }).join('');
    return '<li class="sidebar-item">'+
      '<a data-bs-target="#'+id+'" data-bs-toggle="collapse" class="sidebar-link'+(anyActive?'':' collapsed')+'" href="#">'+
      '<i class="align-middle" data-feather="'+icon+'"></i> <span class="align-middle">'+esc(label)+'</span></a>'+
      '<ul id="'+id+'" class="sidebar-dropdown list-unstyled collapse'+(anyActive?' show':'')+'">'+ sub+'</ul></li>';
  }

  nav.innerHTML = [
    header('Operations'),
    link('/portal/dashboard/', 'sliders', 'HQ Dashboard'),
    submenu('nav-incidents','alert-circle','Incidents',[
      ['/portal/incidents/','All Incidents'],
      ['/portal/dashboard/sla-monitor/','SLA Monitor'],
    ]),
    link('/portal/companies/','briefcase','Companies'),
    link('/portal/users/','users','Users'),
    header('Workshop'),
    submenu('nav-workshop','tool','Workshop',[
      ['/portal/dashboard/job-cards/','Job Cards'],
      ['/portal/dashboard/inventory/','Inventory'],
    ]),
    header('Finance'),
    submenu('nav-finance','dollar-sign','Finance',[
      ['/portal/invoices/','Invoices'],
      ['/portal/reports/','Reports'],
      ['/portal/dashboard/pos/','POS'],
      ['/portal/dashboard/vouchers/','Vouchers'],
      ['/portal/dashboard/cash-management/','Cash Management'],
      ['/portal/dashboard/financial-analytics/','Financial Analytics'],
    ]),
    header('Compliance'),
    submenu('nav-compliance','shield','Compliance',[
      ['/portal/dashboard/compliance/','SARS Hub'],
      ['/portal/dashboard/vat201/','VAT201 Staging'],
      ['/portal/dashboard/emp201/','EMP201 Payroll'],
    ]),
    header('HR'),
    submenu('nav-hr','user-check','HR',[
      ['/portal/dashboard/hr/','Employee Profiles'],
      ['/portal/dashboard/playbook/','Operational Playbook'],
      ['/portal/dashboard/settings/#banking-details','Company Banking Details'],
    ]),
    header('Revenue'),
    submenu('nav-revenue','trending-up','Revenue',[
      ['/portal/dashboard/wifi-sla/','Subscriber & Contract Registry'],
      ['/portal/dashboard/revenue-intelligence/','Business Intelligence'],
    ]),
    header('Website'),
    link('/portal/dashboard/website/','globe','Website Manager'),
    header('System'),
    submenu('nav-system','settings','System',[
      ['/portal/dashboard/notifications/','Notifications'],
      ['/portal/dashboard/audit-log/','Audit Log'],
      ['/portal/dashboard/settings/','Company Settings'],
      ['/portal/admin/','Admin Panel','_blank'],
    ]),
  ].join('\n');

  if (typeof feather !== 'undefined') feather.replace();
})();
