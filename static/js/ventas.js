/* ============================================================
   Ruta: static/js/ventas.js
   Pantalla: Historial de Ventas
   Depende de: filtros-paginacion.js y ventas-comun.js (cargados antes)

   La lista llega paginada de /pos/api/ventas: cambiar de capsula, de fecha o
   de pagina vuelve a pedir solo esa pagina, sin recargar la pantalla. La
   tarjeta, la fila y el ticket viven en ventas-comun.js (tambien los usa el
   modal de trabajador del Panel de Control).
   ============================================================ */

(function () {
  'use strict';

  const V = window.JemVentas;

  const cardsEl = document.getElementById('ventas-cards');
  const tableBody = document.getElementById('ventas-table-body');
  const tableWrap = document.getElementById('ventas-table-wrap');
  const emptyEl = document.getElementById('ventas-empty');

  const statHoy = document.getElementById('stat-hoy');
  const statMes = document.getElementById('stat-mes');

  function render(ventas) {
    cardsEl.innerHTML = ventas.map(V.buildCard).join('');
    tableBody.innerHTML = ventas.map(V.buildRow).join('');

    /* classList y no style.display: gastos.css oculta con .hidden !important */
    const vacio = ventas.length === 0;
    cardsEl.classList.toggle('hidden', vacio);
    tableWrap.classList.toggle('hidden', vacio);
    emptyEl.classList.toggle('hidden', !vacio);
  }

  function renderTotales(t) {
    if (!t) return;
    statHoy.textContent = V.money(t.hoy);
    statMes.textContent = V.money(t.mes);
  }

  /* ── Carga paginada ──────────────────────────────────────── */
  const filtros = window.JemFiltros.init({
    id: 'ventas',
    filtro: 'mes',   /* respaldo: la capsula activa del HTML manda */
    limit: 20,
    onChange: cargar,
  });

  /* Cada peticion lleva numero: si el usuario cambia de capsula mientras una
     esta en vuelo, la respuesta vieja se descarta en vez de pisar la nueva.
     Descartar el clic seria peor: la capsula quedaria activa con datos viejos. */
  let peticion = 0;

  async function cargar() {
    const mia = ++peticion;
    try {
      const res = await fetch('/pos/api/ventas?' + filtros.query(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();
      if (mia !== peticion) return;
      if (!data.ok) {
        notify(data.msg || 'No fue posible cargar las ventas.', 'error');
        return;
      }
      render(data.ventas || []);
      renderTotales(data.totales);
      filtros.setMeta(data.meta);
    } catch (_) {
      if (mia === peticion) notify('Sin conexion con el servidor.', 'error');
    }
  }

  function notify(msg, type) {
    if (window.JemToast && typeof window.JemToast.show === 'function') {
      window.JemToast.show(msg, type || 'info', { duration: 3000 });
      return;
    }
    console[type === 'error' ? 'error' : 'log'](msg);
  }

  V.enlazar(cardsEl);
  V.enlazar(tableBody);

  cargar();
})();
