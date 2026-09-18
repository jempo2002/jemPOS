/* ============================================================
   Ruta: static/js/caja.js
   Pantalla: Caja POS (Pantalla de Ventas)
   Depende de: cop-format.js, toast.js, barcode-scanner.js
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };
  const cajaApiBase = '/pos/api/caja';
  const ventasApi = '/pos/api/ventas';
  const clientesApi = '/pos/api/clientes/buscar';
  const userRol = (document.body?.dataset?.userRol || '').toLowerCase();
  const isAdminUser = userRol === 'admin';
  const offlineQueueKey = 'jempos_offline_sales_queue';
  const offlineLogKey = 'jempos_offline_sales_log';
  const maxOfflineLogRows = 8;
  const SEARCH_DEBOUNCE_MS = 300;

  /* ── Estado del carrito ────────────────────────────────────
     items: Map<productId, { name, price, qty }>
  ─────────────────────────────────────────────────────────── */
  const cart = new Map();
  let selectedPayMethod = 'efectivo';

  /* ── Referencias DOM ─────────────────────────────────────── */
  const cartEmpty      = document.getElementById('cart-empty');
  const cartList       = document.getElementById('cart-list');
  const totalEl        = document.getElementById('val-total');
  const btnCobrar      = document.getElementById('btn-cobrar');
  const btnFiar        = document.getElementById('btn-fiar');
  const cashSection    = document.getElementById('cash-section');
  const cashReceived   = document.getElementById('cash-received');
  const changeBlock    = document.getElementById('change-block');
  const valChange      = document.getElementById('val-change');

  const searchInput    = document.getElementById('search-input');
  const searchWrap     = document.querySelector('.search-wrap');
  const searchDropdown = document.getElementById('search-dropdown');
  const offlineIndicator = document.getElementById('offline-sync-indicator');
  const offlineIndicatorText = document.getElementById('offline-sync-indicator-text');
  const offlineLogBody = document.getElementById('offline-sync-log-body');
  const offlineLogCount = document.getElementById('offline-sync-count');

  const offlineQueue = loadJsonArray(offlineQueueKey);
  const offlineLog = loadJsonArray(offlineLogKey);

  renderOfflineSyncPanel();
  updateConnectionIndicator();
  window.addEventListener('online', handleConnectionChange);
  window.addEventListener('offline', handleConnectionChange);

  if (navigator.onLine) {
    setTimeout(() => {
      syncOfflineQueue();
    }, 0);
  }

  /* ══════════════════════════════════════════════════════════
     PETICIONES DE BUSQUEDA
     debounce: espera a que el usuario deje de teclear.
     getJson:  aborta la peticion anterior del mismo tipo, asi una
               respuesta lenta nunca pisa resultados mas nuevos.
     ══════════════════════════════════════════════════════════ */

  function debounce(fn, wait) {
    let timer;
    const debounced = (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
    debounced.cancel = () => clearTimeout(timer);
    return debounced;
  }

  const inflight = {};

  async function getJson(key, url) {
    inflight[key]?.abort();
    const controller = new AbortController();
    inflight[key] = controller;
    const res = await fetch(url, { signal: controller.signal });
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Sesion expirada.');
    }
    return res.json();
  }

  function cancelRequest(key) {
    inflight[key]?.abort();
  }

  const isAbort = (err) => err?.name === 'AbortError';

  /* ── Busqueda de productos (dropdown) ─────────────────────── */
  let searchResults = [];

  async function searchProducts(query) {
    const data = await getJson('productos', `${cajaApiBase}/productos?q=${encodeURIComponent(query)}`);
    return data.ok ? data.productos || [] : [];
  }

  function hideSearchDropdown() {
    searchDropdown.classList.add('hidden');
    searchDropdown.innerHTML = '';
  }

  function renderSearchDropdown(items) {
    searchDropdown.innerHTML = items.length
      ? items.map((p, idx) => `
          <button type="button" class="search-item" data-index="${idx}">
            <span class="search-item-name">${escapeHtml(p.name)}</span>
            <span class="search-item-price">${money(p.price)}</span>
          </button>`).join('')
      : '<p class="search-empty">Sin resultados</p>';
    searchDropdown.classList.remove('hidden');
  }

  const liveProductSearch = debounce(async (query) => {
    try {
      searchResults = await searchProducts(query);
      renderSearchDropdown(searchResults);
    } catch (err) {
      if (!isAbort(err)) renderSearchDropdown([]);
    }
  }, SEARCH_DEBOUNCE_MS);

  function addProduct(p) {
    addToCart(p.id, 1, p.name, p.price);
    showToast(`"${p.name}" agregado`, false, 1200);
    searchInput.value = '';
    liveProductSearch.cancel();
    cancelRequest('productos');
    hideSearchDropdown();
  }

  searchInput.addEventListener('input', () => {
    const query = searchInput.value.trim();
    if (!query) {
      liveProductSearch.cancel();
      cancelRequest('productos');
      hideSearchDropdown();
      return;
    }
    liveProductSearch(query);
  });

  /* Enter: lectores USB (teclado) escriben el codigo + Enter. */
  searchInput.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;
    liveProductSearch.cancel();
    try {
      searchResults = await searchProducts(query);
    } catch (err) {
      if (!isAbort(err)) showToast('No se pudo buscar el producto.', true);
      return;
    }
    const match = searchResults.find((p) => p.barcode === query)
      || (searchResults.length === 1 ? searchResults[0] : null);
    if (match) addProduct(match);
    else renderSearchDropdown(searchResults);
  });

  searchDropdown.addEventListener('click', (e) => {
    const item = e.target.closest('.search-item');
    const p = item && searchResults[Number(item.dataset.index)];
    if (p) addProduct(p);
  });

  document.addEventListener('click', (e) => {
    if (!searchWrap.contains(e.target)) hideSearchDropdown();
  });

  /* ── Escaner de camara ─────────────────────────────────────── */
  document.getElementById('btn-scan').addEventListener('click', () => {
    BarcodeScanner.open(async (code) => {
      try {
        const match = (await searchProducts(code)).find((p) => p.barcode === code);
        if (match) addProduct(match);
        else showToast(`El código ${code} no está registrado en el inventario.`, true, 4000);
      } catch (err) {
        if (!isAbort(err)) showToast('No se pudo buscar el producto escaneado.', true);
      }
    });
  });

  /* ── Metodos de pago ─────────────────────────────────────── */
  const payMethodButtons = document.querySelectorAll('.pay-method-btn');
  payMethodButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      payMethodButtons.forEach((b) => {
        b.classList.toggle('selected', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      });
      selectedPayMethod = btn.dataset.method;

      /* Calculadora de cambio solo en Efectivo */
      const isEfectivo = selectedPayMethod === 'efectivo';
      cashSection.classList.toggle('visible', isEfectivo);
      if (!isEfectivo) {
        cashReceived.value = '';
        resetChange();
      } else {
        updateChange();
      }
    });
  });

  /* ── Efectivo recibido: formato COP + cambio en tiempo real ── */
  COP.bindInput(cashReceived, { onChange: () => updateChange() });

  function updateChange() {
    const received = COP.parse(cashReceived.value);
    if (isNaN(received)) {
      resetChange();
      return;
    }
    const change = received - calcTotal();
    changeBlock.classList.toggle('negative', change < 0);
    valChange.textContent = change < 0 ? `-${money(Math.abs(change))}` : money(change);
  }

  function resetChange() {
    changeBlock.classList.remove('negative');
    valChange.textContent = '—';
  }

  /* ══════════════════════════════════════════════════════════
     COBRAR / FIAR
     ══════════════════════════════════════════════════════════ */

  function buildSalePayload(method) {
    const total = calcTotal();
    return { items: cartToArray(), subtotal: total, discount: 0, total, method };
  }

  /** Envia la venta. Devuelve { ok, offline?, msg? } sin mostrar UI. */
  async function processSale(payload) {
    try {
      const data = await submitSale(payload);
      if (!data.ok) return { ok: false, msg: data.msg || 'Error al registrar la venta.' };
      if (Array.isArray(data.stock_alerts) && data.stock_alerts.length) {
        showStockAlerts(data.stock_alerts);
      }
      clearCart();
      return { ok: true };
    } catch (error) {
      const msg = normalizeErrorMessage(error);
      if (!navigator.onLine || isNetworkLikeError(error)) {
        enqueueOfflineSale(payload, msg);
        return { ok: false, offline: true, msg: 'Venta guardada localmente. Se sincronizará al volver internet.' };
      }
      return { ok: false, msg };
    }
  }

  btnCobrar.addEventListener('click', async () => {
    if (cart.size === 0) return;
    btnCobrar.disabled = true;
    const total = calcTotal();
    const result = await processSale(buildSalePayload(selectedPayMethod));
    if (result.ok) showToast(`¡Venta de ${money(total)} registrada!`);
    else showToast(result.msg, true, result.offline ? 4200 : 6000);
    btnCobrar.disabled = cart.size === 0;
  });

  /* ── Hoja "Fiar" con live search de clientes ───────────────── */
  const fiarDialog   = document.getElementById('fiar-dialog');
  const fiarForm     = document.getElementById('fiar-form');
  const fiarNombre   = document.getElementById('fiar-nombre');
  const fiarCedula   = document.getElementById('fiar-cedula');
  const fiarTelefono = document.getElementById('fiar-telefono');
  const fiarResults  = document.getElementById('fiar-results');
  const fiarHint     = document.getElementById('fiar-hint');
  const fiarTotal    = document.getElementById('fiar-total');
  const fiarDebt     = document.getElementById('fiar-debt');
  const fiarDebtPrev = document.getElementById('fiar-debt-prev');
  const fiarDebtNew  = document.getElementById('fiar-debt-new');
  const fiarError    = document.getElementById('fiar-error');
  const fiarSubmit   = document.getElementById('fiar-submit');
  const FIAR_HINT    = fiarHint.textContent;

  let fiarCliente = null;   /* cliente existente elegido en el live search */
  let fiarMatches = [];

  btnFiar.addEventListener('click', () => {
    if (cart.size === 0) return;
    fiarTotal.textContent = money(calcTotal());
    renderFiarDebt();
    setFiarError('');
    fiarDialog.showModal();
  });

  document.getElementById('fiar-close').addEventListener('click', () => fiarDialog.close());
  fiarDialog.addEventListener('click', (e) => {
    if (e.target === fiarDialog) fiarDialog.close();
  });
  fiarDialog.addEventListener('close', () => {
    searchClientes.cancel();
    cancelRequest('clientes');
    hideFiarResults();
  });

  /* Cedula y telefono: solo digitos (el teclado numerico movil no basta al pegar). */
  [fiarCedula, fiarTelefono].forEach((input) => {
    input.addEventListener('input', () => {
      input.value = input.value.replace(/\D/g, '');
    });
  });

  const searchClientes = debounce(async (query) => {
    try {
      const data = await getJson('clientes', `${clientesApi}?q=${encodeURIComponent(query)}`);
      fiarMatches = data.ok ? data.clientes || [] : [];
      renderFiarResults();
    } catch (err) {
      if (!isAbort(err)) hideFiarResults();
    }
  }, SEARCH_DEBOUNCE_MS);

  fiarNombre.addEventListener('input', () => {
    if (fiarCliente) {
      fiarCliente = null;   /* editar el nombre suelta la seleccion */
      renderFiarDebt();
    }
    const query = fiarNombre.value.trim();
    if (query.length < 2) {
      searchClientes.cancel();
      cancelRequest('clientes');
      hideFiarResults();
      return;
    }
    searchClientes(query);
  });

  fiarNombre.addEventListener('keydown', (e) => {
    if (fiarResults.hidden) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      fiarResults.querySelector('button')?.focus();
    } else if (e.key === 'Enter') {
      e.preventDefault();   /* Enter elige el primer resultado en vez de enviar */
      selectFiarCliente(fiarMatches[0]);
    }
  });

  fiarResults.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const li = e.target.closest('li');
    const next = e.key === 'ArrowDown' ? li?.nextElementSibling : li?.previousElementSibling;
    if (next) next.querySelector('button').focus();
    else if (e.key === 'ArrowUp') fiarNombre.focus();
  });

  fiarResults.addEventListener('click', (e) => {
    const option = e.target.closest('.combo-option');
    if (option) selectFiarCliente(fiarMatches[Number(option.dataset.index)]);
  });

  function renderFiarResults() {
    if (!fiarMatches.length) {
      hideFiarResults();
      fiarHint.textContent = 'Cliente nuevo: completa su teléfono para registrarlo.';
      return;
    }
    fiarResults.innerHTML = fiarMatches.map((c, idx) => {
      const meta = [c.cedula && `CC ${c.cedula}`, c.phone].filter(Boolean).join(' · ');
      return `
        <li>
          <button type="button" class="combo-option" data-index="${idx}">
            <span class="combo-name">${escapeHtml(c.name)}</span>
            <span class="combo-debt${c.debt > 0 ? ' has-debt' : ''}">${c.debt > 0 ? money(c.debt) : 'Sin deuda'}</span>
            <span class="combo-meta">${escapeHtml(meta)}</span>
          </button>
        </li>`;
    }).join('');
    fiarResults.hidden = false;
    fiarHint.textContent = `${fiarMatches.length} ${fiarMatches.length === 1 ? 'cliente encontrado' : 'clientes encontrados'}.`;
  }

  function hideFiarResults() {
    fiarResults.hidden = true;
    fiarResults.innerHTML = '';
  }

  function selectFiarCliente(cliente) {
    if (!cliente) return;
    fiarCliente = cliente;
    fiarNombre.value = cliente.name;
    fiarCedula.value = cliente.cedula || '';
    fiarTelefono.value = cliente.phone || '';
    hideFiarResults();
    fiarHint.textContent = FIAR_HINT;
    renderFiarDebt();
    fiarSubmit.focus();
  }

  function renderFiarDebt() {
    fiarDebt.hidden = !fiarCliente;
    if (!fiarCliente) return;
    fiarDebtPrev.textContent = money(fiarCliente.debt);
    fiarDebtNew.textContent = money(fiarCliente.debt + calcTotal());
  }

  function setFiarError(msg) {
    fiarError.textContent = msg;
    fiarError.hidden = !msg;
  }

  function resetFiarForm() {
    fiarForm.reset();
    fiarCliente = null;
    fiarMatches = [];
    fiarHint.textContent = FIAR_HINT;
    renderFiarDebt();
  }

  /* 'submit' solo llega si la validacion nativa (required/pattern) paso. */
  fiarForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (cart.size === 0) return;

    const nombre = fiarNombre.value.trim();
    const total = calcTotal();
    const payload = {
      ...buildSalePayload('fiado'),
      cliente: {
        id: fiarCliente?.id ?? null,
        nombre,
        cedula: fiarCedula.value,
        telefono: fiarTelefono.value,
      },
    };

    fiarSubmit.disabled = true;
    setFiarError('');
    const result = await processSale(payload);
    fiarSubmit.disabled = false;

    if (!result.ok) {
      setFiarError(result.msg);   /* dentro de la hoja: un toast quedaria detras del modal */
      return;
    }
    fiarDialog.close();
    resetFiarForm();
    showToast(`Fiado de ${money(total)} registrado a ${nombre}.`, false, 3200);
  });

  /* ══════════════════════════════════════════════════════════
     FUNCIONES DEL CARRITO
     ══════════════════════════════════════════════════════════ */

  function addToCart(productId, qty = 1, name = '', price = 0) {
    if (cart.has(productId)) {
      cart.get(productId).qty += qty;
      updateItemRow(productId);
    } else {
      cart.set(productId, { name, price, qty });
      renderItemRow(productId);
    }
    updateTotals();
  }

  function renderItemRow(productId) {
    const item = cart.get(productId);
    const row = document.createElement('li');
    row.className = 'cart-item';
    row.id = `cart-item-${productId}`;
    row.innerHTML = buildRowHTML(item);
    cartList.appendChild(row);
    bindRowEvents(row, productId);
    cartEmpty.hidden = true;
  }

  /** Actualiza cantidad y subtotal de una fila sin re-renderizarla. */
  function updateItemRow(productId) {
    const row = document.getElementById(`cart-item-${productId}`);
    if (!row) return;
    const item = cart.get(productId);
    row.querySelector('.qty-display').value = item.qty;
    row.querySelector('.item-subtotal').textContent = money(item.price * item.qty);
  }

  function buildRowHTML(item) {
    const name = escapeHtml(item.name);
    return `
      <span class="item-name">${name}</span>
      <span class="item-subtotal">${money(item.price * item.qty)}</span>
      <span class="item-unit-price">${money(item.price)} c/u</span>
      <div class="item-actions">
        <button type="button" class="qty-btn minus" aria-label="Quitar una unidad de ${name}">
          <i class="fa-solid fa-minus" aria-hidden="true"></i>
        </button>
        <input
          class="qty-display"
          type="tel"
          inputmode="numeric"
          value="${item.qty}"
          aria-label="Cantidad de ${name}"
        />
        <button type="button" class="qty-btn plus" aria-label="Agregar una unidad de ${name}">
          <i class="fa-solid fa-plus" aria-hidden="true"></i>
        </button>
        <button type="button" class="btn-delete" aria-label="Eliminar ${name} del carrito">
          <i class="fa-solid fa-trash-can" aria-hidden="true"></i>
        </button>
      </div>
    `;
  }

  function bindRowEvents(row, productId) {
    const qtyInput = row.querySelector('.qty-display');

    row.querySelector('.qty-btn.plus').addEventListener('click', () => {
      cart.get(productId).qty++;
      updateItemRow(productId);
      updateTotals();
    });

    row.querySelector('.qty-btn.minus').addEventListener('click', () => {
      const item = cart.get(productId);
      if (item.qty <= 1) {
        removeFromCart(productId);
      } else {
        item.qty--;
        updateItemRow(productId);
        updateTotals();
      }
    });

    /* Edicion directa de cantidad */
    qtyInput.addEventListener('change', () => {
      const raw = parseInt(qtyInput.value.replace(/\D/g, ''), 10);
      if (isNaN(raw) || raw < 1) {
        removeFromCart(productId);
        return;
      }
      cart.get(productId).qty = raw;
      updateItemRow(productId);
      updateTotals();
    });

    qtyInput.addEventListener('input', () => {
      qtyInput.value = qtyInput.value.replace(/\D/g, '');
    });

    row.querySelector('.btn-delete').addEventListener('click', () => removeFromCart(productId));
  }

  /** Elimina un item del carrito con animacion. */
  function removeFromCart(productId) {
    const row = document.getElementById(`cart-item-${productId}`);
    if (!row) return;

    row.classList.add('removing');
    row.addEventListener('animationend', () => {
      row.remove();
      cart.delete(productId);
      updateTotals();
      if (cart.size === 0) cartEmpty.hidden = false;
    }, { once: true });
  }

  function clearCart() {
    cart.clear();
    cartList.innerHTML = '';
    cartEmpty.hidden = false;
    cashReceived.value = '';
    resetChange();
    updateTotals();
  }

  /* ══════════════════════════════════════════════════════════
     TOTALES
     ══════════════════════════════════════════════════════════ */

  function calcTotal() {
    let total = 0;
    cart.forEach((item) => { total += item.price * item.qty; });
    return total;
  }

  function updateTotals() {
    const total = calcTotal();
    const empty = cart.size === 0;

    totalEl.textContent = money(total);
    btnCobrar.disabled = empty;
    btnFiar.disabled = empty;
    btnCobrar.textContent = empty ? 'Cobrar' : `Cobrar ${money(total)}`;

    /* Recalcular el cambio si el cajero ya digito un monto */
    if (selectedPayMethod === 'efectivo' && cashReceived.value !== '') {
      updateChange();
    }
  }

  async function submitSale(payload) {
    const res = await fetch(ventasApi, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    });

    if (res.status === 401) { window.location.href = '/login'; return { ok: false, msg: 'Sesion expirada.' }; }

    const rawText = await res.text();
    let data = null;
    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch (_) {
      data = null;
    }

    if (res.ok && data && data.ok) {
      return data;
    }

    const message = (data && (data.msg || data.error)) || rawText || `HTTP ${res.status}`;
    throw new Error(message);
  }

  function loadJsonArray(storageKey) {
    try {
      const raw = localStorage.getItem(storageKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  function saveJsonArray(storageKey, value) {
    localStorage.setItem(storageKey, JSON.stringify(value));
  }

  function handleConnectionChange() {
    updateConnectionIndicator();
    if (navigator.onLine) {
      syncOfflineQueue();
    }
  }

  function updateConnectionIndicator(state = null, label = null) {
    if (!offlineIndicator || !isAdminUser) return;

    offlineIndicator.hidden = false;
    offlineIndicator.classList.remove('is-online', 'is-offline', 'is-syncing');

    const pendingCount = offlineQueue.filter((entry) => entry.status === 'pending' || entry.status === 'failed').length;
    if (offlineLogCount) {
      offlineLogCount.textContent = `${pendingCount} ${pendingCount === 1 ? 'pendiente' : 'pendientes'}`;
    }

    const currentState = state || (navigator.onLine ? 'online' : 'offline');
    if (currentState === 'syncing') {
      offlineIndicator.classList.add('is-syncing');
      offlineIndicatorText.textContent = label || 'Sincronizando ventas';
    } else if (!navigator.onLine || currentState === 'offline') {
      offlineIndicator.classList.add('is-offline');
      offlineIndicatorText.textContent = label || 'Offline - guardando localmente';
    } else {
      offlineIndicator.classList.add('is-online');
      offlineIndicatorText.textContent = label || 'Online';
    }
  }

  function renderOfflineSyncPanel() {
    if (!isAdminUser || !offlineLogBody) return;

    const pendingCount = offlineQueue.filter((entry) => entry.status === 'pending' || entry.status === 'failed').length;
    if (offlineLogCount) {
      offlineLogCount.textContent = `${pendingCount} ${pendingCount === 1 ? 'pendiente' : 'pendientes'}`;
    }

    const rows = [...offlineLog, ...offlineQueue]
      .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))
      .slice(0, maxOfflineLogRows);

    if (!rows.length) {
      offlineLogBody.innerHTML = '<tr class="offline-sync-empty"><td colspan="5">No hay eventos offline pendientes.</td></tr>';
      return;
    }
    if (pendingCount) document.getElementById('offline-sync-panel').open = true;

    offlineLogBody.innerHTML = rows.map((entry) => {
      const saleLabel = entry.sale_label || `#${entry.id}`;
      const timeLabel = formatOfflineTime(entry.updated_at || entry.created_at);
      const statusLabel = getOfflineStatusLabel(entry.status);
      const retryCell = entry.status === 'failed'
        ? `<button type="button" class="offline-sync-retry" data-retry-id="${escapeHtml(String(entry.id))}">Reintentar</button>`
        : '';
      const errorCell = entry.error ? `<span class="offline-sync-error">${escapeHtml(entry.error)}</span>` : '—';

      return `
        <tr>
          <td>${escapeHtml(timeLabel)}</td>
          <td>${escapeHtml(saleLabel)}</td>
          <td><span class="offline-sync-status ${escapeHtml(entry.status || 'pending')}">${escapeHtml(statusLabel)}</span></td>
          <td>${errorCell}</td>
          <td>${retryCell}</td>
        </tr>
      `;
    }).join('');

    offlineLogBody.querySelectorAll('[data-retry-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const entryId = btn.getAttribute('data-retry-id');
        await retryOfflineSale(entryId);
      });
    });
  }

  function formatOfflineTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toLocaleString('es-CO', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getOfflineStatusLabel(status) {
    const normalized = String(status || 'pending').toLowerCase();
    if (normalized === 'failed') return 'Falló';
    if (normalized === 'synced') return 'Sincronizada';
    if (normalized === 'syncing') return 'Sincronizando';
    return 'Pendiente';
  }

  function normalizeErrorMessage(error) {
    if (!error) return 'Error desconocido.';
    if (typeof error === 'string') return error;
    if (error instanceof Error) return error.message || 'Error desconocido.';
    if (typeof error === 'object' && error.msg) return String(error.msg);
    return 'Error desconocido.';
  }

  function isNetworkLikeError(error) {
    const message = normalizeErrorMessage(error).toLowerCase();
    return message.includes('failed to fetch') || message.includes('network') || message.includes('conexion') || message.includes('connection');
  }

  function enqueueOfflineSale(payload, errorMessage = '') {
    const now = new Date().toISOString();
    const entry = {
      id: generateOfflineId(),
      sale_label: buildOfflineSaleLabel(payload),
      created_at: now,
      updated_at: now,
      status: 'pending',
      attempts: 0,
      error: errorMessage,
      payload,
    };

    offlineQueue.unshift(entry);
    saveJsonArray(offlineQueueKey, offlineQueue);
    renderOfflineSyncPanel();
    updateConnectionIndicator();
  }

  async function syncOfflineQueue() {
    if (!isAdminUser || !offlineQueue.length) {
      updateConnectionIndicator();
      return;
    }

    updateConnectionIndicator('syncing', 'Sincronizando ventas guardadas');

    const pendingEntries = offlineQueue.filter((entry) => entry.status === 'pending');
    for (const entry of pendingEntries) {
      entry.status = 'syncing';
      entry.attempts = (entry.attempts || 0) + 1;
      entry.updated_at = new Date().toISOString();
      saveJsonArray(offlineQueueKey, offlineQueue);
      renderOfflineSyncPanel();

      try {
        const data = await submitSale(entry.payload);
        if (data.ok) {
          removeOfflineEntry(entry.id, 'synced', 'Sincronizada correctamente.');
          showToast(`Venta offline ${entry.sale_label} sincronizada correctamente.`, false, 3200);
        } else {
          throw new Error(data.msg || 'La sincronizacion fue rechazada por el servidor.');
        }
      } catch (error) {
        const message = normalizeErrorMessage(error);
        moveOfflineEntryToFailed(entry.id, message);
        showToast(`Error al sincronizar ${entry.sale_label}: ${message}`, true, 7000);
        break;
      }
    }

    updateConnectionIndicator();
    renderOfflineSyncPanel();
  }

  function removeOfflineEntry(entryId, finalStatus = 'synced', finalError = '') {
    const idx = offlineQueue.findIndex((entry) => String(entry.id) === String(entryId));
    if (idx === -1) return;

    const [entry] = offlineQueue.splice(idx, 1);
    const logEntry = {
      ...entry,
      status: finalStatus,
      error: finalError,
      updated_at: new Date().toISOString(),
    };

    offlineLog.unshift(logEntry);
    offlineLog.splice(maxOfflineLogRows);
    saveJsonArray(offlineQueueKey, offlineQueue);
    saveJsonArray(offlineLogKey, offlineLog);
  }

  function moveOfflineEntryToFailed(entryId, errorMessage) {
    const idx = offlineQueue.findIndex((entry) => String(entry.id) === String(entryId));
    if (idx === -1) return;

    const [entry] = offlineQueue.splice(idx, 1);
    const logEntry = {
      ...entry,
      status: 'failed',
      error: errorMessage,
      updated_at: new Date().toISOString(),
    };

    offlineLog.unshift(logEntry);
    offlineLog.splice(maxOfflineLogRows);
    saveJsonArray(offlineQueueKey, offlineQueue);
    saveJsonArray(offlineLogKey, offlineLog);
    renderOfflineSyncPanel();
    updateConnectionIndicator();
  }

  async function retryOfflineSale(entryId) {
    const logIdx = offlineLog.findIndex((entry) => String(entry.id) === String(entryId));
    if (logIdx === -1) return;

    const entry = offlineLog[logIdx];
    offlineLog.splice(logIdx, 1);
    offlineQueue.unshift({
      ...entry,
      status: 'pending',
      error: '',
      updated_at: new Date().toISOString(),
      attempts: (entry.attempts || 0) + 1,
    });
    saveJsonArray(offlineLogKey, offlineLog);
    saveJsonArray(offlineQueueKey, offlineQueue);
    renderOfflineSyncPanel();
    showToast(`Reintentando ${entry.sale_label}...`, false, 2400);

    if (navigator.onLine) {
      await syncOfflineQueue();
    } else {
      updateConnectionIndicator('offline', 'Sin internet - reintento pendiente');
    }
  }

  function buildOfflineSaleLabel(payload) {
    const total = Number(payload.total || 0);
    return payload.method === 'fiado' ? `Fiado ${money(total)}` : money(total);
  }

  function generateOfflineId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return `offline-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  /* ── Helpers ─────────────────────────────────────────────── */

  function money(value) {
    return `$${COP.format(value)}`;
  }

  function cartToArray() {
    return Array.from(cart.entries()).map(([id, item]) => ({
      id,
      name  : item.name,
      qty   : item.qty,
      price : item.price,
      total : item.price * item.qty,
    }));
  }

  function showStockAlerts(alerts) {
    alerts.slice(0, 3).forEach((msg, idx) => {
      setTimeout(() => showToast(msg, true, 5000), idx * 5200);
    });
  }

  function showToast(msg, isError = false, duration = 2400) {
    JemToast[isError ? 'error' : 'success'](msg, { duration });
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

});
