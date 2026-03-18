/* ============================================================
   Ruta: static/js/onboarding.js
   Pantalla: Configuracion Inicial (Onboarding de Inventario)
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const jsonHeaders = csrfToken
    ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
    : { 'Content-Type': 'application/json' };

  /* ── Referencias al DOM ──────────────────────────────────── */
  const step1Section   = document.getElementById('step-1');
  const step2Section   = document.getElementById('step-2');

  const categoryInput  = document.getElementById('category-name');
  const categoryError  = document.getElementById('category-error');

  const productName    = document.getElementById('product-name');
  const costPrice      = document.getElementById('cost-price');
  const salePrice      = document.getElementById('sale-price');
  const stockInput     = document.getElementById('stock-initial');
  const profitBadge    = document.getElementById('profit-badge');

  const catNameDisplay = document.getElementById('cat-name-display');
  const btnNext        = document.getElementById('btn-next');
  const btnStart       = document.getElementById('btn-start');

  /* Elementos del indicador de progreso */
  const circle1        = document.getElementById('circle-1');
  const circle2        = document.getElementById('circle-2');
  const label1         = document.getElementById('label-1');
  const label2         = document.getElementById('label-2');
  const connector      = document.getElementById('step-connector');

  /* ── Estado ──────────────────────────────────────────────── */
  let currentStep = 1;

  /* ── Inicializar ─────────────────────────────────────────── */
  activateStep(1);

  /* ── Formateo COP en tiempo real (mobile-first) ─────────── */
  /* cop-format.js debe cargarse antes que este script        */
  COP.bindInputs(costPrice, salePrice, stockInput);

  /* ── Avanzar al Paso 2 ───────────────────────────────────── */
  btnNext.addEventListener('click', () => {
    const catValue = categoryInput.value.trim();

    if (!catValue) {
      showError(categoryInput, categoryError, 'Por favor, escribe el nombre de tu categoria.');
      return;
    }

    clearError(categoryInput, categoryError);

    /* Inyectar el nombre dinamico en el titulo del paso 2 */
    catNameDisplay.textContent = catValue;

    /* Transicion */
    transitionTo(2);
  });

  /* ── Validacion en tiempo real del campo categoria ──────── */
  categoryInput.addEventListener('input', () => {
    if (categoryInput.value.trim()) {
      clearError(categoryInput, categoryError);
    }
  });

  /* Avanzar tambien con Enter en el input de categoria */
  categoryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnNext.click();
  });

  /* ── Calculo dinamico de ganancia ────────────────────────── */
  [costPrice, salePrice].forEach(input => {
    input.addEventListener('input', updateProfit);
  });

  function updateProfit() {
    const cost = COP.parse(costPrice.value);
    const sale = COP.parse(salePrice.value);

    profitBadge.classList.remove('negative', 'neutral');

    if (isNaN(cost) && isNaN(sale)) {
      profitBadge.textContent = 'Ganancia por unidad: —';
      profitBadge.classList.add('neutral');
      return;
    }

    const profit = (isNaN(sale) ? 0 : sale) - (isNaN(cost) ? 0 : cost);

    if (profit > 0) {
      profitBadge.textContent = `Ganancia por unidad: +$${COP.format(profit)}`;
    } else if (profit < 0) {
      profitBadge.textContent = `Perdida por unidad: -$${COP.format(Math.abs(profit))}`;
      profitBadge.classList.add('negative');
    } else {
      profitBadge.textContent = 'Ganancia por unidad: $0';
      profitBadge.classList.add('neutral');
    }
  }

  /* ── Envio final (conectado a la API) ─────────────────────── */
  btnStart.addEventListener('click', async () => {
    if (!validateStep2()) return;

    const payload = {
      category : categoryInput.value.trim(),
      product  : productName.value.trim(),
      cost     : COP.parse(costPrice.value),
      sale     : COP.parse(salePrice.value),
      stock    : COP.parse(stockInput.value),
    };

    btnStart.disabled      = true;
    btnStart.style.opacity = '0.65';

    try {
      const res  = await fetch('/api/onboarding', {
        method:  'POST',
        headers: jsonHeaders,
        body:    JSON.stringify(payload),
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();

      if (data.ok) {
        window.location.href = data.redirect || '/dashboard';
      } else {
        const errEl = document.getElementById('product-name-error');
        if (errEl) { errEl.textContent = data.msg || 'Error al guardar. Intenta de nuevo.'; }
        btnStart.disabled      = false;
        btnStart.style.opacity = '';
      }
    } catch {
      const errEl = document.getElementById('product-name-error');
      if (errEl) { errEl.textContent = 'Error de conexion. Intenta de nuevo.'; }
      btnStart.disabled      = false;
      btnStart.style.opacity = '';
    }
  });

  /* ── Helpers ─────────────────────────────────────────────── */

  /**
   * Cambia el estado visual del wizard y muestra el paso indicado.
   * @param {1|2} toStep
   */
  function transitionTo(toStep) {
    /* Ocultar paso actual con fade-out */
    const leaving = toStep === 2 ? step1Section : step2Section;
    const entering = toStep === 2 ? step2Section : step1Section;

    leaving.classList.remove('visible');
    entering.classList.add('visible');
    currentStep = toStep;

    activateStep(toStep);

    /* Focus en el primer input del paso entrante */
    const firstInput = entering.querySelector('input');
    if (firstInput) setTimeout(() => firstInput.focus(), 80);
  }

  /**
   * Actualiza el indicador visual de los pasos.
   * @param {1|2} step
   */
  function activateStep(step) {
    if (step === 1) {
      /* Circulo 1: activo */
      setCircle(circle1, label1, 'active');
      /* Circulo 2: pendiente */
      setCircle(circle2, label2, 'pending');
      /* Conector: inactivo */
      connector.classList.remove('connector-active');

    } else if (step === 2) {
      /* Circulo 1: completado */
      circle1.innerHTML = '&#10003;';        /* checkmark */
      setCircle(circle1, label1, 'done');
      /* Circulo 2: activo */
      circle2.textContent = '2';
      setCircle(circle2, label2, 'active');
      /* Conector: activo (azul) */
      connector.classList.add('connector-active');
    }
  }

  /**
   * Aplica las clases CSS al circulo y la etiqueta segun el estado.
   */
  function setCircle(circle, label, state) {
    circle.classList.remove('active', 'done');
    label.classList.remove('active', 'done');

    if (state === 'active') {
      circle.classList.add('active');
      label.classList.add('active');
    } else if (state === 'done') {
      circle.classList.add('done');
      label.classList.add('done');
    }
    /* state === 'pending' → sin clases especiales */
  }

  /**
   * Valida todos los campos del paso 2 y marca errores.
   * @returns {boolean}
   */
  function validateStep2() {
    let valid = true;

    if (!productName.value.trim()) {
      showError(productName, document.getElementById('product-name-error'), 'Escribe el nombre del producto.');
      valid = false;
    } else {
      clearError(productName, document.getElementById('product-name-error'));
    }

    const cost = COP.parse(costPrice.value);
    if (isNaN(cost) || cost < 0) {
      showError(costPrice, document.getElementById('cost-error'), 'Ingresa un precio de costo valido.');
      valid = false;
    } else {
      clearError(costPrice, document.getElementById('cost-error'));
    }

    const sale = COP.parse(salePrice.value);
    if (isNaN(sale) || sale <= 0) {
      showError(salePrice, document.getElementById('sale-error'), 'Ingresa un precio de venta valido.');
      valid = false;
    } else {
      clearError(salePrice, document.getElementById('sale-error'));
    }

    const stock = COP.parse(stockInput.value);
    if (isNaN(stock) || stock < 0) {
      showError(stockInput, document.getElementById('stock-error'), 'Ingresa un stock inicial (0 o mas).');
      valid = false;
    } else {
      clearError(stockInput, document.getElementById('stock-error'));
    }

    return valid;
  }

  function showError(input, msgEl, text) {
    input.classList.add('error-field');
    if (msgEl) { msgEl.textContent = text; msgEl.style.display = 'block'; }
  }

  function clearError(input, msgEl) {
    input.classList.remove('error-field');
    if (msgEl) { msgEl.style.display = 'none'; }
  }

  /* ── Validacion en tiempo real para los campos del paso 2 ── */
  /* Los inputs de precio y stock ya disparan updateProfit via   */
  /* su listener de 'input', aqui solo limpiamos los errores.    */
  productName.addEventListener('input', () => {
    if (productName.value.trim()) clearError(productName, document.getElementById('product-name-error'));
  });
  costPrice.addEventListener('input', () => {
    const v = COP.parse(costPrice.value);
    if (!isNaN(v) && v >= 0) clearError(costPrice, document.getElementById('cost-error'));
  });
  salePrice.addEventListener('input', () => {
    const v = COP.parse(salePrice.value);
    if (!isNaN(v) && v > 0) clearError(salePrice, document.getElementById('sale-error'));
  });
  stockInput.addEventListener('input', () => {
    const v = COP.parse(stockInput.value);
    if (!isNaN(v) && v >= 0) clearError(stockInput, document.getElementById('stock-error'));
  });

});
