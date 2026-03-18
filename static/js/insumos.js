document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('ins-modal');
  const btnNew = document.getElementById('btn-ins-new');
  const btnClose = document.getElementById('ins-modal-close');
  const btnCancel = document.getElementById('ins-cancel');
  const form = document.getElementById('ins-form');
  const title = document.getElementById('ins-modal-title');

  const fNombre = document.getElementById('ins-nombre');
  const fStock = document.getElementById('ins-stock');
  const fUnidad = document.getElementById('ins-unidad');
  const fCosto = document.getElementById('ins-costo');
  const fProveedor = document.getElementById('ins-proveedor');

  function openCreate() {
    title.textContent = 'Nuevo Insumo';
    form.action = '/insumos/crear';
    form.reset();
    modal.classList.add('open');
    setTimeout(() => fNombre.focus(), 80);
  }

  function openEdit(btn) {
    title.textContent = 'Editar Insumo';
    form.action = `/insumos/editar/${btn.dataset.id}`;
    fNombre.value = btn.dataset.nombre || '';
    fStock.value = btn.dataset.stock || '';
    fUnidad.value = btn.dataset.unidad || 'Un';
    fCosto.value = btn.dataset.costo || '';
    fProveedor.value = btn.dataset.proveedor || '';
    modal.classList.add('open');
    setTimeout(() => fNombre.focus(), 80);
  }

  function closeModal() {
    modal.classList.remove('open');
  }

  btnNew?.addEventListener('click', openCreate);
  btnClose?.addEventListener('click', closeModal);
  btnCancel?.addEventListener('click', closeModal);
  modal?.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  document.querySelectorAll('[data-action="edit"]').forEach((btn) => {
    btn.addEventListener('click', () => openEdit(btn));
  });
});
