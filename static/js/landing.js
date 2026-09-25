/* ============================================================
   Ruta: static/js/landing.js
   Landing de jemPOS: interactividad y animaciones. Vanilla JS, sin
   dependencias.
     1. Header con sombra al hacer scroll
     2. Menu movil accesible (el boton Iniciar sesion vive fuera del menu)
     3. Entrada de secciones y tarjetas con IntersectionObserver
   Solo se anima opacity/transform (GPU). Con prefers-reduced-motion o sin
   IntersectionObserver todo se muestra de una.
   ============================================================ */

(() => {
  'use strict';

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* 1. HEADER: sombra sutil cuando la pagina tiene scroll */
  const initHeader = () => {
    const header = document.querySelector('[data-header]');
    if (!header) return;

    let ticking = false;
    const update = () => {
      header.classList.toggle('is-scrolled', window.scrollY > 8);
      ticking = false;
    };

    window.addEventListener('scroll', () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    }, { passive: true });

    update();
  };

  /* 2. MENU MOVIL (aria-expanded + cierre por Escape, por enlace o fuera) */
  const initMobileNav = () => {
    const toggle = document.querySelector('[data-nav-toggle]');
    const menu = document.querySelector('[data-nav-menu]');
    if (!toggle || !menu) return;

    const setOpen = (open) => {
      toggle.setAttribute('aria-expanded', String(open));
      menu.classList.toggle('is-open', open);
      toggle.querySelector('.visually-hidden').textContent = open ? 'Cerrar menú' : 'Abrir menú';
    };

    toggle.addEventListener('click', () => {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });

    menu.addEventListener('click', (e) => {
      if (e.target.closest('a')) setOpen(false);
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') setOpen(false);
    });

    document.addEventListener('click', (e) => {
      const isOpen = toggle.getAttribute('aria-expanded') === 'true';
      if (isOpen && !menu.contains(e.target) && !toggle.contains(e.target)) {
        setOpen(false);
      }
    });
  };

  /* 3. ENTRADA AL HACER SCROLL
     Las .reveal dentro de un [data-reveal-grupo] entran escalonadas: cada
     una recibe --i (su posicion) y el CSS lo convierte en transition-delay.
     Al terminar se quita --i para que el hover no herede el retraso. */
  const initReveal = () => {
    const elements = document.querySelectorAll('.reveal');
    if (!elements.length) return;

    if (reducedMotion.matches || !('IntersectionObserver' in window)) {
      elements.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    document.querySelectorAll('[data-reveal-grupo]').forEach((grupo) => {
      grupo.querySelectorAll('.reveal').forEach((el, i) => {
        el.style.setProperty('--i', String(Math.min(i, 5)));
      });
    });

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        el.classList.add('is-visible');
        observer.unobserve(el);
        setTimeout(() => el.style.removeProperty('--i'), 1100);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -5% 0px' });

    elements.forEach((el) => observer.observe(el));
  };

  document.addEventListener('DOMContentLoaded', () => {
    initHeader();
    initMobileNav();
    initReveal();
  });
})();
