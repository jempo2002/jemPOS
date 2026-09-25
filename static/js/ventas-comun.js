/* ============================================================
   Ruta: static/js/ventas-comun.js
   Tarjeta, fila y ticket de una venta. Lo comparten el Historial de Ventas
   (ventas.js) y el modal de trabajador del Panel de Control (dashboard.js),
   asi los dos muestran la venta y su detalle exactamente igual.
   Markup del ticket: templates/pos/_ticket_modal.html. Estilos: ventas.css.

   API:
     JemVentas.buildCard(v) / buildRow(v)  -> HTML de una venta de /pos/api/ventas
     JemVentas.enlazar(host)               -> "Ver detalle" dentro de host abre el ticket
     JemVentas.money(n) / esc(s)
   ============================================================ */

(function (global) {
  'use strict';

  const apiDetalleBase = '/pos/api/ventas/detalle/';

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

  const ESTADOS = {
    'Pagada': 'pagada',
    'Anulada': 'anulada',
    'Fiada/Pendiente': 'fiada',
  };

  function badgeEstado(estado) {
    const clase = ESTADOS[estado] || '';
    return `<span class="vent-estado ${clase}">${esc(estado)}</span>`;
  }

  function cantidad(n) {
    return Number(n || 0).toLocaleString('es-CO', { maximumFractionDigits: 3 });
  }

  function botonDetalle(id) {
    return `<button type="button" class="btn-ver-detalle" data-id="${Number(id)}">Ver detalle</button>`;
  }

  /* Misma tarjeta que Gastos: icono, quien/como, cifra a la derecha. */
  function buildCard(v) {
    const anulada = v.estado_venta === 'Anulada' ? ' vent-anulada' : '';
    return `
    <div class="gast-card${anulada}">
      <div class="gast-card-icon vent-card-icon"><i class="fa-solid fa-receipt"></i></div>
      <div class="gast-card-info">
        <div class="vent-card-head">
          <span class="gast-card-cat">Venta #${Number(v.id_venta)}</span>
          ${badgeEstado(v.estado_venta)}
        </div>
        <div class="gast-card-desc">${esc(v.nombre_cliente)}</div>
        <div class="gast-card-meta">
          <span>${esc(v.fecha || 'Sin fecha')}</span>
          <span class="gast-origen-pill">${esc(v.metodo_pago)}</span>
        </div>
      </div>
      <div class="vent-card-side">
        <div class="gast-card-amount vent-amount">${money(v.total_final)}</div>
        ${botonDetalle(v.id_venta)}
      </div>
    </div>`;
  }

  function buildRow(v) {
    return `
    <tr class="${v.estado_venta === 'Anulada' ? 'vent-anulada' : ''}">
      <td class="gast-td-cat">#${Number(v.id_venta)}</td>
      <td class="gast-td-fecha">${esc(v.fecha || 'Sin fecha')}</td>
      <td class="gast-td-desc">${esc(v.nombre_cliente)}</td>
      <td>${esc(v.nombre_cajero)}</td>
      <td><span class="gast-origen-pill">${esc(v.metodo_pago)}</span></td>
      <td>${badgeEstado(v.estado_venta)}</td>
      <td class="gast-td-monto vent-amount">${money(v.total_final)}</td>
      <td>${botonDetalle(v.id_venta)}</td>
    </tr>`;
  }

  /* ── Detalle del ticket ──────────────────────────────────── */
  const modal = document.getElementById('modal-detalle');
  const closeModalBtn = document.getElementById('btn-cerrar-modal');
  const pdfBtn = document.getElementById('btn-pdf');
  const ticketNumero = document.getElementById('ticket-numero');
  const ticketLoading = document.getElementById('ticket-loading');
  const ticketDetalle = document.getElementById('ticket-detalle');
  const ticketTotal = document.getElementById('ticket-total');
  const ticketMetodo = document.getElementById('ticket-metodo');
  const ticketMeta = document.getElementById('ticket-meta');
  const ticketContent = document.getElementById('ticket-content');

  let focoPrevio = null;

  function openModal() {
    focoPrevio = document.activeElement;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    if (closeModalBtn) closeModalBtn.focus();
  }

  function closeModal() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
    if (focoPrevio && typeof focoPrevio.focus === 'function') focoPrevio.focus();
  }

  async function loadDetalle(idVenta) {
    openModal();
    ticketNumero.textContent = '#' + idVenta;
    ticketLoading.textContent = 'Cargando...';
    ticketDetalle.innerHTML = '';
    ticketMeta.innerHTML = '';
    ticketMetodo.textContent = '-';
    ticketTotal.textContent = '$0';

    try {
      const response = await fetch(apiDetalleBase + encodeURIComponent(idVenta));
      const data = await response.json();

      if (!response.ok || !data.ok) {
        throw new Error(data.msg || 'No fue posible cargar el detalle');
      }

      ticketNumero.textContent = data.numero_venta || ('#' + idVenta);
      ticketLoading.textContent = '';
      ticketMetodo.textContent = data.metodo_pago || '-';
      ticketTotal.textContent = money(data.total);

      /* Cabecera de la factura: quien y cuando. El metodo de pago va junto
         al total, donde se lee en un recibo. */
      const meta = [
        ['Fecha', data.fecha],
        ['Cliente', data.cliente + (data.nit ? ' · NIT ' + data.nit : '')],
        ['Atendio', data.cajero],
        ['Tipo', data.mayorista ? 'Venta mayorista' : ''],
      ].filter(function (par) { return par[1]; });
      ticketMeta.innerHTML = meta.map(function (par) {
        return '<div><dt>' + esc(par[0]) + '</dt><dd>' + esc(par[1]) + '</dd></div>';
      }).join('');

      if (!Array.isArray(data.items) || data.items.length === 0) {
        ticketDetalle.innerHTML = '<p class="ticket-msg">Esta venta no tiene productos.</p>';
        return;
      }

      /* table-layout fijo + anchos por columna: un nombre largo parte en
         lineas dentro de su celda en vez de empujar Valor y Subtotal fuera
         del ancho del ticket (y del PDF, que captura el nodo tal cual). */
      const rows = data.items.map(function (item) {
        const unidad = item.unidad && item.unidad !== 'Unidad' ? ' ' + esc(item.unidad) : '';
        return (
          '<tr>' +
            '<td>' + esc(item.producto || 'Producto') + '</td>' +
            '<td class="num">' + cantidad(item.cantidad) + unidad + '</td>' +
            '<td class="num">' + money(item.precio_unitario || 0) + '</td>' +
            '<td class="num strong">' + money(item.subtotal || 0) + '</td>' +
          '</tr>'
        );
      }).join('');

      ticketDetalle.innerHTML =
        '<table class="ticket-table">' +
          '<colgroup><col class="c-prod"><col class="c-cant"><col class="c-val"><col class="c-sub"></colgroup>' +
          '<thead><tr><th>Producto</th><th class="num">Cant.</th><th class="num">Valor</th><th class="num">Subtotal</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table>';
    } catch (error) {
      ticketLoading.textContent = '';
      ticketDetalle.innerHTML = '<p class="ticket-msg is-error">' + esc(error.message || 'Error inesperado') + '</p>';
    }
  }

  /* Delegacion: las filas se recrean en cada pagina */
  function enlazar(host) {
    if (!host) return;
    host.addEventListener('click', function (event) {
      const btn = event.target.closest('.btn-ver-detalle');
      if (!btn) return;
      const idVenta = btn.getAttribute('data-id');
      if (idVenta) loadDetalle(idVenta);
    });
  }

  if (modal) {
    if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);

    modal.addEventListener('click', function (event) {
      if (event.target === modal) closeModal();
    });

    /* Se registra al cargar el script, antes que los de la pantalla: con el
       ticket abierto encima de otro modal (Panel de Control), Escape cierra
       solo el ticket y no le llega al modal de abajo. */
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !modal.classList.contains('hidden')) {
        event.stopImmediatePropagation();
        closeModal();
      }
    });
  }

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

  global.JemVentas = { money, esc, buildCard, buildRow, enlazar };
})(window);
