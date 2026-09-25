/* ============================================================
   Ruta: static/js/analitica.js
   Google Analytics 4 con consentimiento: gtag.js solo se descarga cuando el
   visitante acepto el aviso de cookies (ahora o en una visita anterior). El
   ID llega en data-ga-id desde templates/_analitica.html.

   Archivo externo y no <script> inline: la CSP publica no permite inline.
   ============================================================ */
(() => {
  'use strict';

  const id = document.currentScript && document.currentScript.dataset.gaId;
  if (!id) return;

  /* Misma clave que static/js/cookies.js. */
  const aceptado = () => {
    try {
      return localStorage.getItem('jempos_cookies_aceptadas') === '1';
    } catch (_) {
      return false;
    }
  };

  const cargar = () => {
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
    document.head.appendChild(s);

    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', id);
  };

  if (aceptado()) {
    cargar();
  } else {
    document.addEventListener('jempos:cookies-aceptadas', cargar, { once: true });
  }
})();
