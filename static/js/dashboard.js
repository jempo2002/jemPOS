/* ============================================================
   Ruta: static/js/dashboard.js
   Pantalla: Dashboard — Resumen del Negocio
   jemPOS — Confianza Financiera
   ============================================================ */

'use strict';

const pills = document.querySelectorAll('.pill');
const dashDate = document.getElementById('dash-date');
const chartCanvas = document.getElementById('ventas-chart');
const chartDataEl = document.getElementById('dash-chart-data');

/* ── Fecha ───────────────────────────────────────────────── */
function renderFecha() {
  const now = new Date();
  const opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
  dashDate.textContent = now.toLocaleDateString('es-CO', opts);
}

function renderVentasChart() {
  if (!chartCanvas || !window.Chart) return;

  let chartData = { labels: [], ingresos: [], gastos: [] };
  if (chartDataEl && chartDataEl.textContent) {
    try {
      chartData = JSON.parse(chartDataEl.textContent);
    } catch (_) {
      chartData = { labels: [], ingresos: [], gastos: [] };
    }
  }
  const labels = Array.isArray(chartData.labels) ? chartData.labels : [];
  const ingresos = Array.isArray(chartData.ingresos) ? chartData.ingresos : [];
  const gastos = Array.isArray(chartData.gastos) ? chartData.gastos : [];

  if (!labels.length) {
    const ctx = chartCanvas.getContext('2d');
    ctx.clearRect(0, 0, chartCanvas.width, chartCanvas.height);
    ctx.font = '500 13px Inter, sans-serif';
    ctx.fillStyle = '#94A3B8';
    ctx.textAlign = 'center';
    ctx.fillText('Sin movimientos para el filtro seleccionado', chartCanvas.width / 2, chartCanvas.height / 2);
    return;
  }

  new Chart(chartCanvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Ingresos',
          data: ingresos,
          backgroundColor: '#3B82F6',
          borderRadius: 8,
          maxBarThickness: 28,
        },
        {
          label: 'Gastos',
          data: gastos,
          backgroundColor: '#EF4444',
          borderRadius: 8,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'bottom' },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#64748B' },
        },
        y: {
          beginAtZero: true,
          ticks: {
            color: '#64748B',
            callback: (value) => window.COP ? `$${window.COP.format(value)}` : `$${Number(value).toLocaleString('es-CO')}`,
          },
          grid: { color: 'rgba(148,163,184,0.2)' },
        },
      },
    },
  });
}

function initWhatsAppInsumos() {
  const btn = document.getElementById('btn-whatsapp-insumos');
  if (!btn) return;

  btn.addEventListener('click', () => {
    const rows = Array.from(document.querySelectorAll('[data-insumo-critico="1"]'));
    if (!rows.length) return;

    const lineas = rows.map((row) => {
      const nombre = row.dataset.nombre || 'Insumo';
      const stock = Number(row.dataset.stock || 0);
      const min = Number(row.dataset.min || 0);
      const unidad = row.dataset.unidad || 'Un';
      return `- ${nombre} (Quedan ${stock.toFixed(3)} ${unidad} | Min: ${min.toFixed(3)} ${unidad})`;
    });

    const mensaje = [
      'Hola, reporte de jemPOS:',
      'Faltan estos insumos urgentes:',
      ...lineas,
    ].join('\n');

    const url = `https://wa.me/?text=${encodeURIComponent(mensaje)}`;
    window.open(url, '_blank', 'noopener');
  });
}

/* ── Pills ───────────────────────────────────────────────── */
pills.forEach(pill => {
  pill.addEventListener('click', () => {
    const filtro = pill.dataset.filter;
    if (!filtro) return;
    window.location.href = `/dashboard?filtro=${encodeURIComponent(filtro)}`;
  });
});

/* ── Init ────────────────────────────────────────────────── */
renderFecha();
renderVentasChart();
initWhatsAppInsumos();
