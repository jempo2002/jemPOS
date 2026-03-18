(function () {
  const form = document.getElementById('reset-form');
  const pwd = document.getElementById('password');
  const cfm = document.getElementById('confirm_password');
  const err = document.getElementById('inline-error');
  const checks = {
    length: document.getElementById('chk-length'),
    upper: document.getElementById('chk-upper'),
    lower: document.getElementById('chk-lower'),
    number: document.getElementById('chk-number'),
  };

  function setCheck(el, ok) {
    el.className = ok ? 'text-emerald-600' : 'text-slate-400';
  }

  pwd.addEventListener('input', () => {
    const v = pwd.value;
    setCheck(checks.length, v.length >= 8);
    setCheck(checks.upper, /[A-Z]/.test(v));
    setCheck(checks.lower, /[a-z]/.test(v));
    setCheck(checks.number, /\d/.test(v));
  });

  form.addEventListener('submit', (e) => {
    const v = pwd.value;
    if (v.length < 8 || !/[A-Z]/.test(v) || !/[a-z]/.test(v) || !/\d/.test(v)) {
      e.preventDefault();
      err.textContent = 'La contrasena debe tener 8+ caracteres, mayuscula, minuscula y numero.';
      err.classList.remove('hidden');
      return;
    }
    if (v !== cfm.value) {
      e.preventDefault();
      err.textContent = 'Las contrasenas no coinciden.';
      err.classList.remove('hidden');
      return;
    }
    err.classList.add('hidden');
  });
}());
