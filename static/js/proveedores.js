document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('prov-modal');
  const modalTitle = document.getElementById('prov-modal-title');
  const form = document.getElementById('prov-form');
  const btnNew = document.getElementById('btn-prov-new');
  const btnClose = document.getElementById('prov-modal-close');
  const btnCancel = document.getElementById('prov-modal-cancel');

  const fEmpresa = document.getElementById('prov-empresa');
  const fNombre = document.getElementById('prov-nombre');
  const fCelular = document.getElementById('prov-celular');
  const fCorreo = document.getElementById('prov-correo');
  const fDetalles = document.getElementById('prov-detalles');

  const deleteModal = document.getElementById('prov-delete-modal');
  const deleteClose = document.getElementById('prov-delete-close');
  const deleteCancel = document.getElementById('prov-delete-cancel');
  const deleteForm = document.getElementById('prov-delete-form');
  const deleteText = document.getElementById('prov-delete-text');

  const productsModal = document.getElementById('prov-products-modal');
  const productsClose = document.getElementById('prov-products-close');
  const productsBody = document.getElementById('prov-products-body');
  const productsTitle = document.getElementById('prov-products-title');

  const searchInput = document.getElementById('prov-search');
  const allItems = Array.from(document.querySelectorAll('.prov-item'));
  const emptyLive = document.getElementById('prov-empty-live');

  function esc(v) {
    return String(v || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function openCreateModal() {
    modalTitle.textContent = 'Nuevo Proveedor';
    form.setAttribute('action', '/proveedores/crear');
    fEmpresa.value = '';
    fNombre.value = '';
    fCelular.value = '';
    fCorreo.value = '';
    fDetalles.value = '';
    modal.classList.remove('hidden');
    setTimeout(() => fEmpresa.focus(), 60);
  }

  function openEditModal(btn) {
    const id = btn.getAttribute('data-id');
    modalTitle.textContent = 'Editar Proveedor';
    form.setAttribute('action', `/proveedores/editar/${id}`);

    fEmpresa.value = btn.getAttribute('data-empresa') || '';
    fNombre.value = btn.getAttribute('data-nombre') || '';
    fCelular.value = btn.getAttribute('data-celular') || '';
    fCorreo.value = btn.getAttribute('data-correo') || '';
    fDetalles.value = btn.getAttribute('data-detalles') || '';

    modal.classList.remove('hidden');
    setTimeout(() => fEmpresa.focus(), 60);
  }

  function closeModal() {
    modal.classList.add('hidden');
  }

  function openDeleteModal(btn) {
    const id = btn.getAttribute('data-id');
    const empresa = btn.getAttribute('data-empresa') || 'este proveedor';
    deleteForm.setAttribute('action', `/proveedores/eliminar/${id}`);
    deleteText.textContent = `Estas seguro de eliminar a ${empresa}?`;
    deleteModal.classList.remove('hidden');
  }

  function closeDeleteModal() {
    deleteModal.classList.add('hidden');
  }

  async function openProductsModal(btn) {
    const id = btn.getAttribute('data-id');
    const empresa = btn.getAttribute('data-empresa') || 'Proveedor';
    productsTitle.textContent = `Productos - ${empresa}`;
    productsBody.innerHTML = '<p>Cargando...</p>';
    productsModal.classList.remove('hidden');

    try {
      const res = await fetch(`/api/proveedores/${encodeURIComponent(id)}/productos`);
      const data = await res.json();
      if (!res.ok || !data.ok) {
        productsBody.innerHTML = `<p>${esc(data.msg || 'No se pudo cargar el listado')}</p>`;
        return;
      }

      if (!Array.isArray(data.productos) || data.productos.length === 0) {
        productsBody.innerHTML = '<p>Este proveedor no tiene productos asociados.</p>';
        return;
      }

      productsBody.innerHTML = `
        <div class="prov-products-list">
          ${data.productos.map((p) => `
            <div class="prov-product-item">
              <span>${esc(p.nombre)}</span>
              <small>Stock: ${Number(p.stock_actual || 0)}</small>
            </div>
          `).join('')}
        </div>
      `;
    } catch (_) {
      productsBody.innerHTML = '<p>Error de conexion al cargar productos.</p>';
    }
  }

  function closeProductsModal() {
    productsModal.classList.add('hidden');
  }

  btnNew.addEventListener('click', openCreateModal);
  btnClose.addEventListener('click', closeModal);
  btnCancel.addEventListener('click', closeModal);

  deleteClose.addEventListener('click', closeDeleteModal);
  deleteCancel.addEventListener('click', closeDeleteModal);

  productsClose.addEventListener('click', closeProductsModal);

  function applyLiveSearch() {
    const q = (searchInput?.value || '').trim().toLowerCase();
    let visible = 0;

    allItems.forEach((item) => {
      const hay = (item.getAttribute('data-search') || '').toLowerCase();
      const match = !q || hay.includes(q);
      item.style.display = match ? '' : 'none';
      if (match) visible += 1;
    });

    if (emptyLive) {
      emptyLive.classList.toggle('hidden', visible > 0);
    }
  }

  if (searchInput) {
    searchInput.addEventListener('input', applyLiveSearch);
  }

  document.querySelectorAll('[data-action="edit"]').forEach((btn) => {
    btn.addEventListener('click', () => openEditModal(btn));
  });

  document.querySelectorAll('[data-action="delete"]').forEach((btn) => {
    btn.addEventListener('click', () => openDeleteModal(btn));
  });

  document.querySelectorAll('[data-action="view-products"]').forEach((btn) => {
    btn.addEventListener('click', () => openProductsModal(btn));
  });

  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  deleteModal.addEventListener('click', (e) => { if (e.target === deleteModal) closeDeleteModal(); });
  productsModal.addEventListener('click', (e) => { if (e.target === productsModal) closeProductsModal(); });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!modal.classList.contains('hidden')) closeModal();
    if (!deleteModal.classList.contains('hidden')) closeDeleteModal();
    if (!productsModal.classList.contains('hidden')) closeProductsModal();
  });

  applyLiveSearch();
});
