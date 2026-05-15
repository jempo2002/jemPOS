/* ============================================================
   Ruta: static/js/caja.js
   Pantalla: Caja POS (Pantalla de Ventas)
   Depende de: cop-format.js (cargado antes en el HTML)
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };
  const cajaApiBase = '/pos/api/caja';
  const ventasApi = '/pos/api/ventas';
  const userRol = (document.body?.dataset?.userRol || '').toLowerCase();
  const isAdminUser = userRol === 'admin';
  const offlineQueueKey = 'jempos_offline_sales_queue';
  const offlineLogKey = 'jempos_offline_sales_log';
  const maxOfflineLogRows = 8;

  /* ── Estado del carrito ────────────────────────────────────
     items: Map<productId, { qty, ... }>
  ─────────────────────────────────────────────────────────── */
  const cart = new Map();
  let selectedPayMethod = 'efectivo';   /* metodo de pago activo */
  const DISCOUNT = 0;                   /* descuento fijo demo (sin logica de UI aun) */

  /* ── Referencias DOM ─────────────────────────────────────── */
  const cartSection    = document.getElementById('cart-section');
  const cartEmpty       = document.getElementById('cart-empty');
  const cartList        = document.getElementById('cart-list');

  const subtotalEl     = document.getElementById('val-subtotal');
  const discountEl     = document.getElementById('val-discount');
  const totalEl        = document.getElementById('val-total');
  const btnCobrar      = document.getElementById('btn-cobrar');
  const cashSection    = document.getElementById('cash-section');
  const cashReceived   = document.getElementById('cash-received');
  const changeBlock    = document.getElementById('change-block');
  const valChange      = document.getElementById('val-change');

  const searchInput    = document.getElementById('search-input');
  const searchWrap     = document.querySelector('.search-wrap');
  const searchDropdown = document.getElementById('search-dropdown');
  const toast          = document.getElementById('toast');
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


  /* ── Busqueda de productos (dropdown) ─────────────────────── */
  let searchTimeout = null;
  let searchResults = [];

  function hideSearchDropdown() {
    if (!searchDropdown) return;
    searchDropdown.classList.add('hidden');
    searchDropdown.innerHTML = '';
  }

  function renderSearchDropdown(items) {
    if (!searchDropdown) return;
    if (!items.length) {
      searchDropdown.innerHTML = '<div class="search-empty">Sin resultados</div>';
      searchDropdown.classList.remove('hidden');
      return;
    }

    searchDropdown.innerHTML = items.map((p, idx) => `
      <div class="search-item" role="option" data-index="${idx}">
        <span class="search-item-name">${escapeHtml(p.name)}</span>
        <span class="search-item-price">$${COP.format(p.price)}</span>
      </div>
    `).join('');
    searchDropdown.classList.remove('hidden');
  }

  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const query = searchInput.value.trim();
    if (!query) {
      hideSearchDropdown();
      return;
    }

    searchTimeout = setTimeout(async () => {
      try {
        const res = await fetch(`${cajaApiBase}/productos?q=` + encodeURIComponent(query));
        if (res.status === 401) { window.location.href = '/login'; return; }
        const data = await res.json();
        if (!data.ok) {
          renderSearchDropdown([]);
          return;
        }
        searchResults = data.productos || [];
        renderSearchDropdown(searchResults);
      } catch (_) {
        renderSearchDropdown([]);
      }
    }, 300);
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
    }
  });

  if (searchDropdown) {
    searchDropdown.addEventListener('click', (e) => {
      const item = e.target.closest('.search-item');
      if (!item) return;
      const idx = parseInt(item.dataset.index, 10);
      const p = searchResults[idx];
      if (!p) return;
      addToCart(p.id, 1, p.name, p.price);
      showToast(`"${p.name}" agregado`);
      searchInput.value = '';
      hideSearchDropdown();
    });
  }

  document.addEventListener('click', (e) => {
    if (!searchWrap || searchWrap.contains(e.target)) return;
    hideSearchDropdown();
  });

  /* ── Metodos de pago ─────────────────────────────────────── */
  document.querySelectorAll('.pay-method-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.pay-method-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedPayMethod = btn.dataset.method;

      /* Mostrar calculadora de cambio solo en Efectivo */
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

  /* ── Formateo COP del input de efectivo ────────────────── */
  COP.bindInput(cashReceived, { onChange: () => updateChange() });

  /* Calculo de cambio en tiempo real */
  cashReceived.addEventListener('input', updateChange);

  function updateChange() {
    const received = COP.parse(cashReceived.value);
    const total    = calcTotal();

    if (isNaN(received) || cashReceived.value === '') {
      resetChange();
      return;
    }

    const change = received - total;
    changeBlock.classList.toggle('negative', change < 0);

    if (change < 0) {
      valChange.textContent = `-$${COP.format(Math.abs(change))}`;
    } else {
      valChange.textContent = `$${COP.format(change)}`;
    }
  }

  function resetChange() {
    changeBlock.classList.remove('negative');
    valChange.textContent = '—';
  }

  /* ── Cobrar ──────────────────────────────────────────────── */
  btnCobrar.addEventListener('click', async () => {
    if (cart.size === 0) return;
    btnCobrar.disabled = true;
    const total = calcTotal();
    const salePayload = {
      items   : cartToArray(),
      subtotal: calcSubtotal(),
      discount: DISCOUNT,
      total,
      method  : selectedPayMethod,
    };
    try {
      const data = await submitSale(salePayload);
      if (data.ok) {
        showToast(`¡Venta de $${COP.format(total)} registrada!`);
        if (Array.isArray(data.stock_alerts) && data.stock_alerts.length) {
          showStockAlerts(data.stock_alerts);
        }
        clearCart();
        cashReceived.value = '';
        resetChange();
      } else {
        showToast(data.msg || 'Error al registrar la venta.', true);
      }
    } catch (error) {
      const errorMessage = normalizeErrorMessage(error);
      if (!navigator.onLine || isNetworkLikeError(error)) {
        enqueueOfflineSale(salePayload, errorMessage);
        showToast('Venta guardada localmente. Se sincronizará al volver internet.', true, 4200);
      } else {
        showToast(errorMessage, true, 6000);
      }
    }
    btnCobrar.disabled = false;
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
    updateCartMeta();
  }

  /**
   * Renderiza la fila HTML de un item del carrito (primera vez).
   */
  function renderItemRow(productId) {
    const item = cart.get(productId);
    const row  = document.createElement('div');

    row.classList.add('cart-item');
    row.id = `cart-item-${productId}`;
    row.dataset.id = productId;
    row.innerHTML = buildRowHTML(productId, item);

    cartList.appendChild(row);
    bindRowEvents(row, productId);

    /* Ocultar estado vacio */
    cartEmpty.style.display = 'none';
  }

  /**
   * Actualiza los datos de una fila existente sin re-renderizarla.
   */
  function updateItemRow(productId) {
    const row = document.getElementById(`cart-item-${productId}`);
    if (!row) return;

    const item     = cart.get(productId);
    const qtyEl    = row.querySelector('.qty-display');
    const subEl    = row.querySelector('.item-subtotal');

    qtyEl.value   = item.qty;
    subEl.textContent = '$' + COP.format(item.price * item.qty);
  }

  /**
   * Genera el innerHTML de una fila del carrito (tarjeta apilada).
   */
  function buildRowHTML(productId, item) {
    const unitFmt = COP.format(item.price);
    const subFmt  = COP.format(item.price * item.qty);

    return `
      <div class="item-top-row">
        <div class="item-icon">
          <i class="fa-solid fa-box"></i>
        </div>
        <div class="item-info">
          <div class="item-name">${escapeHtml(item.name)}</div>
          <div class="item-unit-price">$${unitFmt} por unidad</div>
        </div>
        <button class="btn-delete" aria-label="Eliminar producto">
          <img src="/static/img/basura.png" alt="Eliminar" />
        </button>
      </div>
      <div class="item-bottom-row">
        <div class="item-controls">
          <button class="qty-btn minus" aria-label="Disminuir cantidad">
            <img src="/static/img/menos.png" alt="-" />
          </button>
          <input
            class="qty-display"
            type="tel"
            inputmode="numeric"
            pattern="[0-9]*"
            value="${item.qty}"
            aria-label="Cantidad"
            min="1"
          />
          <button class="qty-btn plus" aria-label="Aumentar cantidad">
            <img src="/static/img/mas.png" alt="+" />
          </button>
        </div>
        <div class="item-subtotal">$${subFmt}</div>
      </div>
    `;
  }

  /**
   * Vincula los eventos de una fila ya renderizada.
   */
  function bindRowEvents(row, productId) {
    const minusBtn = row.querySelector('.qty-btn.minus');
    const plusBtn  = row.querySelector('.qty-btn.plus');
    const qtyInput = row.querySelector('.qty-display');
    const delBtn   = row.querySelector('.btn-delete');

    plusBtn.addEventListener('click', () => {
      cart.get(productId).qty++;
      updateItemRow(productId);
      updateTotals();
    });

    minusBtn.addEventListener('click', () => {
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

    /* Solo permite digitos en el input de cantidad */
    qtyInput.addEventListener('input', () => {
      qtyInput.value = qtyInput.value.replace(/[^\d]/g, '');
    });

    delBtn.addEventListener('click', () => removeFromCart(productId));
  }

  /**
   * Elimina un item del carrito con animacion.
   */
  function removeFromCart(productId) {
    const row = document.getElementById(`cart-item-${productId}`);
    if (!row) return;

    row.classList.add('removing');
    row.addEventListener('animationend', () => {
      row.remove();
      cart.delete(productId);
      updateTotals();
      updateCartMeta();

      if (cart.size === 0) {
        cartEmpty.style.display = 'flex';
      }
    }, { once: true });
  }

  /** Vacia el carrito completamente. */
  function clearCart() {
    cart.clear();
    cartList.innerHTML = '';
    cartEmpty.style.display = 'flex';
    updateTotals();
    updateCartMeta();
  }

  /* ══════════════════════════════════════════════════════════
     TOTALES
     ══════════════════════════════════════════════════════════ */

  function calcSubtotal() {
    let sub = 0;
    cart.forEach(item => { sub += item.price * item.qty; });
    return sub;
  }

  function calcTotal() {
    return Math.max(0, calcSubtotal() - DISCOUNT);
  }

  function updateTotals() {
    const sub   = calcSubtotal();
    const total = calcTotal();

    subtotalEl.textContent  = '$' + COP.format(sub);
    discountEl.textContent  = DISCOUNT > 0 ? '-$' + COP.format(DISCOUNT) : '$0';
    totalEl.textContent     = '$' + COP.format(total);

    btnCobrar.disabled = cart.size === 0;
    btnCobrar.textContent = cart.size === 0
      ? 'Cobrar'
      : `Cobrar  $${COP.format(total)}`;

    /* Recalcular el cambio si el cajero ya digito un monto */
    if (selectedPayMethod === 'efectivo' && cashReceived.value !== '') {
      updateChange();
    }
  }

  /** Actualiza meta-info del carrito. */
  function updateCartMeta() {
    /* badge eliminado — funcion conservada por compatibilidad con llamadas existentes */
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
    try {
      const total = typeof payload.total === 'number' ? payload.total : Number(payload.total || 0);
      return `$${COP.format(total)}`;
    } catch (_) {
      return 'Venta offline';
    }
  }

  function generateOfflineId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return `offline-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  /* ── Helpers ─────────────────────────────────────────────── */

  function cartToArray() {
    return Array.from(cart.entries()).map(([id, item]) => ({
      id,
      name  : item.name,
      qty   : item.qty,
      price : item.price,
      total : item.price * item.qty,
    }));
  }

  let toastTimer;

  function showStockAlerts(alerts) {
    alerts.slice(0, 3).forEach((msg, idx) => {
      setTimeout(() => showToast(msg, true, 5000), idx * 5200);
    });
  }

  /**
   * Muestra un toast de retroalimentacion visual.
   * @param {string}  msg
   * @param {boolean} [isError=false]
   */
  function showToast(msg, isError = false, duration = 2400) {
    toast.textContent = msg;
    toast.style.background = isError ? '#EF4444' : '#10B981';
    toast.classList.add('show');

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), duration);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

});
