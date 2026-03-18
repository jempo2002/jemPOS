/* ============================================================
   Ruta: static/js/nav-rbac.js
   Control de visibilidad del menu segun el rol del usuario.
   Lee window.USER_ROL inyectado por Flask en cada plantilla POS.
   ============================================================ */

'use strict';

(function () {
  const rol = window.USER_ROL || '';

  // Perfil disponible solo para Admin.
  if (rol !== 'Admin') {
    document.querySelectorAll('.nav-link[href="/perfil"], .bottom-btn[href="/perfil"]').forEach((el) => {
      el.style.display = 'none';
    });
  }

  function ensureProveedoresLink(containerSelector, linkClass) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    if (container.querySelector('a[href="/proveedores"]')) return;

    const beforeNode = container.querySelector('a[href="/fiados"]');
    const a = document.createElement('a');
    a.setAttribute('href', '/proveedores');
    a.className = linkClass;
    a.innerHTML = '<i class="fa-solid fa-truck-field"></i><span>Proveedores</span>';

    if (window.location.pathname === '/proveedores') {
      a.classList.add('active');
      a.setAttribute('aria-current', 'page');
    }

    if (beforeNode) {
      container.insertBefore(a, beforeNode);
    } else {
      container.appendChild(a);
    }
  }

  if (rol === 'Admin' || rol === 'Master') {
    ensureProveedoresLink('.sidebar-nav', 'nav-link');
    ensureProveedoresLink('.bottom-bar', 'bottom-btn');
  }

  // Solo aplicar restricciones al rol Cajero
  if (rol !== 'Cajero') return;

  // Links de sidebar y bottom-bar restringidos para Cajero
  const ADMIN_HREFS = ['/dashboard', '/insumos', '/proveedores'];

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
}());
