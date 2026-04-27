/* ============================================================
   Ruta: static/js/nav-rbac.js
   Control de visibilidad del menu segun el rol del usuario.
   Lee window.USER_ROL inyectado por Flask en cada plantilla POS.
   ============================================================ */

'use strict';

(function () {
  const rol = window.USER_ROL || '';

  function isActivePath(href) {
    if (!href) return false;
    const path = window.location.pathname;
    if (href === path) return true;
    if (href === '/inventario') return path.startsWith('/inventario');
    if (href.startsWith('/pos/')) return path.startsWith(href);
    return false;
  }

  // Perfil disponible solo para Admin.
  if (rol !== 'Admin') {
    document.querySelectorAll('.nav-link[href="/perfil"], .bottom-btn[href="/perfil"], .bottom-more-link[href="/perfil"]').forEach((el) => {
      el.style.display = 'none';
    });
  }

  function ensureBottomMoreLogoutLink() {
    const bottomMorePanel = document.getElementById('bottom-more-panel');
    if (!bottomMorePanel) return;

    const sidebarLogout = document.querySelector('.sidebar-logout[href]');
    const logoutHref = sidebarLogout?.getAttribute('href') || '/logout';

    let logoutLink = bottomMorePanel.querySelector('[data-logout-btn]');

    if (!logoutLink) {
      logoutLink = document.createElement('a');
      logoutLink.className = 'bottom-more-link bottom-more-link-danger';
      logoutLink.setAttribute('data-logout-btn', 'true');
      logoutLink.setAttribute('aria-label', 'Cerrar sesion');
      logoutLink.innerHTML = '<i class="fa-solid fa-right-from-bracket"></i><span>Cerrar sesion</span>';
      bottomMorePanel.appendChild(logoutLink);
    }

    logoutLink.setAttribute('href', logoutHref);
    logoutLink.classList.add('bottom-more-link', 'bottom-more-link-danger');
  }

  function syncBottomBarWithSidebar() {
    // Mantiene el orden definido en cada plantilla; evita reordenamientos dinamicos.
    return;
  }

  // Solo aplicar restricciones al rol Cajero
  function applyCajeroRestrictions() {
    if (rol !== 'Cajero') return;

    // Links de sidebar y bottom-bar restringidos para Cajero
    const ADMIN_HREFS = ['/dashboard', '/inventario/insumos', '/inventario/proveedores'];

    document.querySelectorAll('.nav-link, .bottom-btn').forEach(function (el) {
      const href = el.getAttribute('href') || '';

      // Ocultar links de rutas admin-only
      if (ADMIN_HREFS.includes(href)) {
        el.style.display = 'none';
        return;
      }

      // Ocultar el link de Reportes (href="#" con icono fa-chart-line)
      if (href === '#' && el.querySelector('.fa-chart-line')) {
        el.style.display = 'none';
      }
    });
  }

  applyCajeroRestrictions();
  syncBottomBarWithSidebar();
  ensureBottomMoreLogoutLink();

}());
