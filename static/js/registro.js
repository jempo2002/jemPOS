'use strict';

(function () {
  const input = document.getElementById('contrasena');
  const icon = document.getElementById('eyeIcon');
  const toggleBtn = document.getElementById('toggleBtn');

  if (!input || !icon || !toggleBtn) return;

  toggleBtn.addEventListener('click', () => {
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    icon.className = showing ? 'fa-solid fa-eye text-sm' : 'fa-solid fa-eye-slash text-sm';
  });
}());
