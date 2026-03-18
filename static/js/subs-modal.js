/* ============================================================
   Ruta: static/js/subs-modal.js
   Modal de aviso de vencimiento proximo de suscripcion.
   Lee window.SUBS inyectado por Flask en cada plantilla POS.
   ============================================================ */

'use strict';

(function () {
  const subs = window.SUBS || {};
  if (!subs.alerta) return;

  const dias = subs.dias || 0;
  const plural = dias === 1 ? 'dia' : 'dias';

  /* ── Estilos del modal ─────────────────────────────────── */
  const style = document.createElement('style');
  style.textContent = `
    #subs-overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(15, 23, 42, 0.55);
      display: flex; align-items: center; justify-content: center;
      padding: 1.25rem;
      animation: subs-fade-in .2s ease both;
    }
    @keyframes subs-fade-in {
      from { opacity: 0; } to { opacity: 1; }
    }
    #subs-card {
      background: #fff;
      border-radius: 1.25rem;
      box-shadow: 0 8px 40px rgba(15,23,42,.18);
      max-width: 360px; width: 100%;
      padding: 2rem 1.75rem 1.75rem;
      text-align: center;
      animation: subs-slide-up .28s cubic-bezier(.22,.68,0,1.15) both;
    }
    @keyframes subs-slide-up {
      from { transform: translateY(24px); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }
    #subs-icon {
      width: 56px; height: 56px; border-radius: 50%;
      background: #FEF3C7;
      display: inline-flex; align-items: center; justify-content: center;
      margin-bottom: 1.1rem;
    }
    #subs-icon i { font-size: 1.5rem; color: #D97706; }
    #subs-title {
      font-size: 1.05rem; font-weight: 700;
      color: #1E293B; margin-bottom: .5rem;
    }
    #subs-body {
      font-size: .875rem; color: #64748B;
      line-height: 1.6; margin-bottom: 1.5rem;
    }
    #subs-body strong { color: #1E293B; }
    #subs-btn {
      display: block; width: 100%;
      padding: .75rem 1rem;
      background: #3B82F6; color: #fff;
      border: none; border-radius: .75rem;
      font-size: .9rem; font-weight: 600;
      cursor: pointer; transition: background .15s;
    }
    #subs-btn:hover { background: #2563EB; }
  `;
  document.head.appendChild(style);

  /* ── Markup del modal ──────────────────────────────────── */
  const overlay = document.createElement('div');
  overlay.id = 'subs-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'subs-title');

  overlay.innerHTML = `
    <div id="subs-card">
      <div id="subs-icon"><i class="fa-solid fa-bell"></i></div>
      <p id="subs-title">Aviso de suscripcion</p>
      <p id="subs-body">
        Hola, paso a recordarte que tu suscripcion de
        <strong>jemPOS</strong> expira en
        <strong>${dias} ${plural}</strong>.
        Por favor, renueva tu suscripcion a tiempo para evitar
        la suspension del servicio.
      </p>
      <button id="subs-btn" type="button">Entendido</button>
    </div>
  `;

  document.body.appendChild(overlay);

  /* ── Cerrar modal ──────────────────────────────────────── */
  document.getElementById('subs-btn').addEventListener('click', function () {
    overlay.remove();
  });

  // Cerrar tambien al hacer clic fuera de la tarjeta
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) overlay.remove();
  });
}());
