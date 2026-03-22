/* ============================================================
   Ruta: static/js/fiados.js
   Pantalla: Fiados y Cuentas por Cobrar
   Depende de: cop-format.js (cargado antes en el HTML)
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

  /* ── Datos de ejemplo ─────────────────────────────────────
     En produccion vendran de la API / base de datos.
  ─────────────────────────────────────────────────────────── */
  let clients    = [];
  let searchQuery = '';
  let activeId    = null;
  let sortCol     = null;
  let sortDir     = 'asc';

  /* ── Carga inicial desde API ─────────────────────────────── */
  async function loadClients() {
    const res = await fetch('/pos/api/fiados');
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast('Error al cargar fiados.', 'error'); return; }
    clients = data.clientes;
    renderAll();
  }
  loadClients();

  /* ── Referencias DOM ─────────────────────────────────────── */
  const cardsEl    = document.getElementById('fiad-cards');
  const tableBody  = document.getElementById('fiad-table-body');
  const searchInput = document.getElementById('fiad-search');
  const emptyEl    = document.getElementById('fiad-empty');
  const statTotal  = document.getElementById('stat-total');
  const statCount  = document.getElementById('stat-count');
  const toast      = document.getElementById('fiad-toast');

  /* Modales */
  const modalAdd   = document.getElementById('modal-add');
  const modalAbono = document.getElementById('modal-abono');
  const modalSumar = document.getElementById('modal-sumar');

  /* Campos modal Nuevo Cliente */
  const addName    = document.getElementById('add-name');
  const addPhone   = document.getElementById('add-phone');
  const addInitialDebt = document.getElementById('add-initial-debt');

  /* Campos modal Abono */
  const abonoClientName   = document.getElementById('abono-client-name');
  const abonoCurrentDebt  = document.getElementById('abono-current-debt');
  const abonoAmount       = document.getElementById('abono-amount');
  const abonoPreview      = document.getElementById('abono-preview');
  const modalErrorBox      = document.getElementById('alerta-error-modal');
  const modalErrorText     = document.getElementById('texto-alerta-modal');
  const alertaExcesoDeuda  = document.getElementById('alerta-exceso-deuda');

  /* Campos modal Sumar */
  const sumarClientName   = document.getElementById('sumar-client-name');
  const sumarCurrentDebt  = document.getElementById('sumar-current-debt');
  const sumarAmount       = document.getElementById('sumar-amount');
  const sumarDetail       = document.getElementById('sumar-detail');
  const sumarPreview      = document.getElementById('sumar-preview');

  /* Botones confirmar */
  const btnAddConfirm   = document.getElementById('btn-add-confirm');
  const btnAbonoConfirm = document.getElementById('btn-abono-confirm');
  const btnSumarConfirm = document.getElementById('btn-sumar-confirm');

  /* ── Bind COP formatting en inputs de monto ─────────────── */
  COP.bindInput(sumarAmount);
  COP.bindInput(addInitialDebt);
  COP.bindInput(abonoAmount);

  /* ── Renderizado ─────────────────────────────────────────── */
  renderAll();

  /* ── Busqueda ────────────────────────────────────────────── */
  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    renderAll();
  });

  /* ── Ordenamiento de tabla ───────────────────────────────── */
  function applySort(list) {
    if (!sortCol) return list;
    return [...list].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
      if (va < vb) return sortDir === 'asc' ? -1 :  1;
      if (va > vb) return sortDir === 'asc' ?  1 : -1;
      return 0;
    });
  }

  function updateSortIcons(col, dir) {
    document.querySelectorAll('#fiad-thead .th-sortable').forEach(th => {
      const wrap = th.querySelector('.sort-icon-wrap');
      if (th.dataset.col === col) {
        const src = `/static/img/${dir === 'asc' ? 'up' : 'down'}.png`;
        wrap.innerHTML = `<img src="${src}" class="sort-img" alt="${dir}">`;
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
    renderAll();
  });

  /* ══════════════════════════════════════════════════════════
     HELPERS DE INICIALES
     ══════════════════════════════════════════════════════════ */
  function initials(name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  /* ── HTML tarjeta (movil) ────────────────────────────────── */
  function buildCardHTML(c) {
    const debtTag = c.debt > 0
      ? `<div class="fiad-debt-tag">${formatoMoneda(c.debt)}</div>
         <div class="fiad-debt-sublabel">Pendiente</div>`
      : `<div class="fiad-debt-tag at-zero">¡Al dia!</div>`;

    return `
    <div class="fiad-card" data-id="${c.id}">
      <div class="fiad-card-top">
        <div class="fiad-avatar">${initials(c.name)}</div>
        <div class="fiad-card-info">
          <div class="fiad-card-name">${esc(c.name)}</div>
          <div class="fiad-card-phone">${esc(c.phone)}</div>
        </div>
        <div class="fiad-card-debt">${debtTag}</div>
      </div>
      <div class="fiad-card-actions">
        <button class="fiad-action-btn btn-abonar" data-action="abonar" aria-label="Registrar abono">
          <i class="fa-solid fa-circle-minus"></i> Abonar
        </button>
        <button class="fiad-action-btn btn-sumar" data-action="sumar" aria-label="Aumentar deuda">
          <i class="fa-solid fa-circle-plus"></i> Aumentar
        </button>
      </div>
    </div>`;
  }

  /* ── HTML fila de tabla (desktop) ──────────────────────── */
  function buildRowHTML(c) {
    const debtCell = c.debt > 0
      ? `<span class="fiad-td-debt">${formatoMoneda(c.debt)}</span>`
      : `<span class="fiad-td-debt at-zero">¡Al dia!</span>`;

    return `
    <tr data-id="${c.id}">
      <td>
        <div class="fiad-td-client">
          <div class="fiad-avatar">${initials(c.name)}</div>
          <div>
            <div class="fiad-td-name">${esc(c.name)}</div>
          </div>
        </div>
      </td>
      <td class="fiad-td-phone">${esc(c.phone)}</td>
      <td>${debtCell}</td>
      <td>
        <div class="fiad-table-actions">
          <button class="fiad-action-btn btn-abonar" data-action="abonar" aria-label="Registrar abono">
            <i class="fa-solid fa-circle-minus"></i> Abonar
          </button>
          <button class="fiad-action-btn btn-sumar" data-action="sumar" aria-label="Aumentar deuda">
            <i class="fa-solid fa-circle-plus"></i> Aumentar
          </button>
        </div>
      </td>
    </tr>`;
  }

  /* ── Renderiza todo ──────────────────────────────────────── */
  function renderAll() {
    const q = searchQuery;
    const filtered = q
      ? clients.filter(c =>
          c.name.toLowerCase().includes(q) ||
          c.phone.replace(/\s/g, '').includes(q.replace(/\s/g, ''))
        )
      : clients;

    /* Tarjetas movil */
    cardsEl.innerHTML = filtered.map(buildCardHTML).join('');
    /* Tabla desktop — aplica sort si hay columna activa */
    const display = applySort(filtered);
    tableBody.innerHTML = display.map(buildRowHTML).join('');

    /* Estado vacio */
    const isEmpty = filtered.length === 0;
    emptyEl.classList.toggle('hidden', !isEmpty);
    cardsEl.classList.toggle('hidden', isEmpty);

    /* Stats */
    const totalDebt = clients.reduce((s, c) => s + c.debt, 0);
    const withDebt  = clients.filter(c => c.debt > 0).length;
    statTotal.textContent = formatoMoneda(totalDebt);
    statCount.textContent = withDebt;
  }

  /* ── Escapa HTML ─────────────────────────────────────────── */
  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ══════════════════════════════════════════════════════════
     DELEGACION DE EVENTOS — tarjetas y tabla
     ══════════════════════════════════════════════════════════ */
  function handleAction(el) {
    const row    = el.closest('[data-id]');
    if (!row) return;
    const id     = parseInt(row.dataset.id, 10);
    const action = el.dataset.action;
    const client = clients.find(c => c.id === id);
    if (!client) return;

    if (action === 'abonar') openModalAbono(client);
    if (action === 'sumar')  openModalSumar(client);
  }

  cardsEl.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (btn) handleAction(btn);
  });

  tableBody.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (btn) handleAction(btn);
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — NUEVO CLIENTE
     ══════════════════════════════════════════════════════════ */
  document.getElementById('btn-new-client').addEventListener('click', () => {
    addName.value  = '';
    addPhone.value = '';
    addInitialDebt.value = '';
    openModal(modalAdd);
    addName.focus();
  });

  addPhone.addEventListener('input', () => {
    addPhone.value = addPhone.value.replace(/\D/g, '').slice(0, 10);
  });

  btnAddConfirm.addEventListener('click', async () => {
    const name  = addName.value.trim();
    const phone = addPhone.value.replace(/\D/g, '').slice(0, 10);
    const deudaInicial = COP.parse(addInitialDebt.value);
    if (!name) { shake(addName); return; }
    if (phone.length > 10) { shake(addPhone); return; }
    if (deudaInicial < 0) { shake(addInitialDebt); return; }

    btnAddConfirm.disabled = true;
    const res = await fetch('/pos/api/fiados', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ nombre: name, telefono: phone, deuda_inicial: deudaInicial }),
    });
    btnAddConfirm.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast(data.msg || 'Error al agregar cliente.', 'error'); return; }
    await loadClients();
    closeModal(modalAdd);
    if (deudaInicial > 0) {
      showToast(`Cliente agregado con deuda inicial de ${formatoMoneda(deudaInicial)}`, 'success');
    } else {
      showToast('Cliente agregado', 'success');
    }
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — REGISTRAR ABONO
     ══════════════════════════════════════════════════════════ */
  function openModalAbono(client) {
    activeId = client.id;
    abonoClientName.textContent  = client.name;
    abonoCurrentDebt.textContent = formatoMoneda(client.debt);
    abonoAmount.value = '';
    abonoPreview.textContent = '';
    if (alertaExcesoDeuda) alertaExcesoDeuda.classList.add('hidden');
    abonoAmount.classList.remove('border-red-500');
    btnAbonoConfirm.disabled = false;
    hideModalError();
    openModal(modalAbono);
    setTimeout(() => abonoAmount.focus(), 80);
  }

  function validarAbonoVisual(client, abono) {
    const excedeDeuda = abono > client.debt;
    if (alertaExcesoDeuda) alertaExcesoDeuda.classList.toggle('hidden', !excedeDeuda);
    abonoAmount.classList.toggle('border-red-500', excedeDeuda);
    btnAbonoConfirm.disabled = excedeDeuda;
    return !excedeDeuda;
  }

  /* Previsualizacion en tiempo real */
  abonoAmount.addEventListener('input', () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const abono = Number(abonoAmount.value || 0);
    validarAbonoVisual(client, abono);
    if (abono <= 0) { abonoPreview.textContent = ''; return; }
    const remaining = Math.max(0, client.debt - abono);
    if (abono >= client.debt) {
      abonoPreview.textContent = '✓ Quedara en $0 - ¡Al dia!';
    } else {
      abonoPreview.textContent = `Deuda restante: ${formatoMoneda(remaining)}`;
    }
  });

  btnAbonoConfirm.addEventListener('click', async () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const abono = Number(abonoAmount.value || 0);
    if (abono <= 0 || abono > client.debt) {
      showModalError('El monto debe ser mayor a 0 y no puede superar la deuda actual.');
      shake(abonoAmount);
      return;
    }
    hideModalError();

    btnAbonoConfirm.disabled = true;
    const res = await fetch(`/pos/api/fiados/${activeId}/abonar`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ monto: abono }),
    });
    btnAbonoConfirm.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showModalError(data.error || data.msg || 'Error al registrar abono.');
      return;
    }
    await loadClients();
    closeModal(modalAbono);
    showToast(`Abono de ${formatoMoneda(abono)} registrado`, 'success');
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — SUMAR A LA DEUDA
     ══════════════════════════════════════════════════════════ */
  function openModalSumar(client) {
    activeId = client.id;
    sumarClientName.textContent  = client.name;
    sumarCurrentDebt.textContent = formatoMoneda(client.debt);
    sumarAmount.value = '';
    sumarDetail.value = '';
    sumarPreview.textContent = '';
    openModal(modalSumar);
    setTimeout(() => sumarAmount.focus(), 80);
  }

  /* Previsualizacion en tiempo real */
  sumarAmount.addEventListener('input', () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const suma = COP.parse(sumarAmount.value);
    if (suma <= 0) { sumarPreview.textContent = ''; return; }
    const newDebt = client.debt + suma;
    sumarPreview.textContent = `Nueva deuda: ${formatoMoneda(newDebt)}`;
  });

  btnSumarConfirm.addEventListener('click', async () => {
    const client = clients.find(c => c.id === activeId);
    if (!client) return;
    const suma = COP.parse(sumarAmount.value);
    if (suma <= 0) { shake(sumarAmount); return; }

    btnSumarConfirm.disabled = true;
    const res = await fetch(`/pos/api/fiados/${activeId}/sumar`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ monto: suma, concepto: sumarDetail.value.trim() || 'Fiado' }),
    });
    btnSumarConfirm.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      showToast('No se pudo procesar la respuesta del servidor.', 'error');
      return;
    }
    if (!data.ok) { showToast(data.msg || 'Error al registrar deuda.', 'error'); return; }
    await loadClients();
    closeModal(modalSumar);
    const detail = sumarDetail.value.trim();
    showToast(detail ? `+${formatoMoneda(suma)} — "${detail}"` : `+${formatoMoneda(suma)} sumado a la deuda`, 'error');
  });

  /* ══════════════════════════════════════════════════════════
     CIERRE GENERICO DE MODALES
     ══════════════════════════════════════════════════════════ */
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.close;
      const modal = document.getElementById(id);
      if (modal) closeModal(modal);
    });
  });

  /* Clic fuera del card cierra el modal */
  [modalAdd, modalAbono, modalSumar].forEach(m => {
    m.addEventListener('click', e => {
      if (e.target === m) closeModal(m);
    });
  });

  /* Escape cierra el modal visible */
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    [modalAdd, modalAbono, modalSumar].forEach(m => {
      if (!m.classList.contains('hidden')) closeModal(m);
    });
  });

  /* ── Helpers de modal ────────────────────────────────────── */
  function openModal(m) {
    m.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(m) {
    m.classList.add('hidden');
    document.body.style.overflow = '';
    activeId = null;
    if (alertaExcesoDeuda) alertaExcesoDeuda.classList.add('hidden');
    if (abonoAmount) abonoAmount.classList.remove('border-red-500');
    if (btnAbonoConfirm) btnAbonoConfirm.disabled = false;
    hideModalError();
  }

  function showModalError(msg) {
    if (!modalErrorBox || !modalErrorText) return;
    modalErrorText.textContent = msg;
    modalErrorBox.classList.remove('hidden');
  }

  function hideModalError() {
    if (!modalErrorBox || !modalErrorText) return;
    modalErrorText.textContent = '';
    modalErrorBox.classList.add('hidden');
  }

  /* ── Toast ───────────────────────────────────────────────── */
  let toastTimer = null;
  function showToast(msg, type = '') {
    toast.textContent = msg;
    toast.className   = `fiad-toast ${type}`;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.className = 'fiad-toast hidden';
    }, 3000);
  }

  /* ── Shake (campo requerido vacio) ───────────────────────── */
  function shake(el) {
    el.style.transition = 'transform 0.05s';
    const steps = [4, -4, 4, -4, 0];
    steps.forEach((x, i) => {
      setTimeout(() => {
        el.style.transform = `translateX(${x}px)`;
        if (x === 0) el.style.transform = '';
      }, i * 50);
    });
    el.focus();
  }

});
