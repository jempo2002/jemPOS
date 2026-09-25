// Ruta: static/js/dashboard.js
// Panel de Control: tarjetas financieras + personal en tiempo real.
// Todo sale de /api/dashboard; se refresca solo cada minuto mientras la
// pestana esta visible (el personal es "en vivo": ventas y cuadre del turno).
// Clic en un trabajador: modal con sus ventas por periodo desde
// /pos/api/ventas?id_cajero= (lista y ticket de ventas-comun.js).

(function () {
  'use strict';

  var REFRESCO_MS = 60000;
  var PERIODOS = {
    dia: 'hoy', hoy: 'hoy', ayer: 'ayer', semana: 'esta semana', mes: 'este mes',
    tres_meses: 'ultimos 3 meses', anio: 'este año', fecha: 'dia elegido',
  };

  function money(value) {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency', currency: 'COP', minimumFractionDigits: 0, maximumFractionDigits: 0,
    }).format(Number(value || 0));
  }

  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  /* ---------- Tarjetas financieras ---------- */
  function finCard(o) {
    return '<article class="fin-card" style="--fin-accent:' + o.color + '">' +
      '<h3 class="fin-label"><i class="fa-solid ' + o.icon + '" aria-hidden="true"></i>' + esc(o.label) + '</h3>' +
      (o.value != null ? '<p class="fin-value' + (o.valueClass ? ' ' + o.valueClass : '') + '">' + esc(o.value) + '</p>' : '') +
      (o.html || '') +
      (o.note ? '<p class="fin-note' + (o.noteClass ? ' ' + o.noteClass : '') + '">' + esc(o.note) + '</p>' : '') +
      '</article>';
  }

  function finList(items, vacio) {
    if (!items.length) return '<p class="fin-note">' + esc(vacio) + '</p>';
    return '<ul class="fin-list">' + items.map(function (it) {
      return '<li><span>' + esc(it[0]) + '</span><span>' + esc(it[1]) + '</span></li>';
    }).join('') + '</ul>';
  }

  function num(n) {
    return Number(n || 0).toLocaleString('es-CO', { maximumFractionDigits: 3 });
  }

  function dias(n) { return n + (n === 1 ? ' dia' : ' dias'); }

  /* Punto de equilibrio: ventas que cubren los gastos del periodo con el
     margen bruto actual (el calculo esta en core._build_dashboard_data). */
  function equilibrioCard(f) {
    var o = { label: 'Punto de equilibrio', icon: 'fa-bullseye', color: '#0D9488' };
    var pe = f.punto_equilibrio;
    if (pe == null) {
      o.value = 'Sin margen';
      o.note = 'Las ventas no dejan utilidad bruta';
      o.noteClass = 'is-down';
    } else if (pe === 0) {
      o.value = money(0);
      o.note = 'Sin gastos en el periodo';
    } else {
      var ventas = f.ventas || 0;
      var pct = Math.round(ventas / pe * 100);
      o.value = money(pe);
      o.html = '<div class="fin-bar" aria-hidden="true"><span style="width:' + Math.min(pct, 100) + '%"></span></div>';
      o.note = pct >= 100 ? 'Cubierto · ' + pct + '%' : 'Faltan ' + money(pe - ventas);
      o.noteClass = pct >= 100 ? 'is-up' : 'is-down';
    }
    return o;
  }

  function renderFinanzas(data) {
    var f = data.finanzas || {};
    var t = f.tendencia;
    var kpis = [
      { label: 'Ventas', icon: 'fa-sack-dollar', color: '#3B82F6', value: money(f.ventas),
        note: t ? t.text : (f.num_ventas || 0) + ' ventas', noteClass: t ? (t.up ? 'is-up' : 'is-down') : '' },
      { label: 'Ticket promedio', icon: 'fa-receipt', color: '#6366F1', value: money(f.ticket_promedio),
        note: (f.num_ventas || 0) + (f.num_ventas === 1 ? ' venta pagada' : ' ventas pagadas') },
      { label: 'Utilidad bruta', icon: 'fa-chart-line', color: '#10B981', value: money(f.utilidad_bruta),
        note: f.margen == null ? 'Sin ventas' : 'Margen ' + f.margen + '%' },
      { label: 'Gastos', icon: 'fa-money-bill-transfer', color: '#EF4444', value: money(f.gastos),
        note: 'Salidas del periodo' },
      { label: 'Utilidad neta', icon: 'fa-scale-balanced', color: f.utilidad_neta < 0 ? '#EF4444' : '#16A34A',
        value: money(f.utilidad_neta), valueClass: f.utilidad_neta < 0 ? 'is-neg' : 'is-pos',
        note: 'Utilidad bruta - gastos' },
      equilibrioCard(f),
      { label: 'Por cobrar', icon: 'fa-hand-holding-dollar', color: '#F59E0B', value: money(f.por_cobrar),
        note: (f.deudores || 0) + (f.deudores === 1 ? ' cliente debe' : ' clientes deben') },
      { label: 'Por pagar', icon: 'fa-file-invoice-dollar', color: '#8B5CF6', value: money(f.por_pagar),
        note: f.vencido > 0 ? 'Vencido ' + money(f.vencido) : (f.obligaciones || 0) + ' obligaciones al dia',
        noteClass: f.vencido > 0 ? 'is-down' : '' },
    ];
    var listas = [
      { label: 'Deudas más antiguas', icon: 'fa-hourglass-half', color: '#DC2626',
        html: finList((data.deudas_antiguas || []).map(function (d) {
          return [d.nombre, dias(d.dias)];
        }), 'Nadie debe') },
      { label: 'Deudas de mayor monto', icon: 'fa-sack-xmark', color: '#D97706',
        html: finList((data.deudas_mayores || []).map(function (d) {
          return [d.nombre, money(d.saldo)];
        }), 'Nadie debe') },
      { label: 'Stock bajo', icon: 'fa-triangle-exclamation', color: '#F97316',
        html: finList((data.stock_alertas || []).map(function (s) {
          return [s.name, num(s.stock) + ' / min ' + num(s.min)];
        }), 'Sin alertas de stock') },
      { label: 'Mas vendidos', icon: 'fa-fire', color: '#0EA5E9',
        html: finList((data.top_vendidos || []).map(function (p) {
          return [p.name, num(p.total) + ' und'];
        }), 'Sin ventas en el periodo') },
    ];
    document.getElementById('dash-finanzas').innerHTML =
      '<div class="fin-grid">' + kpis.map(finCard).join('') + '</div>' +
      '<div class="fin-lists">' + listas.map(finCard).join('') + '</div>';
    document.getElementById('dash-periodo').textContent = PERIODOS[data.filtro] || '';
  }

  /* ---------- Personal ---------- */
  function kv(label, value) {
    return '<div class="staff-kv"><dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd></div>';
  }

  function turnoHTML(t) {
    if (!t) return '<p class="staff-sin-turno">No ha abierto turno hoy.</p>';
    var pill;
    if (t.estado === 'En curso') pill = '<span class="pill live">En curso</span>';
    else if (t.estado === 'Cuadrada') pill = '<span class="pill ok">Cuadrada</span>';
    else pill = '<span class="pill bad">Descuadrada ' + (t.diferencia > 0 ? '+' : '-') + money(Math.abs(t.diferencia)) + '</span>';

    var formula = 'Base ' + money(t.base) + ' + efectivo ' + money(t.ventas_efectivo) +
      ' + abonos ' + money(t.abonos_efectivo) + ' - gastos de caja ' + money(t.gastos_de_caja) +
      (t.gastos_de_base > 0 ? ' (' + money(t.gastos_de_base) + ' de la base)' : '');

    return '<dl class="staff-turno">' +
      kv('Inicio turno', t.apertura || '-') +
      kv('Base', money(t.base)) +
      kv(t.abierto ? 'Debe haber en caja' : 'Esperado', money(t.esperado)) +
      kv(t.abierto ? 'Cierre' : 'Contado', t.abierto ? 'Pendiente' : money(t.contado)) +
      '<div class="staff-cuadre"><span>' + (t.abierto ? 'Cuadre al cerrar' : 'Cerro ' + esc(t.cierre || '')) + '</span>' + pill + '</div>' +
      '<div class="staff-formula">' + esc(formula) + '</div>' +
      '</dl>';
  }

  /* Una sola capsula de estado en la tarjeta compacta; el desglose del
     turno vive en el modal. */
  function estadoPill(p) {
    var t = p.turno;
    if (!t) return '<span class="pill">Sin turno hoy</span>';
    if (t.estado === 'En curso') return '<span class="pill on">En turno</span>';
    if (t.estado === 'Cuadrada') return '<span class="pill ok">Cuadrada</span>';
    return '<span class="pill bad">Descuadre ' + (t.diferencia > 0 ? '+' : '-') + money(Math.abs(t.diferencia)) + '</span>';
  }

  /* <button> nativo: rol de boton, foco y Enter/Espacio sin JS extra. */
  function staffCard(p) {
    var v = p.ventas || {};
    var sub = p.rol + (p.ultima_venta ? ' · ultima ' + p.ultima_venta : '');
    return '<button type="button" class="staff-card' + (p.en_turno ? ' is-on' : '') + '" data-id="' + Number(p.id) + '" title="Ver historial de ventas">' +
      '<span class="dash-avatar" aria-hidden="true">' + esc(initials(p.nombre)) + '</span>' +
      '<span class="staff-id">' +
        '<span class="staff-name">' + esc(p.nombre) + '</span>' +
        '<span class="staff-sub">' + esc(sub) + '</span>' +
        estadoPill(p) +
      '</span>' +
      '<span class="staff-total"><b>' + money(v.total) + '</b><span>' +
        (v.cantidad || 0) + (v.cantidad === 1 ? ' venta hoy' : ' ventas hoy') + '</span></span>' +
    '</button>';
  }

  var personalPorId = {};
  var modalPersonal = null;

  function renderPersonal(personal) {
    var cont = document.getElementById('dash-personal');
    var enTurno = personal.filter(function (p) { return p.en_turno; }).length;
    personalPorId = {};
    personal.forEach(function (p) { personalPorId[p.id] = p; });
    document.getElementById('dash-en-turno').textContent =
      personal.length ? enTurno + ' en turno · ' + personal.length + ' activos' : '';
    cont.innerHTML = personal.length
      ? personal.map(staffCard).join('')
      : '<p class="dash-empty">No hay personal activo. Crea un cajero para empezar.</p>';
    if (modalPersonal) modalPersonal.refrescarTurno();
  }

  /* ---------- Modal de trabajador ---------- */
  function initPersonalModal() {
    var modal = document.getElementById('modal-personal');
    if (!modal || !window.JemFiltros || !window.JemVentas) return null;
    var V = window.JemVentas;
    var body = document.getElementById('mp-body');
    var statsEl = document.getElementById('mp-stats');
    var turnoEl = document.getElementById('mp-turno');
    var cardsEl = document.getElementById('mp-cards');
    var tableBody = document.getElementById('mp-table-body');
    var tableWrap = document.getElementById('mp-table-wrap');
    var emptyEl = document.getElementById('mp-empty');
    var pillHoy = modal.querySelector('.jem-pill[data-periodo="hoy"]');
    var closeBtn = modal.querySelector('.dash-modal-close');
    var actual = null;
    var peticion = 0;

    var filtros = window.JemFiltros.init({ id: 'personal', filtro: 'hoy', limit: 20, onChange: cargarVentas });
    V.enlazar(cardsEl);
    V.enlazar(tableBody);

    function stat(valor, etiqueta, clase) {
      return '<div class="staff-stat' + (clase ? ' ' + clase : '') + '"><b>' + esc(valor) + '</b><span>' + esc(etiqueta) + '</span></div>';
    }

    function renderStats(r) {
      r = r || {};
      statsEl.innerHTML =
        stat(V.money(r.total), 'Total vendido', 'mp-stat-main') +
        stat(String(r.cantidad || 0), r.cantidad === 1 ? 'Venta' : 'Ventas') +
        stat(V.money(r.ticket_promedio), 'Ticket promedio') +
        stat(V.money(r.efectivo), 'Efectivo') +
        stat(V.money(r.otros), 'Otros medios') +
        stat(V.money(r.fiado), 'Fiado') +
        stat(String(r.anuladas || 0), 'Anuladas');
    }

    function renderLista(ventas) {
      cardsEl.innerHTML = ventas.map(V.buildCard).join('');
      tableBody.innerHTML = ventas.map(V.buildRow).join('');
      var vacio = ventas.length === 0;
      cardsEl.classList.toggle('hidden', vacio);
      tableWrap.classList.toggle('hidden', vacio);
      emptyEl.classList.toggle('hidden', !vacio);
    }

    /* Cada capsula, fecha o pagina pide por fetch solo las ventas: el modal
       sigue abierto. Las respuestas viejas se descartan por numero. */
    async function cargarVentas() {
      if (!actual) return;
      var mia = ++peticion;
      body.setAttribute('aria-busy', 'true');
      try {
        var res = await fetch('/pos/api/ventas?' + filtros.query() + '&id_cajero=' + encodeURIComponent(actual.id), {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (res.status === 401) { window.location.href = '/login'; return; }
        var data = await res.json().catch(function () { return {}; });
        if (mia !== peticion) return;
        if (!res.ok || !data.ok) throw new Error(data.msg || 'No fue posible cargar las ventas.');
        renderStats(data.resumen);
        renderLista(data.ventas || []);
        filtros.setMeta(data.meta);
        body.scrollTop = 0;
      } catch (err) {
        if (mia !== peticion) return;
        statsEl.innerHTML = '<p class="staff-sin-turno mp-error" role="alert">' +
          esc(err instanceof TypeError ? 'Sin conexion con el servidor.' : err.message) + '</p>';
        renderLista([]);
        filtros.setMeta({ page: 1, pages: 1, total: 0 });
      } finally {
        if (mia === peticion) body.setAttribute('aria-busy', 'false');
      }
    }

    function pintarTurno() {
      turnoEl.innerHTML = '<h3 class="staff-ventas-title">Turno de hoy</h3>' + turnoHTML(actual.turno);
    }

    function abrir(id) {
      var p = personalPorId[id];
      if (!p) return;
      actual = p;
      document.getElementById('mp-avatar').textContent = initials(p.nombre);
      document.getElementById('mp-nombre').textContent = p.nombre;
      document.getElementById('mp-sub').textContent = p.rol + (p.en_turno ? ' · en turno' : '');
      pintarTurno();
      statsEl.innerHTML = '';
      renderLista([]);
      modal.hidden = false;
      modal.setAttribute('aria-hidden', 'false');
      closeBtn.focus();
      pillHoy.click(); /* vuelve a Hoy, pagina 1, sin fecha, y carga */
    }

    function cerrar() {
      if (modal.hidden) return;
      var id = actual && actual.id;
      actual = null;
      peticion++; /* descarta lo que siga en vuelo */
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
      var card = document.querySelector('.staff-card[data-id="' + Number(id) + '"]');
      if (card) card.focus();
    }

    document.getElementById('dash-personal').addEventListener('click', function (e) {
      var card = e.target.closest('.staff-card');
      if (card) abrir(Number(card.getAttribute('data-id')));
    });
    modal.querySelectorAll('[data-close-personal]').forEach(function (el) {
      el.addEventListener('click', cerrar);
    });
    /* Con el ticket abierto encima, ventas-comun.js corta este Escape. */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') cerrar();
    });

    return {
      /* El refresco de cada minuto trae el cuadre nuevo del turno. */
      refrescarTurno: function () {
        if (actual && personalPorId[actual.id]) {
          actual = personalPorId[actual.id];
          pintarTurno();
        }
      },
    };
  }

  /* ---------- Carga ---------- */
  var estado = { period: 'hoy', fecha: null };
  var peticion = 0;
  var btnRefrescar = null;

  async function cargar() {
    var mia = ++peticion;
    var params = new URLSearchParams();
    if (estado.fecha) params.set('fecha', estado.fecha);
    else params.set('filter', estado.period);
    if (btnRefrescar) btnRefrescar.classList.add('is-loading');
    try {
      var res = await fetch('/api/dashboard?' + params.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var data = await res.json();
      if (mia !== peticion) return;
      if (!res.ok || !data.ok) throw new Error(data.msg || 'Respuesta invalida');
      renderFinanzas(data);
      renderPersonal(data.personal || []);
      document.getElementById('dash-actualizado').textContent = data.actualizado || '';
    } catch (err) {
      console.error(err);
      if (mia === peticion) document.getElementById('dash-actualizado').textContent = 'sin conexion, reintentando';
    } finally {
      if (mia === peticion && btnRefrescar) btnRefrescar.classList.remove('is-loading');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var pills = document.getElementById('dash-pills');
    var dateInput = document.getElementById('filtro-fecha');
    btnRefrescar = document.getElementById('btn-refrescar');

    pills.addEventListener('click', function (e) {
      var btn = e.target.closest('.dash-pill');
      if (!btn) return;
      pills.querySelectorAll('.dash-pill').forEach(function (p) { p.classList.toggle('is-active', p === btn); });
      dateInput.value = '';
      estado = { period: btn.getAttribute('data-period'), fecha: null };
      cargar();
    });

    dateInput.addEventListener('change', function () {
      if (!dateInput.value) return;
      pills.querySelectorAll('.dash-pill').forEach(function (p) { p.classList.remove('is-active'); });
      estado = { period: null, fecha: dateInput.value };
      cargar();
    });

    btnRefrescar.addEventListener('click', cargar);

    // Tiempo real: refresco periodico solo con la pestana visible, y uno al volver.
    setInterval(function () { if (!document.hidden) cargar(); }, REFRESCO_MS);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) cargar(); });

    modalPersonal = initPersonalModal();
    initCajeroModal(cargar);
    cargar();
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
