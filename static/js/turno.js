/* ============================================================
   Ruta: static/js/turno.js
   Pantalla: Mi Turno (Apertura / Arqueo / Cierre de Caja)
   Depende de: cop-format.js
   ============================================================ */

'use strict';

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
const jsonHeaders = csrfToken
  ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
  : { 'Content-Type': 'application/json' };
const turnoApiBase = '/pos/api/turno';

/* ── Referencias DOM ─────────────────────────────────────── */
const stateApertura  = document.getElementById('state-apertura');
const stateCierre    = document.getElementById('state-cierre');
const stateResultado = document.getElementById('state-resultado');

const inpBase   = document.getElementById('inp-base');
const inpCierre = document.getElementById('inp-cierre');

const btnAbrir      = document.getElementById('btn-abrir');
const btnCerrar     = document.getElementById('btn-cerrar');
const btnNuevoTurno = document.getElementById('btn-nuevo-turno');

const lblHoraApertura   = document.getElementById('lbl-hora-apertura');
const lblBaseInicial    = document.getElementById('lbl-base-inicial');
const lblVentas         = document.getElementById('lbl-ventas');
const lblVentasEfectivo = document.getElementById('lbl-ventas-efectivo');
const lblGastos         = document.getElementById('lbl-gastos');
const lblGastosBase     = document.getElementById('lbl-gastos-base');
const lblEsperado       = document.getElementById('lbl-esperado');

const brkBase   = document.getElementById('brk-base');
const brkVentas = document.getElementById('brk-ventas');
const brkAbonos = document.getElementById('brk-abonos');
const brkGastos = document.getElementById('brk-gastos');
const brkTotal  = document.getElementById('brk-total');

const balanceBox = document.getElementById('turno-balance');

const resIcon       = document.getElementById('res-icon');
const resHeading    = document.getElementById('res-heading');
const resSub        = document.getElementById('res-sub');
const resEsperado   = document.getElementById('res-esperado');
const resContado    = document.getElementById('res-contado');
const resDiferencia = document.getElementById('res-diferencia');

const msgApertura = document.getElementById('msg-apertura');
const msgCierre   = document.getElementById('msg-cierre');

/* Total esperado del turno abierto. Lo manda el servidor; aqui solo se usa
   para pintar el indicador mientras el cajero teclea. La cifra que decide el
   cierre la vuelve a calcular el backend dentro de la transaccion. */
let totalEsperado = 0;

/* ── Helpers ─────────────────────────────────────────────── */
function shake(el) {
  if (!el) return;
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
  if (!btn) return;
  btn.disabled = loading;
  btn.style.opacity = loading ? '0.65' : '';
}

function cop(n) {
  const value = Number(n) || 0;
  return window.COP ? `$${COP.format(value)}` : `$${value.toLocaleString('es-CO')}`;
}

function leerMonto(input) {
  if (!input) return NaN;
  return window.COP ? COP.parse(input.value) : Number(input.value.replace(/\D/g, ''));
}

function mostrar(seccion) {
  [stateApertura, stateCierre, stateResultado].forEach((el) => {
    if (el) el.classList.toggle('hidden', el !== seccion);
  });
}

/* ── Formateo COP en tiempo real ─────────────────────────── */
if (window.COP) {
  COP.bindInput(inpBase);
  /* onChange lo dispara bindInput en cada tecla, ya con el valor formateado
     (ver cop-format.js). No hace falta un listener propio de 'input': se
     ejecutaria antes del formateo y solo duplicaria el repintado. */
  COP.bindInput(inpCierre, { onChange: renderBalance });
} else {
  inpCierre.addEventListener('input', renderBalance);
}

/* ══════════════════════════════════════════════════════════
   INDICADOR CUADRADO / DESCUADRADO
   ══════════════════════════════════════════════════════════ */
function renderBalance() {
  const contado = leerMonto(inpCierre);

  /* Sin cifra todavia no hay nada que comparar: mostrar "faltan $X" antes de
     que el cajero escriba nada lo empuja a cuadrar hacia el numero en vez de
     contar lo que hay. */
  if (inpCierre.value.trim() === '' || !Number.isFinite(contado)) {
    balanceBox.hidden = true;
    balanceBox.className = 'turno-balance';
    balanceBox.textContent = '';
    return;
  }

  const diferencia = Math.round((contado - totalEsperado) * 100) / 100;
  balanceBox.hidden = false;

  if (diferencia === 0) {
    balanceBox.className = 'turno-balance ok';
    balanceBox.innerHTML = 'Caja cuadrada<span class="turno-balance-amount">Coincide con lo esperado</span>';
    return;
  }

  const sobra = diferencia > 0;
  balanceBox.className = 'turno-balance off';
  balanceBox.innerHTML =
    `Caja descuadrada: ${sobra ? 'sobra' : 'falta'}` +
    `<span class="turno-balance-amount">${cop(Math.abs(diferencia))}</span>`;
}

/* ══════════════════════════════════════════════════════════
   ESTADOS
   ══════════════════════════════════════════════════════════ */
function showAperturaState() {
  mostrar(stateApertura);
  inpBase.value = '';
  inpCierre.value = '';
  totalEsperado = 0;
  renderBalance();
  setMsg(msgApertura, '');
  setMsg(msgCierre, '');
  setTimeout(() => inpBase.focus(), 80);
}

function showCierreState(turno) {
  totalEsperado = Number(turno.total_esperado) || 0;

  lblHoraApertura.textContent = turno.hora_apertura || '-';
  lblBaseInicial.textContent  = cop(turno.base ?? turno.monto_inicial);

  lblVentas.textContent         = cop(turno.ventas_total);
  lblVentasEfectivo.textContent = `En efectivo ${cop(turno.ventas_efectivo)}`;

  lblGastos.textContent     = cop(turno.gastos_total);
  lblGastosBase.textContent = `De la base ${cop(turno.gastos_de_base)}`;

  lblEsperado.textContent = cop(totalEsperado);

  brkBase.textContent   = cop(turno.base ?? turno.monto_inicial);
  brkVentas.textContent = cop(turno.ventas_efectivo);
  brkAbonos.textContent = cop(turno.abonos_efectivo);
  brkGastos.textContent = cop(turno.gastos_de_caja);
  brkTotal.textContent  = cop(totalEsperado);

  mostrar(stateCierre);
  inpCierre.value = '';
  renderBalance();
  setMsg(msgCierre, '');
}

function showResultadoState(arqueo) {
  const cuadrado = !!arqueo.cuadrado;
  const diferencia = Number(arqueo.diferencia) || 0;

  resIcon.className = `turno-icon-wrap ${cuadrado ? 'turno-icon-ok' : 'turno-icon-off'}`;
  resIcon.innerHTML = `<i class="fa-solid ${cuadrado ? 'fa-circle-check' : 'fa-triangle-exclamation'}"></i>`;

  resHeading.textContent = cuadrado ? 'Turno cerrado y cuadrado' : 'Turno cerrado con descuadre';
  resSub.textContent = cuadrado
    ? 'El efectivo contado coincide con lo esperado.'
    : `${diferencia > 0 ? 'Sobraron' : 'Faltaron'} ${cop(Math.abs(diferencia))} frente a lo esperado.`;

  resEsperado.textContent   = cop(arqueo.total_esperado);
  resContado.textContent    = cop(arqueo.monto_reportado);
  resDiferencia.textContent = (diferencia > 0 ? '+' : diferencia < 0 ? '-' : '') + cop(Math.abs(diferencia));

  mostrar(stateResultado);
}

/* ── Cargar estado desde el servidor ────────────────────── */
async function initTurno() {
  try {
    const res = await fetch(`${turnoApiBase}/estado`);
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (data.ok && data.turno) showCierreState(data.turno);
    else showAperturaState();
  } catch {
    showAperturaState();
  }
}

/* ══════════════════════════════════════════════════════════
   ABRIR TURNO
   ══════════════════════════════════════════════════════════ */
btnAbrir.addEventListener('click', async () => {
  setMsg(msgApertura, '');
  const raw = leerMonto(inpBase);

  if (!raw || raw <= 0) {
    shake(inpBase.closest('.turno-input-group'));
    inpBase.focus();
    return;
  }

  setLoading(btnAbrir, true);
  try {
    const res = await fetch(`${turnoApiBase}/abrir`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ monto_inicial: raw }),
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();

    if (data.ok) {
      /* Se relee el estado en vez de construirlo aqui: la hora de apertura y
         el esperado los pone el servidor, y duplicar ese calculo en el
         navegador es como empiezan a divergir. */
      const estado = await fetch(`${turnoApiBase}/estado`).then((r) => r.json());
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
  const raw = leerMonto(inpCierre);

  if (inpCierre.value.trim() === '' || !Number.isFinite(raw) || raw < 0) {
    shake(inpCierre.closest('.turno-input-group'));
    inpCierre.focus();
    return;
  }

  setLoading(btnCerrar, true);
  try {
    const res = await fetch(`${turnoApiBase}/cerrar`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ monto_final: raw }),
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();

    if (data.ok) showResultadoState(data.arqueo || { monto_reportado: raw });
    else setMsg(msgCierre, data.msg || 'No se pudo cerrar el turno.');
  } catch {
    setMsg(msgCierre, 'Error de conexion. Intenta de nuevo.');
  } finally {
    setLoading(btnCerrar, false);
  }
});

btnNuevoTurno?.addEventListener('click', showAperturaState);

/* ── Inicializar ────────────────────────────────────────── */
initTurno();
