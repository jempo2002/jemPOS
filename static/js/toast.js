// Ruta: static/js/toast.js
// Sistema global de notificaciones toast para toda la app.

(function initJemToast() {
  'use strict';

  function ensureHost() {
    let host = document.getElementById('jem-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'jem-toast-host';
      host.className = 'jem-toast-host';
      // popover="manual" mete el host en la top layer, la capa de los <dialog>
      // abiertos con showModal() (cobro, fiar, escaner). Ahi ningun z-index
      // compite: con solo z-index el aviso "Abre un turno antes de registrar
      // ventas" quedaba detras del backdrop del modal de cobro.
      if (typeof host.showPopover === 'function') host.popover = 'manual';
      document.body.appendChild(host);
    }
    return host;
  }

  // Reabrir el popover lo pone encima de lo ultimo que entro a la top layer
  // (un modal abierto despues del primer toast).
  // ponytail: sin Popover API (Safari < 17) queda el z-index de siempre.
  function alFrente(host) {
    if (typeof host.showPopover !== 'function') return;
    if (host.matches(':popover-open')) host.hidePopover();
    host.showPopover();
  }

  function normalizeType(type) {
    if (type === 'success' || type === 'error') return type;
    return 'info';
  }

  function show(message, type, options) {
    if (!message) return;

    const opts = options || {};
    const duration = Number.isFinite(opts.duration) ? Math.max(900, opts.duration) : 3000;
    const toastType = normalizeType(type);
    const host = ensureHost();

    const toast = document.createElement('div');
    toast.className = `jem-toast ${toastType}`;
    toast.textContent = String(message);
    host.appendChild(toast);
    alFrente(host);

    requestAnimationFrame(() => {
      toast.classList.add('show');
    });

    const removeToast = () => {
      toast.classList.remove('show');
      toast.classList.add('hide');
      setTimeout(() => {
        toast.remove();
      }, 220);
    };

    setTimeout(removeToast, duration);
    return toast;
  }

  window.JemToast = {
    show,
    success(message, options) {
      return show(message, 'success', options);
    },
    error(message, options) {
      return show(message, 'error', options);
    },
    info(message, options) {
      return show(message, 'info', options);
    },
  };
})();
