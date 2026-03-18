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
        const res = await fetch('/api/caja/productos?q=' + encodeURIComponent(query));
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
    try {
      const res = await fetch('/api/ventas', {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          items   : cartToArray(),
          subtotal: calcSubtotal(),
          discount: DISCOUNT,
          total,
          method  : selectedPayMethod,
        }),
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();
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
    } catch (_) {
      showToast('Error de conexion.', true);
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
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

});
