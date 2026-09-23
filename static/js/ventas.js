/* ============================================================
   Ruta: static/js/ventas.js
   Pantalla: Historial de Ventas
   Depende de: filtros-paginacion.js (cargado antes en el HTML)

   La lista llega paginada de /pos/api/ventas: cambiar de capsula, de fecha o
   de pagina vuelve a pedir solo esa pagina, sin recargar la pantalla.
   ============================================================ */

(function () {
  'use strict';

  const modal = document.getElementById('modal-detalle');
  const closeModalBtn = document.getElementById('btn-cerrar-modal');
  const pdfBtn = document.getElementById('btn-pdf');
  const ticketNumero = document.getElementById('ticket-numero');
  const ticketLoading = document.getElementById('ticket-loading');
  const ticketDetalle = document.getElementById('ticket-detalle');
  const ticketTotal = document.getElementById('ticket-total');
  const ticketContent = document.getElementById('ticket-content');
  const apiDetalleBase = '/pos/api/ventas/detalle/';

  const cardsEl = document.getElementById('ventas-cards');
  const tableBody = document.getElementById('ventas-table-body');
  const tableWrap = document.getElementById('ventas-table-wrap');
  const emptyEl = document.getElementById('ventas-empty');

  function money(value) {
    return '$' + Number(value || 0).toLocaleString('es-CO', { maximumFractionDigits: 0 });
  }

  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* Los contenedores de tarjetas/tabla los gobierna ventas.css segun el ancho:
     se ocultan con style.display para no pelear con la utilidad de Tailwind. */
  function mostrar(el, visible, displayVisible) {
    if (!el) return;
    el.style.display = visible ? (displayVisible || '') : 'none';
  }

  const ESTADOS = {
    'Pagada': 'bg-green-100 text-green-800',
    'Anulada': 'bg-red-100 text-red-800',
    'Fiada/Pendiente': 'bg-orange-100 text-orange-800',
  };

  function badgeEstado(estado) {
    const clases = ESTADOS[estado] || 'bg-gray-200 text-gray-700';
    return `<span class="rounded-full px-3 py-1 text-xs font-bold ${clases}">${esc(estado)}</span>`;
  }

  function botonDetalle(id) {
    return `<button type="button" class="btn-ver-detalle bg-blue-100 text-blue-700 rounded-xl px-4 py-2 text-center font-semibold" data-id="${Number(id)}">Ver Detalle</button>`;
  }

  function buildCard(v) {
    return `
    <div class="bg-gray-50 rounded-2xl p-5 border border-gray-100 flex flex-col gap-3">
      <div class="flex items-center justify-between gap-3">
        <p class="text-sm font-semibold text-gray-800">Venta #${Number(v.id_venta)}</p>
        ${badgeEstado(v.estado_venta)}
      </div>
      <p class="text-sm text-gray-700"><span class="font-semibold text-gray-800">Cliente:</span> ${esc(v.nombre_cliente)}</p>
      <p class="text-lg font-bold text-gray-900">${money(v.total_final)}</p>
      <p class="text-xs text-gray-500">${esc(v.fecha || 'Sin fecha')}</p>
      ${botonDetalle(v.id_venta)}
    </div>`;
  }

  function buildRow(v) {
    return `
    <tr class="border-b border-gray-50 hover:bg-gray-50 transition">
      <td class="py-4 text-sm font-semibold text-gray-800">#${Number(v.id_venta)}</td>
      <td class="py-4 text-sm text-gray-700">${esc(v.fecha || 'Sin fecha')}</td>
      <td class="py-4 text-sm text-gray-700">${esc(v.nombre_cliente)}</td>
      <td class="py-4 text-sm text-gray-700">${esc(v.nombre_cajero)}</td>
      <td class="py-4 text-sm font-bold text-gray-900">${money(v.total_final)}</td>
      <td class="py-4 text-sm">${badgeEstado(v.estado_venta)}</td>
      <td class="py-4 text-sm">${botonDetalle(v.id_venta)}</td>
    </tr>`;
  }

  function render(ventas) {
    cardsEl.innerHTML = ventas.map(buildCard).join('');
    tableBody.innerHTML = ventas.map(buildRow).join('');

    const vacio = ventas.length === 0;
    mostrar(cardsEl, !vacio);
    mostrar(tableWrap, !vacio);
    mostrar(emptyEl, vacio, 'block');
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

  /* ── Detalle del ticket ──────────────────────────────────── */
  function openModal() {
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }

  async function loadDetalle(idVenta) {
    openModal();
    ticketNumero.textContent = '#' + idVenta;
    ticketLoading.textContent = 'Cargando...';
    ticketDetalle.innerHTML = '';
    ticketTotal.textContent = '$0';

    try {
      const response = await fetch(apiDetalleBase + encodeURIComponent(idVenta));
      const data = await response.json();

      if (!response.ok || !data.ok) {
        throw new Error(data.msg || 'No fue posible cargar el detalle');
      }

      ticketNumero.textContent = data.numero_venta || ('#' + idVenta);
      ticketLoading.textContent = '';

      if (!Array.isArray(data.items) || data.items.length === 0) {
        ticketDetalle.innerHTML = '<p class="text-sm text-gray-500">Esta venta no tiene productos.</p>';
        ticketTotal.textContent = money(data.total);
        return;
      }

      const rows = data.items.map(function (item) {
        return (
          '<tr class="border-b border-gray-100">' +
            '<td class="py-2 pr-2 text-sm text-gray-700">' + esc(item.producto || 'Producto') + '</td>' +
            '<td class="py-2 px-2 text-center text-sm text-gray-700">' + Number(item.cantidad || 0).toLocaleString('es-CO') + '</td>' +
            '<td class="py-2 pl-2 text-right text-sm font-medium text-gray-700">' + money(item.subtotal || 0) + '</td>' +
          '</tr>'
        );
      }).join('');

      ticketDetalle.innerHTML =
        '<table class="w-full">' +
          '<thead><tr class="border-b border-gray-200 text-xs uppercase text-gray-500"><th class="py-2 pr-2 text-left">Producto</th><th class="py-2 px-2 text-center">Cantidad</th><th class="py-2 pl-2 text-right">Subtotal</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table>';

      ticketTotal.textContent = money(data.total);
    } catch (error) {
      ticketLoading.textContent = '';
      ticketDetalle.innerHTML = '<p class="text-sm text-red-600">' + esc(error.message || 'Error inesperado') + '</p>';
    }
  }

  /* Delegacion: las filas se recrean en cada pagina */
  [cardsEl, tableBody].forEach(function (host) {
    if (!host) return;
    host.addEventListener('click', function (event) {
      const btn = event.target.closest('.btn-ver-detalle');
      if (!btn) return;
      const idVenta = btn.getAttribute('data-id');
      if (idVenta) loadDetalle(idVenta);
    });
  });

  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);

  if (modal) {
    modal.addEventListener('click', function (event) {
      if (event.target === modal) closeModal();
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
      closeModal();
    }
  });

  if (pdfBtn) {
    pdfBtn.addEventListener('click', function () {
      if (window.html2pdf) {
        const filename = 'ticket_' + (ticketNumero.textContent || 'venta').replace(/\s+/g, '_') + '.pdf';
        window.html2pdf().set({
          margin: [8, 8, 8, 8],
          filename: filename,
          image: { type: 'jpeg', quality: 0.98 },
          html2canvas: { scale: 2, useCORS: true },
          jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(ticketContent).save();
      } else {
        window.print();
      }
    });
  }

  cargar();
})();
