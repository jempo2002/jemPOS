// Ruta: static/js/fab-scroll.js
// FAB inteligente: colapsa texto al hacer scroll hacia abajo en movil.

(function initSmartFab() {
  'use strict';

  const MOBILE_MEDIA = '(max-width: 768px)';

  function resolveScrollContainer() {
    const explicit = document.querySelector('[data-fab-scroll-container]');
    if (explicit) return explicit;

    const candidates = [
      '.gast-body',
      '.fiad-body',
      '.inv-body',
      '.ins-main',
      '.prov-content',
      '.main-area',
    ];

    for (const selector of candidates) {
      const el = document.querySelector(selector);
      if (el && el.scrollHeight > el.clientHeight) return el;
    }

    return window;
  }

  function bindSmartFab(fab) {
    const scroller = resolveScrollContainer();
    let lastY = scroller === window ? (window.scrollY || 0) : scroller.scrollTop;
    let ticking = false;

    function updateFab() {
      ticking = false;
      const y = scroller === window ? (window.scrollY || 0) : scroller.scrollTop;
      const delta = y - lastY;

      if (y < 36 || delta < -4) {
        fab.classList.remove('fab-collapsed');
      } else if (delta > 4) {
        fab.classList.add('fab-collapsed');
      }

      lastY = y;
    }

    function onScroll() {
      if (!window.matchMedia(MOBILE_MEDIA).matches) {
        fab.classList.remove('fab-collapsed');
        return;
      }
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(updateFab);
      }
    }

    if (scroller === window) {
      window.addEventListener('scroll', onScroll, { passive: true });
    } else {
      scroller.addEventListener('scroll', onScroll, { passive: true });
    }
    window.addEventListener('resize', onScroll, { passive: true });
  }

  function init() {
    const fabs = document.querySelectorAll('[data-fab-smart]');
    if (!fabs.length) return;
    fabs.forEach(bindSmartFab);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
