/* ============================================================
   Ruta: static/js/inventario.js
   Pantalla: Inventario de Productos
   Depende de: cop-format.js, barcode-scanner.js (cargados antes)
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  function jsonHeaders() {
    return csrfToken
      ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
      : { 'Content-Type': 'application/json' };
  }

  let products    = [];
  let proveedores = [];
  let editingId   = null;
  let searchQuery  = '';
  let sortCol      = null;
  let sortDir      = 'asc';
  /* Pestana activa: 'Producto' o 'Servicio'. Filtra la lista y decide el
     tipo de lo que se crea con el boton Anadir. */
  let activeTipo   = 'Producto';

  /* ── Referencias DOM ─────────────────────────────────────── */
  const cardsList      = document.getElementById('cards-list');
  const tableBody      = document.getElementById('table-body');
  const searchInput    = document.getElementById('inv-search');
  const modal          = document.getElementById('modal');
  const modalTitle     = document.getElementById('modal-title');
  const btnAdd         = document.getElementById('btn-add');
  const btnModalClose  = document.getElementById('modal-close');
  const btnModalCancel = document.getElementById('btn-modal-cancel');
  const btnModalSave   = document.getElementById('btn-modal-save');
  const toast          = document.getElementById('inv-toast');

  /* Modal de anadir stock */
  const modalStock        = document.getElementById('modal-stock');
  const stockProductName  = document.getElementById('s-product-name');
  const stockCurrentBadge = document.getElementById('s-current-stock');
  const stockUnits        = document.getElementById('s-units');
  const stockPreview      = document.getElementById('s-preview');
  const btnStockClose     = document.getElementById('stock-modal-close');
  const btnStockCancel    = document.getElementById('btn-stock-cancel');
  const btnStockConfirm   = document.getElementById('btn-stock-confirm');
  let   stockTargetId     = null;

  /* Modal confirmar eliminacion */
  const modalConfirm       = document.getElementById('modal-confirm');
  const confirmProductName = document.getElementById('confirm-product-name');
  const btnConfirmCancel   = document.getElementById('btn-confirm-cancel');
  const btnConfirmClose    = document.getElementById('confirm-modal-close');
  const btnConfirmDelete   = document.getElementById('btn-confirm-delete');
  let   deleteTargetId     = null;

  /* Campos del modal */
  const fName     = document.getElementById('f-name');
  const fBarcode  = document.getElementById('f-barcode');
  const fCategory = document.getElementById('f-category');
  const fCategoryDropdown = document.getElementById('f-category-dropdown');
  const fCost     = document.getElementById('f-cost');
  const fSale     = document.getElementById('f-sale');
  const fSaleLock = document.getElementById('f-sale-lock');
  /* El Cajero puede editar un producto pero no su precio de venta. Es solo
     la cara visible: el backend rechaza el cambio igual (403). */
  const esCajero  = (document.getElementById('app-context')?.dataset.userRol || '').toLowerCase() === 'cajero';
  const fStock    = document.getElementById('f-stock');
  const fStockMin = document.getElementById('f-stock-min');
  const fProvider = document.getElementById('f-provider');
  const fUnidad   = document.getElementById('f-unidad');
  const fUnidadHelp = document.getElementById('f-unidad-help');
  const fMayorista = document.getElementById('f-mayorista');
  const fEmpaque  = document.getElementById('f-empaque');
  const fEmpaqueCant = document.getElementById('f-empaque-cant');
  const fEmpaquePrecio = document.getElementById('f-empaque-precio');
  const stockRow  = document.getElementById('stock-row');
  const empaqueField = document.getElementById('empaque-field');
  const providerField = document.getElementById('provider-field');
  const btnAddLabel = btnAdd.querySelector('.fab-label');
  const stockUnitLabel = document.getElementById('s-unit-label');
  let fraccionables = [];
  try { fraccionables = JSON.parse(fUnidad.dataset.fraccionables || '[]'); } catch (_) { fraccionables = []; }
  const esFraccionable = (unidad) => fraccionables.includes(unidad);
  const fProfit   = document.getElementById('f-profit');
  const modalErrorBox = document.getElementById('alerta-error-modal');
  const modalErrorText = document.getElementById('texto-alerta-modal');
  const fPrepared = document.getElementById('f-prepared');
  const stockField = document.getElementById('stock-field');
  const costField = document.getElementById('cost-field');
  const recipeBuilder = document.getElementById('recipe-builder');
  const recipeRows = document.getElementById('recipe-rows');
  const btnAddIngredient = document.getElementById('btn-add-ingredient');
  const recipeTotalHelp = document.getElementById('recipe-total-help');

  let insumosData = [];
  try {
    const node = document.getElementById('insumos-json');
    insumosData = node ? JSON.parse(node.textContent || '[]') : [];
  } catch (_) {
    insumosData = [];
  }

  const categoryOptions = fCategoryDropdown
    ? Array.from(fCategoryDropdown.querySelectorAll('.inv-category-option')).map(el => el.dataset.value || '')
    : [];

  /* ── Carga inicial desde API ─────────────────────────────── */
  async function loadProducts() {
    const res = await fetch('/inventario/api/productos');
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast('Error al cargar productos.', true); return; }
    products = data.productos;
    renderAll();
  }
  loadProducts();

  async function loadProveedores() {
    if (!fProvider) return;
    const res = await fetch('/inventario/api/proveedores');
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok || !Array.isArray(data.proveedores)) return;
    proveedores = data.proveedores;
    const current = fProvider.value;
    fProvider.innerHTML = '<option value="">Sin proveedor</option>' + proveedores
      .map((p) => `<option value="${p.id}">${esc(p.empresa)}</option>`)
      .join('');
    fProvider.value = current || '';
  }
  loadProveedores();

  /* ── Busqueda ──────────────────────────────────────────── */
  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    renderAll();
  });

  /* ── Pestanas Productos / Servicios ─────────────────────── */
  document.querySelectorAll('.inv-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      activeTipo = tab.dataset.tab === 'servicios' ? 'Servicio' : 'Producto';
      document.querySelectorAll('.inv-tab').forEach((t) => {
        t.classList.toggle('is-active', t === tab);
        t.setAttribute('aria-selected', String(t === tab));
      });
      if (btnAddLabel) btnAddLabel.textContent = activeTipo === 'Servicio' ? 'Anadir servicio' : 'Anadir producto';
      renderAll();
    });
  });

  /* Unidad: rotula precios/stock ("por Metro") y dice si admite fracciones */
  function updateUnidadUI() {
    const unidad = fUnidad.value || 'Unidad';
    document.querySelectorAll('#modal [data-unidad-label]').forEach((el) => {
      el.textContent = `(por ${unidad})`;
    });
    const fracc = esFraccionable(unidad);
    fUnidadHelp.textContent = fracc
      ? `Se puede vender por fracciones, ej. 0.5 ${unidad}.`
      : `Se vende por ${unidad} completa.`;
    fStock.step = fracc ? 'any' : '1';
    if (fStockMin) fStockMin.step = fracc ? 'any' : '1';
  }
  fUnidad.addEventListener('change', updateUnidadUI);

  /* ── Escaner: buscar por codigo; si no existe, ofrecer crearlo ── */
  document.getElementById('inv-btn-scan').addEventListener('click', () => {
    BarcodeScanner.open((code) => {
      searchInput.value = code;
      searchQuery = code.toLowerCase();
      renderAll();
      if (products.some((p) => p.barcode === code)) return;
      openModal(null);
      fBarcode.value = code;
      showToast(`El código ${code} no está registrado. Completa los datos para añadirlo.`, true);
    });
  });

  document.getElementById('f-barcode-scan').addEventListener('click', () => {
    BarcodeScanner.open((code) => {
      fBarcode.value = code;
    });
  });

  /* ── Abrir modal (nuevo producto) ───────────────────────── */
  btnAdd.addEventListener('click', () => openModal(null));

  /* ── Cerrar modal ────────────────────────────────────────── */
  btnModalClose.addEventListener('click',  closeModal);
  btnModalCancel.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  /* ── Calculo de ganancia en tiempo real ─────────────────── */
  [fCost, fSale].forEach(el => el.addEventListener('input', updateProfit));
  fPrepared?.addEventListener('change', toggleRecipeMode);
  btnAddIngredient?.addEventListener('click', () => {
    addRecipeRow();
    updateRecipeCost();
  });

  /* ── Dropdown categorias personalizado ──────────────────── */
  function renderCategoryDropdown(filterValue = '') {
    if (!fCategoryDropdown) return;
    const q = filterValue.trim().toLowerCase();
    const filtered = categoryOptions.filter(opt => opt.toLowerCase().includes(q));
    if (!filtered.length) {
      fCategoryDropdown.innerHTML = '<div class="p-3" style="color:#57667A;">Sin coincidencias</div>';
      fCategoryDropdown.classList.remove('hidden');
      return;
    }
    fCategoryDropdown.innerHTML = filtered
      .map(opt => `<div class="hover:bg-slate-50 cursor-pointer p-3 inv-category-option" data-value="${esc(opt)}">${esc(opt)}</div>`)
      .join('');
    fCategoryDropdown.classList.remove('hidden');
  }

  function hideCategoryDropdown() {
    if (!fCategoryDropdown) return;
    fCategoryDropdown.classList.add('hidden');
  }

  if (fCategory && fCategoryDropdown) {
    fCategory.addEventListener('focus', () => renderCategoryDropdown(fCategory.value));
    fCategory.addEventListener('input', () => renderCategoryDropdown(fCategory.value));

    fCategoryDropdown.addEventListener('click', (e) => {
      const option = e.target.closest('.inv-category-option');
      if (!option) return;
      fCategory.value = option.dataset.value || option.textContent || '';
      hideCategoryDropdown();
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('.modal-field .relative')) {
        hideCategoryDropdown();
      }
    });
  }

  /* ── Guardar producto ────────────────────────────────────── */
  btnModalSave.addEventListener('click', saveProduct);

  /* ── Modal anadir stock ───────────────────────────────── */
  /* Cantidad escrita a mano: admite coma o punto decimal ("2,5" = 2.5). */
  function parseCantidad(value) {
    const n = parseFloat(String(value).trim().replace(',', '.'));
    return Number.isFinite(n) ? Math.round(n * 1000) / 1000 : NaN;
  }

  function openModalStock(id) {
    const p = products.find(x => x.id === id);
    stockTargetId = id;
    stockProductName.textContent  = p.name;
    stockCurrentBadge.textContent = `${formatStock(p.stock)} ${p.unidad} actuales`;
    if (stockUnitLabel) stockUnitLabel.textContent = `(${p.unidad})`;
    stockUnits.value   = '';
    stockPreview.textContent = '';
    modalStock.classList.add('open');
    setTimeout(() => stockUnits.focus(), 80);
  }

  function closeModalStock() {
    modalStock.classList.remove('open');
    stockTargetId = null;
  }

  stockUnits.addEventListener('input', () => {
    const p = products.find(x => x.id === stockTargetId);
    const qty = parseCantidad(stockUnits.value);
    if (!p || isNaN(qty) || qty <= 0) { stockPreview.textContent = ''; return; }
    stockPreview.textContent = `→ Nuevo stock: ${formatStock(p.stock + qty)} ${p.unidad}`;
  });

  btnStockConfirm.addEventListener('click', async () => {
    const qty = parseCantidad(stockUnits.value);
    if (isNaN(qty) || qty <= 0) { shake(stockUnits); return; }
    btnStockConfirm.disabled = true;
    const res  = await fetch(`/inventario/api/productos/${stockTargetId}/stock`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ cantidad: qty }),
    });
    btnStockConfirm.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast(data.msg || 'Error al anadir stock.', true); return; }
    const p = products.find(x => x.id === stockTargetId);
    closeModalStock();
    await loadProducts();
    showToast(`+${formatStock(qty)} ${p ? p.unidad : ''} anadidas a "${p ? p.name : ''}".`);
  });

  [btnStockClose, btnStockCancel].forEach(b => b.addEventListener('click', closeModalStock));
  modalStock.addEventListener('click', e => { if (e.target === modalStock) closeModalStock(); });

  function shake(el) {
    el.style.transition = 'transform 0.05s';
    [4, -4, 4, -4, 0].forEach((x, i) =>
      setTimeout(() => { el.style.transform = x ? `translateX(${x}px)` : ''; }, i * 50)
    );
    el.focus();
  }
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
    document.querySelectorAll('#inv-thead .th-sortable').forEach(th => {
      const wrap = th.querySelector('.sort-icon-wrap');
      if (th.dataset.col === col) {
        const src = `/static/img/${dir === 'asc' ? 'up' : 'down'}.png`;
        wrap.innerHTML = `<img src="${src}" class="sort-img" alt="" aria-hidden="true" width="13" height="13" decoding="async">`;
      } else {
        wrap.innerHTML = '<i class="fa-solid fa-sort sort-icon"></i>';
      }
    });
  }

  document.getElementById('inv-thead').addEventListener('click', e => {
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
     RENDER
     ══════════════════════════════════════════════════════════ */

  function renderAll() {
    const filtered = products.filter(p => p.tipo === activeTipo && (
      p.name.toLowerCase().includes(searchQuery) ||
      p.category.toLowerCase().includes(searchQuery) ||
      (p.barcode || '').toLowerCase().includes(searchQuery)
    ));
    const display = applySort(filtered);
    renderCards(display);
    renderTable(display);
  }

  /** Renderiza la lista de tarjetas (movil). */
  function renderCards(list) {
    cardsList.innerHTML = '';

    if (list.length === 0) {
      cardsList.innerHTML = `
        <div class="inv-empty-state">
          <i class="fa-solid fa-box-open"></i>
          <p>Sin resultados</p>
        </div>`;
      return;
    }

    list.forEach(p => {
      const div = document.createElement('div');
      div.className = 'product-card';
      div.dataset.id = p.id;
      div.innerHTML = buildCardHTML(p);
      cardsList.appendChild(div);
    });

    bindCardEvents();
  }

  /** Renderiza la tabla (desktop). */
  function renderTable(list) {
    tableBody.innerHTML = '';

    if (list.length === 0) {
      tableBody.innerHTML = `
        <tr class="no-results">
          <td colspan="7">No se encontraron ${activeTipo === 'Servicio' ? 'servicios' : 'productos'}.</td>
        </tr>`;
      return;
    }

    list.forEach(p => {
      const tr = document.createElement('tr');
      tr.dataset.id = p.id;
      tr.innerHTML = buildRowHTML(p);
      tableBody.appendChild(tr);
    });

    bindTableEvents();
  }

  /* ── Constructores de HTML ──────────────────────────────── */

  /* Badge de stock o, sin stock que contar, que clase de item es. */
  function stockCell(p) {
    if (p.tipo === 'Servicio') return '<span class="stock-badge ok"><span class="stock-dot"></span>Servicio</span>';
    if (p.es_preparado) return '<span class="stock-badge ok"><span class="stock-dot"></span>Receta preparada</span>';
    const { cls, label } = stockInfo(p.stock, p.unidad);
    return stockBadge(p.stock, cls, label);
  }

  function precioMayorista(p) {
    return p.mayorista ? `$${COP.format(p.mayorista)}` : '—';
  }

  /* "Rollo x100: $90.000" bajo el precio unitario, si se vende por empaque */
  function empaqueTexto(p) {
    return p.empaque_nombre
      ? `${esc(p.empaque_nombre)} x${formatStock(p.empaque_cantidad)}: $${COP.format(p.precio_empaque)}`
      : '';
  }

  function buildCardHTML(p) {
    const stockAction = stockCell(p);
    const addStockButton = (p.es_preparado || p.tipo === 'Servicio')
      ? ''
      : `<button class="action-btn add" data-action="addstock" aria-label="Anadir stock">
            <img src="/static/img/mas.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>`;
    return `
      <div class="card-top">
        <div class="card-info">
          <div class="card-name">${esc(p.name)}</div>
          <div class="card-category">${esc(p.category)}</div>
        </div>
        <div class="card-actions">
          <button class="action-btn edit" data-action="edit" aria-label="Editar">
            <img src="/static/img/editar.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>
          ${addStockButton}
          <button class="action-btn del" data-action="del" aria-label="Eliminar">
            <img src="/static/img/basura.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>
        </div>
      </div>
      <div class="card-bottom">
        <div class="card-prices">
          <span class="card-price-label">Venta / ${esc(p.unidad)}</span>
          <span class="card-price-value">$${COP.format(p.sale)}</span>
          ${p.mayorista ? `<span class="td-unit card-price-mayor">Mayorista ${precioMayorista(p)}</span>` : ''}
          ${p.empaque_nombre ? `<span class="td-unit">${empaqueTexto(p)}</span>` : ''}
        </div>
        <div class="card-prices card-prices-right">
          <span class="card-price-label">Costo</span>
          <span class="card-price-value card-price-cost">$${COP.format(p.cost)}</span>
        </div>
        ${stockAction}
      </div>`;
  }

  function buildRowHTML(p) {
    const stockAction = stockCell(p);
    const addStockButton = (p.es_preparado || p.tipo === 'Servicio')
      ? ''
      : `<button class="action-btn add" data-action="addstock" aria-label="Anadir stock">
            <img src="/static/img/mas.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>`;
    return `
      <td>
        <div class="td-name">
          <span class="td-name-text">${esc(p.name)}</span>
        </div>
      </td>
      <td class="td-category">${esc(p.category)}</td>
      <td class="td-price">$${COP.format(p.cost)}</td>
      <td class="td-price">$${COP.format(p.sale)}<span class="td-unit">por ${esc(p.unidad)}${p.empaque_nombre ? ' · ' + empaqueTexto(p) : ''}</span></td>
      <td class="td-price card-price-mayor">${precioMayorista(p)}</td>
      <td>${stockAction}</td>
      <td>
        <div class="td-actions">
          <button class="action-btn edit" data-action="edit" aria-label="Editar">
            <img src="/static/img/editar.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>
          ${addStockButton}
          <button class="action-btn del" data-action="del" aria-label="Eliminar">
            <img src="/static/img/basura.png" alt="" aria-hidden="true" width="18" height="18" decoding="async" />
          </button>
        </div>
      </td>`;
  }

  /* ── Helpers de stock ───────────────────────────────────── */

  /**
   * Formatea un numero de stock eliminando ceros decimales innecesarios.
   * Ej: 9.000 → "9",  9.500 → "9.5",  9 → "9"
   */
  function formatStock(n) {
    const num = Number(n);
    if (!isFinite(num)) return String(n);
    return parseFloat(num.toFixed(3)).toString();
  }

  function stockInfo(qty, unidad = 'Unidad') {
    const txt = `${formatStock(qty)} ${unidad === 'Unidad' ? 'unidades' : unidad}`;
    if (qty <= 0)   return { cls: 'out', label: 'Agotado' };
    if (qty <= 10)  return { cls: 'low', label: txt };
    return { cls: 'ok', label: txt };
  }

  function stockBadge(qty, cls, label) {
    return `<span class="stock-badge ${cls}"><span class="stock-dot"></span>${label}</span>`;
  }

  /* ── Eventos de tarjetas y tabla ────────────────────────── */

  function bindCardEvents() {
    cardsList.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', handleAction);
    });
  }

  function bindTableEvents() {
    tableBody.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', handleAction);
    });
  }

  function handleAction(e) {
    const btn  = e.currentTarget;
    const row  = btn.closest('[data-id]');
    const id   = Number(row.dataset.id);
    const action = btn.dataset.action;

    if (action === 'edit')     openModal(id);
    if (action === 'addstock') openModalStock(id);
    if (action === 'del')      deleteProduct(id);
  }

  /* ══════════════════════════════════════════════════════════
     MODAL
     ══════════════════════════════════════════════════════════ */

  /* Tipo del item abierto en el modal: el del producto al editar, el de la
     pestana al crear. */
  let modalTipo = 'Producto';

  function openModal(id) {
    editingId = id;
    hideModalError();
    /* Precios del Cajero: se ven pero no se editan (el backend responde 403
       si llegan distintos). Mayorista y empaque viajan tal cual se cargaron. */
    const lockPrices = id !== null && esCajero;

    if (id !== null) {
      const p = products.find(x => x.id === id);
      modalTipo = p.tipo;
      modalTitle.textContent  = p.tipo === 'Servicio' ? 'Editar Servicio' : 'Editar Producto';
      fName.value             = p.name;
      fBarcode.value          = p.barcode || '';
      fCategory.value         = p.category;
      fCost.value             = COP.format(p.cost);
      fSale.value             = COP.format(p.sale);
      fStock.value            = formatStock(p.stock);
      if (fStockMin) fStockMin.value = (p.stock_min != null ? formatStock(p.stock_min) : '');
      fProvider.value         = p.proveedor_id ? String(p.proveedor_id) : '';
      fUnidad.value           = p.unidad || 'Unidad';
      fMayorista.value        = p.mayorista ? COP.format(p.mayorista) : '';
      fEmpaque.value          = p.empaque_nombre || '';
      fEmpaqueCant.value      = p.empaque_cantidad ? formatStock(p.empaque_cantidad) : '';
      fEmpaquePrecio.value    = p.precio_empaque ? COP.format(p.precio_empaque) : '';
      fCost.dataset.rawValue  = String(p.cost);
      fSale.dataset.rawValue  = String(p.sale);
      if (fPrepared) fPrepared.checked = Boolean(p.es_preparado);
      clearRecipeRows();
      updateProfit();
      fSale.disabled = esCajero;
      if (fSaleLock) fSaleLock.hidden = !esCajero;
    } else {
      modalTipo = activeTipo;
      fSale.disabled = false;
      if (fSaleLock) fSaleLock.hidden = true;
      modalTitle.textContent = activeTipo === 'Servicio' ? 'Anadir Servicio' : 'Anadir Producto';
      [fName, fBarcode, fCategory, fCost, fSale, fStock, fMayorista, fEmpaque, fEmpaqueCant, fEmpaquePrecio]
        .forEach(f => f.value = '');
      if (fStockMin) fStockMin.value = '';
      if (fProvider) fProvider.value = '';
      fUnidad.value = 'Unidad';
      if (fPrepared) fPrepared.checked = false;
      fCost.dataset.rawValue = '';
      fSale.dataset.rawValue = '';
      fProfit.textContent = '—';
      clearRecipeRows();
    }

    fMayorista.disabled = lockPrices;
    fEmpaquePrecio.disabled = lockPrices;
    /* Un servicio no tiene stock, ni empaque, ni proveedor de mercancia. */
    const esServicio = modalTipo === 'Servicio';
    [stockRow, empaqueField, providerField].forEach((el) => el?.classList.toggle('hidden', esServicio));
    fName.placeholder = esServicio ? 'Ej. Instalacion de cable' : 'Ej. Coca-Cola 350ml';
    updateUnidadUI();

    toggleRecipeMode();

    modal.classList.add('open');
    setTimeout(() => fName.focus(), 80);
  }

  function closeModal() {
    modal.classList.remove('open');
    hideCategoryDropdown();
    editingId = null;
    if (recipeTotalHelp) recipeTotalHelp.textContent = '';
    hideModalError();
  }

  async function saveProduct() {
    const name  = fName.value.trim();
    const cat   = fCategory.value.trim();
    let cost  = COP.parse(fCost.value);
    const sale  = COP.parse(fSale.value);
    const esServicio = modalTipo === 'Servicio';
    let stock = esServicio ? 0 : parseCantidad(fStock.value);
    const stockMinRaw = fStockMin ? String(fStockMin.value).trim() : '';
    const stockMin = esServicio || stockMinRaw === '' ? 0 : parseCantidad(stockMinRaw);
    const idProveedor = !esServicio && fProvider && fProvider.value ? parseInt(fProvider.value, 10) : null;
    const unidad = fUnidad.value || 'Unidad';
    if (!esServicio && !esFraccionable(unidad) && stock !== Math.trunc(stock)) {
      showModalError(`El stock en ${unidad} debe ser un numero entero.`);
      return;
    }
    const isPrepared = Boolean(fPrepared?.checked);
    const ingredientes = isPrepared ? collectRecipeRows() : [];

    if (isPrepared) {
      if (!ingredientes.length) {
        showModalError('Agrega ingredientes para la receta.');
        return;
      }
      cost = getRecipeTotal();
      stock = 0;
    }

    if (!name || !cat || isNaN(cost) || isNaN(sale) || isNaN(stock) || isNaN(stockMin)) {
      showModalError('Completa todos los campos correctamente.');
      return;
    }
    /* Empaque: los tres campos o ninguno (el servidor lo revalida). */
    const empaque = esServicio ? '' : fEmpaque.value.trim();
    const empaqueCant = esServicio ? NaN : parseCantidad(fEmpaqueCant.value);
    const empaquePrecio = esServicio ? NaN : COP.parse(fEmpaquePrecio.value);
    const conEmpaque = Boolean(empaque) || !isNaN(empaqueCant) || !isNaN(empaquePrecio);
    if (conEmpaque && !(empaque && empaqueCant > 0 && empaquePrecio > 0)) {
      showModalError('Para vender por empaque indica nombre, unidades y precio del empaque.');
      return;
    }
    const mayorista = COP.parse(fMayorista.value);
    hideModalError();

    btnModalSave.disabled = true;
    const url    = editingId !== null ? `/inventario/api/productos/${editingId}` : '/inventario/api/productos';
    const method = editingId !== null ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: jsonHeaders(),
      body: JSON.stringify({
        nombre: name,
        codigo_barras: fBarcode.value.trim(),
        categoria: cat,
        costo: cost,
        venta: fSale.disabled ? undefined : sale,   /* bloqueado: el servidor conserva el actual */
        tipo: modalTipo,
        unidad,
        mayorista: isNaN(mayorista) ? null : mayorista,
        empaque_nombre: conEmpaque ? empaque : null,
        empaque_cantidad: conEmpaque ? empaqueCant : null,
        precio_empaque: conEmpaque ? empaquePrecio : null,
        stock,
        stock_min: stockMin,
        es_preparado: isPrepared,
        ingredientes,
        id_proveedor: Number.isInteger(idProveedor) ? idProveedor : null,
      }),
    });
    btnModalSave.disabled = false;
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showModalError(data.error || data.msg || 'Error al guardar.');
      return;
    }

    closeModal();
    await loadProducts();
    showToast(editingId !== null ? `"${name}" actualizado.` : `"${name}" anadido al inventario.`);
  }

  function deleteProduct(id) {
    const p = products.find(x => x.id === id);
    if (!p) return;
    deleteTargetId = id;
    confirmProductName.textContent = p.name;
    modalConfirm.classList.add('open');
  }

  function closeModalConfirm() {
    modalConfirm.classList.remove('open');
    deleteTargetId = null;
  }

  btnConfirmDelete.addEventListener('click', async () => {
    const id = deleteTargetId;
    const p  = products.find(x => x.id === id);
    closeModalConfirm();
    const res = await fetch(`/inventario/api/productos/${id}`, {
      method: 'DELETE',
      headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!data.ok) { showToast(data.msg || 'Error al eliminar.', true); return; }
    await loadProducts();
    showToast(`"${p ? p.name : 'Producto'}" eliminado.`);
  });

  [btnConfirmCancel, btnConfirmClose].forEach(b => b.addEventListener('click', closeModalConfirm));
  modalConfirm.addEventListener('click', e => { if (e.target === modalConfirm) closeModalConfirm(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modalConfirm.classList.contains('open')) closeModalConfirm();
  });

  /* ── Ganancia dinamica en el modal ──────────────────────── */
  function updateProfit() {
    const cost = COP.parse(fCost.value);
    const sale = COP.parse(fSale.value);
    if (isNaN(cost) || isNaN(sale)) { fProfit.textContent = '—'; return; }
    const diff = sale - cost;
    fProfit.textContent = diff >= 0
      ? `+$${COP.format(diff)}`
      : `-$${COP.format(Math.abs(diff))}`;
    fProfit.style.color = diff >= 0 ? '#10B981' : '#EF4444';
  }

  function toggleRecipeMode() {
    const prepared = Boolean(fPrepared?.checked);
    if (stockField) stockField.classList.toggle('hidden', prepared);
    if (costField) costField.classList.toggle('hidden', prepared);
    if (recipeBuilder) recipeBuilder.classList.toggle('hidden', !prepared);

    if (prepared) {
      fStock.value = '0';
      if (!recipeRows?.children.length) addRecipeRow();
      updateRecipeCost();
      return;
    }

    if (recipeTotalHelp) recipeTotalHelp.textContent = '';
    updateProfit();
  }

  function ingredientOptions(selectedId = '') {
    return insumosData.map((insumo) => {
      const selected = String(insumo.id_insumo) === String(selectedId) ? 'selected' : '';
      return `<option value="${insumo.id_insumo}" data-costo="${Number(insumo.costo_unitario || 0)}" ${selected}>${esc(insumo.nombre || 'Insumo')}</option>`;
    }).join('');
  }

  function addRecipeRow(item = null) {
    if (!recipeRows) return;
    const idInsumo = item?.id_insumo || '';
    const cantidad = item?.cantidad || '';

    const row = document.createElement('div');
    row.className = 'recipe-row';
    row.innerHTML = `
      <select name="id_insumo[]">
        <option value="">Selecciona insumo</option>
        ${ingredientOptions(idInsumo)}
      </select>
      <input type="number" name="cantidad_insumo[]" step="any" min="0" placeholder="Cantidad" value="${cantidad}" />
      <button type="button" class="recipe-remove" aria-label="Eliminar ingrediente">x</button>
    `;

    const select = row.querySelector('select[name="id_insumo[]"]');
    const input = row.querySelector('input[name="cantidad_insumo[]"]');
    const remove = row.querySelector('.recipe-remove');

    select?.addEventListener('change', updateRecipeCost);
    input?.addEventListener('input', updateRecipeCost);
    remove?.addEventListener('click', () => {
      row.remove();
      if (!recipeRows.children.length) addRecipeRow();
      updateRecipeCost();
    });

    recipeRows.appendChild(row);
  }

  function clearRecipeRows() {
    if (recipeRows) recipeRows.innerHTML = '';
  }

  function collectRecipeRows() {
    if (!recipeRows) return [];
    return Array.from(recipeRows.querySelectorAll('.recipe-row')).map((row) => {
      const select = row.querySelector('select[name="id_insumo[]"]');
      const input = row.querySelector('input[name="cantidad_insumo[]"]');
      return {
        id_insumo: Number(select?.value || 0),
        cantidad: Number(input?.value || 0),
      };
    }).filter((x) => x.id_insumo > 0 && x.cantidad > 0);
  }

  function getRecipeTotal() {
    if (!recipeRows) return 0;
    let total = 0;
    recipeRows.querySelectorAll('.recipe-row').forEach((row) => {
      const select = row.querySelector('select[name="id_insumo[]"]');
      const input = row.querySelector('input[name="cantidad_insumo[]"]');
      const selected = select?.selectedOptions?.[0];
      const costo = Number(selected?.dataset?.costo || 0);
      const cantidad = Number(input?.value || 0);
      if (costo > 0 && cantidad > 0) total += costo * cantidad;
    });
    return total;
  }

  function updateRecipeCost() {
    const total = getRecipeTotal();
    fCost.value = COP.format(total || 0);
    fCost.dataset.rawValue = String(total || 0);
    if (recipeTotalHelp) {
      recipeTotalHelp.textContent = `Costo total de preparacion: $${COP.format(total || 0)}`;
    }
    updateProfit();
  }

  /* ── Formateo COP en inputs del modal ───────────────────── */
  COP.bindInputs(fCost, fSale, fMayorista, fEmpaquePrecio);

  /* ── Toast ──────────────────────────────────────────────── */
  let toastTimer;
  function showToast(msg, isError = false) {
    toast.textContent = msg;
    toast.classList.toggle('error', isError);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
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

  function esc(str) {
    return str
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

});
