// Ruta: static/js/dashboard.js
// Centro de Mando Financiero - consumo de datos reales desde /api/dashboard

(function () {
  'use strict';

  let chartInstance = null;

  function getCssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function toCOP(value) {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency',
      currency: 'COP',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(Number(value || 0));
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
  }

  function renderList(id, items) {
    const list = document.getElementById(id);
    if (!list) return;
    list.innerHTML = '';

    if (!Array.isArray(items) || !items.length) {
      const li = document.createElement('li');
      li.className = 'dash-list-item';
      li.textContent = 'Sin datos para este periodo';
      list.appendChild(li);
      return;
    }

    items.forEach(function (item) {
      const li = document.createElement('li');
      li.className = 'dash-list-item';
      li.textContent = item;
      list.appendChild(li);
    });
  }

  function renderChart(labels, ingresos, salidas) {
    const canvas = document.getElementById('graficaFinanzas');
    if (!canvas || typeof Chart === 'undefined') return;

    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }

    const colorSuccess = getCssVar('--color-success', '#10b981');
    const colorDanger = getCssVar('--color-danger', '#ef4444');
    const colorTextMuted = getCssVar('--color-text-muted', '#64748b');

    chartInstance = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels || [],
        datasets: [
          {
            label: 'Entradas',
            data: ingresos || [],
            backgroundColor: colorSuccess,
            borderRadius: 8,
            maxBarThickness: 28,
          },
          {
            label: 'Salidas',
            data: salidas || [],
            backgroundColor: colorDanger,
            borderRadius: 8,
            maxBarThickness: 28,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: {
              color: colorTextMuted,
              font: { weight: '600' },
            },
          },
        },
        scales: {
          x: {
            ticks: { color: colorTextMuted },
            grid: { display: false },
          },
          y: {
            ticks: {
              color: colorTextMuted,
              callback: function (value) {
                return '$' + (Number(value) / 1000).toFixed(0) + 'k';
              },
            },
            grid: {
              color: 'rgba(148, 163, 184, 0.15)',
            },
          },
        },
      },
    });
  }

  function normalizeFilter(value) {
    const raw = String(value || '').toLowerCase();
    if (raw === 'año' || raw === 'ano') return 'anio';
    if (raw === 'dia') return 'hoy';
    return raw || 'hoy';
  }

  function mapTopVendidos(vendidos) {
    if (!Array.isArray(vendidos)) return [];
    return vendidos.slice(0, 5).map(function (item, index) {
      const name = item && item.name ? item.name : 'Producto';
      const total = Number(item && item.total ? item.total : 0);
      return (index + 1) + '. ' + name + ' - ' + total.toFixed(0) + ' und';
    });
  }

  function mapStockAlerts(stock) {
    if (!Array.isArray(stock)) return [];
    return stock.map(function (item) {
      const name = item && item.name ? item.name : 'Producto';
      const currentStock = Number(item && item.stock ? item.stock : 0);
      const minStock = Number(item && item.min ? item.min : 0);
      return name + ' - ' + currentStock.toFixed(0) + ' (min. ' + minStock.toFixed(0) + ')';
    });
  }

  function pintarDashboard(data) {
    const ingresos = Number(data && data.ventas ? data.ventas : 0);
    const gastos = Number(data && data.gastos ? data.gastos : 0);

    setText('kpi-ingresos', toCOP(ingresos));
    setText('kpi-gastos', toCOP(gastos));
    setText('kpi-balance', toCOP(ingresos - gastos));
    setText('estado-turno', 'Abierto');

    renderList('lista-top-ventas', mapTopVendidos(data && data.vendidos));
    renderList('lista-stock-bajo', mapStockAlerts(data && data.stock_alertas));

    const chart = data && data.chart ? data.chart : {};
    renderChart(chart.labels || [], chart.ingresos || [], chart.gastos || []);
  }

  async function actualizarDashboard(rango) {
    const filtro = normalizeFilter(rango);
    try {
      const response = await fetch('/api/dashboard?filter=' + encodeURIComponent(filtro), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });

      if (!response.ok) {
        throw new Error('No se pudo cargar la informacion del dashboard.');
      }

      const payload = await response.json();
      if (!payload || !payload.ok) {
        throw new Error('Respuesta invalida del dashboard.');
      }

      pintarDashboard(payload);
    } catch (error) {
      console.error(error);
      renderList('lista-top-ventas', []);
      renderList('lista-stock-bajo', []);
      setText('kpi-ingresos', toCOP(0));
      setText('kpi-gastos', toCOP(0));
      setText('kpi-balance', toCOP(0));
      setText('estado-turno', 'Sin datos');
      renderChart([], [], []);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const filtro = document.getElementById('filtro-tiempo');
    let filtroInicial = 'hoy';

    if (filtro) {
      filtroInicial = normalizeFilter(filtro.value);
      filtro.addEventListener('change', function (event) {
        actualizarDashboard(event.target.value);
      });
    }

    actualizarDashboard(filtroInicial);
  });
})();
