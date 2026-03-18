setTimeout(function () {
  var el = document.getElementById('flash-container');
  if (el) {
    el.style.transition = 'opacity .4s';
    el.style.opacity = '0';
    setTimeout(function () {
      el.remove();
    }, 400);
  }
}, 4000);
