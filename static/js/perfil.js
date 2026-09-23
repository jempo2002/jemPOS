/* ============================================================
   Ruta: static/js/perfil.js
   Pantalla: Mi Perfil
   jemPOS — Confianza Financiera
   ============================================================ */

'use strict';

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

/* ── Referencias DOM ─────────────────────────────────────── */
const form           = document.getElementById('perf-form');
const btnGuardar     = document.getElementById('btn-guardar');
const btnIcon        = document.getElementById('btn-guardar-icon');
const btnText        = document.getElementById('btn-guardar-text');

const inpNombre      = document.getElementById('inp-nombre');
const inpNegocio     = document.getElementById('inp-negocio');
const inpTelefono    = document.getElementById('inp-telefono');
const inpCorreo      = document.getElementById('inp-correo');
const inpRol         = document.getElementById('inp-rol');
const btnTogglePassword = document.getElementById('btn-toggle-password');
const passwordFields = document.getElementById('password-fields');

const perfDisplayName = document.getElementById('perf-display-name');

/* ── Helpers ─────────────────────────────────────────────── */
function shake(el) {
  el.classList.remove('perf-shake');
  void el.offsetWidth;   // reflow para reiniciar la animacion
  el.classList.add('perf-shake');
  el.addEventListener('animationend', () => el.classList.remove('perf-shake'), { once: true });
}

function notify(msg, type) {
  if (window.JemToast && typeof window.JemToast.show === 'function') {
    window.JemToast.show(msg, type || 'info', { duration: 3000 });
    return;
  }
  console[type === 'error' ? 'error' : 'log'](msg);
}

/* ── Actualizar nombre en la cabecera en tiempo real ────── */
inpNombre.addEventListener('input', () => {
  const trimmed = inpNombre.value.trim();
  perfDisplayName.textContent = trimmed || perfDisplayName.textContent;
});

/* ── Cargar perfil desde API ────────────────────────────── */
async function initPerfil() {
  const res = await fetch('/api/perfil');
  if (res.status === 401) { window.location.href = '/login'; return; }
  const data = await res.json();
  if (!data.ok) return;
  const p = data.perfil;
  inpNombre.value  = p.nombre_completo  || '';
  inpNegocio.value = p.nombre_negocio   || '';
  if (inpTelefono) inpTelefono.value = p.telefono || '';
  if (inpCorreo) inpCorreo.value = p.correo || '';
  if (inpRol) inpRol.value = p.rol || '';
  perfDisplayName.textContent = p.nombre_completo || '';
  // Actualizar iniciales y rol en la tarjeta de avatar
  const avatarEl = document.getElementById('perf-avatar');
  if (avatarEl && p.nombre_completo) {
    const parts = p.nombre_completo.trim().split(/\s+/);
    avatarEl.textContent = parts.length >= 2
      ? (parts[0][0] + parts[1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase();
  }
  const roleEl = document.querySelector('.perf-display-role');
  if (roleEl && p.rol) roleEl.textContent = p.rol;
}
initPerfil();

/* ── Toggle panel de cambio de contrasena ────────────────── */
if (btnTogglePassword && passwordFields) {
  btnTogglePassword.addEventListener('click', () => {
    const isOpen = passwordFields.classList.toggle('is-open');
    passwordFields.setAttribute('aria-hidden', String(!isOpen));
    btnTogglePassword.setAttribute('aria-expanded', String(isOpen));
    btnTogglePassword.innerHTML = isOpen
      ? '<i class="fa-solid fa-chevron-up"></i> Ocultar Contrasena'
      : '<i class="fa-solid fa-key"></i> Modificar Contrasena';
  });
}

/* ── Guardar cambios ─────────────────────────────────────── */
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  /* Validaciones basicas */
  if (!inpNombre.value.trim()) {
    shake(inpNombre.closest('.perf-field'));
    inpNombre.focus();
    return;
  }

  if (!inpNegocio.value.trim()) {
    shake(inpNegocio.closest('.perf-field'));
    inpNegocio.focus();
    return;
  }

  const telefonoRaw = String(inpTelefono?.value || '').trim();
  const telefono = telefonoRaw.replace(/\D/g, '').slice(0, 10);
  if (telefonoRaw && telefono.length < 7) {
    shake(inpTelefono.closest('.perf-field'));
    inpTelefono.focus();
    return;
  }

  if (inpTelefono) inpTelefono.value = telefono;

  btnGuardar.disabled = true;

  const res = await fetch('/api/perfil', {
    method: 'PUT',
    headers: csrfToken
      ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
      : { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nombre_completo: inpNombre.value.trim(),
      nombre_negocio:  inpNegocio.value.trim(),
      telefono,
    }),
  });

  if (res.status === 401) { window.location.href = '/login'; return; }
  const data = await res.json();

  if (!data.ok) {
    btnGuardar.disabled = false;
    notify(data.msg || 'Error al guardar.', 'error');
    return;
  }

  notify('Cambios guardados correctamente.', 'success');

  /* Feedback visual: boton verde */
  btnGuardar.classList.add('saved');
  btnIcon.className   = 'fa-solid fa-circle-check';
  btnText.textContent = '¡Guardado!';

  setTimeout(() => {
    btnGuardar.disabled = false;
    btnGuardar.classList.remove('saved');
    btnIcon.className   = 'fa-solid fa-floppy-disk';
    btnText.textContent = 'Guardar Cambios';
  }, 2000);
});
