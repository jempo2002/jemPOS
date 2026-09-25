'use strict';

const $ = (id) => document.getElementById(id);
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

function openModal(id) {
  $(id).classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeModal(id) {
  $(id).classList.add('hidden');
  document.body.style.overflow = '';
}

window.closeModal = closeModal;

async function jsonFetch(url, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };
  if (csrfToken) headers['X-CSRFToken'] = csrfToken;

  const res = await fetch(url, {
    ...options,
    headers,
  });
  if (res.status === 401) {
    window.location.href = '/login';
    return null;
  }
  // Un 500 de Flask llega como HTML: sin este catch el error se tragaba en silencio.
  return res.json().catch(() => ({ ok: false, msg: 'Error del servidor. Intenta de nuevo.' }));
}

function toast(msg, type) {
  if (window.JemToast) window.JemToast.show(msg, type);
}

function showInlineError(elId, msg) {
  const el = $(elId);
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideInlineError(elId) {
  $(elId).classList.add('hidden');
  $(elId).textContent = '';
}

function sanitizePhone(value) {
  return String(value || '').replace(/\D/g, '').slice(0, 10);
}

function bindLiveSearch(inputId, dropdownId, endpoint, mapRow, onSelect) {
  const input = $(inputId);
  const dd = $(dropdownId);
  let timer = null;

  function hideDd() {
    dd.classList.add('hidden');
    dd.innerHTML = '';
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    timer = setTimeout(async () => {
      const data = await jsonFetch(endpoint + '?q=' + encodeURIComponent(q));
      if (!data || !data.ok) return;
      const rows = (data.admins || data.tiendas || []);
      if (!rows.length) {
        dd.innerHTML = '<div class="p-3 text-sm text-slate-500">Sin resultados</div>';
        dd.classList.remove('hidden');
        return;
      }
      dd.innerHTML = rows.map((r) => mapRow(r)).join('');
      dd.classList.remove('hidden');
    }, 250);
  });

  dd.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-pick]');
    if (!btn) return;
    const payload = JSON.parse(btn.dataset.pick);
    onSelect(payload);
    hideDd();
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !dd.contains(e.target)) hideDd();
  });
}

// Close modals from declarative buttons/icons.
document.querySelectorAll('[data-close-modal]').forEach((el) => {
  el.addEventListener('click', () => closeModal(el.dataset.closeModal));
});

// Logout
$('btn-logout').addEventListener('click', async () => {
  await jsonFetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
});

// Modal open buttons
$('btn-abrir-crear-usuario').addEventListener('click', () => openModal('modal-crear-usuario'));
$('btn-abrir-crear-tienda').addEventListener('click', () => openModal('modal-crear-tienda'));
$('btn-abrir-suscripciones').addEventListener('click', () => openModal('modal-suscripciones'));

// Create user
$('form-crear-usuario').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideInlineError('cu-error');

  const payload = {
    nombre: $('cu-nombre').value.trim(),
    correo: $('cu-correo').value.trim(),
    cc: $('cu-cc').value.trim(),
    rol: $('cu-rol').value,
    password: $('cu-password').value,
    confirm_password: $('cu-confirm').value,
  };

  if (!payload.nombre || !payload.cc || !payload.correo || !payload.password) {
    showInlineError('cu-error', 'Completa los campos requeridos (nombre, cedula, correo y contrasena).');
    return;
  }

  const data = await jsonFetch('/api/crear_usuario', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data) return;
  if (!data.ok) {
    showInlineError('cu-error', data.msg || 'No se pudo crear el usuario.');
    return;
  }
  window.location.reload();
});

// Escapa texto para innerHTML. El correo no se sanea al guardarlo y el nombre
// llega ya escapado: se decodifica primero para no mostrar &amp;amp;.
function esc(value) {
  return unescapeHtml(String(value ?? '')).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

const adminRow = (a) => `<button type="button" data-pick="${esc(JSON.stringify({ id: a.id_usuario, name: a.nombre_completo }))}" class="w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm">${esc(a.nombre_completo)} <span class="text-slate-500">(${esc(a.correo)})</span></button>`;

// Live search Admins (create/edit tienda)
bindLiveSearch(
  'ct-owner-search',
  'ct-owner-dropdown',
  '/api/master/admins',
  adminRow,
  (pick) => {
    $('ct-owner-search').value = pick.name;
    $('ct-owner-id').value = pick.id;
  }
);

bindLiveSearch(
  'et-owner-search',
  'et-owner-dropdown',
  '/api/master/admins',
  adminRow,
  (pick) => {
    $('et-owner-search').value = pick.name;
    $('et-owner-id').value = pick.id;
  }
);

// Live search tiendas (suscripciones)
bindLiveSearch(
  'sus-tienda-search',
  'sus-tienda-dropdown',
  '/api/tiendas',
  (t) => `<button type="button" data-pick="${esc(JSON.stringify({ id: t.id_tienda, name: t.nombre_negocio }))}" class="w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm">${esc(t.nombre_negocio)}</button>`,
  (pick) => {
    $('sus-tienda-search').value = pick.name;
    $('sus-id-tienda').value = pick.id;
  }
);

// Create tienda
$('form-crear-tienda').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideInlineError('ct-error');
  const payload = {
    nombre_negocio: $('ct-nombre').value.trim(),
    nit: $('ct-nit').value.trim(),
    telefono: sanitizePhone($('ct-telefono').value),
    owner_id: $('ct-owner-id').value,
  };
  if (!payload.nombre_negocio || !payload.owner_id) {
    showInlineError('ct-error', 'Nombre del negocio y dueno son requeridos.');
    return;
  }
  const data = await jsonFetch('/api/master/tiendas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data) return;
  if (!data.ok) {
    showInlineError('ct-error', data.msg || 'No se pudo crear la tienda.');
    return;
  }
  window.location.reload();
});

// Open edit modal
document.querySelectorAll('.btn-editar-tienda').forEach((btn) => {
  btn.addEventListener('click', () => {
    $('et-id').value = btn.dataset.id;
    $('et-nombre').value = btn.dataset.nombre || '';
    $('et-nit').value = btn.dataset.nit || '';
    $('et-telefono').value = btn.dataset.telefono || '';
    $('et-owner-id').value = btn.dataset.ownerId || '';
    $('et-owner-search').value = btn.dataset.ownerName || '';
    hideInlineError('et-error');
    openModal('modal-editar-tienda');
  });
});

// Update tienda
$('form-editar-tienda').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideInlineError('et-error');
  const id = $('et-id').value;
  const payload = {
    nombre_negocio: $('et-nombre').value.trim(),
    nit: $('et-nit').value.trim(),
    telefono: sanitizePhone($('et-telefono').value),
    owner_id: $('et-owner-id').value,
  };
  if (!payload.nombre_negocio) {
    showInlineError('et-error', 'El nombre del negocio es requerido.');
    return;
  }
  const data = await jsonFetch('/api/master/tiendas/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data) return;
  if (!data.ok) {
    showInlineError('et-error', data.msg || 'No se pudo actualizar la tienda.');
    return;
  }
  window.location.reload();
});

// Open delete modal
document.querySelectorAll('.btn-eliminar-tienda').forEach((btn) => {
  btn.addEventListener('click', () => {
    $('del-tienda-id').value = btn.dataset.id;
    $('del-tienda-nombre').textContent = btn.dataset.nombre;
    openModal('modal-eliminar-tienda');
  });
});

// Delete tienda
$('btn-confirmar-eliminar').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const id = $('del-tienda-id').value;
  btn.disabled = true;
  try {
    const data = await jsonFetch('/api/master/tiendas/' + encodeURIComponent(id), { method: 'DELETE' });
    if (!data) return;
    if (!data.ok) {
      toast(data.msg || 'No se pudo eliminar la tienda.', 'error');
      return;
    }
    document.querySelectorAll(`[data-tienda-row="${CSS.escape(id)}"]`).forEach((el) => el.remove());
    closeModal('modal-eliminar-tienda');
    toast(data.msg || 'Tienda eliminada.', 'success');
  } finally {
    btn.disabled = false;
  }
});

// ---- Gestion de usuarios ----
let usuarios = [];

// El backend guarda nombres ya escapados (sanitize_text): se decodifican para
// mostrarlos con textContent y para que editar no los escape dos veces.
function unescapeHtml(value) {
  const t = document.createElement('textarea');
  t.innerHTML = value || '';
  return t.value;
}

function cell(text, extraClass) {
  const td = document.createElement('td');
  td.className = 'px-4 py-3 ' + (extraClass || 'text-slate-600');
  td.textContent = text;
  return td;
}

function renderUsuarios() {
  const tbody = $('gu-tbody');
  const q = $('gu-buscar').value.trim().toLowerCase();
  const rows = usuarios.filter((u) => !q || [u.nombre, u.cc, u.correo, u.tienda].join(' ').toLowerCase().includes(q));
  tbody.replaceChildren();

  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = cell(usuarios.length ? 'Sin resultados.' : 'No hay usuarios activos.', 'text-center text-slate-500');
    td.colSpan = 5;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  rows.forEach((u) => {
    const tr = document.createElement('tr');
    tr.className = 'border-t border-slate-100';
    const nombre = cell(u.nombre + (u.es_actual ? ' (tu)' : ''), 'font-semibold text-slate-800');
    const correo = document.createElement('span');
    correo.className = 'block text-xs font-normal text-slate-500';
    correo.textContent = u.correo;
    nombre.appendChild(correo);
    tr.append(
      nombre,
      cell(u.rol),
      cell(u.cc || 'Sin CC', u.cc ? 'text-slate-600' : 'text-amber-600'),
      cell(u.tienda || 'Sin tienda', 'text-slate-600 hidden sm:table-cell')
    );

    const acciones = document.createElement('td');
    acciones.className = 'px-4 py-3';
    const wrap = document.createElement('div');
    wrap.className = 'flex gap-2';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 px-3 py-1.5 text-xs font-semibold';
    edit.textContent = 'Editar';
    edit.addEventListener('click', () => abrirEdicion(u));
    wrap.appendChild(edit);
    // El backend es quien manda; ocultar aqui solo evita un clic inutil.
    if (!u.es_actual && u.rol !== 'Master') {
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'rounded-lg bg-red-50 text-red-700 hover:bg-red-100 px-3 py-1.5 text-xs font-semibold';
      del.textContent = 'Eliminar';
      del.addEventListener('click', () => eliminarUsuario(u));
      wrap.appendChild(del);
    }
    acciones.appendChild(wrap);
    tr.appendChild(acciones);
    tbody.appendChild(tr);
  });
}

async function cargarUsuarios() {
  const data = await jsonFetch('/api/master/usuarios');
  if (!data) return;
  if (!data.ok) {
    toast(data.msg || 'No se pudieron cargar los usuarios.', 'error');
    return;
  }
  usuarios = data.usuarios.map((u) => ({
    id: u.id_usuario,
    nombre: unescapeHtml(u.nombre_completo),
    correo: u.correo,
    rol: u.rol,
    cc: u.cc || '',
    tienda: unescapeHtml(u.nombre_negocio),
    es_actual: u.es_actual,
  }));
  renderUsuarios();
}

function cerrarEdicion() {
  $('form-editar-usuario').classList.add('hidden');
  hideInlineError('eu-error');
}

function abrirEdicion(u) {
  $('eu-id').value = u.id;
  $('eu-correo').textContent = '(' + u.correo + ')';
  $('eu-nombre').value = u.nombre;
  $('eu-cc').value = u.cc;
  $('eu-rol').value = u.rol;
  $('eu-rol').disabled = u.es_actual;
  $('eu-password').value = '';
  hideInlineError('eu-error');
  $('form-editar-usuario').classList.remove('hidden');
  $('eu-nombre').focus();
}

async function eliminarUsuario(u) {
  if (!window.confirm(`Eliminar al usuario "${u.nombre}"? Ya no podra iniciar sesion.`)) return;
  const data = await jsonFetch('/api/master/usuarios/' + u.id, { method: 'DELETE' });
  if (!data) return;
  if (!data.ok) {
    toast(data.msg || 'No se pudo eliminar el usuario.', 'error');
    return;
  }
  usuarios = usuarios.filter((x) => x.id !== u.id);
  if ($('eu-id').value === String(u.id)) cerrarEdicion();
  renderUsuarios();
  toast(data.msg || 'Usuario eliminado.', 'success');
}

$('btn-abrir-gestion-usuarios').addEventListener('click', () => {
  cerrarEdicion();
  $('gu-buscar').value = '';
  openModal('modal-gestion-usuarios');
  cargarUsuarios();
});
$('gu-buscar').addEventListener('input', renderUsuarios);
$('eu-cancelar').addEventListener('click', cerrarEdicion);

$('form-editar-usuario').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideInlineError('eu-error');
  const id = $('eu-id').value;
  const payload = {
    nombre: $('eu-nombre').value.trim(),
    cc: $('eu-cc').value.trim(),
    rol: $('eu-rol').value,
    password: $('eu-password').value,
  };
  if (!payload.nombre || !payload.cc) {
    showInlineError('eu-error', 'Nombre y cedula son requeridos.');
    return;
  }
  const data = await jsonFetch('/api/master/usuarios/' + encodeURIComponent(id), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data) return;
  if (!data.ok) {
    showInlineError('eu-error', data.msg || 'No se pudo actualizar el usuario.');
    return;
  }
  cerrarEdicion();
  toast(data.msg || 'Usuario actualizado.', 'success');
  cargarUsuarios();
});

// Suscripciones pills
document.querySelectorAll('.sus-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.sus-pill').forEach((p) => {
      p.classList.remove('bg-blue-600', 'text-white', 'border-blue-600');
    });
    pill.classList.add('bg-blue-600', 'text-white', 'border-blue-600');
    $('sus-meses').value = pill.dataset.months;
    $('sus-fecha-manual').value = '';
  });
});

$('sus-fecha-manual').addEventListener('change', () => {
  if ($('sus-fecha-manual').value) {
    $('sus-meses').value = '';
    document.querySelectorAll('.sus-pill').forEach((p) => p.classList.remove('bg-blue-600', 'text-white', 'border-blue-600'));
  }
});

// Update suscripcion
$('form-suscripciones').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideInlineError('sus-error');

  const payload = {
    id_tienda: $('sus-id-tienda').value,
    meses: $('sus-meses').value,
    fecha_manual: $('sus-fecha-manual').value,
  };

  if (!payload.id_tienda) {
    showInlineError('sus-error', 'Selecciona una tienda.');
    return;
  }
  if (!payload.meses && !payload.fecha_manual) {
    showInlineError('sus-error', 'Selecciona un periodo o una fecha manual.');
    return;
  }

  const data = await jsonFetch('/api/master/suscripciones', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data) return;
  if (!data.ok) {
    showInlineError('sus-error', data.msg || 'No se pudo actualizar la suscripcion.');
    return;
  }
  window.location.reload();
});
