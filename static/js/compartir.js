/* ============================================================
   Ruta: static/js/compartir.js
   Muestra el boton nativo de compartir (Web Share API) donde el navegador lo
   soporta: en el celular abre la hoja de WhatsApp, Telegram, etc. Donde no,
   el boton sigue oculto y quedan los enlaces de templates/_compartir.html.
   ============================================================ */
(() => {
  'use strict';
  if (typeof navigator.share !== 'function') return;

  document.querySelectorAll('[data-compartir]').forEach((caja) => {
    const boton = caja.querySelector('[data-compartir-nativo]');
    if (!boton) return;
    boton.hidden = false;
    caja.classList.add('compartir--nativo');
    boton.addEventListener('click', () => {
      navigator.share({
        title: document.title,
        text: caja.dataset.texto || '',
        url: caja.dataset.url || location.href,
      }).catch(() => { /* El usuario cerro la hoja: no es un error. */ });
    });
  });
})();
