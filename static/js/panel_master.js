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
  return res.json();
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
        dd.innerHTML = '<div class="p-3 text-sm text-slate-400">Sin resultados</div>';
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
    rol: $('cu-rol').value,
    password: $('cu-password').value,
    confirm_password: $('cu-confirm').value,
  };

  if (!payload.nombre || !payload.correo || !payload.password) {
    showInlineError('cu-error', 'Completa los campos requeridos.');
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

// Live search Admins (create/edit tienda)
bindLiveSearch(
  'ct-owner-search',
  'ct-owner-dropdown',
  '/api/master/admins',
  (a) => `<button type="button" data-pick='${JSON.stringify({ id: a.id_usuario, name: a.nombre_completo }).replace(/'/g, '&apos;')}' class="w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm">${a.nombre_completo} <span class="text-slate-400">(${a.correo})</span></button>`,
  (pick) => {
    $('ct-owner-search').value = pick.name;
    $('ct-owner-id').value = pick.id;
  }
);

bindLiveSearch(
  'et-owner-search',
  'et-owner-dropdown',
  '/api/master/admins',
  (a) => `<button type="button" data-pick='${JSON.stringify({ id: a.id_usuario, name: a.nombre_completo }).replace(/'/g, '&apos;')}' class="w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm">${a.nombre_completo} <span class="text-slate-400">(${a.correo})</span></button>`,
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
  (t) => `<button type="button" data-pick='${JSON.stringify({ id: t.id_tienda, name: t.nombre_negocio }).replace(/'/g, '&apos;')}' class="w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm">${t.nombre_negocio}</button>`,
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
    es_restaurante: $('ct-es-restaurante').checked,
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
$('btn-confirmar-eliminar').addEventListener('click', async () => {
  const id = $('del-tienda-id').value;
  const data = await jsonFetch('/api/master/tiendas/' + id, { method: 'DELETE' });
  if (!data) return;
  if (!data.ok) return;
  window.location.reload();
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
