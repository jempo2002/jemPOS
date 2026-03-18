'use strict';

(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  function csrfHeaders(extra = {}) {
    return csrfToken ? { ...extra, 'X-CSRFToken': csrfToken } : extra;
  }

  const modal = document.getElementById('modal-crear-usuario');
  const overlay = document.getElementById('modal-cu-overlay');
  const btnAbrir = document.getElementById('btn-abrir-crear-usuario');
  const btnCerrar = document.getElementById('btn-cerrar-modal-cu');
  const form = document.getElementById('form-crear-usuario');
  const pwdInput = document.getElementById('cu-password');
  const cfmInput = document.getElementById('cu-confirm');
  const errorBox = document.getElementById('cu-error-box');
  const errorMsg = document.getElementById('cu-error-msg');

  const checks = {
    length: document.getElementById('chk-length'),
    upper: document.getElementById('chk-upper'),
    lower: document.getElementById('chk-lower'),
    number: document.getElementById('chk-number'),
  };

  document.getElementById('cu-toggle-pwd').addEventListener('click', function () {
    const showing = pwdInput.type === 'text';
    pwdInput.type = showing ? 'password' : 'text';
    document.getElementById('cu-eye-icon').className = showing ? 'fa-solid fa-eye' : 'fa-solid fa-eye-slash';
    this.setAttribute('aria-label', showing ? 'Mostrar contrasena' : 'Ocultar contrasena');
  });

  btnAbrir.addEventListener('click', function () {
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    document.getElementById('cu-nombre').focus();
  });

  function closeModal() {
    modal.classList.add('hidden');
    modal.style.display = '';
    form.reset();
    hideError();
    ['length', 'upper', 'lower', 'number'].forEach(function (k) {
      setCheck(k, false);
    });
    const w1 = document.getElementById('cu-negocio-wrap');
    const w2 = document.getElementById('cu-tienda-wrap');
    const dd = document.getElementById('cu-tienda-dropdown');
    if (w1) w1.style.display = 'none';
    if (w2) w2.style.display = 'none';
    if (dd) {
      dd.style.display = 'none';
      dd.innerHTML = '';
    }
  }

  btnCerrar.addEventListener('click', closeModal);
  overlay.addEventListener('click', closeModal);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeModal();
  });

  const cuRolSel = document.getElementById('cu-rol');
  if (cuRolSel) {
    cuRolSel.addEventListener('change', function () {
      const negWrap = document.getElementById('cu-negocio-wrap');
      const tidWrap = document.getElementById('cu-tienda-wrap');
      if (negWrap) negWrap.style.display = cuRolSel.value === 'Admin' ? '' : 'none';
      if (tidWrap) tidWrap.style.display = cuRolSel.value === 'Cajero' ? '' : 'none';
    });

    const tidSearch = document.getElementById('cu-tienda-search');
    const tidDd = document.getElementById('cu-tienda-dropdown');
    const tidIdInp = document.getElementById('cu-tienda-id');
    if (tidSearch && tidDd && tidIdInp) {
      let tidTimer;
      tidSearch.addEventListener('input', function () {
        clearTimeout(tidTimer);
        tidIdInp.value = '';
        const q = tidSearch.value.trim();
        if (!q) {
          tidDd.style.display = 'none';
          tidDd.innerHTML = '';
          return;
        }
        tidTimer = setTimeout(async function () {
          try {
            const res = await fetch('/api/tiendas?q=' + encodeURIComponent(q));
            const data = await res.json();
            if (!data.ok || !data.tiendas.length) {
              tidDd.innerHTML = '<div style="padding:.6rem 1rem;font-size:.82rem;color:#94A3B8;">Sin resultados</div>';
            } else {
              tidDd.innerHTML = data.tiendas
                .map(function (t) {
                  const safe = t.nombre_negocio.replace(/"/g, '&quot;');
                  return '<button type="button" data-id="' + t.id_tienda + '" data-name="' + safe + '"'
                    + ' class="cu-store-item"'
                    + '>'
                    + t.nombre_negocio + '</button>';
                })
                .join('');
            }
            tidDd.style.display = 'block';
          } catch (_) {
          }
        }, 280);
      });
      tidDd.addEventListener('click', function (e) {
        const btn = e.target.closest('button[data-id]');
        if (!btn) return;
        tidSearch.value = btn.dataset.name;
        tidIdInp.value = btn.dataset.id;
        tidDd.style.display = 'none';
      });
      document.addEventListener('click', function (e) {
        if (!tidSearch.contains(e.target) && !tidDd.contains(e.target)) tidDd.style.display = 'none';
      });
    }
  }

  pwdInput.addEventListener('input', function () {
    const v = pwdInput.value;
    setCheck('length', v.length >= 8);
    setCheck('upper', /[A-Z]/.test(v));
    setCheck('lower', /[a-z]/.test(v));
    setCheck('number', /\d/.test(v));
  });

  function setCheck(key, ok) {
    const li = checks[key];
    const icon = li.querySelector('i');
    const span = li.querySelector('span');
    if (ok) {
      icon.style.color = '#10B981';
      icon.className = 'fa-solid fa-circle-check';
      span.style.color = '#059669';
    } else {
      icon.style.color = '#CBD5E1';
      icon.className = 'fa-solid fa-circle';
      span.style.color = '#94A3B8';
    }
  }

  function showError(msg) {
    errorMsg.textContent = msg;
    errorBox.style.display = 'flex';
  }

  function hideError() {
    errorBox.style.display = 'none';
  }

  function showToast(msg, ok) {
    const bg = ok ? '#F0FDF4' : '#FEF2F2';
    const br = ok ? '#BBF7D0' : '#FECACA';
    const fg = ok ? '#166534' : '#B91C1C';
    const ic = ok ? 'fa-circle-check' : 'fa-circle-exclamation';
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;top:1rem;left:50%;transform:translateX(-50%);z-index:10000;width:min(92vw,400px);';
    wrap.innerHTML = `<div role="alert" style="background:${bg};border:1px solid ${br};color:${fg};border-radius:.75rem;padding:.85rem 1rem;font-size:.875rem;font-weight:500;display:flex;align-items:center;gap:.6rem;box-shadow:0 4px 16px rgba(0,0,0,.12);animation:cu-slide-up .2s ease both;"><i class="fa-solid ${ic}" style="flex-shrink:0"></i>${msg}</div>`;
    document.body.appendChild(wrap);
    setTimeout(function () {
      wrap.style.transition = 'opacity .4s';
      wrap.style.opacity = '0';
      setTimeout(function () {
        wrap.remove();
      }, 400);
    }, 3500);
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    hideError();

    const nombre = document.getElementById('cu-nombre').value.trim();
    const cedula = (document.getElementById('cu-cedula')?.value || '').trim();
    const telefono = (document.getElementById('cu-telefono')?.value || '').trim();
    const correo = document.getElementById('cu-correo').value.trim();
    const password = pwdInput.value;
    const confirm = cfmInput.value;
    const rolEl = document.getElementById('cu-rol');
    const rol = rolEl ? rolEl.value : null;

    if (!nombre) {
      showError('El nombre completo es requerido.');
      return;
    }
    if (!correo || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(correo)) {
      showError('Ingresa un correo valido.');
      return;
    }
    if (password.length < 8) {
      showError('La contrasena debe tener al menos 8 caracteres.');
      return;
    }
    if (!/[A-Z]/.test(password)) {
      showError('Falta una letra mayuscula.');
      return;
    }
    if (!/[a-z]/.test(password)) {
      showError('Falta una letra minuscula.');
      return;
    }
    if (!/\d/.test(password)) {
      showError('Falta un numero.');
      return;
    }
    if (password !== confirm) {
      showError('Las contrasenas no coinciden.');
      return;
    }

    const btn = document.getElementById('btn-cu-submit');
    btn.disabled = true;
    btn.style.opacity = '0.65';

    const payload = { nombre, correo, password, confirm_password: confirm };
    if (rol) payload.rol = rol;
    if (cedula) payload.cedula = cedula;
    if (telefono) payload.telefono = telefono;
    if (rol === 'Admin') {
      const negInp = document.getElementById('cu-negocio');
      if (negInp && !negInp.value.trim()) {
        btn.disabled = false;
        btn.style.opacity = '';
        showError('El nombre del negocio es requerido.');
        return;
      }
      if (negInp) payload.nombre_negocio = negInp.value.trim();
    }
    if (rol === 'Cajero') {
      const tidInp = document.getElementById('cu-tienda-id');
      if (tidInp && !tidInp.value) {
        btn.disabled = false;
        btn.style.opacity = '';
        showError('Debes seleccionar una tienda.');
        return;
      }
      if (tidInp) payload.id_tienda = parseInt(tidInp.value, 10);
    }

    try {
      const res = await fetch('/api/crear_usuario', {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      const data = await res.json();

      if (data.ok) {
        closeModal();
        showToast(data.msg || 'Usuario creado exitosamente.', true);
      } else {
        showError(data.msg || 'No se pudo crear el usuario.');
        btn.disabled = false;
        btn.style.opacity = '';
      }
    } catch {
      showError('Error de conexion. Intenta de nuevo.');
      btn.disabled = false;
      btn.style.opacity = '';
    }
  });
}());
