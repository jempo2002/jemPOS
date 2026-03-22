/* ============================================================
   Ruta: static/js/inventario.js
   Pantalla: Inventario de Productos
   Depende de: cop-format.js (cargado antes en el HTML)
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
  const fCategory = document.getElementById('f-category');
  const fCategoryDropdown = document.getElementById('f-category-dropdown');
  const fCost     = document.getElementById('f-cost');
  const fSale     = document.getElementById('f-sale');
  const fStock    = document.getElementById('f-stock');
  const fProvider = document.getElementById('f-provider');
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
      fCategoryDropdown.innerHTML = '<div class="p-3" style="color:#94A3B8;">Sin coincidencias</div>';
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
  function openModalStock(id) {
    const p = products.find(x => x.id === id);
    stockTargetId = id;
    stockProductName.textContent  = p.name;
    stockCurrentBadge.textContent = `${formatStock(p.stock)} unidades actuales`;
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
    const qty = parseInt(String(stockUnits.value).replace(/\D/g, ''), 10);
    if (!p || isNaN(qty) || qty <= 0) { stockPreview.textContent = ''; return; }
    stockPreview.textContent = `→ Nuevo stock: ${formatStock(p.stock + qty)} unidades`;
  });

  btnStockConfirm.addEventListener('click', async () => {
    const qty = parseInt(String(stockUnits.value).replace(/\D/g, ''), 10);
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
    showToast(`+${qty} unidades anadidas a "${p ? p.name : ''}".`);
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
        wrap.innerHTML = `<img src="${src}" class="sort-img" alt="${dir}">`;
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
    const filtered = products.filter(p =>
      p.name.toLowerCase().includes(searchQuery) ||
      p.category.toLowerCase().includes(searchQuery)
    );
    const display = applySort(filtered);
    renderCards(display);
    renderTable(display);
  }

  /** Renderiza la lista de tarjetas (movil). */
  function renderCards(list) {
    cardsList.innerHTML = '';

    if (list.length === 0) {
      cardsList.innerHTML = `
        <div style="text-align:center;padding:2.5rem;color:#94A3B8;">
          <i class="fa-solid fa-box-open" style="font-size:2.5rem;opacity:.35;"></i>
          <p style="margin-top:.75rem;font-size:.9rem;">Sin resultados</p>
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
          <td colspan="6">No se encontraron productos.</td>
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

  function buildCardHTML(p) {
    const { cls, label } = stockInfo(p.stock);
    const stockAction = p.es_preparado
      ? '<span class="stock-badge ok"><span class="stock-dot"></span>Receta preparada</span>'
      : stockBadge(p.stock, cls, label);
    const addStockButton = p.es_preparado
      ? ''
      : `<button class="action-btn add" data-action="addstock" aria-label="Anadir stock">
            <img src="/static/img/mas.png" alt="Anadir" />
          </button>`;
    return `
      <div class="card-top">
        <div class="card-icon"><i class="fa-solid fa-box"></i></div>
        <div class="card-info">
          <div class="card-name">${esc(p.name)}</div>
          <div class="card-category">${esc(p.category)}</div>
        </div>
        <div class="card-actions">
          <button class="action-btn edit" data-action="edit" aria-label="Editar">
            <img src="/static/img/editar.png" alt="Editar" />
          </button>
          ${addStockButton}
          <button class="action-btn del" data-action="del" aria-label="Eliminar">
            <img src="/static/img/basura.png" alt="Eliminar" />
          </button>
        </div>
      </div>
      <div class="card-bottom">
        <div class="card-prices">
          <span class="card-price-label">Precio venta</span>
          <span class="card-price-value">$${COP.format(p.sale)}</span>
        </div>
        <div class="card-prices" style="text-align:right;">
          <span class="card-price-label">Costo</span>
          <span class="card-price-value" style="color:#475569;">$${COP.format(p.cost)}</span>
        </div>
        ${stockAction}
      </div>`;
  }

  function buildRowHTML(p) {
    const { cls, label } = stockInfo(p.stock);
    const stockAction = p.es_preparado
      ? '<span class="stock-badge ok"><span class="stock-dot"></span>Receta preparada</span>'
      : stockBadge(p.stock, cls, label);
    const addStockButton = p.es_preparado
      ? ''
      : `<button class="action-btn add" data-action="addstock" aria-label="Anadir stock">
            <img src="/static/img/mas.png" alt="Anadir" />
          </button>`;
    return `
      <td>
        <div class="td-name">
          <div class="td-icon"><i class="fa-solid fa-box"></i></div>
          <span class="td-name-text">${esc(p.name)}</span>
        </div>
      </td>
      <td class="td-category">${esc(p.category)}</td>
      <td class="td-price">$${COP.format(p.cost)}</td>
      <td class="td-price">$${COP.format(p.sale)}</td>
      <td>${stockAction}</td>
      <td>
        <div style="display:flex;gap:.4rem;">
          <button class="action-btn edit" data-action="edit" aria-label="Editar">
            <img src="/static/img/editar.png" alt="Editar" />
          </button>
          ${addStockButton}
          <button class="action-btn del" data-action="del" aria-label="Eliminar">
            <img src="/static/img/basura.png" alt="Eliminar" />
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

  function stockInfo(qty) {
    if (qty === 0)  return { cls: 'out', label: 'Agotado' };
    if (qty <= 10)  return { cls: 'low', label: `${formatStock(qty)} unidades` };
    return { cls: 'ok', label: `${formatStock(qty)} unidades` };
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

  function openModal(id) {
    editingId = id;
    hideModalError();

    if (id !== null) {
      const p = products.find(x => x.id === id);
      modalTitle.textContent  = 'Editar Producto';
      fName.value             = p.name;
      fCategory.value         = p.category;
      fCost.value             = COP.format(p.cost);
      fSale.value             = COP.format(p.sale);
      fStock.value            = formatStock(p.stock);
      fProvider.value         = p.proveedor_id ? String(p.proveedor_id) : '';
      fCost.dataset.rawValue  = String(p.cost);
      fSale.dataset.rawValue  = String(p.sale);
      if (fPrepared) fPrepared.checked = Boolean(p.es_preparado);
      clearRecipeRows();
      updateProfit();
    } else {
      modalTitle.textContent = 'Anadir Producto';
      [fName, fCategory, fCost, fSale, fStock].forEach(f => f.value = '');
      if (fProvider) fProvider.value = '';
      if (fPrepared) fPrepared.checked = false;
      fCost.dataset.rawValue = '';
      fSale.dataset.rawValue = '';
      fProfit.textContent = '—';
      clearRecipeRows();
    }

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
    let stock = parseInt(String(fStock.value).replace(/\D/g, ''), 10);
    const idProveedor = fProvider && fProvider.value ? parseInt(fProvider.value, 10) : null;
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

    if (!name || !cat || isNaN(cost) || isNaN(sale) || isNaN(stock)) {
      showModalError('Completa todos los campos correctamente.');
      return;
    }
    hideModalError();

    btnModalSave.disabled = true;
    const url    = editingId !== null ? `/inventario/api/productos/${editingId}` : '/inventario/api/productos';
    const method = editingId !== null ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: jsonHeaders(),
      body: JSON.stringify({
        nombre: name,
        categoria: cat,
        costo: cost,
        venta: sale,
        stock,
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
  COP.bindInputs(fCost, fSale);

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
