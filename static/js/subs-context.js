/* Context bootstrap for RBAC + suscripcion data from template attributes */
(function () {
  var ctx = document.getElementById('app-context');
  if (!ctx) return;

  var rol = ctx.getAttribute('data-user-rol') || '';
  var alertaRaw = ctx.getAttribute('data-subs-alerta') || 'false';
  var diasRaw = ctx.getAttribute('data-subs-dias') || '0';

  var alerta = false;
  try {
    alerta = JSON.parse(alertaRaw);
  } catch (_) {
    alerta = alertaRaw === 'true';
  }

  var dias = parseInt(diasRaw, 10);
  if (isNaN(dias)) dias = 0;

  window.USER_ROL = rol;
  window.SUBS = { alerta: alerta, dias: dias };
})();
