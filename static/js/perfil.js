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

const perfDisplayName = document.getElementById('perf-display-name');

/* ── Helpers ─────────────────────────────────────────────── */
function shake(el) {
  el.classList.remove('perf-shake');
  void el.offsetWidth;   // reflow para reiniciar la animacion
  el.classList.add('perf-shake');
  el.addEventListener('animationend', () => el.classList.remove('perf-shake'), { once: true });
}

/* ── Actualizar nombre en la cabecera en tiempo real ────── */
inpNombre.addEventListener('input', () => {
  const trimmed = inpNombre.value.trim();
  perfDisplayName.textContent = trimmed || perfDisplayName.textContent;
});

/* ── Foto de perfil ──────────────────────────────────────── */
function setProfilePhoto(url) {
  const img    = document.getElementById('perf-avatar-img');
  const avatar = document.getElementById('perf-avatar');
  const btnEliminar = document.getElementById('btn-eliminar-foto');
  if (!img) return;
  img.src = url;
  img.style.display = 'block';
  avatar.style.visibility = 'hidden';
  if (btnEliminar) btnEliminar.classList.remove('hidden');
}

function clearProfilePhoto() {
  const img    = document.getElementById('perf-avatar-img');
  const avatar = document.getElementById('perf-avatar');
  const btnEliminar = document.getElementById('btn-eliminar-foto');
  if (img) {
    img.src = '';
    img.style.display = 'none';
  }
  if (avatar) avatar.style.visibility = 'visible';
  if (btnEliminar) btnEliminar.classList.add('hidden');
}

const cameraBtnEl = document.getElementById('perf-camera-btn');
const inpFoto     = document.getElementById('inp-foto-perfil');

if (cameraBtnEl && inpFoto) {
  cameraBtnEl.addEventListener('click', () => inpFoto.click());

  inpFoto.addEventListener('change', async () => {
    const file = inpFoto.files[0];
    if (!file) return;

    const allowed = ['image/jpeg', 'image/jpg', 'image/png'];
    if (!allowed.includes(file.type)) {
      alert('Solo se permiten imagenes JPG o PNG.');
      inpFoto.value = '';
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      alert('El archivo supera los 5 MB permitidos.');
      inpFoto.value = '';
      return;
    }

    const formData = new FormData();
    formData.append('foto', file);

    cameraBtnEl.disabled = true;
    const res = await fetch('/api/perfil/foto', {
      method: 'POST',
      headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
      body: formData,
    });
    cameraBtnEl.disabled = false;

    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (data.ok) {
      setProfilePhoto(data.url);
    } else {
      alert(data.msg || 'Error al subir la foto.');
    }
    inpFoto.value = '';
  });
}

/* ── Eliminar foto de perfil - con modal de confirmacion ─── */
const btnEliminarFoto = document.getElementById('btn-eliminar-foto');
const modalDeletePhoto = document.getElementById('modal-delete-photo');
const btnConfirmDelete = document.getElementById('btn-confirm-delete');
const btnCancelDelete = document.getElementById('btn-cancel-delete');
const deletePhotoModalClose = document.getElementById('delete-photo-modal-close');

if (btnEliminarFoto && modalDeletePhoto) {
  /* Abrir modal de confirmacion */
  btnEliminarFoto.addEventListener('click', () => {
    modalDeletePhoto.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  });

  /* Cerrar modal */
  function closeDeleteModal() {
    modalDeletePhoto.classList.add('hidden');
    document.body.style.overflow = '';
  }

  if (btnCancelDelete) btnCancelDelete.addEventListener('click', closeDeleteModal);
  if (deletePhotoModalClose) deletePhotoModalClose.addEventListener('click', closeDeleteModal);

  /* Clic fuera del modal lo cierra */
  modalDeletePhoto.addEventListener('click', (e) => {
    if (e.target === modalDeletePhoto) closeDeleteModal();
  });

  /* Escape cierra el modal */
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modalDeletePhoto.classList.contains('hidden')) {
      closeDeleteModal();
    }
  });

  /* Confirmar eliminacion */
  if (btnConfirmDelete) {
    btnConfirmDelete.addEventListener('click', async () => {
      btnConfirmDelete.disabled = true;

      const res = await fetch('/api/perfil/foto', {
        method: 'DELETE',
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
      });

      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();

      if (data.ok) {
        clearProfilePhoto();
        closeDeleteModal();
      } else {
        alert(data.msg || 'Error al eliminar la foto.');
      }

      btnConfirmDelete.disabled = false;
    });
  }
}

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
  if (p.foto_url) {
    setProfilePhoto(p.foto_url);
  } else {
    clearProfilePhoto();
  }
}
initPerfil();

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
    alert(data.msg || 'Error al guardar.');
    return;
  }

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
