/* ============================================================
   Ruta: static/js/fiados.js
   Pantalla: Cartera — Cuentas por Cobrar + Cuentas por Pagar
   Depende de: cop-format.js y toast.js (cargados antes en el HTML)

   La pestana "Cuentas por Pagar" solo existe en el DOM para perfiles
   administrativos; el backend valida el rol de nuevo en cada ruta.
   ============================================================ */

function formatoMoneda(numero) {
  const valor = Number(numero || 0);
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    minimumFractionDigits: 0,
  }).format(valor);
}

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };

  /* ── Estado ──────────────────────────────────────────────── */
  let clients     = [];
  let cuentas     = [];
  let resumen     = {};
  let searchQuery = '';
  let activeId    = null;   /* cliente activo en modales de cobrar */
  let activeCxp   = null;   /* obligacion activa en modales de pagar */
  let sortCol     = null;
  let sortDir     = 'asc';
  let activeTab   = 'cobrar';
  let pendingConfirm = null;

  /* ── Referencias DOM — comunes ───────────────────────────── */
  const searchInput = document.getElementById('fiad-search');
  const statTotal   = document.getElementById('stat-total');
  const statCount   = document.getElementById('stat-count');
  const statTotalLabel = document.getElementById('stat-total-label');
  const statCountLabel = document.getElementById('stat-count-label');
  const tabButtons  = Array.from(document.querySelectorAll('.fiad-tab'));
  const panelCobrar = document.getElementById('panel-cobrar');
  const panelPagar  = document.getElementById('panel-pagar');
  const btnNewClient = document.getElementById('btn-new-client');

  /* Pestana por pagar: presente solo para Admin/Master */
  const esAdmin = !!panelPagar;

  /* ── Cobrar ──────────────────────────────────────────────── */
  const cardsEl   = document.getElementById('fiad-cards');
  const tableBody = document.getElementById('fiad-table-body');
  const emptyEl   = document.getElementById('fiad-empty');

  const modalAdd   = document.getElementById('modal-add');
  const modalAbono = document.getElementById('modal-abono');
  const modalSumar = document.getElementById('modal-sumar');

  const addName = document.getElementById('add-name');
  const addPhone = document.getElementById('add-phone');
  const addInitialDebt = document.getElementById('add-initial-debt');

  const abonoClientName  = document.getElementById('abono-client-name');
  const abonoCurrentDebt = document.getElementById('abono-current-debt');
  const abonoAmount      = document.getElementById('abono-amount');
  const abonoPreview     = document.getElementById('abono-preview');
  const modalErrorBox    = document.getElementById('alerta-error-modal');
  const modalErrorText   = document.getElementById('texto-alerta-modal');
  const alertaExcesoDeuda = document.getElementById('alerta-exceso-deuda');

  const sumarClientName  = document.getElementById('sumar-client-name');
  const sumarCurrentDebt = document.getElementById('sumar-current-debt');
  const sumarAmount      = document.getElementById('sumar-amount');
  const sumarDetail      = document.getElementById('sumar-detail');
  const sumarPreview     = document.getElementById('sumar-preview');

  const btnAddConfirm   = document.getElementById('btn-add-confirm');
  const btnAbonoConfirm = document.getElementById('btn-abono-confirm');
  const btnSumarConfirm = document.getElementById('btn-sumar-confirm');

  /* ── Pagar (solo admin) ──────────────────────────────────── */
  const cxpCards     = document.getElementById('cxp-cards');
  const cxpTableBody = document.getElementById('cxp-table-body');
  const cxpEmpty     = document.getElementById('cxp-empty');
  const btnNewCxp    = document.getElementById('btn-new-cxp');

  const modalCxp    = document.getElementById('modal-cxp');
  const modalCxpPay = document.getElementById('modal-cxp-pay');
  const modalConfirm = document.getElementById('modal-confirm');

  const cxpCategoria = document.getElementById('cxp-categoria');
  const cxpProveedorField = document.getElementById('cxp-proveedor-field');
  const cxpProveedor = document.getElementById('cxp-proveedor');
  const cxpConcepto  = document.getElementById('cxp-concepto');
  const cxpMonto     = document.getElementById('cxp-monto');
  const cxpVence     = document.getElementById('cxp-vence');
  const cxpDesc      = document.getElementById('cxp-desc');
  const cxpError     = document.getElementById('cxp-error');
  const cxpErrorText = document.getElementById('cxp-error-text');
  const btnCxpConfirm = document.getElementById('btn-cxp-confirm');

  const cxpPayConcepto = document.getElementById('cxp-pay-concepto');
  const cxpPaySaldo    = document.getElementById('cxp-pay-saldo');
  const cxpPayMonto    = document.getElementById('cxp-pay-monto');
  const cxpPayExceso   = document.getElementById('cxp-pay-exceso');
  const cxpPayPreview  = document.getElementById('cxp-pay-preview');
  const cxpPayOrigen   = document.getElementById('cxp-pay-origen');
  const cxpPayOrigenErr = document.getElementById('cxp-pay-origen-error');
  const cxpPayError    = document.getElementById('cxp-pay-error');
  const cxpPayErrorText = document.getElementById('cxp-pay-error-text');
  const btnCxpPayConfirm = document.getElementById('btn-cxp-pay-confirm');

  const confirmTarget = document.getElementById('confirm-target');
  const confirmText   = document.getElementById('confirm-text');
  const btnConfirmYes = document.getElementById('btn-confirm-yes');

  /* Todos los modales presentes en la pagina */
  const modales = [modalAdd, modalAbono, modalSumar, modalCxp, modalCxpPay, modalConfirm]
    .filter(Boolean);

  /* ── Formato COP en inputs de monto ──────────────────────── */
  COP.bindInput(sumarAmount);
  COP.bindInput(addInitialDebt);
  COP.bindInput(abonoAmount);
  if (cxpMonto) COP.bindInput(cxpMonto);
  if (cxpPayMonto) COP.bindInput(cxpPayMonto);

  /* ══════════════════════════════════════════════════════════
     CARGA DE DATOS
     ══════════════════════════════════════════════════════════ */
  async function getJson(url) {
    const res = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (res.status === 401) { window.location.href = '/login'; return null; }
    if (res.status === 403) return null;
    try {
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  async function loadResumen() {
    const data = await getJson('/pos/api/cartera/resumen');
    if (data && data.ok) resumen = data.resumen || {};
    renderStats();
  }

  async function loadClients() {
    const data = await getJson('/pos/api/fiados');
    if (!data) return;
    if (!data.ok) { notify('Error al cargar la cartera.', 'error'); return; }
    clients = data.clientes || [];
    renderCobrar();
  }

  async function loadCuentas() {
    if (!esAdmin) return;
    const data = await getJson('/pos/api/cartera/por-pagar');
    if (!data) return;
    if (!data.ok) { notify('Error al cargar las obligaciones.', 'error'); return; }
    cuentas = data.cuentas || [];
    renderProveedores(data.proveedores || []);
    renderOrigenes(data.origenes || []);
    renderPagar();
  }

  /* Las opciones de origen las define el backend (ORIGENES_PAGO): el DOM no
     inventa valores, y aun asi el servidor revalida al aprobar. */
  function renderOrigenes(lista) {
    if (!cxpPayOrigen || !lista.length) return;
    const seleccion = cxpPayOrigen.value;
    cxpPayOrigen.innerHTML = '<option value="">Selecciona el origen...</option>'
      + lista.map(o => `<option value="${esc(o.valor)}">${esc(o.etiqueta)}</option>`).join('');
    cxpPayOrigen.value = seleccion;
  }

  function renderProveedores(lista) {
    if (!cxpProveedor) return;
    const seleccion = cxpProveedor.value;
    cxpProveedor.innerHTML = '<option value="">Sin proveedor</option>'
      + lista.map(p => `<option value="${Number(p.id)}">${esc(p.nombre)}</option>`).join('');
    cxpProveedor.value = seleccion;
  }

  /* ══════════════════════════════════════════════════════════
     PESTANAS
     ══════════════════════════════════════════════════════════ */
  function setTab(tab) {
    if (tab === 'pagar' && !esAdmin) return;
    activeTab = tab;
    tabButtons.forEach(btn => {
      const on = btn.dataset.tab === tab;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    panelCobrar.classList.toggle('hidden', tab !== 'cobrar');
    if (panelPagar) panelPagar.classList.toggle('hidden', tab !== 'pagar');
    searchInput.placeholder = tab === 'cobrar'
      ? 'Buscar cliente o telefono...'
      : 'Buscar concepto, proveedor o categoria...';
    searchInput.value = '';
    searchQuery = '';
    renderStats();
    if (tab === 'cobrar') renderCobrar(); else renderPagar();
  }

  tabButtons.forEach(btn => btn.addEventListener('click', () => setTab(btn.dataset.tab)));

  /* ══════════════════════════════════════════════════════════
     ENCABEZADO — STATS
     ══════════════════════════════════════════════════════════ */
  function renderStats() {
    if (activeTab === 'cobrar') {
      const total = resumen.por_cobrar != null
        ? Number(resumen.por_cobrar)
        : clients.reduce((s, c) => s + Number(c.debt || 0), 0);
      const cuenta = resumen.deudores != null
        ? Number(resumen.deudores)
        : clients.filter(c => Number(c.debt || 0) > 0).length;
      statTotalLabel.textContent = 'Total por cobrar';
      statCountLabel.textContent = 'Clientes con deuda';
      statTotal.textContent = formatoMoneda(total);
      statCount.textContent = cuenta;
    } else {
      const total = resumen.por_pagar != null
        ? Number(resumen.por_pagar)
        : cuentas.reduce((s, c) => s + Number(c.saldo || 0), 0);
      statTotalLabel.textContent = 'Total por pagar';
      statCountLabel.textContent = 'Vencido';
      statTotal.textContent = formatoMoneda(total);
      statCount.textContent = formatoMoneda(Number(resumen.vencido || 0));
    }
  }

  /* ══════════════════════════════════════════════════════════
     CUENTAS POR COBRAR
     ══════════════════════════════════════════════════════════ */
  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/);
    if (parts.length >= 2 && parts[1]) return (parts[0][0] + parts[1][0]).toUpperCase();
    return String(name || '??').slice(0, 2).toUpperCase();
  }

  /** Etiqueta de mora a partir de los dias de la deuda mas antigua. */
  function moraInfo(c) {
    const debt = Number(c.debt || 0);
    if (debt <= 0) return { cls: 'ok', text: 'Al dia' };
    const dias = Number(c.dias_mora || 0);
    if (dias > 30) return { cls: 'late', text: `En mora ${dias} d` };
    if (dias > 15) return { cls: 'warn', text: `En riesgo ${dias} d` };
    return { cls: 'ok', text: `${dias} d` };
  }

  function tipoBadge(c) {
    return c.tipo === 'B2B'
      ? '<span class="fiad-badge fiad-badge-b2b">B2B</span>'
      : '';
  }

  function accionesCobrarHTML() {
    const borrar = esAdmin
      ? `<button class="fiad-action-btn btn-borrar" data-action="borrar" aria-label="Eliminar cliente y su deuda">
           <i class="fa-solid fa-trash-can"></i> Borrar
         </button>`
      : '';
    return `
      <button class="fiad-action-btn btn-abonar" data-action="abonar" aria-label="Registrar abono">
        <i class="fa-solid fa-circle-minus"></i> Abonar
      </button>
      <button class="fiad-action-btn btn-sumar" data-action="sumar" aria-label="Aumentar deuda">
        <i class="fa-solid fa-circle-plus"></i> Aumentar
      </button>${borrar}`;
  }

  function buildCardHTML(c) {
    const mora = moraInfo(c);
    const debtTag = Number(c.debt || 0) > 0
      ? `<div class="fiad-debt-tag">${formatoMoneda(c.debt)}</div>
         <div class="fiad-debt-sublabel">Pendiente</div>`
      : `<div class="fiad-debt-tag at-zero">¡Al dia!</div>`;

    return `
    <div class="fiad-card" data-id="${Number(c.id)}">
      <div class="fiad-card-top">
        <div class="fiad-avatar">${esc(initials(c.name))}</div>
        <div class="fiad-card-info">
          <div class="fiad-card-name">${esc(c.name)} ${tipoBadge(c)}</div>
          <div class="fiad-card-phone">${esc(c.phone)}</div>
          <span class="fiad-mora ${mora.cls}">${esc(mora.text)}</span>
        </div>
        <div class="fiad-card-debt">${debtTag}</div>
      </div>
      <div class="fiad-card-actions">${accionesCobrarHTML()}</div>
    </div>`;
  }

  function buildRowHTML(c) {
    const mora = moraInfo(c);
    const debtCell = Number(c.debt || 0) > 0
      ? `<span class="fiad-td-debt">${formatoMoneda(c.debt)}</span>`
      : `<span class="fiad-td-debt at-zero">¡Al dia!</span>`;

    return `
    <tr data-id="${Number(c.id)}">
      <td>
        <div class="fiad-td-client">
          <div class="fiad-avatar">${esc(initials(c.name))}</div>
          <div>
            <div class="fiad-td-name">${esc(c.name)} ${tipoBadge(c)}</div>
          </div>
        </div>
      </td>
      <td class="fiad-td-phone">${esc(c.phone)}</td>
      <td>${debtCell}</td>
      <td><span class="fiad-mora ${mora.cls}">${esc(mora.text)}</span></td>
      <td><div class="fiad-table-actions">${accionesCobrarHTML()}</div></td>
    </tr>`;
  }

  function applySort(list) {
    if (!sortCol) return list;
    return [...list].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (typeof va === 'string') { va = va.toLowerCase(); vb = String(vb || '').toLowerCase(); }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  function updateSortIcons(col, dir) {
    document.querySelectorAll('#fiad-thead .th-sortable').forEach(th => {
      const wrap = th.querySelector('.sort-icon-wrap');
      if (!wrap) return;
      if (th.dataset.col === col) {
        const src = `/static/img/${dir === 'asc' ? 'up' : 'down'}.png`;
        wrap.innerHTML = `<img src="${src}" class="sort-img" alt="" aria-hidden="true" width="13" height="13" decoding="async">`;
      } else {
        wrap.innerHTML = '<i class="fa-solid fa-sort sort-icon"></i>';
      }
    });
  }

  document.getElementById('fiad-thead').addEventListener('click', e => {
    const th = e.target.closest('.th-sortable');
    if (!th) return;
    const col = th.dataset.col;
    if (sortCol === col) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortCol = col;
      sortDir = 'asc';
    }
    updateSortIcons(sortCol, sortDir);
    renderCobrar();
  });

  function renderCobrar() {
    const q = searchQuery;
    const filtered = q
      ? clients.filter(c =>
          String(c.name || '').toLowerCase().includes(q) ||
          String(c.phone || '').replace(/\s/g, '').includes(q.replace(/\s/g, ''))
        )
      : clients;

    cardsEl.innerHTML = filtered.map(buildCardHTML).join('');
    tableBody.innerHTML = applySort(filtered).map(buildRowHTML).join('');

    const isEmpty = filtered.length === 0;
    emptyEl.classList.toggle('hidden', !isEmpty);
    cardsEl.classList.toggle('hidden', isEmpty);
    renderStats();
  }

  /* ══════════════════════════════════════════════════════════
     CUENTAS POR PAGAR
     ══════════════════════════════════════════════════════════ */
  function vencInfo(c) {
    if (c.estado === 'Pagada') return { cls: 'ok', text: 'Pagada' };
    if (!c.vence) return { cls: 'ok', text: 'Sin fecha' };
    const dias = Number(c.dias_mora || 0);
    if (dias > 0) return { cls: 'late', text: `Vencida ${dias} d` };
    if (dias === 0) return { cls: 'warn', text: 'Vence hoy' };
    if (dias >= -5) return { cls: 'warn', text: `En ${Math.abs(dias)} d` };
    return { cls: 'ok', text: `En ${Math.abs(dias)} d` };
  }

  function accionesPagarHTML(c) {
    if (c.estado !== 'Pendiente') return '<span class="fiad-mora ok">Cerrada</span>';
    return `
      <button class="fiad-action-btn btn-abonar" data-cxp="pagar" aria-label="Aprobar pago">
        <i class="fa-solid fa-circle-check"></i> Pagar
      </button>
      <button class="fiad-action-btn btn-borrar" data-cxp="anular" aria-label="Anular obligacion">
        <i class="fa-solid fa-ban"></i> Anular
      </button>`;
  }

  function buildCxpCard(c) {
    const venc = vencInfo(c);
    return `
    <div class="fiad-card" data-cxp-id="${Number(c.id)}">
      <div class="fiad-card-top">
        <div class="fiad-avatar fiad-avatar-cxp"><i class="fa-solid fa-file-invoice"></i></div>
        <div class="fiad-card-info">
          <div class="fiad-card-name">${esc(c.concepto)}</div>
          <div class="fiad-card-phone">
            <span class="fiad-badge">${esc(c.categoria)}</span>
            ${c.proveedor ? esc(c.proveedor) : ''}
          </div>
          <span class="fiad-mora ${venc.cls}">${esc(venc.text)}</span>
        </div>
        <div class="fiad-card-debt">
          <div class="fiad-debt-tag">${formatoMoneda(c.saldo)}</div>
          <div class="fiad-debt-sublabel">de ${formatoMoneda(c.total)}</div>
        </div>
      </div>
      <div class="fiad-card-actions">${accionesPagarHTML(c)}</div>
    </div>`;
  }

  function buildCxpRow(c) {
    const venc = vencInfo(c);
    return `
    <tr data-cxp-id="${Number(c.id)}">
      <td>
        <div class="fiad-td-name">${esc(c.concepto)}</div>
        ${c.proveedor ? `<div class="fiad-td-phone">${esc(c.proveedor)}</div>` : ''}
      </td>
      <td><span class="fiad-badge">${esc(c.categoria)}</span></td>
      <td>
        <span class="fiad-td-debt">${formatoMoneda(c.saldo)}</span>
        <div class="fiad-debt-sublabel">de ${formatoMoneda(c.total)}</div>
      </td>
      <td><span class="fiad-mora ${venc.cls}">${esc(venc.text)}</span></td>
      <td><div class="fiad-table-actions">${accionesPagarHTML(c)}</div></td>
    </tr>`;
  }

  function renderPagar() {
    if (!esAdmin) return;
    const q = searchQuery;
    const filtered = q
      ? cuentas.filter(c =>
          String(c.concepto || '').toLowerCase().includes(q) ||
          String(c.proveedor || '').toLowerCase().includes(q) ||
          String(c.categoria || '').toLowerCase().includes(q)
        )
      : cuentas;

    cxpCards.innerHTML = filtered.map(buildCxpCard).join('');
    cxpTableBody.innerHTML = filtered.map(buildCxpRow).join('');

    const isEmpty = filtered.length === 0;
    cxpEmpty.classList.toggle('hidden', !isEmpty);
    cxpCards.classList.toggle('hidden', isEmpty);
    renderStats();
  }

  /* ── Busqueda (comun a las dos pestanas) ─────────────────── */
  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    if (activeTab === 'cobrar') renderCobrar(); else renderPagar();
  });

  /* ── Escapa HTML ─────────────────────────────────────────── */
  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ══════════════════════════════════════════════════════════
     DELEGACION DE EVENTOS
     ══════════════════════════════════════════════════════════ */
  function handleCobrarAction(el) {
    const row = el.closest('[data-id]');
    if (!row) return;
    const id = parseInt(row.dataset.id, 10);
    const client = clients.find(c => c.id === id);
    if (!client) return;

    if (el.dataset.action === 'abonar') openModalAbono(client);
    if (el.dataset.action === 'sumar') openModalSumar(client);
    if (el.dataset.action === 'borrar') openConfirmBorrarCliente(client);
  }

  [cardsEl, tableBody].forEach(host => {
    host.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (btn) handleCobrarAction(btn);
    });
  });

  function handlePagarAction(el) {
    const row = el.closest('[data-cxp-id]');
    if (!row) return;
    const id = parseInt(row.dataset.cxpId, 10);
    const cuenta = cuentas.find(c => c.id === id);
    if (!cuenta) return;

    if (el.dataset.cxp === 'pagar') openModalPagar(cuenta);
    if (el.dataset.cxp === 'anular') openConfirmAnular(cuenta);
  }

  if (esAdmin) {
    [cxpCards, cxpTableBody].forEach(host => {
      host.addEventListener('click', e => {
        const btn = e.target.closest('[data-cxp]');
        if (btn) handlePagarAction(btn);
      });
    });
  }

  /* ══════════════════════════════════════════════════════════
     MODAL — NUEVO CLIENTE
     ══════════════════════════════════════════════════════════ */
  btnNewClient.addEventListener('click', () => {
    addName.value = '';
    addPhone.value = '';
    addInitialDebt.value = '';
    openModal(modalAdd);
    addName.focus();
  });

  addPhone.addEventListener('input', () => {
    addPhone.value = addPhone.value.replace(/\D/g, '').slice(0, 10);
  });

  btnAddConfirm.addEventListener('click', async () => {
    const name = addName.value.trim();
    const phone = addPhone.value.replace(/\D/g, '').slice(0, 10);
    const deudaInicial = montoDe(addInitialDebt);

    if (!name) { notify('El nombre es requerido.', 'error'); shake(addName); return; }
    if (phone.length < 7) { notify('El telefono debe tener al menos 7 digitos.', 'error'); shake(addPhone); return; }
    if (deudaInicial < 0) { shake(addInitialDebt); return; }

    btnAddConfirm.disabled = true;
    const data = await postJson('/pos/api/fiados', {
      nombre: name, telefono: phone, deuda_inicial: deudaInicial,
    });
    btnAddConfirm.disabled = false;
    if (!data) return;
    if (!data.ok) { notify(data.msg || 'Error al agregar cliente.', 'error'); return; }

    await Promise.all([loadClients(), loadResumen()]);
    closeModal(modalAdd);
    notify(
      deudaInicial > 0
        ? `Cliente agregado con deuda inicial de ${formatoMoneda(deudaInicial)}`
        : 'Cliente agregado',
      'success',
    );
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — REGISTRAR ABONO
     ══════════════════════════════════════════════════════════ */
  function openModalAbono(client) {
    activeId = client.id;
    abonoClientName.textContent = client.name;
    abonoCurrentDebt.textContent = formatoMoneda(client.debt);
    abonoAmount.value = '';
    abonoPreview.textContent = '';
    alertaExcesoDeuda.classList.add('hidden');
    abonoAmount.classList.remove('is-invalid');
    btnAbonoConfirm.disabled = false;
    hideModalError();
    openModal(modalAbono);
    setTimeout(() => abonoAmount.focus(), 80);
  }

  abonoAmount.addEventListener('input', () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const abono = montoDe(abonoAmount);
    const excede = abono > Number(client.debt || 0);
    alertaExcesoDeuda.classList.toggle('hidden', !excede);
    abonoAmount.classList.toggle('is-invalid', excede);
    btnAbonoConfirm.disabled = excede;

    if (abono <= 0) { abonoPreview.textContent = ''; return; }
    const restante = Math.max(0, Number(client.debt || 0) - abono);
    abonoPreview.textContent = abono >= Number(client.debt || 0)
      ? '✓ Quedara en $0 - ¡Al dia!'
      : `Deuda restante: ${formatoMoneda(restante)}`;
  });

  btnAbonoConfirm.addEventListener('click', async () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const abono = montoDe(abonoAmount);
    if (abono <= 0 || abono > Number(client.debt || 0)) {
      showModalError('El monto debe ser mayor a 0 y no puede superar la deuda actual.');
      shake(abonoAmount);
      return;
    }
    hideModalError();

    btnAbonoConfirm.disabled = true;
    const data = await postJson(`/pos/api/fiados/${client.id}/abonar`, { monto: abono });
    btnAbonoConfirm.disabled = false;
    if (!data) return;
    if (!data.ok) { showModalError(data.msg || data.error || 'Error al registrar abono.'); return; }

    await Promise.all([loadClients(), loadResumen()]);
    closeModal(modalAbono);
    notify(`Abono de ${formatoMoneda(abono)} registrado`, 'success');
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — SUMAR A LA DEUDA
     ══════════════════════════════════════════════════════════ */
  function openModalSumar(client) {
    activeId = client.id;
    sumarClientName.textContent = client.name;
    sumarCurrentDebt.textContent = formatoMoneda(client.debt);
    sumarAmount.value = '';
    sumarDetail.value = '';
    sumarPreview.textContent = '';
    openModal(modalSumar);
    setTimeout(() => sumarAmount.focus(), 80);
  }

  sumarAmount.addEventListener('input', () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const suma = montoDe(sumarAmount);
    sumarPreview.textContent = suma <= 0
      ? ''
      : `Nueva deuda: ${formatoMoneda(Number(client.debt || 0) + suma)}`;
  });

  btnSumarConfirm.addEventListener('click', async () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const suma = montoDe(sumarAmount);
    if (suma <= 0) { notify('El monto debe ser mayor a cero.', 'error'); shake(sumarAmount); return; }

    btnSumarConfirm.disabled = true;
    const data = await postJson(`/pos/api/fiados/${client.id}/sumar`, {
      monto: suma, concepto: sumarDetail.value.trim() || 'Fiado',
    });
    btnSumarConfirm.disabled = false;
    if (!data) return;
    if (!data.ok) { notify(data.msg || 'Error al registrar deuda.', 'error'); return; }

    await Promise.all([loadClients(), loadResumen()]);
    closeModal(modalSumar);
    const detalle = sumarDetail.value.trim();
    notify(detalle ? `+${formatoMoneda(suma)} - "${detalle}"` : `+${formatoMoneda(suma)} sumado a la deuda`, 'info');
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — NUEVA OBLIGACION (cuentas por pagar)
     ══════════════════════════════════════════════════════════ */
  if (esAdmin) {
    /* El selector de proveedor solo aplica a la categoria Proveedor */
    function syncProveedorField() {
      const esProveedor = cxpCategoria.value === 'Proveedor';
      cxpProveedorField.classList.toggle('hidden', !esProveedor);
      if (!esProveedor) cxpProveedor.value = '';
    }
    cxpCategoria.addEventListener('change', syncProveedorField);

    btnNewCxp.addEventListener('click', () => {
      cxpConcepto.value = '';
      cxpMonto.value = '';
      cxpVence.value = '';
      cxpDesc.value = '';
      cxpCategoria.value = 'Proveedor';
      syncProveedorField();
      hideBox(cxpError, cxpErrorText);
      openModal(modalCxp);
      cxpConcepto.focus();
    });

    btnCxpConfirm.addEventListener('click', async () => {
      const concepto = cxpConcepto.value.trim();
      const monto = montoDe(cxpMonto);

      if (!concepto) { showBox(cxpError, cxpErrorText, 'El concepto es requerido.'); shake(cxpConcepto); return; }
      if (!(monto > 0)) { showBox(cxpError, cxpErrorText, 'El monto debe ser un numero mayor a cero.'); shake(cxpMonto); return; }
      hideBox(cxpError, cxpErrorText);

      btnCxpConfirm.disabled = true;
      const data = await postJson('/pos/api/cartera/por-pagar', {
        categoria: cxpCategoria.value,
        concepto,
        descripcion: cxpDesc.value.trim(),
        monto,
        vence: cxpVence.value || '',
        id_proveedor: cxpProveedor.value || null,
      });
      btnCxpConfirm.disabled = false;
      if (!data) return;
      if (!data.ok) { showBox(cxpError, cxpErrorText, data.msg || 'No se pudo registrar.'); return; }

      await Promise.all([loadCuentas(), loadResumen()]);
      closeModal(modalCxp);
      notify('Obligacion registrada', 'success');
    });

    /* ── Aprobar pago ─────────────────────────────────────── */
    cxpPayMonto.addEventListener('input', () => {
      if (!activeCxp) return;
      const monto = montoDe(cxpPayMonto);
      const excede = monto > Number(activeCxp.saldo || 0);
      cxpPayExceso.classList.toggle('hidden', !excede);
      cxpPayMonto.classList.toggle('is-invalid', excede);
      btnCxpPayConfirm.disabled = excede;
      if (monto <= 0) { cxpPayPreview.textContent = ''; return; }
      const restante = Math.max(0, Number(activeCxp.saldo || 0) - monto);
      cxpPayPreview.textContent = restante === 0
        ? '✓ Queda totalmente pagada'
        : `Saldo restante: ${formatoMoneda(restante)}`;
    });

    /* Quitar el aviso en cuanto elige un origen valido */
    cxpPayOrigen.addEventListener('change', () => {
      const ok = !!cxpPayOrigen.value;
      cxpPayOrigenErr.classList.toggle('hidden', ok);
      cxpPayOrigen.classList.toggle('is-invalid', !ok);
    });

    btnCxpPayConfirm.addEventListener('click', async () => {
      if (!activeCxp) return;
      const monto = montoDe(cxpPayMonto);
      const origen = cxpPayOrigen.value;
      if (!(monto > 0) || monto > Number(activeCxp.saldo || 0)) {
        showBox(cxpPayError, cxpPayErrorText, 'El pago debe ser mayor a 0 y no puede superar el saldo.');
        shake(cxpPayMonto);
        return;
      }
      if (!origen) {
        cxpPayOrigenErr.classList.remove('hidden');
        cxpPayOrigen.classList.add('is-invalid');
        showBox(cxpPayError, cxpPayErrorText, 'Selecciona el origen de los fondos.');
        shake(cxpPayOrigen);
        return;
      }
      hideBox(cxpPayError, cxpPayErrorText);

      btnCxpPayConfirm.disabled = true;
      const data = await postJson(`/pos/api/cartera/por-pagar/${activeCxp.id}/pagar`, { monto, origen });
      btnCxpPayConfirm.disabled = false;
      if (!data) return;
      if (!data.ok) { showBox(cxpPayError, cxpPayErrorText, data.msg || 'No se pudo aprobar el pago.'); return; }

      await Promise.all([loadCuentas(), loadResumen()]);
      closeModal(modalCxpPay);
      notify(
        `Pago de ${formatoMoneda(monto)} aprobado desde ${data.origen || origen}. Gasto registrado.`,
        'success',
      );
    });
  }

  function openModalPagar(cuenta) {
    activeCxp = cuenta;
    cxpPayConcepto.textContent = cuenta.concepto;
    cxpPaySaldo.textContent = formatoMoneda(cuenta.saldo);
    cxpPayMonto.value = '';
    cxpPayPreview.textContent = '';
    cxpPayOrigen.value = '';
    cxpPayOrigen.classList.remove('is-invalid');
    cxpPayOrigenErr.classList.add('hidden');
    cxpPayExceso.classList.add('hidden');
    cxpPayMonto.classList.remove('is-invalid');
    btnCxpPayConfirm.disabled = false;
    hideBox(cxpPayError, cxpPayErrorText);
    openModal(modalCxpPay);
    setTimeout(() => cxpPayMonto.focus(), 80);
  }

  /* ══════════════════════════════════════════════════════════
     MODAL — CONFIRMAR (borrar deuda / anular obligacion)
     ══════════════════════════════════════════════════════════ */
  function openConfirm(titulo, objetivo, texto, accion) {
    if (!modalConfirm) return;
    document.getElementById('modal-confirm-title').textContent = titulo;
    confirmTarget.textContent = objetivo;
    confirmText.textContent = texto;
    pendingConfirm = accion;
    openModal(modalConfirm);
  }

  function openConfirmBorrarCliente(client) {
    openConfirm(
      'Eliminar cliente',
      client.name,
      'El cliente sale de la cartera y su deuda deja de cobrarse. Las ventas historicas se conservan.',
      async () => {
        const data = await sendJson('DELETE', `/pos/api/fiados/${client.id}`);
        if (!data) return;
        if (!data.ok) { notify(data.msg || 'No se pudo eliminar.', 'error'); return; }
        await Promise.all([loadClients(), loadResumen()]);
        notify('Cliente eliminado de la cartera', 'success');
      },
    );
  }

  function openConfirmAnular(cuenta) {
    openConfirm(
      'Anular obligacion',
      cuenta.concepto,
      'La obligacion queda anulada y deja de sumar al total por pagar. El registro se conserva.',
      async () => {
        const data = await sendJson('DELETE', `/pos/api/cartera/por-pagar/${cuenta.id}`);
        if (!data) return;
        if (!data.ok) { notify(data.msg || 'No se pudo anular.', 'error'); return; }
        await Promise.all([loadCuentas(), loadResumen()]);
        notify('Obligacion anulada', 'success');
      },
    );
  }

  if (btnConfirmYes) {
    btnConfirmYes.addEventListener('click', async () => {
      const accion = pendingConfirm;
      if (!accion) return;
      btnConfirmYes.disabled = true;
      try {
        await accion();
      } finally {
        btnConfirmYes.disabled = false;
        closeModal(modalConfirm);
      }
    });
  }

  /* ══════════════════════════════════════════════════════════
     HELPERS
     ══════════════════════════════════════════════════════════ */
  /** Monto entero de un input COP. Devuelve 0 si esta vacio o no es numero. */
  function montoDe(input) {
    const valor = COP.parse(input.value);
    return Number.isFinite(valor) ? valor : 0;
  }

  async function sendJson(method, url, payload) {
    const opciones = { method, headers: jsonHeaders };
    if (payload !== undefined) opciones.body = JSON.stringify(payload);
    let res;
    try {
      res = await fetch(url, opciones);
    } catch (_) {
      notify('Sin conexion con el servidor.', 'error');
      return null;
    }
    if (res.status === 401) { window.location.href = '/login'; return null; }
    if (res.status === 403) { notify('No tienes permisos para esta accion.', 'error'); return null; }
    try {
      return await res.json();
    } catch (_) {
      notify('No se pudo procesar la respuesta del servidor.', 'error');
      return null;
    }
  }

  const postJson = (url, payload) => sendJson('POST', url, payload);

  function openModal(m) {
    m.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(m) {
    m.classList.add('hidden');
    document.body.style.overflow = '';
    if (m === modalAbono || m === modalSumar) activeId = null;
    if (m === modalCxpPay) activeCxp = null;
    if (m === modalConfirm) pendingConfirm = null;
    alertaExcesoDeuda.classList.add('hidden');
    abonoAmount.classList.remove('is-invalid');
    btnAbonoConfirm.disabled = false;
    hideModalError();
  }

  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const modal = document.getElementById(btn.dataset.close);
      if (modal) closeModal(modal);
    });
  });

  modales.forEach(m => {
    m.addEventListener('click', e => {
      if (e.target === m) closeModal(m);
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    modales.forEach(m => {
      if (!m.classList.contains('hidden')) closeModal(m);
    });
  });

  function showModalError(msg) { showBox(modalErrorBox, modalErrorText, msg); }
  function hideModalError() { hideBox(modalErrorBox, modalErrorText); }

  function showBox(box, textEl, msg) {
    if (!box || !textEl) return;
    textEl.textContent = msg;
    box.classList.remove('hidden');
  }

  function hideBox(box, textEl) {
    if (!box || !textEl) return;
    textEl.textContent = '';
    box.classList.add('hidden');
  }

  function notify(msg, type) {
    if (window.JemToast && typeof window.JemToast.show === 'function') {
      window.JemToast.show(msg, type || 'info', { duration: 3000 });
      return;
    }
    console[type === 'error' ? 'error' : 'log'](msg);
  }

  function shake(el) {
    el.style.transition = 'transform 0.05s';
    [4, -4, 4, -4, 0].forEach((x, i) => {
      setTimeout(() => {
        el.style.transform = x === 0 ? '' : `translateX(${x}px)`;
      }, i * 50);
    });
    el.focus();
  }

  /* ── Arranque ────────────────────────────────────────────── */
  loadResumen();
  loadClients();
  if (esAdmin) loadCuentas();
});
