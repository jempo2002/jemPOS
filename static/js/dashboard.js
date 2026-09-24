// Ruta: static/js/dashboard.js
// Centro de Mando Financiero - consumo de datos reales desde /api/dashboard

(function () {
  'use strict';

  var CHART_PAGE_SIZE = 15;   // maximo de registros por pagina de la grafica
  var PRODUCTS_PER_PAGE = 5;  // maximo de registros por pagina de cada tarjeta de producto

  var chartInstance = null;
  var chartData = { labels: [], ingresos: [], gastos: [], page: 0 };

  function getCssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  // Punto de equilibrio (ingresos necesarios para cubrir gastos):
  // ganancia_bruta = ganancia_neta + gastos ; margen = ganancia_bruta / ventas ; equilibrio = gastos / margen
  function puntoEquilibrio(ventas, gastos, ganancia) {
    var brutaMargen = Number(ganancia) + Number(gastos);
    if (ventas <= 0 || brutaMargen <= 0) return null;
    var margen = brutaMargen / ventas;
    if (margen <= 0) return null;
    return gastos / margen;
  }

  /* ---------- Listas simples ---------- */
  function emptyLi(text) {
    var li = document.createElement('li');
    li.className = 'dash-list-empty';
    li.textContent = text || 'Sin datos para este periodo';
    return li;
  }

  function itemLi(name, value) {
    var li = document.createElement('li');
    li.className = 'dash-list-item';
    var n = document.createElement('span');
    n.className = 'dash-item-name';
    n.textContent = name;
    li.appendChild(n);
    if (value != null && value !== '') {
      var v = document.createElement('span');
      v.className = 'dash-item-value';
      v.textContent = value;
      li.appendChild(v);
    }
    return li;
  }

  function renderStockAlerts(items) {
    var list = document.getElementById('lista-stock-bajo');
    if (!list) return;
    list.innerHTML = '';
    if (!Array.isArray(items) || !items.length) {
      list.appendChild(emptyLi('Sin alertas de stock'));
      return;
    }
    items.forEach(function (item) {
      var name = item && item.name ? item.name : 'Producto';
      var stock = Number(item && item.stock != null ? item.stock : 0);
      var min = Number(item && item.min != null ? item.min : 0);
      list.appendChild(itemLi(name, stock.toFixed(0) + ' / min ' + min.toFixed(0)));
    });
  }

  /* ---------- Tarjetas de productos con paginacion ---------- */
  function setupProductCard(card) {
    return {
      card: card,
      list: card.querySelector('[data-list]'),
      pager: card.querySelector('[data-pager]'),
      info: card.querySelector('[data-info]'),
      prev: card.querySelector('[data-prev]'),
      next: card.querySelector('[data-next]'),
      records: [],
      page: 0,
    };
  }

  function renderProductPage(pc) {
    var records = pc.records;
    var pages = Math.max(1, Math.ceil(records.length / PRODUCTS_PER_PAGE));
    if (pc.page >= pages) pc.page = pages - 1;

    pc.list.innerHTML = '';
    if (!records.length) {
      pc.list.appendChild(emptyLi());
    } else {
      var start = pc.page * PRODUCTS_PER_PAGE;
      records.slice(start, start + PRODUCTS_PER_PAGE).forEach(function (item) {
        pc.list.appendChild(itemLi(item.name || 'Producto', item.value || ''));
      });
    }

    // microinteraccion: fade sutil al repintar
    pc.list.classList.remove('dash-fade-swap');
    void pc.list.offsetWidth;
    pc.list.classList.add('dash-fade-swap');

    if (pc.pager) {
      pc.pager.hidden = pages <= 1;
      if (pc.info) pc.info.textContent = (pc.page + 1) + ' / ' + pages;
      if (pc.prev) pc.prev.disabled = pc.page === 0;
      if (pc.next) pc.next.disabled = pc.page >= pages - 1;
    }
  }

  function fillProductCard(pc, records) {
    // maximo 2 paginas -> 10 registros en memoria
    pc.records = (Array.isArray(records) ? records : []).slice(0, PRODUCTS_PER_PAGE * 2);
    pc.page = 0;
    renderProductPage(pc);
  }

  /* ---------- Rendimiento del personal ---------- */
  function renderStaff(cajeros) {
    var container = document.getElementById('lista-staff');
    if (!container) return;
    container.innerHTML = '';

    if (!Array.isArray(cajeros) || !cajeros.length) {
      var empty = document.createElement('p');
      empty.className = 'dash-list-empty';
      empty.textContent = 'No hay personal registrado';
      container.appendChild(empty);
      return;
    }

    cajeros.forEach(function (c) {
      var balance = Number(c && c.balance != null ? c.balance : 0);
      var count = Number(c && c.ventas_count != null ? c.ventas_count : 0);
      var onShift = !c || c.status !== 'Fuera de turno';

      var row = document.createElement('div');
      row.className = 'dash-staff-row';

      var avatar = document.createElement('div');
      avatar.className = 'dash-avatar';
      avatar.textContent = initials(c && c.name);

      var info = document.createElement('div');
      info.className = 'dash-staff-info';
      var name = document.createElement('p');
      name.className = 'dash-staff-name';
      name.textContent = (c && c.name) || 'Cajero';
      var status = document.createElement('p');
      status.className = 'dash-staff-status ' + (onShift ? 'is-on' : 'is-off');
      status.textContent = onShift ? 'En turno' : 'Fuera de turno';
      info.appendChild(name);
      info.appendChild(status);

      var bal = document.createElement('div');
      bal.className = 'dash-staff-balance';
      var amount = document.createElement('p');
      amount.className = 'dash-staff-amount ' + (balance >= 0 ? 'is-pos' : 'is-neg');
      amount.textContent = (c && c.value) || toCOP(balance);
      var cnt = document.createElement('p');
      cnt.className = 'dash-staff-count';
      cnt.textContent = count + (count === 1 ? ' venta hoy' : ' ventas hoy');
      bal.appendChild(amount);
      bal.appendChild(cnt);

      row.appendChild(avatar);
      row.appendChild(info);
      row.appendChild(bal);
      container.appendChild(row);
    });
  }

  /* ---------- Grafica con paginacion ---------- */
  function chartPages() {
    return Math.max(1, Math.ceil(chartData.labels.length / CHART_PAGE_SIZE));
  }

  function renderChartPage() {
    var canvas = document.getElementById('graficaFinanzas');
    if (!canvas || typeof Chart === 'undefined') return;

    var pages = chartPages();
    if (chartData.page >= pages) chartData.page = pages - 1;
    if (chartData.page < 0) chartData.page = 0;

    var start = chartData.page * CHART_PAGE_SIZE;
    var end = start + CHART_PAGE_SIZE;
    var labels = chartData.labels.slice(start, end);
    var ingresos = chartData.ingresos.slice(start, end);
    var gastos = chartData.gastos.slice(start, end);

    var colorSuccess = getCssVar('--color-success', '#10b981');
    var colorDanger = getCssVar('--color-danger', '#ef4444');
    var colorTextMuted = getCssVar('--color-text-muted', '#64748b');

    if (chartInstance) {
      chartInstance.data.labels = labels;
      chartInstance.data.datasets[0].data = ingresos;
      chartInstance.data.datasets[1].data = gastos;
      chartInstance.update();
    } else {
      chartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: 'Entradas', data: ingresos, backgroundColor: colorSuccess, borderRadius: 8, maxBarThickness: 28 },
            { label: 'Salidas', data: gastos, backgroundColor: colorDanger, borderRadius: 8, maxBarThickness: 28 },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: colorTextMuted, font: { weight: '600' } } },
          },
          scales: {
            x: { ticks: { color: colorTextMuted }, grid: { display: false } },
            y: {
              ticks: {
                color: colorTextMuted,
                callback: function (value) { return '$' + (Number(value) / 1000).toFixed(0) + 'k'; },
              },
              grid: { color: 'rgba(148, 163, 184, 0.15)' },
            },
          },
        },
      });
    }

    var pager = document.getElementById('chart-pager');
    if (pager) {
      pager.hidden = pages <= 1;
      setText('chart-pageinfo', (chartData.page + 1) + ' / ' + pages);
      var prev = document.getElementById('chart-prev');
      var next = document.getElementById('chart-next');
      if (prev) prev.disabled = chartData.page === 0;
      if (next) next.disabled = chartData.page >= pages - 1;
    }
  }

  function loadChart(chart) {
    chartData.labels = (chart && chart.labels) || [];
    chartData.ingresos = (chart && chart.ingresos) || [];
    chartData.gastos = (chart && chart.gastos) || [];
    chartData.page = chartPages() - 1; // mostrar el periodo mas reciente
    renderChartPage();
  }

  /* ---------- Pintado general ---------- */
  var productCards = [];

  function pintarDashboard(data) {
    var ingresos = Number(data && data.ventas ? data.ventas : 0);
    var gastos = Number(data && data.gastos ? data.gastos : 0);
    var ganancia = Number(data && data.ganancia ? data.ganancia : (ingresos - gastos));

    setText('kpi-ingresos', toCOP(ingresos));
    setText('kpi-gastos', toCOP(gastos));
    setText('kpi-balance', toCOP(ingresos - gastos));

    var eq = puntoEquilibrio(ingresos, gastos, ganancia);
    setText('kpi-equilibrio', eq == null ? 'N/D' : toCOP(eq));

    var byTop = { vendidos: data && data.vendidos, menos: data && data.menosVendidos, rentables: data && data.rentables };
    productCards.forEach(function (pc) {
      fillProductCard(pc, byTop[pc.card.getAttribute('data-top')]);
    });

    renderStockAlerts(data && data.stock_alertas);
    renderStaff(data && data.cajeros);
    loadChart(data && data.chart ? data.chart : {});
  }

  function pintarVacio() {
    setText('kpi-ingresos', toCOP(0));
    setText('kpi-gastos', toCOP(0));
    setText('kpi-balance', toCOP(0));
    setText('kpi-equilibrio', 'N/D');
    productCards.forEach(function (pc) { fillProductCard(pc, []); });
    renderStockAlerts([]);
    renderStaff([]);
    loadChart({});
  }

  async function actualizarDashboard(period, fecha) {
    var params = new URLSearchParams();
    if (fecha) {
      params.set('fecha', fecha);
    } else {
      params.set('filter', period || 'hoy');
    }
    try {
      var response = await fetch('/api/dashboard?' + params.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error('No se pudo cargar el dashboard.');
      var payload = await response.json();
      if (!payload || !payload.ok) throw new Error('Respuesta invalida.');
      pintarDashboard(payload);
    } catch (error) {
      console.error(error);
      pintarVacio();
    }
  }

  /* ---------- Init ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.dash-product-card').forEach(function (card) {
      var pc = setupProductCard(card);
      if (pc.prev) pc.prev.addEventListener('click', function () { pc.page--; renderProductPage(pc); });
      if (pc.next) pc.next.addEventListener('click', function () { pc.page++; renderProductPage(pc); });
      productCards.push(pc);
    });

    var pills = document.getElementById('dash-pills');
    var dateInput = document.getElementById('filtro-fecha');
    var current = 'hoy';

    if (pills) {
      pills.addEventListener('click', function (e) {
        var btn = e.target.closest('.dash-pill');
        if (!btn) return;
        pills.querySelectorAll('.dash-pill').forEach(function (p) { p.classList.remove('is-active'); });
        btn.classList.add('is-active');
        if (dateInput) dateInput.value = '';
        current = btn.getAttribute('data-period');
        actualizarDashboard(current, null);
      });
    }

    if (dateInput) {
      dateInput.addEventListener('change', function () {
        if (!dateInput.value) return;
        if (pills) pills.querySelectorAll('.dash-pill').forEach(function (p) { p.classList.remove('is-active'); });
        actualizarDashboard(null, dateInput.value);
      });
    }

    var chartPrev = document.getElementById('chart-prev');
    var chartNext = document.getElementById('chart-next');
    if (chartPrev) chartPrev.addEventListener('click', function () { chartData.page--; renderChartPage(); });
    if (chartNext) chartNext.addEventListener('click', function () { chartData.page++; renderChartPage(); });

    initCajeroModal(function () { actualizarDashboard(current, dateInput && dateInput.value ? dateInput.value : null); });

    actualizarDashboard(current, null);
  });

  /* ---------- Modal Crear Cajero (Admin) ---------- */
  function initCajeroModal(onCreated) {
    var modal = document.getElementById('modal-crear-cajero');
    var openBtn = document.getElementById('btn-crear-cajero');
    var form = document.getElementById('form-crear-cajero');
    if (!modal || !openBtn || !form) return;

    var errBox = document.getElementById('cc-error');
    var csrf = document.querySelector('meta[name="csrf-token"]');
    csrf = csrf ? csrf.getAttribute('content') : '';

    function open() {
      modal.hidden = false;
      modal.setAttribute('aria-hidden', 'false');
      var f = document.getElementById('cc-nombre');
      if (f) f.focus();
    }
    function close() {
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
      form.reset();
      if (errBox) errBox.hidden = true;
    }

    openBtn.addEventListener('click', open);
    modal.querySelectorAll('[data-close-cajero]').forEach(function (el) {
      el.addEventListener('click', close);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (errBox) errBox.hidden = true;

      var nombre = document.getElementById('cc-nombre').value.trim();
      var cc = document.getElementById('cc-cedula').value.trim();
      var correo = document.getElementById('cc-correo').value.trim();
      var password = document.getElementById('cc-password').value;
      var confirm = document.getElementById('cc-confirm').value;

      if (!nombre || !cc || !correo || !password) {
        showErr('Completa los campos requeridos.');
        return;
      }
      if (password !== confirm) {
        showErr('Las contrasenas no coinciden.');
        return;
      }

      try {
        var res = await fetch('/api/crear_usuario', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ nombre: nombre, cc: cc, correo: correo, password: password, confirm_password: confirm }),
        });
        var data = await res.json().catch(function () { return null; });
        if (!data || !data.ok) {
          showErr((data && data.msg) || 'No se pudo crear el cajero.');
          return;
        }
        close();
        if (typeof onCreated === 'function') onCreated();
      } catch (err) {
        showErr('Error de conexion.');
      }
    });

    function showErr(msg) {
      if (!errBox) return;
      errBox.textContent = msg;
      errBox.hidden = false;
    }
  }
})();
