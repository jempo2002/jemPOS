// Ruta: static/js/gastos.js
// Pantalla: Control de Gastos y Compras
// Depende de: cop-format.js (cargado antes en el HTML)

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };

  let gastos  = [];
  let sortCol = null;
  let sortDir = 'asc';

  /* ── Carga inicial desde API ─────────────────────────────── */
  async function loadGastos() {
    const res = await fetch('/api/gastos');
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast('Error al cargar gastos.', 'error'); return; }
    gastos = data.gastos;
    renderAll();
  }
  loadGastos();

  /* ── Referencias DOM ─────────────────────────────────────── */
  const cardsEl     = document.getElementById('gast-cards');
  const tableBody   = document.getElementById('gast-table-body');
  const emptyEl     = document.getElementById('gast-empty');
  const statHoy     = document.getElementById('stat-hoy');
  const statMes     = document.getElementById('stat-mes');
  const toast       = document.getElementById('gast-toast');

  /* Modal */
  const modalGasto  = document.getElementById('modal-gasto');
  const gAmount     = document.getElementById('g-amount');
  const gCategory   = document.getElementById('g-category');
  const gCategoryDropdown = document.getElementById('g-category-dropdown');
  const gDesc       = document.getElementById('g-desc');
  const gMetodo     = document.getElementById('g-metodo');
  const gFuenteWrap = document.getElementById('g-fuente-wrap');
  const gFuente     = document.getElementById('g-fuente');
  const gOrigenBadge = document.getElementById('g-origen-badge');
  const btnConfirm  = document.getElementById('btn-gasto-confirm');
  const gastoForm   = document.getElementById('gasto-form');
  const modalErrorBox = document.getElementById('alerta-error-modal');
  const modalErrorText = document.getElementById('texto-alerta-modal');

  const gastoCategoryOptions = gCategoryDropdown
    ? Array.from(gCategoryDropdown.querySelectorAll('.gast-category-option')).map(el => el.dataset.value || '')
    : [];

  /* ── Bind COP en el input de monto ───────────────────────── */
  COP.bindInput(gAmount);

  /* ── Dropdown categorias personalizado ───────────────────── */
  function renderGastCategoryDropdown(filterValue = '') {
    if (!gCategoryDropdown) return;
    const q = filterValue.trim().toLowerCase();
    const filtered = gastoCategoryOptions.filter(opt => opt.toLowerCase().includes(q));
    if (!filtered.length) {
      gCategoryDropdown.innerHTML = '<div class="p-3" style="color:#94A3B8;">Sin coincidencias</div>';
      gCategoryDropdown.classList.remove('hidden');
      return;
    }
    gCategoryDropdown.innerHTML = filtered
      .map(opt => `<div class="hover:bg-slate-50 cursor-pointer p-3 gast-category-option" data-value="${esc(opt)}">${esc(opt)}</div>`)
      .join('');
    gCategoryDropdown.classList.remove('hidden');
  }

  function hideGastCategoryDropdown() {
    if (!gCategoryDropdown) return;
    gCategoryDropdown.classList.add('hidden');
  }

  if (gCategory && gCategoryDropdown) {
    gCategory.addEventListener('focus', () => renderGastCategoryDropdown(gCategory.value));
    gCategory.addEventListener('input', () => renderGastCategoryDropdown(gCategory.value));

    gCategoryDropdown.addEventListener('click', e => {
      const option = e.target.closest('.gast-category-option');
      if (!option) return;
      gCategory.value = option.dataset.value || option.textContent || '';
      hideGastCategoryDropdown();
    });

    document.addEventListener('click', e => {
      if (!e.target.closest('.gast-field .relative')) {
        hideGastCategoryDropdown();
      }
    });
  }

  /* ── Iconos por categoria ────────────────────────────────── */
  const CAT_ICON = {
    'Pago a Proveedores':    'fa-truck',
    'Nomina / Trabajadores': 'fa-user-tie',
    'Servicios / Arriendo':  'fa-file-invoice',
    'Otros':                 'fa-tag',
  };

  /* ── Renderizado inicial ───────────────────────────────────────── */
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
    document.querySelectorAll('#gast-thead .th-sortable').forEach(th => {
      const wrap = th.querySelector('.sort-icon-wrap');
      if (th.dataset.col === col) {
        const src = `/static/img/${dir === 'asc' ? 'up' : 'down'}.png`;
        wrap.innerHTML = `<img src="${src}" class="sort-img" alt="${dir}">`;
      } else {
        wrap.innerHTML = '<i class="fa-solid fa-sort sort-icon"></i>';
      }
    });
  }

  document.getElementById('gast-thead').addEventListener('click', e => {
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
     RENDERIZADO
     ══════════════════════════════════════════════════════════ */
  function renderAll() {
    /* Tarjetas movil: siempre mas recientes primero */
    const byDate = [...gastos].sort((a, b) => b.ts - a.ts);
    cardsEl.innerHTML = byDate.map(buildCardHTML).join('');

    /* Tabla desktop: aplica sort seleccionado, o por fecha por defecto */
    const tableData = applySort(byDate);
    tableBody.innerHTML = tableData.map(buildRowHTML).join('');

    const isEmpty = gastos.length === 0;
    emptyEl.classList.toggle('hidden', !isEmpty);
    cardsEl.classList.toggle('hidden', isEmpty);

    updateStats();
  }

  function updateStats() {
    const startOfDay = new Date(); startOfDay.setHours(0,0,0,0);
    const startOfMonth = new Date(); startOfMonth.setDate(1); startOfMonth.setHours(0,0,0,0);

    const totalHoy = gastos
      .filter(g => g.ts >= startOfDay.getTime())
      .reduce((s, g) => s + g.amount, 0);
    const totalMes = gastos
      .filter(g => g.ts >= startOfMonth.getTime())
      .reduce((s, g) => s + g.amount, 0);

    statHoy.textContent = `$${COP.format(totalHoy)}`;
    statMes.textContent = `$${COP.format(totalMes)}`;
  }

  /* ── HTML tarjeta (movil) ────────────────────────────────── */
  function buildCardHTML(g) {
    const icon = CAT_ICON[g.category] || 'fa-tag';
    const origenText = g.origen || 'Efectivo de la Caja';
    const origenClass = origenText.includes('Caja') ? 'efectivo' : 'banco';
    const origenIcon  = origenText.includes('Caja') ? 'fa-money-bill-wave' : 'fa-building-columns';
    const fecha = formatFecha(g.ts);
    return `
    <div class="gast-card">
      <div class="gast-card-icon"><i class="fa-solid ${icon}"></i></div>
      <div class="gast-card-info">
        <div class="gast-card-cat">${esc(g.category)}</div>
        <div class="gast-card-desc">${g.desc ? esc(g.desc) : '<span style="color:#94A3B8">Sin descripcion</span>'}</div>
        <div class="gast-card-meta">
          <span>${fecha}</span>
          <span class="gast-origen-pill ${origenClass}">
            <i class="fa-solid ${origenIcon}" style="font-size:.65rem;"></i>
            ${esc(origenText)}
          </span>
        </div>
      </div>
      <div class="gast-card-amount">−$${COP.format(g.amount)}</div>
    </div>`;
  }

  /* ── HTML fila de tabla (desktop) ──────────────────────── */
  function buildRowHTML(g) {
    const origenText = g.origen || 'Efectivo de la Caja';
    const origenClass = origenText.includes('Caja') ? 'efectivo' : 'banco';
    const fecha = formatFecha(g.ts);
    return `
    <tr>
      <td class="gast-td-fecha">${fecha}</td>
      <td class="gast-td-cat">${esc(g.category)}</td>
      <td class="gast-td-desc">${g.desc ? esc(g.desc) : '<span style="color:#94A3B8">—</span>'}</td>
      <td>
        <span class="gast-origen-pill ${origenClass}">${esc(origenText)}</span>
      </td>
      <td class="gast-td-monto">−$${COP.format(g.amount)}</td>
    </tr>`;
  }

  /* ── Formatea timestamp a texto ──────────────────────────── */
  function formatFecha(ts) {
    const d = new Date(ts);
    const ahora = new Date();
    const diffH = (ahora - d) / 3600000;

    if (diffH < 1)    return 'Hace un momento';
    if (diffH < 2)    return 'Hace 1 hora';
    if (diffH < 24)   return `Hace ${Math.floor(diffH)} h`;
    if (diffH < 48)   return 'Ayer';

    return d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short' });
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
     MODAL — ABRIR / CERRAR
     ══════════════════════════════════════════════════════════ */
  document.getElementById('btn-nuevo-gasto').addEventListener('click', () => {
    /* Limpiar campos */
    gAmount.value   = '';
    gCategory.value = '';
    gDesc.value     = '';
    gMetodo.value   = 'Efectivo';
    if (gFuente) gFuente.value = 'Caja Menor';
    gFuenteWrap.classList.remove('hidden');
    gOrigenBadge.className = 'gast-origen-badge hidden';
    gOrigenBadge.textContent = '';
    hideModalError();
    renderFuenteEstado();
    openModal(modalGasto);
    setTimeout(() => gAmount.focus(), 80);
  });

  function renderFuenteEstado() {
    const metodo = gMetodo.value;
    if (metodo === 'Efectivo') {
      gFuenteWrap.classList.remove('hidden');
      const val = gFuente.value || 'Caja Menor';
      gOrigenBadge.className = 'gast-origen-badge efectivo';
      gOrigenBadge.innerHTML = `<i class="fa-solid fa-money-bill-wave"></i> Se descuenta de ${esc(val)}`;
      return;
    }
    gFuenteWrap.classList.add('hidden');
    gOrigenBadge.className = 'gast-origen-badge banco';
    gOrigenBadge.innerHTML = '<i class="fa-solid fa-building-columns"></i> Saldra de Bancos / Nequi';
  }
  gMetodo.addEventListener('change', renderFuenteEstado);
  if (gFuente) gFuente.addEventListener('change', renderFuenteEstado);

  /* Confirmar gasto (submit del form) */
  gastoForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const amount   = COP.parse(gAmount.value);
    const category = gCategory.value;
    const metodoPago = gMetodo.value;
    const fuenteDinero = metodoPago === 'Efectivo' ? (gFuente.value || 'Caja Menor') : 'Bancos';
    const desc     = gDesc.value.trim();

    if (amount <= 0)  { showModalError('El monto debe ser mayor a 0.'); shake(gAmount); return; }
    if (!category)    { showModalError('La categoria es requerida.'); shake(gCategory);  return; }
    if (metodoPago === 'Efectivo' && !fuenteDinero) { showModalError('Selecciona la fuente del dinero.'); shake(gFuente); return; }
    hideModalError();

    btnConfirm.disabled = true;
    const res = await fetch('/api/gastos', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({
        amount,
        category,
        desc,
        metodo_pago: metodoPago,
        fuente_dinero: fuenteDinero,
      }),
    });
    btnConfirm.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      showModalError('No se pudo procesar la respuesta del servidor.');
      return;
    }
    if (!res.ok || !data.ok) { showModalError(data.error || data.msg || 'Error al registrar gasto.'); return; }

    closeModal(modalGasto);
    await loadGastos();
    showToast(`Gasto de $${COP.format(amount)} registrado`, 'error');
  });

  /* Cierre generico por data-close */
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const el = document.getElementById(btn.dataset.close);
      if (el) closeModal(el);
    });
  });

  /* Clic fuera del card */
  modalGasto.addEventListener('click', e => {
    if (e.target === modalGasto) closeModal(modalGasto);
  });

  renderFuenteEstado();

  /* Escape */
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !modalGasto.classList.contains('hidden')) {
      closeModal(modalGasto);
    }
  });

  /* ── Helpers de modal ────────────────────────────────────── */
  function openModal(m) {
    m.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(m) {
    m.classList.add('hidden');
    document.body.style.overflow = '';
    hideGastCategoryDropdown();
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
    toast.className   = `gast-toast ${type}`;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.className = 'gast-toast hidden';
    }, 3200);
  }

  /* ── Shake (validacion) ──────────────────────────────────── */
  function shake(el) {
    el.style.transition = 'transform 0.05s';
    const steps = [5, -5, 5, -5, 0];
    steps.forEach((x, i) => {
      setTimeout(() => {
        el.style.transform = `translateX(${x}px)`;
        if (x === 0) el.style.transform = '';
      }, i * 50);
    });
    el.focus();
  }

});
