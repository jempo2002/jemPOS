/* ============================================================
   Ruta: static/js/clientes-proveer.js
   Pantalla: Clientes a Proveer (B2B) — dashboard comercial y
             listas de precios mayoristas.
   Depende de: cop-format.js y toast.js (cargados antes en el HTML)

   La pantalla completa es Admin/Master: el backend revalida el rol
   en cada ruta, aqui no se decide nada de permisos.
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };

  /* ── Estado ──────────────────────────────────────────────── */
  let clientes = [];
  let listas   = [];
  let detalle  = null;   /* cliente abierto en el modal de dashboard */
  let editandoLista = null;
  let editandoCliente = null;
  let pendingConfirm = null;
  let searchQuery = '';
  let activeTab = 'clientes';
  let sortCol = null;
  let sortDir = 'asc';

  /* ── DOM ─────────────────────────────────────────────────── */
  const searchInput = document.getElementById('b2b-search');
  const tabButtons  = Array.from(document.querySelectorAll('.fiad-tab'));
  const panelClientes = document.getElementById('panel-clientes');
  const panelListas   = document.getElementById('panel-listas');

  const statComprado = document.getElementById('stat-comprado');
  const statTicket   = document.getElementById('stat-ticket');
  const statClientes = document.getElementById('stat-clientes');

  const b2bCards = document.getElementById('b2b-cards');
  const b2bBody  = document.getElementById('b2b-table-body');
  const b2bEmpty = document.getElementById('b2b-empty');

  const listasCards = document.getElementById('listas-cards');
  const listasBody  = document.getElementById('listas-table-body');
  const listasEmpty = document.getElementById('listas-empty');

  const modalDetalle = document.getElementById('modal-b2b-detalle');
  const modalB2b     = document.getElementById('modal-b2b');
  const modalLista   = document.getElementById('modal-lista');
  const modalConfirm = document.getElementById('modal-confirm');
  const modales = [modalDetalle, modalB2b, modalLista, modalConfirm];

  const detalleNombre = document.getElementById('b2b-detalle-nombre');
  const detalleKpis   = document.getElementById('b2b-detalle-kpis');
  const detalleTop    = document.getElementById('b2b-detalle-top');
  const detalleLista  = document.getElementById('b2b-detalle-lista');
  const detalleHint   = document.getElementById('b2b-detalle-lista-hint');
  const btnListaSave  = document.getElementById('btn-b2b-lista-save');

  const b2bNombre = document.getElementById('b2b-nombre');
  const b2bTelefono = document.getElementById('b2b-telefono');
  const b2bNit = document.getElementById('b2b-nit');
  const b2bListaSel = document.getElementById('b2b-lista');
  const b2bError = document.getElementById('b2b-error');
  const b2bErrorText = document.getElementById('b2b-error-text');
  const btnB2bConfirm = document.getElementById('btn-b2b-confirm');

  const listaNombre = document.getElementById('lista-nombre');
  const listaPct = document.getElementById('lista-pct');
  const listaMin = document.getElementById('lista-min');
  const listaError = document.getElementById('lista-error');
  const listaErrorText = document.getElementById('lista-error-text');
  const btnListaConfirm = document.getElementById('btn-lista-confirm');

  const confirmTarget = document.getElementById('confirm-target');
  const confirmText = document.getElementById('confirm-text');
  const btnConfirmYes = document.getElementById('btn-confirm-yes');

  /* ══════════════════════════════════════════════════════════
     UTILIDADES
     ══════════════════════════════════════════════════════════ */
  function money(n) {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency', currency: 'COP', minimumFractionDigits: 0,
    }).format(Number(n || 0));
  }

  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/);
    if (parts.length >= 2 && parts[1]) return (parts[0][0] + parts[1][0]).toUpperCase();
    return String(name || '??').slice(0, 2).toUpperCase();
  }

  function frecuenciaTexto(dias) {
    if (dias == null) return 'Sin historial';
    if (dias === 0) return 'Mismo dia';
    return `Cada ${dias} d`;
  }

  function listaTexto(lista) {
    if (!lista || !lista.id) return 'Sin lista';
    const desde = lista.min_pedidos > 0 ? ` desde pedido ${Number(lista.min_pedidos)}` : '';
    return `${lista.nombre} -${Number(lista.descuento_pct)}%${desde}`;
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
      setTimeout(() => { el.style.transform = x === 0 ? '' : `translateX(${x}px)`; }, i * 50);
    });
    el.focus();
  }

  function showBox(box, textEl, msg) {
    textEl.textContent = msg;
    box.classList.remove('hidden');
  }

  function hideBox(box, textEl) {
    textEl.textContent = '';
    box.classList.add('hidden');
  }

  /* ══════════════════════════════════════════════════════════
     RED
     ══════════════════════════════════════════════════════════ */
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

  const getJson  = (url) => sendJson('GET', url);
  const postJson = (url, payload) => sendJson('POST', url, payload);
  const putJson  = (url, payload) => sendJson('PUT', url, payload);

  async function loadClientes() {
    const data = await getJson('/pos/api/b2b/clientes');
    if (!data) return;
    if (!data.ok) { notify('Error al cargar clientes B2B.', 'error'); return; }
    clientes = data.clientes || [];
    listas = data.listas || [];
    renderSelectListas();
    renderClientes();
    renderListas();
  }

  /* ══════════════════════════════════════════════════════════
     PESTANAS
     ══════════════════════════════════════════════════════════ */
  function setTab(tab) {
    activeTab = tab;
    tabButtons.forEach(btn => {
      const on = btn.dataset.tab === tab;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    panelClientes.classList.toggle('hidden', tab !== 'clientes');
    panelListas.classList.toggle('hidden', tab !== 'listas');
    searchInput.value = '';
    searchQuery = '';
    searchInput.placeholder = tab === 'clientes'
      ? 'Buscar empresa, NIT o telefono...'
      : 'Buscar lista...';
    if (tab === 'clientes') renderClientes(); else renderListas();
  }

  tabButtons.forEach(btn => btn.addEventListener('click', () => setTab(btn.dataset.tab)));

  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    if (activeTab === 'clientes') renderClientes(); else renderListas();
  });

  /* ══════════════════════════════════════════════════════════
     CLIENTES B2B
     ══════════════════════════════════════════════════════════ */
  function renderStats(lista) {
    const comprado = lista.reduce((s, c) => s + Number(c.comprado || 0), 0);
    const pedidos = lista.reduce((s, c) => s + Number(c.pedidos || 0), 0);
    statComprado.textContent = money(comprado);
    statTicket.textContent = money(pedidos ? comprado / pedidos : 0);
    statClientes.textContent = lista.length;
  }

  function accionesClienteHTML() {
    return `
      <button class="fiad-action-btn btn-abonar" data-action="ver" aria-label="Ver dashboard del cliente">
        <i class="fa-solid fa-chart-simple"></i> Dashboard
      </button>
      <button class="fiad-action-btn btn-borrar" data-action="editar" aria-label="Editar cliente">
        <i class="fa-solid fa-pen"></i> Editar
      </button>`;
  }

  function buildClienteCard(c) {
    return `
    <div class="fiad-card" data-id="${Number(c.id)}">
      <div class="fiad-card-top">
        <div class="fiad-avatar">${esc(initials(c.name))}</div>
        <div class="fiad-card-info">
          <div class="fiad-card-name">${esc(c.name)} <span class="fiad-badge fiad-badge-b2b">B2B</span></div>
          <div class="fiad-card-phone">${esc(c.phone)}${c.nit ? ' · NIT ' + esc(c.nit) : ''}</div>
          <span class="fiad-mora ${c.lista.id ? 'ok' : 'warn'}">${esc(listaTexto(c.lista))}</span>
        </div>
        <div class="fiad-card-debt">
          <div class="fiad-debt-tag">${money(c.ticket_promedio)}</div>
          <div class="fiad-debt-sublabel">${Number(c.pedidos || 0)} pedidos · ${esc(frecuenciaTexto(c.frecuencia_dias))}</div>
        </div>
      </div>
      <div class="fiad-card-actions">${accionesClienteHTML()}</div>
    </div>`;
  }

  function buildClienteRow(c) {
    return `
    <tr data-id="${Number(c.id)}">
      <td>
        <div class="fiad-td-client">
          <div class="fiad-avatar">${esc(initials(c.name))}</div>
          <div>
            <div class="fiad-td-name">${esc(c.name)}</div>
            <div class="fiad-td-phone">${esc(c.phone)}${c.nit ? ' · NIT ' + esc(c.nit) : ''}</div>
          </div>
        </div>
      </td>
      <td>${Number(c.pedidos || 0)}</td>
      <td><span class="fiad-td-debt">${money(c.ticket_promedio)}</span></td>
      <td>${esc(frecuenciaTexto(c.frecuencia_dias))}</td>
      <td><span class="fiad-mora ${c.lista.id ? 'ok' : 'warn'}">${esc(listaTexto(c.lista))}</span></td>
      <td><div class="fiad-table-actions">${accionesClienteHTML()}</div></td>
    </tr>`;
  }

  function applySort(lista) {
    if (!sortCol) return lista;
    return [...lista].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      /* null (sin historial) siempre al final */
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'string') { va = va.toLowerCase(); vb = String(vb).toLowerCase(); }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  document.getElementById('b2b-thead').addEventListener('click', e => {
    const th = e.target.closest('.th-sortable');
    if (!th) return;
    const col = th.dataset.col;
    if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { sortCol = col; sortDir = 'asc'; }

    document.querySelectorAll('#b2b-thead .th-sortable').forEach(el => {
      const wrap = el.querySelector('.sort-icon-wrap');
      if (!wrap) return;
      wrap.innerHTML = el.dataset.col === sortCol
        ? `<img src="/static/img/${sortDir === 'asc' ? 'up' : 'down'}.png" class="sort-img" alt="" aria-hidden="true" width="13" height="13" decoding="async">`
        : '<i class="fa-solid fa-sort sort-icon"></i>';
    });
    renderClientes();
  });

  function renderClientes() {
    const q = searchQuery;
    const filtrados = q
      ? clientes.filter(c =>
          String(c.name || '').toLowerCase().includes(q) ||
          String(c.nit || '').toLowerCase().includes(q) ||
          String(c.phone || '').replace(/\s/g, '').includes(q.replace(/\s/g, ''))
        )
      : clientes;

    b2bCards.innerHTML = filtrados.map(buildClienteCard).join('');
    b2bBody.innerHTML = applySort(filtrados).map(buildClienteRow).join('');

    const vacio = filtrados.length === 0;
    b2bEmpty.classList.toggle('hidden', !vacio);
    b2bCards.classList.toggle('hidden', vacio);
    renderStats(filtrados);
  }

  [b2bCards, b2bBody].forEach(host => {
    host.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const row = btn.closest('[data-id]');
      if (!row) return;
      const cliente = clientes.find(c => c.id === parseInt(row.dataset.id, 10));
      if (!cliente) return;
      if (btn.dataset.action === 'ver') abrirDashboard(cliente);
      if (btn.dataset.action === 'editar') abrirModalCliente(cliente);
    });
  });

  /* ══════════════════════════════════════════════════════════
     DASHBOARD DEL CLIENTE
     ══════════════════════════════════════════════════════════ */
  async function abrirDashboard(cliente) {
    const data = await getJson(`/pos/api/b2b/clientes/${cliente.id}`);
    if (!data) return;
    if (!data.ok) { notify(data.msg || 'No se pudo cargar el cliente.', 'error'); return; }

    detalle = data.cliente;
    detalleNombre.textContent = detalle.name;

    const kpis = [
      ['Ticket promedio', money(detalle.ticket_promedio)],
      ['Pedidos', String(detalle.pedidos)],
      ['Frecuencia', frecuenciaTexto(detalle.frecuencia_dias)],
      ['Total comprado', money(detalle.comprado)],
      ['Deuda vigente', money(detalle.debt)],
      ['Sin comprar', detalle.dias_sin_comprar == null ? '—' : `${detalle.dias_sin_comprar} d`],
    ];
    detalleKpis.innerHTML = kpis.map(([label, valor]) => `
      <div class="fiad-kpi">
        <span class="fiad-kpi-label">${esc(label)}</span>
        <span class="fiad-kpi-value">${esc(valor)}</span>
      </div>`).join('');

    const top = detalle.top_productos || [];
    detalleTop.innerHTML = top.length
      ? top.map(p => `
        <li>
          <span class="fiad-toplist-name">${esc(p.nombre)}</span>
          <span class="fiad-toplist-meta">${money(p.importe)}
            <span class="fiad-toplist-units">${Number(p.unidades).toLocaleString('es-CO')} und</span>
          </span>
        </li>`).join('')
      : '<li class="fiad-toplist-empty">Todavia no hay compras registradas</li>';

    detalleLista.value = detalle.lista.id ? String(detalle.lista.id) : '';
    actualizarHintLista();
    openModal(modalDetalle);
  }

  function actualizarHintLista() {
    const id = detalleLista.value;
    const lista = listas.find(l => String(l.id) === id);
    if (!lista) {
      detalleHint.textContent = 'Sin descuento automatico: se cobra el precio normal.';
      return;
    }
    detalleHint.textContent = lista.min_pedidos > 0
      ? `-${Number(lista.descuento_pct)}% automatico desde el pedido ${Number(lista.min_pedidos)}.`
      : `-${Number(lista.descuento_pct)}% automatico en todos los pedidos.`;
  }

  detalleLista.addEventListener('change', actualizarHintLista);

  btnListaSave.addEventListener('click', async () => {
    if (!detalle) return;
    btnListaSave.disabled = true;
    const data = await putJson(`/pos/api/b2b/clientes/${detalle.id}/lista`, {
      id_lista: detalleLista.value || null,
    });
    btnListaSave.disabled = false;
    if (!data) return;
    if (!data.ok) { notify(data.msg || 'No se pudo asignar la lista.', 'error'); return; }
    await loadClientes();
    closeModal(modalDetalle);
    notify('Lista mayorista actualizada', 'success');
  });

  /* ══════════════════════════════════════════════════════════
     MODAL — CLIENTE B2B
     ══════════════════════════════════════════════════════════ */
  function renderSelectListas() {
    const opciones = '<option value="">Sin lista (precio normal)</option>'
      + listas.map(l => `<option value="${Number(l.id)}">${esc(l.nombre)} (-${Number(l.descuento_pct)}%)</option>`).join('');
    [b2bListaSel, detalleLista].forEach(sel => {
      const previo = sel.value;
      sel.innerHTML = opciones;
      sel.value = previo;
    });
  }

  function abrirModalCliente(cliente) {
    editandoCliente = cliente || null;
    document.getElementById('modal-b2b-title').textContent =
      cliente ? 'Editar Cliente B2B' : 'Nuevo Cliente B2B';
    b2bNombre.value = cliente ? cliente.name : '';
    b2bTelefono.value = cliente ? String(cliente.phone || '').replace(/\D/g, '') : '';
    b2bNit.value = cliente ? (cliente.nit || '') : '';
    b2bListaSel.value = cliente && cliente.lista.id ? String(cliente.lista.id) : '';
    hideBox(b2bError, b2bErrorText);
    openModal(modalB2b);
    b2bNombre.focus();
  }

  document.getElementById('btn-new-b2b').addEventListener('click', () => abrirModalCliente(null));

  b2bTelefono.addEventListener('input', () => {
    b2bTelefono.value = b2bTelefono.value.replace(/\D/g, '').slice(0, 25);
  });

  btnB2bConfirm.addEventListener('click', async () => {
    const nombre = b2bNombre.value.trim();
    const telefono = b2bTelefono.value.replace(/\D/g, '');

    if (!nombre) { showBox(b2bError, b2bErrorText, 'El nombre es requerido.'); shake(b2bNombre); return; }
    if (telefono.length < 7) {
      showBox(b2bError, b2bErrorText, 'El telefono debe tener al menos 7 digitos.');
      shake(b2bTelefono);
      return;
    }
    hideBox(b2bError, b2bErrorText);

    btnB2bConfirm.disabled = true;
    const data = await postJson('/pos/api/b2b/clientes', {
      id_cliente: editandoCliente ? editandoCliente.id : null,
      nombre,
      telefono,
      nit: b2bNit.value.trim(),
      id_lista: b2bListaSel.value || null,
    });
    btnB2bConfirm.disabled = false;
    if (!data) return;
    if (!data.ok) { showBox(b2bError, b2bErrorText, data.msg || 'No se pudo guardar.'); return; }

    await loadClientes();
    closeModal(modalB2b);
    notify(editandoCliente ? 'Cliente actualizado' : 'Cliente B2B creado', 'success');
  });

  /* ══════════════════════════════════════════════════════════
     LISTAS MAYORISTAS
     ══════════════════════════════════════════════════════════ */
  function accionesListaHTML() {
    return `
      <button class="fiad-action-btn btn-abonar" data-lista="editar" aria-label="Editar lista">
        <i class="fa-solid fa-pen"></i> Editar
      </button>
      <button class="fiad-action-btn btn-borrar" data-lista="eliminar" aria-label="Eliminar lista">
        <i class="fa-solid fa-trash-can"></i> Eliminar
      </button>`;
  }

  function desdeTexto(l) {
    return l.min_pedidos > 0 ? `Pedido ${Number(l.min_pedidos)}` : 'Primer pedido';
  }

  function buildListaCard(l) {
    return `
    <div class="fiad-card" data-lista-id="${Number(l.id)}">
      <div class="fiad-card-top">
        <div class="fiad-avatar fiad-avatar-cxp"><i class="fa-solid fa-tags"></i></div>
        <div class="fiad-card-info">
          <div class="fiad-card-name">${esc(l.nombre)}</div>
          <div class="fiad-card-phone">${esc(desdeTexto(l))} · ${Number(l.clientes || 0)} cliente(s)</div>
        </div>
        <div class="fiad-card-debt">
          <div class="fiad-debt-tag at-zero">-${Number(l.descuento_pct)}%</div>
        </div>
      </div>
      <div class="fiad-card-actions">${accionesListaHTML()}</div>
    </div>`;
  }

  function buildListaRow(l) {
    return `
    <tr data-lista-id="${Number(l.id)}">
      <td><div class="fiad-td-name">${esc(l.nombre)}</div></td>
      <td><span class="fiad-td-debt at-zero">-${Number(l.descuento_pct)}%</span></td>
      <td>${esc(desdeTexto(l))}</td>
      <td>${Number(l.clientes || 0)}</td>
      <td><div class="fiad-table-actions">${accionesListaHTML()}</div></td>
    </tr>`;
  }

  function renderListas() {
    const q = searchQuery;
    const filtradas = q
      ? listas.filter(l => String(l.nombre || '').toLowerCase().includes(q))
      : listas;

    listasCards.innerHTML = filtradas.map(buildListaCard).join('');
    listasBody.innerHTML = filtradas.map(buildListaRow).join('');

    const vacio = filtradas.length === 0;
    listasEmpty.classList.toggle('hidden', !vacio);
    listasCards.classList.toggle('hidden', vacio);
  }

  [listasCards, listasBody].forEach(host => {
    host.addEventListener('click', e => {
      const btn = e.target.closest('[data-lista]');
      if (!btn) return;
      const row = btn.closest('[data-lista-id]');
      if (!row) return;
      const lista = listas.find(l => l.id === parseInt(row.dataset.listaId, 10));
      if (!lista) return;
      if (btn.dataset.lista === 'editar') abrirModalLista(lista);
      if (btn.dataset.lista === 'eliminar') confirmarEliminarLista(lista);
    });
  });

  function abrirModalLista(lista) {
    editandoLista = lista || null;
    document.getElementById('modal-lista-title').textContent =
      lista ? 'Editar Lista Mayorista' : 'Nueva Lista Mayorista';
    listaNombre.value = lista ? lista.nombre : '';
    listaPct.value = lista ? lista.descuento_pct : '';
    listaMin.value = lista ? lista.min_pedidos : 0;
    hideBox(listaError, listaErrorText);
    openModal(modalLista);
    listaNombre.focus();
  }

  document.getElementById('btn-new-lista').addEventListener('click', () => abrirModalLista(null));

  btnListaConfirm.addEventListener('click', async () => {
    const nombre = listaNombre.value.trim();
    const pct = Number(listaPct.value);
    const min = listaMin.value === '' ? 0 : Number(listaMin.value);

    if (!nombre) { showBox(listaError, listaErrorText, 'El nombre es requerido.'); shake(listaNombre); return; }
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
      showBox(listaError, listaErrorText, 'El descuento debe ser un numero entre 0 y 100.');
      shake(listaPct);
      return;
    }
    if (!Number.isInteger(min) || min < 0 || min > 999) {
      showBox(listaError, listaErrorText, 'Los pedidos minimos deben ser un entero entre 0 y 999.');
      shake(listaMin);
      return;
    }
    hideBox(listaError, listaErrorText);

    const payload = { nombre, descuento_pct: pct, min_pedidos: min };
    btnListaConfirm.disabled = true;
    const data = editandoLista
      ? await putJson(`/pos/api/b2b/listas/${editandoLista.id}`, payload)
      : await postJson('/pos/api/b2b/listas', payload);
    btnListaConfirm.disabled = false;
    if (!data) return;
    if (!data.ok) { showBox(listaError, listaErrorText, data.msg || 'No se pudo guardar.'); return; }

    await loadClientes();
    closeModal(modalLista);
    notify(editandoLista ? 'Lista actualizada' : 'Lista creada', 'success');
  });

  function confirmarEliminarLista(lista) {
    confirmTarget.textContent = lista.nombre;
    confirmText.textContent = lista.clientes > 0
      ? `${Number(lista.clientes)} cliente(s) quedaran sin descuento mayorista. Las ventas ya cobradas no cambian.`
      : 'La lista deja de estar disponible. Las ventas ya cobradas no cambian.';
    document.getElementById('modal-confirm-title').textContent = 'Eliminar lista';
    pendingConfirm = async () => {
      const data = await sendJson('DELETE', `/pos/api/b2b/listas/${lista.id}`);
      if (!data) return;
      if (!data.ok) { notify(data.msg || 'No se pudo eliminar.', 'error'); return; }
      await loadClientes();
      notify('Lista eliminada', 'success');
    };
    openModal(modalConfirm);
  }

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

  /* ══════════════════════════════════════════════════════════
     MODALES
     ══════════════════════════════════════════════════════════ */
  function openModal(m) {
    m.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(m) {
    m.classList.add('hidden');
    document.body.style.overflow = '';
    if (m === modalDetalle) detalle = null;
    if (m === modalLista) editandoLista = null;
    if (m === modalB2b) editandoCliente = null;
    if (m === modalConfirm) pendingConfirm = null;
  }

  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const modal = document.getElementById(btn.dataset.close);
      if (modal) closeModal(modal);
    });
  });

  modales.forEach(m => {
    m.addEventListener('click', e => { if (e.target === m) closeModal(m); });
  });

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    modales.forEach(m => { if (!m.classList.contains('hidden')) closeModal(m); });
  });

  /* ── Arranque ────────────────────────────────────────────── */
  loadClientes();
});
