/* ============================================================
   Ruta: static/js/nav-rbac.js
   Control de visibilidad del menu segun el rol del usuario, y
   centrado del enlace activo en la barra inferior movil.
   Lee window.USER_ROL inyectado por Flask en cada plantilla POS.
   ============================================================ */

'use strict';

(function () {
  const rol = window.USER_ROL || '';

  // Solo aplicar restricciones al rol Cajero
  function applyCajeroRestrictions() {
    if (rol !== 'Cajero') return;

    // Links de sidebar y bottom-bar restringidos para Cajero
    const ADMIN_HREFS = ['/dashboard', '/inventario/insumos', '/inventario/proveedores'];

    document.querySelectorAll('.nav-link, .bottom-btn').forEach(function (el) {
      const href = el.getAttribute('href') || '';
      if (ADMIN_HREFS.includes(href)) {
        el.style.display = 'none';
      }
    });
  }

  // La barra inferior movil hace scroll horizontal; centra el enlace
  // activo para que no quede fuera de vista al cargar la pagina.
  function centerActiveBottomNavLink() {
    const bar = document.querySelector('[data-bottom-nav]');
    const active = bar && bar.querySelector('.bottom-btn.active');
    if (active) {
      active.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'center' });
    }
  }

  applyCajeroRestrictions();
  centerActiveBottomNavLink();
}());
