/* ============================================================
   Ruta: static/js/cop-format.js
   Utilidad global de formato monetario COP para jemPOS.
   Incluir ANTES de cualquier script de pantalla.

   La moneda colombiana (COP) usa:
     · Punto (.) como separador de miles  →  1.200.000
     · Sin decimales en la practica cotidiana

   API expuesta en window.COP:
     COP.format(1200000)      → "1.200.000"
     COP.parse("1.200.000")   → 1200000
     COP.bindInput(inputEl)   → formatea en tiempo real mientras el usuario escribe
     COP.bindInputs(el, el2)  → igual para multiples inputs
   ============================================================ */

(function (global) {
  'use strict';

  /* ── Nucleo ──────────────────────────────────────────────── */

  /**
   * Formatea un numero entero con separador de miles colombiano (punto).
   * @param {number|string} value  Numero o string sin formato.
   * @returns {string}  "1.200.000" | "" si no es un numero valido.
   */
  function format(value) {
    const digits = String(value).replace(/[^\d]/g, '');
    if (digits === '') return '';
    const n = parseInt(digits, 10);
    /* es-CO: punto como separador de miles */
    return n.toLocaleString('es-CO', { maximumFractionDigits: 0 });
  }

  /**
   * Convierte un string formateado en COP a entero puro.
   * @param {string} str  "1.200.000" | "1200000" | "  "
   * @returns {number}  Entero | NaN si esta vacio/invalido.
   */
  function parse(str) {
    const digits = String(str).replace(/\./g, '').replace(/[^\d]/g, '');
    return digits === '' ? NaN : parseInt(digits, 10);
  }

  /* ── Formateo en tiempo real ──────────────────────────────── */

  /**
   * Adjunta el comportamiento de formateo COP a un input type="tel".
   * Almacena el entero sin formato en `input.dataset.rawValue`.
   *
   * @param {HTMLInputElement} input
   * @param {object}  [opts]
   * @param {boolean} [opts.allowZero=true]   Permite que el valor sea 0.
   * @param {Function}[opts.onChange]         Callback que recibe el valor raw (number).
   */
  function bindInput(input, opts) {
    if (!input) return;
    opts = Object.assign({ allowZero: true, onChange: null }, opts);

    function applyFormat() {
      const raw = input.value.replace(/\./g, '').replace(/[^\d]/g, '');

      if (raw === '') {
        input.value = '';
        input.dataset.rawValue = '';
        if (opts.onChange) opts.onChange(NaN);
        return;
      }

      const n = parseInt(raw, 10);
      const formatted = n.toLocaleString('es-CO', { maximumFractionDigits: 0 });

      /* Preservar posicion del cursor despues del formateo */
      const start = input.selectionStart;
      const prevLen = input.value.length;
      input.value = formatted;
      const delta = formatted.length - prevLen;
      try { input.setSelectionRange(start + delta, start + delta); } catch (_) {}

      input.dataset.rawValue = String(n);
      if (opts.onChange) opts.onChange(n);
    }

    input.addEventListener('input', applyFormat);

    /* Re-formatear al perder el foco por si quedo incompleto */
    input.addEventListener('blur', () => {
      const raw = parse(input.value);
      if (!isNaN(raw)) {
        input.value = format(raw);
        input.dataset.rawValue = String(raw);
      }
    });

    /* Bloquear teclas no numericas en teclados fisicos (desktop) */
    input.addEventListener('keydown', (e) => {
      const allowed = [
        'Backspace', 'Delete', 'Tab', 'Escape', 'Enter',
        'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown',
        'Home', 'End',
      ];
      if (allowed.includes(e.key)) return;
      if (e.ctrlKey || e.metaKey) return;              /* Ctrl+C, Ctrl+V, etc. */
      if (!/^\d$/.test(e.key)) e.preventDefault();     /* Bloquear no-digitos  */
    });
  }

  /**
   * Vincula multiples inputs a la vez.
   * @param {...HTMLInputElement} inputs
   */
  function bindInputs(...inputs) {
    inputs.forEach(el => bindInput(el));
  }

  /* ── Exponemos la API ─────────────────────────────────────── */
  global.COP = { format, parse, bindInput, bindInputs };

})(window);
