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
      document.body.appendChild(host);
    }
    return host;
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
