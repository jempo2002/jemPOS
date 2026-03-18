'use strict';

document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  document.querySelectorAll('.sidebar-logout, [data-logout-btn], #btn-logout').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
        });
      } finally {
        window.location.href = '/login';
      }
    });
  });
});
