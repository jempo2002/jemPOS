/* ============================================================
   Ruta: static/js/ventas.js
   Pantalla: Historial de Ventas
   ============================================================ */

(function () {
  const modal = document.getElementById('modal-detalle');
  const closeModalBtn = document.getElementById('btn-cerrar-modal');
  const pdfBtn = document.getElementById('btn-pdf');
  const ticketNumero = document.getElementById('ticket-numero');
  const ticketLoading = document.getElementById('ticket-loading');
  const ticketDetalle = document.getElementById('ticket-detalle');
  const ticketTotal = document.getElementById('ticket-total');
  const ticketContent = document.getElementById('ticket-content');
  const apiDetalleBase = '/pos/api/ventas/detalle/';

  function money(value) {
    return '$' + Number(value || 0).toLocaleString('es-CO', { maximumFractionDigits: 0 });
  }

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
            '<td class="py-2 pr-2 text-sm text-gray-700">' + (item.producto || 'Producto') + '</td>' +
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
      ticketDetalle.innerHTML = '<p class="text-sm text-red-600">' + (error.message || 'Error inesperado') + '</p>';
    }
  }

  document.querySelectorAll('.btn-ver-detalle').forEach(function (button) {
    button.addEventListener('click', function () {
      const idVenta = this.getAttribute('data-id');
      if (!idVenta) return;
      loadDetalle(idVenta);
    });
  });

  if (closeModalBtn) {
    closeModalBtn.addEventListener('click', closeModal);
  }

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
})();
