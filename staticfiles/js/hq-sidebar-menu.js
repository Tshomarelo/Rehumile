/* Rehumile TMW — HQ Shared Sidebar with Collapsible Submenus
   Include AFTER app.js on every HQ page. Replaces the static sidebar-nav
   with a full menu definition that auto-expands the current section.
*/
(function () {

  // ── 1. Inject shared CSS ────────────────────────────────────────────────────
  // Keep the navbar hamburger ALWAYS accessible (top:56px at every viewport).
  // On desktop (≥992px) with the sidebar visible, also offset the modal left of
  // the sidebar so the sidebar itself stays reachable.
  // Targets div.modal.fade (Bootstrap-specific) — does NOT affect custom modal
  // overlays (e.g. hq-website.html uses .modal-overlay, not div.modal.fade).
  // body.hq-sidebar-collapsed is toggled below to track the sidebar state.
  var _st = document.createElement('style');
  _st.textContent = (
    // Backdrop always starts below navbar
    '.modal-backdrop{top:56px!important}' +
    // Navbar sits above modal backdrop so hamburger is always clickable
    '.navbar.navbar-bg{position:relative;z-index:1060!important}'
  );
  document.head.appendChild(_st);

  // ── JS-driven modal positioning (more reliable than pure CSS) ───────────────
  // Runs on every modal open/close and on sidebar toggle so modals never
  // overlap the sidebar regardless of viewport width.
  function _positionModals() {
    var sidebarEl = document.getElementById('sidebar');
    var sidebarOpen = sidebarEl && !sidebarEl.classList.contains('collapsed');
    var left = sidebarOpen ? '260px' : '0';
    var width = sidebarOpen ? 'calc(100% - 260px)' : '100%';
    document.querySelectorAll('div.modal').forEach(function(m) {
      m.style.top = '56px';
      m.style.height = 'calc(100% - 56px)';
      m.style.left = left;
      m.style.width = width;
    });
    document.querySelectorAll('.modal-backdrop').forEach(function(b) {
      b.style.top = '56px';
      b.style.left = left;
      b.style.width = width;
    });
  }
  document.addEventListener('show.bs.modal', _positionModals);
  document.addEventListener('shown.bs.modal', _positionModals);
  document.addEventListener('hidden.bs.modal', _positionModals);

  // ── 2. Track sidebar collapsed state ───────────────────────────────────────
  var _sidebar = document.getElementById('sidebar');
  if (_sidebar) {
    function _syncCollapsed() {
      document.body.classList.toggle('hq-sidebar-collapsed', _sidebar.classList.contains('collapsed'));
      _positionModals();
    }
    _syncCollapsed();
    new MutationObserver(_syncCollapsed).observe(_sidebar, { attributes: true, attributeFilter: ['class'] });
  }

  // ── 3. Build sidebar nav ────────────────────────────────────────────────────
  var nav = document.querySelector('.sidebar .sidebar-nav');
  if (!nav) return;

  var path = window.location.pathname;

  function isActive(href) {
    try {
      var p = new URL(href, location.href).pathname;
      return p === path;
    } catch (e) { return false; }
  }

  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function header(label) {
    return '<li class="sidebar-header">' + esc(label) + '</li>';
  }

  function link(href, icon, label, extra) {
    var active = isActive(href) ? ' active' : '';
    return '<li class="sidebar-item' + active + '">' +
      '<a class="sidebar-link" href="' + href + '"' + (extra || '') + '>' +
      '<i class="align-middle" data-feather="' + icon + '"></i>' +
      ' <span class="align-middle">' + esc(label) + '</span></a></li>';
  }

  function submenu(id, icon, label, items) {
    var anyActive = items.some(function (i) { return isActive(i[0]); });
    var sub = items.map(function (i) {
      var href = i[0], lbl = i[1], tgt = i[2] ? ' target="' + i[2] + '"' : '';
      var active = isActive(href) ? ' active' : '';
      return '<li class="sidebar-item' + active + '">' +
        '<a class="sidebar-link" href="' + href + '"' + tgt + '>' + esc(lbl) + '</a></li>';
    }).join('');
    var collapsed = anyActive ? '' : ' collapsed';
    var show = anyActive ? ' show' : '';
    return '<li class="sidebar-item">' +
      '<a data-bs-target="#' + id + '" data-bs-toggle="collapse" ' +
      'class="sidebar-link' + collapsed + '" href="#">' +
      '<i class="align-middle" data-feather="' + icon + '"></i>' +
      ' <span class="align-middle">' + esc(label) + '</span></a>' +
      '<ul id="' + id + '" class="sidebar-dropdown list-unstyled collapse' + show + '">' +
      sub + '</ul></li>';
  }

  nav.innerHTML = [
    header('Operations'),
    link('/portal/dashboard/', 'sliders', 'HQ Dashboard'),
    submenu('nav-incidents', 'alert-circle', 'Incidents', [
      ['/portal/incidents/', 'All Incidents'],
      ['/portal/dashboard/sla-monitor/', 'SLA Monitor'],
    ]),
    link('/portal/companies/', 'briefcase', 'Companies'),
    link('/portal/users/', 'users', 'Users'),

    header('Workshop'),
    submenu('nav-workshop', 'tool', 'Workshop', [
      ['/portal/dashboard/job-cards/', 'Job Cards'],
      ['/portal/dashboard/inventory/', 'Inventory'],
    ]),

    header('Finance'),
    submenu('nav-finance', 'dollar-sign', 'Finance', [
      ['/portal/invoices/', 'Invoices'],
      ['/portal/reports/', 'Reports'],
      ['/portal/dashboard/pos/', 'POS'],
      ['/portal/dashboard/vouchers/', 'Vouchers'],
      ['/portal/dashboard/cash-management/', 'Cash Management'],
      ['/portal/dashboard/financial-analytics/', 'Financial Analytics'],
    ]),

    header('Compliance'),
    submenu('nav-compliance', 'shield', 'Compliance', [
      ['/portal/dashboard/compliance/', 'SARS Hub'],
      ['/portal/dashboard/vat201/', 'VAT201 Staging'],
      ['/portal/dashboard/emp201/', 'EMP201 Payroll'],
    ]),

    header('HR'),
    submenu('nav-hr', 'user-check', 'HR', [
      ['/portal/dashboard/hr/', 'Employee Profiles'],
      ['/portal/dashboard/playbook/', 'Operational Playbook'],
    ]),

    header('Revenue'),
    submenu('nav-revenue', 'trending-up', 'Revenue', [
      ['/portal/dashboard/wifi-sla/', 'Subscriber & Contract Registry'],
      ['/portal/dashboard/revenue-intelligence/', 'Business Intelligence'],
    ]),

    header('Website'),
    link('/portal/dashboard/website/', 'globe', 'Website Manager'),

    header('System'),
    submenu('nav-system', 'settings', 'System', [
      ['/portal/dashboard/notifications/', 'Notifications'],
      ['/portal/dashboard/audit-log/', 'Audit Log'],
      ['/portal/dashboard/settings/', 'Company Settings'],
      ['/portal/admin/', 'Admin Panel', '_blank'],
    ]),
  ].join('\n');

  if (typeof feather !== 'undefined') feather.replace();
})();
