/* ============================================================
   Ruta: static/js/filtros-paginacion.js
   Control compartido de capsulas de tiempo + fecha + paginacion.
   Lo usan Ventas y Gastos; el markup vive en templates/pos/_filtros.html
   y templates/pos/_paginador.html, los estilos en global.css (.jem-*).

   API:
     const f = JemFiltros.init({
       id: 'ventas',                 // debe coincidir con data-jem-filters
       filtro: 'mes',                // capsula inicial
       limit: 20,
       onChange: (params) => {...},  // params = {filtro, fecha, page, limit}
     });
     f.setMeta(meta);   // pinta el paginador con la respuesta de la API
     f.reload();        // vuelve a disparar onChange con el estado actual

   Regla clave: cambiar de capsula o de fecha REINICIA a la pagina 1. Solo los
   botones Anterior/Siguiente mueven la pagina.
   ============================================================ */

(function (global) {
  'use strict';

  function init(opciones) {
    const cfg = Object.assign({ id: 'default', filtro: 'mes', limit: 20, onChange: null }, opciones);

    const raiz = document.querySelector(`[data-jem-filters="${cfg.id}"]`);
    const pager = document.querySelector(`[data-jem-pager="${cfg.id}"]`);

    // La capsula inicial es la que el servidor marco como activa en el HTML;
    // cfg.filtro solo sirve de respaldo (por ejemplo, si no hay capsulas).
    const pillActiva = raiz ? raiz.querySelector('.jem-pill.active') : null;
    const estado = {
      filtro: (pillActiva && pillActiva.dataset.periodo) || cfg.filtro,
      fecha: '',
      page: 1,
      limit: cfg.limit,
    };

    const inputFecha = raiz ? raiz.querySelector('[data-jem-fecha]') : null;
    const btnLimpiar = raiz ? raiz.querySelector('[data-jem-fecha-clear]') : null;
    const btnPrev = pager ? pager.querySelector('[data-jem-prev]') : null;
    const btnNext = pager ? pager.querySelector('[data-jem-next]') : null;
    const labelPage = pager ? pager.querySelector('[data-jem-pager-page]') : null;
    const labelInfo = pager ? pager.querySelector('[data-jem-pager-info]') : null;

    function emitir() {
      if (typeof cfg.onChange === 'function') cfg.onChange(Object.assign({}, estado));
    }

    function marcarPill() {
      if (!raiz) return;
      raiz.querySelectorAll('.jem-pill').forEach(btn => {
        /* Con una fecha concreta ninguna capsula manda */
        btn.classList.toggle('active', !estado.fecha && btn.dataset.periodo === estado.filtro);
      });
    }

    /* ── Capsulas ─────────────────────────────────────────── */
    if (raiz) {
      raiz.querySelectorAll('.jem-pill').forEach(btn => {
        btn.addEventListener('click', () => {
          estado.filtro = btn.dataset.periodo || 'mes';
          estado.fecha = '';              /* la capsula anula la fecha */
          estado.page = 1;                /* y siempre vuelve a la pagina 1 */
          if (inputFecha) inputFecha.value = '';
          if (btnLimpiar) btnLimpiar.classList.add('hidden');
          marcarPill();
          emitir();
        });
      });
    }

    /* ── Buscador de un dia ───────────────────────────────── */
    if (inputFecha) {
      inputFecha.addEventListener('change', () => {
        estado.fecha = inputFecha.value || '';
        estado.page = 1;                  /* nueva busqueda, pagina 1 */
        if (btnLimpiar) btnLimpiar.classList.toggle('hidden', !estado.fecha);
        marcarPill();
        emitir();
      });
    }

    if (btnLimpiar) {
      btnLimpiar.addEventListener('click', () => {
        estado.fecha = '';
        estado.page = 1;
        if (inputFecha) inputFecha.value = '';
        btnLimpiar.classList.add('hidden');
        marcarPill();
        emitir();
      });
    }

    /* ── Paginacion ───────────────────────────────────────── */
    function mover(delta) {
      const siguiente = estado.page + delta;
      if (siguiente < 1) return;
      estado.page = siguiente;
      emitir();
    }

    if (btnPrev) btnPrev.addEventListener('click', () => mover(-1));
    if (btnNext) btnNext.addEventListener('click', () => mover(1));

    /**
     * Pinta el paginador con los metadatos del servidor y adopta su `page`:
     * si se pidio una pagina fuera de rango, el backend devuelve la ultima y el
     * estado local se sincroniza para que Anterior/Siguiente sigan coherentes.
     */
    function setMeta(meta) {
      if (!meta) return;
      const page = Number(meta.page) || 1;
      const pages = Number(meta.pages) || 1;
      const total = Number(meta.total) || 0;
      estado.page = page;

      if (!pager) return;
      /* Con una sola pagina el paginador no aporta nada */
      pager.classList.toggle('hidden', total === 0 || pages <= 1);
      if (labelPage) labelPage.textContent = `${page} / ${pages}`;
      if (labelInfo) {
        const desde = total === 0 ? 0 : (page - 1) * (Number(meta.limit) || estado.limit) + 1;
        const hasta = Math.min(total, desde + (Number(meta.limit) || estado.limit) - 1);
        labelInfo.textContent = `Mostrando ${desde}-${hasta} de ${total}`;
      }
      if (btnPrev) btnPrev.disabled = !meta.has_prev;
      if (btnNext) btnNext.disabled = !meta.has_next;
    }

    /** Query string listo para la API, sin claves vacias. */
    function query() {
      const p = new URLSearchParams({ page: estado.page, limit: estado.limit });
      if (estado.fecha) p.set('fecha', estado.fecha);
      else p.set('filtro', estado.filtro);
      return p.toString();
    }

    marcarPill();

    return {
      estado,
      setMeta,
      query,
      reload: emitir,
    };
  }

  global.JemFiltros = { init };
})(window);
