// Ruta: static/js/proveedores.js
// Pantalla Proveedores (templates/pos/proveedores.html): CRUD + modal de
// visualizacion (productos asociados con filtro por categoria y paginacion
// client-side).

(function () {
  'use strict';

  var PV_PER_PAGE = 6; // productos por pagina en el modal de visualizacion

  var csrf = document.querySelector('meta[name="csrf-token"]');
  csrf = csrf ? csrf.getAttribute('content') : '';

  function headers() {
    var h = { 'Content-Type': 'application/json' };
    if (csrf) h['X-CSRFToken'] = csrf;
    return h;
  }

  function $(id) { return document.getElementById(id); }

  function toast(msg, isError) {
    if (!window.JemToast) return;
    if (isError) window.JemToast.error(msg);
    else window.JemToast.success(msg);
  }

  function openModal(id) { var m = $(id); if (m) m.classList.add('open'); }
  function closeModal(id) { var m = $(id); if (m) m.classList.remove('open'); }

  var proveedores = [];

  /* ================= Listado ================= */
  async function loadProveedores() {
    try {
      var res = await fetch('/inventario/api/proveedores', { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var data = await res.json();
      if (!data || !data.ok) { toast('No se pudieron cargar los proveedores.', true); return; }
      proveedores = data.proveedores || [];
      renderProveedores();
    } catch (e) {
      toast('Error de conexion.', true);
    }
  }

  function renderProveedores() {
    var list = $('prov-list');
    if (!list) return;
    list.innerHTML = '';

    if (!proveedores.length) {
      var empty = document.createElement('div');
      empty.className = 'inv-empty-state';
      empty.innerHTML = '<i class="fa-solid fa-truck-field"></i><p>Aun no hay proveedores. Anade el primero.</p>';
      list.appendChild(empty);
      return;
    }

    proveedores.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'prov-card';
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.dataset.id = p.id;

      var tel = p.telefono_1 || p.celular || '';
      var tel2 = p.telefono_2 || '';
      var phoneTxt = tel ? tel : 'Sin telefono';
      if (tel2) phoneTxt += ' · ' + tel2;

      card.innerHTML =
        '<div class="prov-avatar"><i class="fa-solid fa-truck-field"></i></div>' +
        '<div class="prov-info">' +
          '<p class="prov-name"></p>' +
          '<p class="prov-phone"></p>' +
        '</div>' +
        '<div class="prov-card-actions">' +
          '<button type="button" class="prov-mini-btn" data-act="edit" aria-label="Editar proveedor"><i class="fa-solid fa-pen"></i></button>' +
          '<button type="button" class="prov-mini-btn danger" data-act="del" aria-label="Eliminar proveedor"><i class="fa-solid fa-trash"></i></button>' +
        '</div>';
      card.querySelector('.prov-name').textContent = p.empresa || 'Proveedor';
      card.querySelector('.prov-phone').textContent = phoneTxt;

      card.addEventListener('click', function (e) {
        var act = e.target.closest('[data-act]');
        if (act) {
          e.stopPropagation();
          if (act.dataset.act === 'edit') openEdit(p);
          else deleteProveedor(p);
          return;
        }
        openView(p.id);
      });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openView(p.id); }
      });

      list.appendChild(card);
    });
  }

  /* ================= Crear / Editar ================= */
  var editingId = null;

  function showProvError(msg) {
    var box = $('prov-error');
    if (!box) return;
    $('prov-error-text').textContent = msg;
    box.classList.remove('hidden');
  }
  function hideProvError() {
    var box = $('prov-error');
    if (box) box.classList.add('hidden');
  }

  function openCreate() {
    editingId = null;
    $('prov-modal-title').textContent = 'Anadir Proveedor';
    $('prov-nombre').value = '';
    $('prov-tel1').value = '';
    $('prov-tel2').value = '';
    hideProvError();
    openModal('modal-proveedor');
    setTimeout(function () { $('prov-nombre').focus(); }, 80);
  }

  function openEdit(p) {
    editingId = p.id;
    $('prov-modal-title').textContent = 'Editar Proveedor';
    $('prov-nombre').value = p.empresa || '';
    $('prov-tel1').value = p.telefono_1 || p.celular || '';
    $('prov-tel2').value = p.telefono_2 || '';
    hideProvError();
    openModal('modal-proveedor');
    setTimeout(function () { $('prov-nombre').focus(); }, 80);
  }

  async function saveProveedor() {
    var empresa = $('prov-nombre').value.trim();
    var tel1 = $('prov-tel1').value.replace(/\D/g, '');
    var tel2 = $('prov-tel2').value.replace(/\D/g, '');

    if (!empresa) { showProvError('El nombre del proveedor es requerido.'); return; }
    if (!tel1) { showProvError('El telefono 1 es requerido.'); return; }
    hideProvError();

    var url = editingId !== null ? '/inventario/api/proveedores/' + editingId : '/inventario/api/proveedores';
    var method = editingId !== null ? 'PUT' : 'POST';
    var btn = $('prov-save');
    btn.disabled = true;
    try {
      var res = await fetch(url, {
        method: method,
        headers: headers(),
        body: JSON.stringify({ empresa: empresa, celular: tel1, telefono_2: tel2 }),
      });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var data = await res.json().catch(function () { return null; });
      if (!data || !data.ok) { showProvError((data && data.msg) || 'No se pudo guardar.'); return; }
      closeModal('modal-proveedor');
      toast(editingId !== null ? 'Proveedor actualizado.' : 'Proveedor anadido.');
      await loadProveedores();
    } catch (e) {
      showProvError('Error de conexion.');
    } finally {
      btn.disabled = false;
    }
  }

  async function deleteProveedor(p) {
    if (!window.confirm('Eliminar el proveedor "' + (p.empresa || '') + '"? Sus productos quedaran sin proveedor.')) return;
    try {
      var res = await fetch('/inventario/api/proveedores/' + p.id, { method: 'DELETE', headers: headers() });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var data = await res.json().catch(function () { return null; });
      if (!data || !data.ok) { toast((data && data.msg) || 'No se pudo eliminar.', true); return; }
      toast('Proveedor eliminado.');
      await loadProveedores();
    } catch (e) {
      toast('Error de conexion.', true);
    }
  }

  /* ================= Ver proveedor (productos) ================= */
  var pv = { all: [], filtered: [], page: 0, category: 'Todas' };

  async function openView(id) {
    openModal('modal-prov-view');
    $('pv-title').textContent = 'Proveedor';
    $('pv-contact').textContent = '';
    $('pv-filters').innerHTML = '';
    $('pv-products').innerHTML = '<div class="pv-empty">Cargando...</div>';
    $('pv-pager').hidden = true;

    try {
      var res = await fetch('/inventario/api/proveedores/' + id + '/productos', { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (res.status === 401) { window.location.href = '/login'; return; }
      var data = await res.json();
      if (!data || !data.ok) { $('pv-products').innerHTML = '<div class="pv-empty">No se pudo cargar.</div>'; return; }

      var prov = proveedores.find(function (x) { return x.id === id; }) || data.proveedor || {};
      $('pv-title').textContent = data.proveedor && data.proveedor.empresa ? data.proveedor.empresa : (prov.empresa || 'Proveedor');
      renderPvContact(prov);

      pv.all = data.productos || [];
      pv.category = 'Todas';
      pv.page = 0;
      buildFilters();
      applyPvFilter();
    } catch (e) {
      $('pv-products').innerHTML = '<div class="pv-empty">Error de conexion.</div>';
    }
  }

  function renderPvContact(prov) {
    var c = $('pv-contact');
    var t1 = prov.telefono_1 || prov.celular || '';
    var t2 = prov.telefono_2 || '';
    var parts = [];
    if (t1) parts.push('<span><i class="fa-solid fa-phone"></i> ' + t1 + '</span>');
    if (t2) parts.push('<span><i class="fa-solid fa-phone"></i> ' + t2 + '</span>');
    c.innerHTML = parts.join('');
  }

  function buildFilters() {
    var cats = ['Todas'];
    pv.all.forEach(function (p) {
      if (p.categoria && cats.indexOf(p.categoria) === -1) cats.push(p.categoria);
    });
    var wrap = $('pv-filters');
    wrap.innerHTML = '';
    if (cats.length <= 2) { wrap.style.display = pv.all.length ? '' : 'none'; }
    else { wrap.style.display = ''; }
    cats.forEach(function (cat) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pv-chip' + (cat === pv.category ? ' is-active' : '');
      b.textContent = cat;
      b.addEventListener('click', function () {
        pv.category = cat;
        pv.page = 0;
        wrap.querySelectorAll('.pv-chip').forEach(function (x) { x.classList.remove('is-active'); });
        b.classList.add('is-active');
        applyPvFilter();
      });
      wrap.appendChild(b);
    });
  }

  function applyPvFilter() {
    pv.filtered = pv.category === 'Todas'
      ? pv.all.slice()
      : pv.all.filter(function (p) { return p.categoria === pv.category; });
    renderPvPage();
  }

  function renderPvPage() {
    var box = $('pv-products');
    var pager = $('pv-pager');
    var pages = Math.max(1, Math.ceil(pv.filtered.length / PV_PER_PAGE));
    if (pv.page >= pages) pv.page = pages - 1;
    if (pv.page < 0) pv.page = 0;

    box.innerHTML = '';
    if (!pv.filtered.length) {
      box.innerHTML = '<div class="pv-empty">Este proveedor no tiene productos en esta categoria.</div>';
      pager.hidden = true;
      return;
    }

    var start = pv.page * PV_PER_PAGE;
    pv.filtered.slice(start, start + PV_PER_PAGE).forEach(function (p) {
      var money = (window.COP && window.COP.format) ? window.COP.format(p.precio_venta) : ('$' + p.precio_venta);
      var row = document.createElement('div');
      row.className = 'pv-product';
      row.innerHTML =
        '<div class="pv-product-info">' +
          '<p class="pv-product-name"></p>' +
          '<p class="pv-product-cat"></p>' +
        '</div>' +
        '<div class="pv-product-right">' +
          '<p class="pv-product-price">' + money + '</p>' +
          '<p class="pv-product-stock">Stock: ' + p.stock_actual + '</p>' +
        '</div>';
      row.querySelector('.pv-product-name').textContent = p.nombre || 'Producto';
      row.querySelector('.pv-product-cat').textContent = p.categoria || '';
      box.appendChild(row);
    });

    // fade sutil al cambiar de pagina/filtro
    box.style.animation = 'none';
    void box.offsetWidth;
    box.style.animation = 'fadeIn 0.25s ease';

    pager.hidden = pages <= 1;
    $('pv-pageinfo').textContent = (pv.page + 1) + ' / ' + pages;
    $('pv-prev').disabled = pv.page === 0;
    $('pv-next').disabled = pv.page >= pages - 1;
  }

  /* ================= Init ================= */
  document.addEventListener('DOMContentLoaded', function () {
    loadProveedores();

    var addBtn = $('btn-add-prov');
    if (addBtn) addBtn.addEventListener('click', openCreate);

    $('prov-save').addEventListener('click', saveProveedor);
    $('prov-cancel').addEventListener('click', function () { closeModal('modal-proveedor'); });
    $('prov-modal-close').addEventListener('click', function () { closeModal('modal-proveedor'); });

    $('pv-close').addEventListener('click', function () { closeModal('modal-prov-view'); });
    $('pv-prev').addEventListener('click', function () { pv.page--; renderPvPage(); });
    $('pv-next').addEventListener('click', function () { pv.page++; renderPvPage(); });

    // Cerrar modales al hacer click en el backdrop
    ['modal-proveedor', 'modal-prov-view'].forEach(function (mid) {
      var m = $(mid);
      if (m) m.addEventListener('click', function (e) { if (e.target === m) closeModal(mid); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      closeModal('modal-proveedor');
      closeModal('modal-prov-view');
    });
  });
})();
