/* ============================================================
   Ruta: static/js/cookies.js
   Aviso de cookies — Vanilla JS, sin dependencias.

   Se carga en el <head> SIN defer a proposito. El script corre mientras el
   navegador todavia parsea el <head>, cuando document.documentElement ya
   existe pero el banner aun no se ha pintado: si el usuario ya acepto, marca
   <html data-cookies-ok> y el CSS oculta el banner antes del primer frame.
   Asi no hay parpadeo y no hace falta un <script> inline, que la CSP del
   landing (default-src 'self') bloquearia.

   Sin JavaScript el banner se ve igual, porque en el HTML no viene oculto.
   ============================================================ */

(() => {
  'use strict';

  const CLAVE = 'jempos_cookies_aceptadas';
  const RAIZ = document.documentElement;

  /* localStorage lanza excepcion en modo privado o con el almacenamiento
     bloqueado: si no se puede leer ni escribir, el banner simplemente se
     muestra en cada visita. */
  const leer = () => {
    try {
      return localStorage.getItem(CLAVE) === '1';
    } catch (_) {
      return false;
    }
  };

  const guardar = () => {
    try {
      localStorage.setItem(CLAVE, '1');
    } catch (_) {
      /* Sin persistencia: se oculta solo en esta pagina. */
    }
  };

  /* Paso 1 — antes de pintar: si ya se acepto, el CSS lo oculta. */
  if (leer()) RAIZ.setAttribute('data-cookies-ok', '');

  /* Paso 2 — con el DOM listo: enganchar el boton Aceptar. */
  const init = () => {
    const banner = document.querySelector('[data-cookies]');
    if (!banner) return;

    const aceptar = banner.querySelector('[data-cookies-aceptar]');
    if (!aceptar) return;

    aceptar.addEventListener('click', () => {
      guardar();
      RAIZ.setAttribute('data-cookies-ok', '');
      /* Que el foco no quede en un boton que acaba de desaparecer. */
      if (banner.contains(document.activeElement)) {
        document.activeElement.blur();
      }
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
