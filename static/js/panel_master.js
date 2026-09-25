'use strict';

const $ = (id) => document.getElementById(id);
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

/* ── Modales ────────────────────────────────────────────────
   Pueden apilarse (Editar usuario se abre sobre Gestion): el scroll del body
   solo vuelve cuando se cierra el ultimo, y Escape cierra el de arriba. */
const modalesAbiertos = () => [...document.querySelectorAll('[data-modal]:not(.hidden)')];

function openModal(id) {
  const modal = $(id);
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  const campo = modal.querySelector('input:not([type="hidden"]):not(:disabled):not(.sr-only), select:not(:disabled)');
  if (campo) setTimeout(() => campo.focus(), 50);
}

function closeModal(id) {
  $(id).classList.add('hidden');
  if (!modalesAbiertos().length) document.body.style.overflow = '';
}

window.closeModal = closeModal;

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const abiertos = modalesAbiertos();
  // El de capa mas alta es el ultimo del DOM (modal-usuario va despues de Gestion).
  if (abiertos.length) closeModal(abiertos[abiertos.length - 1].id);
});

document.querySelectorAll('[data-close-modal]').forEach((el) => {
  el.addEventListener('click', () => closeModal(el.dataset.closeModal));
});

// Clic en el fondo oscuro cierra, igual que las hojas del POS.
document.querySelectorAll('[data-modal]').forEach((modal) => {
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal(modal.id);
  });
});

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

const enviarJson = (url, method, payload) => jsonFetch(url, {
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

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

/* Bloquea el boton de envio mientras la peticion viaja: evita dobles altas. */
async function conEnvio(form, tarea) {
  const btn = form.querySelector('[type="submit"]');
  if (btn) btn.disabled = true;
  try {
    return await tarea();
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Campos numericos (cedula, telefono): solo digitos y con tope de largo.
document.querySelectorAll('[data-solo-digitos]').forEach((el) => {
  el.addEventListener('input', () => {
    el.value = el.value.replace(/\D/g, '').slice(0, Number(el.dataset.soloDigitos));
  });
});

// El backend guarda nombres ya escapados (sanitize_text): se decodifican para
// mostrarlos con textContent y para que editar no los escape dos veces.
function unescapeHtml(value) {
  const t = document.createElement('textarea');
  t.innerHTML = value || '';
  return t.value;
}

// Escapa texto para innerHTML. El correo no se sanea al guardarlo y el nombre
// llega ya escapado: se decodifica primero para no mostrar &amp;amp;.
function esc(value) {
  return unescapeHtml(String(value ?? '')).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
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

const opcionClase = 'w-full text-left p-3 hover:bg-slate-50 border-b border-slate-100 text-sm';
const adminRow = (a) => `<button type="button" data-pick="${esc(JSON.stringify({ id: a.id_usuario, name: unescapeHtml(a.nombre_completo) }))}" class="${opcionClase}">${esc(a.nombre_completo)} <span class="text-slate-500">(${esc(a.correo)})</span></button>`;
const tiendaRow = (t) => `<button type="button" data-pick="${esc(JSON.stringify({ id: t.id_tienda, name: unescapeHtml(t.nombre_negocio) }))}" class="${opcionClase}">${esc(t.nombre_negocio)}</button>`;

// Logout
$('btn-logout').addEventListener('click', async () => {
  await jsonFetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
});

/* ══════════════════════════════════════════════════════════
   USUARIOS: crear y editar comparten #modal-usuario
   ══════════════════════════════════════════════════════════ */
let editando = null;   // usuario en edicion, o null al crear

function sincronizarTienda() {
  // Un Master no pertenece a ninguna tienda: el campo se oculta.
  $('usr-tienda-wrap').classList.toggle('hidden', $('usr-rol').value === 'Master');
}

function abrirUsuario(u) {
  editando = u || null;
  $('form-usuario').reset();
  hideInlineError('usr-error');

  $('modal-usuario-titulo').textContent = u ? 'Editar usuario' : 'Crear usuario';
  $('modal-usuario-sub').textContent = u
    ? 'Actualiza los datos del integrante.'
    : 'Completa los datos del nuevo integrante.';
  $('usr-submit').textContent = u ? 'Guardar cambios' : 'Crear usuario';

  $('usr-nombre').value = u ? u.nombre : '';
  $('usr-correo').value = u ? u.correo : '';
  // La CC queda visible pero bloqueada. Solo una cuenta antigua sin CC puede
  // registrarla (el backend aplica la misma regla).
  const ccBloqueada = Boolean(u && u.cc);
  $('usr-cc').value = u ? u.cc : '';
  $('usr-cc').disabled = ccBloqueada;
  $('usr-cc-ayuda').classList.toggle('hidden', !ccBloqueada);

  $('usr-rol').value = u ? u.rol : 'Cajero';
  $('usr-rol').disabled = Boolean(u && u.es_actual);
  $('usr-tienda-search').value = u ? u.tienda : '';
  $('usr-tienda-id').value = u && u.id_tienda ? String(u.id_tienda) : '';

  $('usr-pass-label').textContent = u ? 'Nueva contraseña (opcional)' : 'Contraseña';
  $('usr-pass-req').classList.toggle('hidden', Boolean(u));
  $('usr-password').placeholder = u ? 'Déjala vacía para no cambiarla' : '';

  sincronizarTienda();
  openModal('modal-usuario');
}

$('btn-abrir-crear-usuario').addEventListener('click', () => abrirUsuario(null));
$('usr-rol').addEventListener('change', sincronizarTienda);
// Escribir invalida la tienda elegida hasta que se escoja otra de la lista.
$('usr-tienda-search').addEventListener('input', () => { $('usr-tienda-id').value = ''; });

bindLiveSearch('usr-tienda-search', 'usr-tienda-dropdown', '/api/tiendas', tiendaRow, (pick) => {
  $('usr-tienda-search').value = pick.name;
  $('usr-tienda-id').value = pick.id;
});

$('form-usuario').addEventListener('submit', (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  hideInlineError('usr-error');

  const rol = $('usr-rol').value;
  const ccEditable = !$('usr-cc').disabled;
  const payload = {
    nombre: $('usr-nombre').value.trim(),
    correo: $('usr-correo').value.trim(),
    rol,
    password: $('usr-password').value,
    confirm_password: $('usr-confirm').value,
  };
  if (ccEditable) payload.cc = $('usr-cc').value.trim();
  if (rol !== 'Master') payload.id_tienda = $('usr-tienda-id').value;   // '' = sin tienda

  if (!payload.nombre || !payload.correo || (ccEditable && !payload.cc) || (!editando && !payload.password)) {
    showInlineError('usr-error', editando
      ? 'Nombre, cédula y correo son obligatorios.'
      : 'Completa los campos obligatorios: nombre, cédula, correo, rol y contraseña.');
    return;
  }
  if (rol !== 'Master' && $('usr-tienda-search').value.trim() && !payload.id_tienda) {
    showInlineError('usr-error', 'Elige la tienda de la lista o deja el campo vacío.');
    return;
  }
  if (payload.password !== payload.confirm_password) {
    showInlineError('usr-error', 'Las contraseñas no coinciden.');
    return;
  }

  conEnvio(form, async () => {
    const data = editando
      ? await enviarJson('/api/master/usuarios/' + encodeURIComponent(editando.id), 'PUT', payload)
      : await enviarJson('/api/crear_usuario', 'POST', payload);
    if (!data) return;
    if (!data.ok) {
      showInlineError('usr-error', data.msg || 'No se pudo guardar el usuario.');
      return;
    }
    closeModal('modal-usuario');
    if ($('modal-gestion-usuarios').classList.contains('hidden')) {
      window.location.reload();   // alta desde Acciones: refresca las tarjetas
      return;
    }
    toast(data.msg || 'Usuario actualizado.', 'success');
    cargarUsuarios();
  });
});

/* ── Gestion de usuarios: listado paginado en el servidor ─── */
const POR_PAGINA_USUARIOS = 10;
let usuarios = [];
let ultimoPedido = 0;
const pagerUsuarios = window.JemFiltros.init({
  id: 'usuarios',
  limit: POR_PAGINA_USUARIOS,
  onChange: () => cargarUsuarios(),
});

const ROL_PILL = {
  Master: 'bg-violet-100 text-violet-700',
  Admin: 'bg-blue-100 text-blue-700',
  Cajero: 'bg-slate-100 text-slate-700',
};

function cell(extraClass) {
  const td = document.createElement('td');
  td.className = 'px-4 lg:px-6 py-3 ' + (extraClass || 'text-slate-600');
  return td;
}

function linea(texto, clase) {
  const span = document.createElement('span');
  span.className = clase;
  span.textContent = texto;
  return span;
}

function filaMensaje(texto) {
  const tr = document.createElement('tr');
  const td = cell('text-center text-slate-500 py-8');
  td.colSpan = 4;
  td.textContent = texto;
  tr.appendChild(td);
  return tr;
}

function botonesUsuario(u) {
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap justify-end gap-2';
  const edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 px-3 py-2 text-xs font-semibold';
  edit.textContent = 'Editar';
  edit.addEventListener('click', () => abrirUsuario(u));
  wrap.appendChild(edit);
  // El backend es quien manda; ocultar aqui solo evita un clic inutil.
  if (!u.es_actual && u.rol !== 'Master') {
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'rounded-lg bg-red-50 text-red-700 hover:bg-red-100 px-3 py-2 text-xs font-semibold';
    del.textContent = 'Eliminar';
    del.addEventListener('click', () => eliminarUsuario(u));
    wrap.appendChild(del);
  }
  return wrap;
}

function renderUsuarios(hayBusqueda) {
  const tbody = $('gu-tbody');
  tbody.replaceChildren();

  if (!usuarios.length) {
    tbody.appendChild(filaMensaje(hayBusqueda ? 'Sin resultados.' : 'No hay usuarios activos.'));
    return;
  }

  usuarios.forEach((u) => {
    const tr = document.createElement('tr');
    tr.className = 'border-t border-slate-100';

    // En movil solo quedan las columnas Usuario y Rol: la tienda y los
    // botones bajan dentro de la celda del usuario (sin scroll lateral a 320px).
    const quien = cell('min-w-0');
    const botonesMovil = botonesUsuario(u);
    botonesMovil.className = 'mt-2 flex flex-wrap gap-2 sm:hidden';
    quien.append(
      linea(u.nombre + (u.es_actual ? ' (tú)' : ''), 'block font-semibold text-slate-800 break-words'),
      linea(u.correo, 'block text-xs text-slate-500 break-all'),
      linea(u.tienda || 'Sin tienda', 'block text-xs text-slate-500 sm:hidden'),
      botonesMovil,
    );

    const rol = cell();
    rol.appendChild(linea(u.rol, 'inline-block rounded-full px-2.5 py-1 text-xs font-semibold ' + (ROL_PILL[u.rol] || ROL_PILL.Cajero)));

    const tienda = cell('hidden sm:table-cell ' + (u.tienda ? 'text-slate-600' : 'text-slate-500'));
    tienda.textContent = u.tienda || 'Sin tienda';

    const acciones = cell('hidden sm:table-cell');
    acciones.appendChild(botonesUsuario(u));

    tr.append(quien, rol, tienda, acciones);
    tbody.appendChild(tr);
  });
}

async function cargarUsuarios() {
  const pedido = ++ultimoPedido;
  const q = $('gu-buscar').value.trim();
  const params = new URLSearchParams({ page: pagerUsuarios.estado.page, limit: POR_PAGINA_USUARIOS });
  if (q) params.set('q', q);
  const data = await jsonFetch('/api/master/usuarios?' + params);
  // Al escribir rapido las respuestas pueden llegar en otro orden: gana la ultima.
  if (!data || pedido !== ultimoPedido) return;
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
    id_tienda: u.id_tienda,
    tienda: unescapeHtml(u.nombre_negocio),
    es_actual: u.es_actual,
  }));
  renderUsuarios(Boolean(q));
  pagerUsuarios.setMeta(data.meta);
}

async function eliminarUsuario(u) {
  if (!window.confirm(`¿Eliminar al usuario "${u.nombre}"? Ya no podrá iniciar sesión.`)) return;
  const data = await jsonFetch('/api/master/usuarios/' + encodeURIComponent(u.id), { method: 'DELETE' });
  if (!data) return;
  if (!data.ok) {
    toast(data.msg || 'No se pudo eliminar el usuario.', 'error');
    return;
  }
  toast(data.msg || 'Usuario eliminado.', 'success');
  cargarUsuarios();   // si era el ultimo de su pagina, el backend devuelve la anterior
}

$('btn-abrir-gestion-usuarios').addEventListener('click', () => {
  $('gu-buscar').value = '';
  pagerUsuarios.estado.page = 1;
  $('gu-tbody').replaceChildren(filaMensaje('Cargando...'));
  openModal('modal-gestion-usuarios');
  cargarUsuarios();
});

let timerBusqueda = null;
$('gu-buscar').addEventListener('input', () => {
  clearTimeout(timerBusqueda);
  timerBusqueda = setTimeout(() => {
    pagerUsuarios.estado.page = 1;   // nueva busqueda, pagina 1
    cargarUsuarios();
  }, 250);
});

/* ══════════════════════════════════════════════════════════
   TIENDAS
   ══════════════════════════════════════════════════════════ */
$('btn-abrir-crear-tienda').addEventListener('click', () => openModal('modal-crear-tienda'));

bindLiveSearch('ct-owner-search', 'ct-owner-dropdown', '/api/master/admins', adminRow, (pick) => {
  $('ct-owner-search').value = pick.name;
  $('ct-owner-id').value = pick.id;
});

bindLiveSearch('et-owner-search', 'et-owner-dropdown', '/api/master/admins', adminRow, (pick) => {
  $('et-owner-search').value = pick.name;
  $('et-owner-id').value = pick.id;
});

$('form-crear-tienda').addEventListener('submit', (e) => {
  e.preventDefault();
  hideInlineError('ct-error');
  const payload = {
    nombre_negocio: $('ct-nombre').value.trim(),
    nit: $('ct-nit').value.trim(),
    telefono: $('ct-telefono').value,
    owner_id: $('ct-owner-id').value,
  };
  if (!payload.nombre_negocio || !payload.owner_id) {
    showInlineError('ct-error', 'El nombre del negocio y el dueño son obligatorios.');
    return;
  }
  conEnvio(e.currentTarget, async () => {
    const data = await enviarJson('/api/master/tiendas', 'POST', payload);
    if (!data) return;
    if (!data.ok) {
      showInlineError('ct-error', data.msg || 'No se pudo crear la tienda.');
      return;
    }
    window.location.reload();
  });
});

document.querySelectorAll('.btn-editar-tienda').forEach((btn) => {
  btn.addEventListener('click', () => {
    $('et-id').value = btn.dataset.id;
    $('et-nombre').value = unescapeHtml(btn.dataset.nombre);
    $('et-nit').value = unescapeHtml(btn.dataset.nit);
    $('et-telefono').value = btn.dataset.telefono || '';
    $('et-owner-id').value = btn.dataset.ownerId || '';
    $('et-owner-search').value = unescapeHtml(btn.dataset.ownerName);
    hideInlineError('et-error');
    openModal('modal-editar-tienda');
  });
});

$('form-editar-tienda').addEventListener('submit', (e) => {
  e.preventDefault();
  hideInlineError('et-error');
  const id = $('et-id').value;
  const payload = {
    nombre_negocio: $('et-nombre').value.trim(),
    nit: $('et-nit').value.trim(),
    telefono: $('et-telefono').value,
    owner_id: $('et-owner-id').value,
  };
  if (!payload.nombre_negocio) {
    showInlineError('et-error', 'El nombre del negocio es obligatorio.');
    return;
  }
  conEnvio(e.currentTarget, async () => {
    const data = await enviarJson('/api/master/tiendas/' + encodeURIComponent(id), 'PUT', payload);
    if (!data) return;
    if (!data.ok) {
      showInlineError('et-error', data.msg || 'No se pudo actualizar la tienda.');
      return;
    }
    window.location.reload();
  });
});

document.querySelectorAll('.btn-eliminar-tienda').forEach((btn) => {
  btn.addEventListener('click', () => {
    $('del-tienda-id').value = btn.dataset.id;
    $('del-tienda-nombre').textContent = unescapeHtml(btn.dataset.nombre);
    openModal('modal-eliminar-tienda');
  });
});

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
    // Recargar: la pagina actual se reacomoda y las tarjetas cambian.
    window.location.reload();
  } finally {
    btn.disabled = false;
  }
});

/* ── Suscripciones ─────────────────────────────────────── */
$('btn-abrir-suscripciones').addEventListener('click', () => openModal('modal-suscripciones'));

bindLiveSearch('sus-tienda-search', 'sus-tienda-dropdown', '/api/tiendas', tiendaRow, (pick) => {
  $('sus-tienda-search').value = pick.name;
  $('sus-id-tienda').value = pick.id;
});

const PILL_ACTIVA = ['bg-blue-600', 'text-white', 'border-blue-600', 'hover:bg-blue-600'];

document.querySelectorAll('.sus-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.sus-pill').forEach((p) => p.classList.remove(...PILL_ACTIVA));
    pill.classList.add(...PILL_ACTIVA);
    $('sus-meses').value = pill.dataset.months;
    $('sus-fecha-manual').value = '';
  });
});

$('sus-fecha-manual').addEventListener('change', () => {
  if ($('sus-fecha-manual').value) {
    $('sus-meses').value = '';
    document.querySelectorAll('.sus-pill').forEach((p) => p.classList.remove(...PILL_ACTIVA));
  }
});

$('form-suscripciones').addEventListener('submit', (e) => {
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
    showInlineError('sus-error', 'Selecciona un periodo o una fecha.');
    return;
  }

  conEnvio(e.currentTarget, async () => {
    const data = await enviarJson('/api/master/suscripciones', 'POST', payload);
    if (!data) return;
    if (!data.ok) {
      showInlineError('sus-error', data.msg || 'No se pudo actualizar la suscripción.');
      return;
    }
    window.location.reload();
  });
});

/* ══════════════════════════════════════════════════════════
   FINANZAS DEL PROYECTO (ingresos y gastos del SaaS)
   ══════════════════════════════════════════════════════════ */
if (window.COP) window.COP.bindInput($('mov-monto'));

$('btn-abrir-movimiento').addEventListener('click', () => {
  $('form-movimiento').reset();
  $('mov-fecha').value = $('mov-fecha').dataset.hoy;
  hideInlineError('mov-error');
  openModal('modal-movimiento');
});

$('form-movimiento').addEventListener('submit', (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  hideInlineError('mov-error');
  const monto = window.COP ? window.COP.parse($('mov-monto').value) : parseInt($('mov-monto').value.replace(/\D/g, ''), 10);
  const payload = {
    tipo: form.querySelector('[name="mov-tipo"]:checked').value,
    concepto: $('mov-concepto').value.trim(),
    monto,
    fecha: $('mov-fecha').value,
  };
  if (!payload.concepto || !(monto > 0) || !payload.fecha) {
    showInlineError('mov-error', 'Completa el concepto, un monto mayor a cero y la fecha.');
    return;
  }
  conEnvio(form, async () => {
    const data = await enviarJson('/api/master/movimientos', 'POST', payload);
    if (!data) return;
    if (!data.ok) {
      showInlineError('mov-error', data.msg || 'No se pudo registrar el movimiento.');
      return;
    }
    window.location.reload();
  });
});

document.querySelectorAll('.btn-eliminar-movimiento').forEach((btn) => {
  btn.addEventListener('click', async () => {
    if (!window.confirm(`¿Eliminar el movimiento "${unescapeHtml(btn.dataset.concepto)}"?`)) return;
    btn.disabled = true;
    const data = await jsonFetch('/api/master/movimientos/' + encodeURIComponent(btn.dataset.id), { method: 'DELETE' });
    btn.disabled = false;
    if (!data) return;
    if (!data.ok) {
      toast(data.msg || 'No se pudo eliminar el movimiento.', 'error');
      return;
    }
    window.location.reload();
  });
});
