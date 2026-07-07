/* ============================================================
   Ruta: js/landing.js
   Landing Page jemPOS — Interactividad y animaciones
   ------------------------------------------------------------
   Vanilla JS (ES6+), sin dependencias.
   Módulos:
     1. Header con sombra al hacer scroll
     2. Menú móvil accesible
     3. Animaciones de entrada (IntersectionObserver)
     4. Product Tour: scroll vertical → desplazamiento horizontal
        suave (sticky + requestAnimationFrame + lerp)
   Rendimiento:
     - Solo se anima `transform` (acelerado por GPU).
     - Listeners de scroll pasivos; el trabajo pesado vive en rAF.
     - Todo se desactiva con prefers-reduced-motion o en móvil,
       donde el CSS degrada a un carrusel nativo con scroll-snap.
   ============================================================ */

(() => {
  'use strict';

  /** Media queries que gobiernan el comportamiento del tour. */
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const desktopView = window.matchMedia('(min-width: 768px)');

  /* ------------------------------------------------------------
     1. HEADER: sombra sutil cuando la página tiene scroll
     ------------------------------------------------------------ */
  const initHeader = () => {
    const header = document.querySelector('[data-header]');
    if (!header) return;

    let ticking = false;

    const update = () => {
      header.classList.toggle('is-scrolled', window.scrollY > 8);
      ticking = false;
    };

    window.addEventListener('scroll', () => {
      // rAF-throttle: máximo una actualización por frame
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    }, { passive: true });

    update();
  };

  /* ------------------------------------------------------------
     2. MENÚ MÓVIL accesible (aria-expanded + cierre por Escape)
     ------------------------------------------------------------ */
  const initMobileNav = () => {
    const toggle = document.querySelector('[data-nav-toggle]');
    const menu = document.querySelector('[data-nav-menu]');
    if (!toggle || !menu) return;

    const setOpen = (open) => {
      toggle.setAttribute('aria-expanded', String(open));
      menu.classList.toggle('is-open', open);
      toggle.querySelector('.visually-hidden').textContent =
        open ? 'Cerrar menú' : 'Abrir menú';
    };

    toggle.addEventListener('click', () => {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });

    // Cerrar al elegir un enlace (navegación por anclas)
    menu.addEventListener('click', (e) => {
      if (e.target.closest('a')) setOpen(false);
    });

    // Usabilidad (Nielsen: control y libertad del usuario)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') setOpen(false);
    });
  };

  /* ------------------------------------------------------------
     3. ANIMACIONES DE ENTRADA con IntersectionObserver
        Los elementos .reveal aparecen al entrar al viewport.
     ------------------------------------------------------------ */
  const initReveal = () => {
    const elements = document.querySelectorAll('.reveal');
    if (!elements.length) return;

    // Con movimiento reducido el CSS ya los muestra; no observamos nada.
    if (reducedMotion.matches || !('IntersectionObserver' in window)) {
      elements.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target); // animar una sola vez
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -5% 0px' });

    elements.forEach((el) => observer.observe(el));
  };

  /* ------------------------------------------------------------
     4. PRODUCT TOUR: scroll vertical → horizontal suave
     ------------------------------------------------------------
     Técnica:
     - La sección .tour mide ~4×105vh; su hijo .tour__sticky queda
       fijo (position: sticky en CSS) mientras se recorre.
     - El progreso vertical (0..1) se mapea a un "índice virtual"
       de tarjeta con ZONAS DE RETENCIÓN: cada tarjeta permanece
       quieta el 55% de su segmento para dar tiempo de lectura, y
       el 45% restante transiciona con easing suave a la siguiente.
     - El translateX final se interpola (lerp) en un bucle de
       requestAnimationFrame → movimiento orgánico sin saltos,
       tocando solo `transform` (sin reflow, sin lag).
     ------------------------------------------------------------ */
  const initTour = () => {
    const section = document.querySelector('[data-tour]');
    const viewport = document.querySelector('[data-tour-viewport]');
    const track = document.querySelector('[data-tour-track]');
    const cards = [...document.querySelectorAll('[data-tour-card]')];
    const dots = [...document.querySelectorAll('[data-tour-progress] .tour__dot')];
    if (!section || !viewport || !track || cards.length < 2) return;

    const HOLD = 0.55;        // % del segmento en que la tarjeta "descansa"
    const LERP_FACTOR = 0.1;  // suavizado del movimiento (0..1)

    let currentX = 0;         // posición interpolada actual
    let targetX = 0;          // posición objetivo según el scroll
    let maxTranslate = 0;     // desplazamiento horizontal máximo
    let rafId = null;
    let active = false;       // ¿el modo horizontal está activo?

    /** Easing suave para la fase de transición entre tarjetas. */
    const easeInOut = (t) => t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2;

    /**
     * Convierte el progreso global (0..1) en un índice virtual de
     * tarjeta (0..N-1) insertando una zona de retención por tarjeta.
     */
    const progressToIndex = (progress) => {
      const segments = cards.length;
      const pos = Math.min(Math.max(progress, 0), 0.9999) * segments;
      const seg = Math.floor(pos);         // tarjeta actual
      const within = pos - seg;            // avance dentro del segmento

      if (within <= HOLD || seg >= segments - 1) return seg;
      // Fase de transición: easing del tramo restante hacia la siguiente
      return seg + easeInOut((within - HOLD) / (1 - HOLD));
    };

    /** Marca la tarjeta protagonista y sincroniza los puntos ARIA. */
    const setActiveCard = (index) => {
      cards.forEach((card, i) => card.classList.toggle('is-active', i === index));
      dots.forEach((dot, i) => {
        dot.classList.toggle('is-active', i === index);
        dot.setAttribute('aria-selected', String(i === index));
      });
    };

    /** Recalcula medidas (en resize y al activar el modo). */
    const measure = () => {
      maxTranslate = Math.max(track.scrollWidth - viewport.clientWidth, 0);
    };

    /** Lee el scroll y calcula la posición horizontal objetivo. */
    const computeTarget = () => {
      const rect = section.getBoundingClientRect();
      const total = section.offsetHeight - window.innerHeight;
      const progress = total > 0 ? -rect.top / total : 0;

      const virtualIndex = progressToIndex(progress);
      targetX = (virtualIndex / (cards.length - 1)) * maxTranslate;
      setActiveCard(Math.round(virtualIndex));
    };

    /** Bucle de animación: interpola currentX hacia targetX. */
    const loop = () => {
      currentX += (targetX - currentX) * LERP_FACTOR;
      if (Math.abs(targetX - currentX) < 0.1) currentX = targetX;
      track.style.transform = `translate3d(${-currentX}px, 0, 0)`;
      rafId = requestAnimationFrame(loop);
    };

    const onScroll = () => computeTarget();
    const onResize = () => { measure(); computeTarget(); };

    /** Activa/desactiva el modo horizontal según media queries. */
    const evaluateMode = () => {
      const shouldRun = desktopView.matches && !reducedMotion.matches;
      if (shouldRun === active) return;
      active = shouldRun;

      if (shouldRun) {
        measure();
        computeTarget();
        currentX = targetX; // sin animación inicial brusca
        window.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', onResize);
        rafId = requestAnimationFrame(loop);
      } else {
        window.removeEventListener('scroll', onScroll);
        window.removeEventListener('resize', onResize);
        if (rafId) cancelAnimationFrame(rafId);
        track.style.transform = '';
        cards.forEach((c) => c.classList.add('is-active'));
      }
    };

    // Los puntos permiten saltar directo a una tarjeta (Nielsen:
    // visibilidad del estado + control del usuario)
    dots.forEach((dot, i) => {
      dot.addEventListener('click', () => {
        if (!active) return;
        const total = section.offsetHeight - window.innerHeight;
        // Centro de la zona de retención de la tarjeta i
        const progress = (i + HOLD / 2) / cards.length;
        window.scrollTo({
          top: section.offsetTop + progress * total,
          behavior: 'smooth'
        });
      });
    });

    evaluateMode();
    desktopView.addEventListener('change', evaluateMode);
    reducedMotion.addEventListener('change', evaluateMode);
  };

  /* ------------------------------------------------------------
     Arranque
     ------------------------------------------------------------ */
  document.addEventListener('DOMContentLoaded', () => {
    initHeader();
    initMobileNav();
    initReveal();
    initTour();
  });
})();
