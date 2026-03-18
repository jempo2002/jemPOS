// Ruta: static/js/login.js

'use strict';

/* ── Toggle mostrar / ocultar contrasena ─────── */
function togglePassword() {
  const input   = document.getElementById('contrasena');
  const icon    = document.getElementById('eyeIcon');
  const showing = input.type === 'text';

  input.type     = showing ? 'password' : 'text';
  icon.className = showing
    ? 'fa-solid fa-eye'
    : 'fa-solid fa-eye-slash';
}

/* ── Helpers de validacion ───────────────────── */
function showError(fieldId, msgId, message) {
  const field = document.getElementById(fieldId);
  const msg   = document.getElementById(msgId);
  if (!field || !msg) return;
  field.classList.add('input-error');
  msg.textContent = message;
  msg.classList.add('visible');
}

function clearError(fieldId, msgId) {
  const field = document.getElementById(fieldId);
  const msg   = document.getElementById(msgId);
  if (!field || !msg) return;
  field.classList.remove('input-error');
  msg.classList.remove('visible');
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

/* ── Inicializacion ──────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

  // Limpiar error al corregir cada campo
  [['correo', 'err_correo'], ['contrasena', 'err_contrasena']].forEach(([id, errId]) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', () => clearError(id, errId));
  });

  // Binding del boton toggle
  const toggleBtn = document.getElementById('toggleBtn');
  if (toggleBtn) toggleBtn.addEventListener('click', togglePassword);

  // Validacion y envio al servidor
  const form = document.getElementById('formLogin');
  if (!form) return;

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    let valid = true;

    // Correo
    const correo = document.getElementById('correo').value.trim();
    if (!correo) {
      showError('correo', 'err_correo', 'Ingresa tu correo electronico.');
      valid = false;
    } else if (!isValidEmail(correo)) {
      showError('correo', 'err_correo', 'El formato del correo no es valido.');
      valid = false;
    }

    // Contrasena
    const contrasena = document.getElementById('contrasena').value;
    if (!contrasena) {
      showError('contrasena', 'err_contrasena', 'Ingresa tu contrasena.');
      valid = false;
    }

    if (!valid) return;

    const btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;

    try {
      const res  = await fetch('/login', {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body:    JSON.stringify({ correo, contrasena }),
      });
      const contentType = res.headers.get('content-type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        data = await res.json();
      }

      if (data && data.ok) {
        window.location.href = data.redirect;
      } else {
        if (!data) {
          // Respuestas HTML (CSRF, 429, 500) no deben mostrarse como "error de conexion".
          const fallbackMsg = res.status === 429
            ? 'Demasiados intentos. Espera un minuto e intenta de nuevo.'
            : 'No se pudo iniciar sesion. Recarga la pagina e intenta de nuevo.';
          showError('correo', 'err_correo', fallbackMsg);
        } else {
          const failedField = data.field || 'correo';
          if (failedField === 'contrasena') {
            showError('contrasena', 'err_contrasena', data.msg || 'Contrasena incorrecta.');
          } else {
            showError('correo', 'err_correo', data.msg || 'Usuario no encontrado.');
          }
        }
        if (btn) btn.disabled = false;
      }
    } catch {
      showError('correo', 'err_correo', 'No fue posible conectar con el servidor. Intenta de nuevo.');
      if (btn) btn.disabled = false;
    }
  });
});
