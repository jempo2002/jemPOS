/* ============================================================
   Ruta: static/js/turno.js
   Pantalla: Mi Turno (Apertura / Cierre de Caja)
   jemPOS — Confianza Financiera
   ============================================================ */

'use strict';

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
const jsonHeaders = csrfToken
  ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
  : { 'Content-Type': 'application/json' };

/* ── Referencias DOM ─────────────────────────────────────── */
const stateApertura   = document.getElementById('state-apertura');
const stateCierre     = document.getElementById('state-cierre');

const inpBase         = document.getElementById('inp-base');
const inpCierre       = document.getElementById('inp-cierre');

const btnAbrir        = document.getElementById('btn-abrir');
const btnCerrar       = document.getElementById('btn-cerrar');

const lblHoraApertura = document.getElementById('lbl-hora-apertura');
const lblBaseInicial  = document.getElementById('lbl-base-inicial');

const msgApertura     = document.getElementById('msg-apertura');
const msgCierre       = document.getElementById('msg-cierre');

/* ── Helpers ─────────────────────────────────────────────── */
function shake(el) {
  el.classList.remove('shake');
  void el.offsetWidth;
  el.classList.add('shake');
  el.addEventListener('animationend', () => el.classList.remove('shake'), { once: true });
}

function setMsg(el, msg) {
  if (!el) return;
  el.textContent = msg || '';
}

function setLoading(btn, loading) {
  btn.disabled     = loading;
  btn.style.opacity = loading ? '0.65' : '';
}

function cop(n) {
  return window.COP ? `$${COP.format(n)}` : `$${Number(n).toLocaleString('es-CO')}`;
}

/* ── Formateo COP en tiempo real ─────────────────────────── */
if (window.COP) {
  COP.bindInput(inpBase);
  COP.bindInput(inpCierre);
}

/* ── Mostrar estado apertura ─────────────────────────────── */
function showAperturaState() {
  stateCierre.classList.add('hidden');
  stateApertura.classList.remove('hidden');
  inpBase.value   = '';
  inpCierre.value = '';
  setMsg(msgApertura, '');
  setMsg(msgCierre, '');
  setTimeout(() => inpBase.focus(), 80);
}

/* ── Mostrar estado cierre con datos del turno ───────────── */
function showCierreState(turno) {
  lblHoraApertura.textContent = turno.hora_apertura;
  lblBaseInicial.textContent  = cop(turno.monto_inicial);
  stateApertura.classList.add('hidden');
  stateCierre.classList.remove('hidden');
  setMsg(msgCierre, '');
  setTimeout(() => inpCierre.focus(), 80);
}

/* ── Cargar estado desde el servidor ────────────────────── */
async function initTurno() {
  try {
    const res = await fetch('/api/turno/estado');
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (data.ok && data.turno) {
      showCierreState(data.turno);
    } else {
      showAperturaState();
    }
  } catch {
    showAperturaState();
  }
}

/* ══════════════════════════════════════════════════════════
   ABRIR TURNO
   ══════════════════════════════════════════════════════════ */
btnAbrir.addEventListener('click', async () => {
  setMsg(msgApertura, '');
  const raw = window.COP ? COP.parse(inpBase.value) : Number(inpBase.value.replace(/\D/g, ''));

  if (!raw || raw <= 0) {
    shake(inpBase.closest('.turno-input-group'));
    inpBase.focus();
    return;
  }

  setLoading(btnAbrir, true);
  try {
    const res  = await fetch('/api/turno/abrir', {
      method:  'POST',
      headers: jsonHeaders,
      body:    JSON.stringify({ monto_inicial: raw }),
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();

    if (data.ok) {
      // Refrescar para obtener hora_apertura del servidor
      const estado = await fetch('/api/turno/estado').then(r => r.json());
      if (estado.ok && estado.turno) showCierreState(estado.turno);
    } else {
      setMsg(msgApertura, data.msg || 'No se pudo abrir el turno.');
    }
  } catch {
    setMsg(msgApertura, 'Error de conexion. Intenta de nuevo.');
  } finally {
    setLoading(btnAbrir, false);
  }
});

/* ══════════════════════════════════════════════════════════
   CERRAR TURNO
   ══════════════════════════════════════════════════════════ */
btnCerrar.addEventListener('click', async () => {
  setMsg(msgCierre, '');
  const raw = window.COP ? COP.parse(inpCierre.value) : Number(inpCierre.value.replace(/\D/g, ''));

  if (raw === undefined || raw === null || raw < 0 || isNaN(raw)) {
    shake(inpCierre.closest('.turno-input-group'));
    inpCierre.focus();
    return;
  }

  setLoading(btnCerrar, true);
  try {
    const res  = await fetch('/api/turno/cerrar', {
      method:  'POST',
      headers: jsonHeaders,
      body:    JSON.stringify({ monto_final: raw }),
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();

    if (data.ok) {
      showAperturaState();
    } else {
      setMsg(msgCierre, data.msg || 'No se pudo cerrar el turno.');
    }
  } catch {
    setMsg(msgCierre, 'Error de conexion. Intenta de nuevo.');
  } finally {
    setLoading(btnCerrar, false);
  }
});

/* ── Inicializar ────────────────────────────────────────── */
initTurno();

