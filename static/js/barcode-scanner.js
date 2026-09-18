/* ============================================================
   Ruta: static/js/barcode-scanner.js
   Escaner de codigos de barras con la camara (Html5Qrcode).
   Requiere el <dialog> de templates/pos/_scanner_dialog.html.

   Uso:  BarcodeScanner.open((codigo) => { ... })
   La camara se apaga al leer un codigo, al cerrar la hoja
   (boton, Esc, clic fuera) o si la app pasa a segundo plano.
   ============================================================ */

window.BarcodeScanner = (() => {
  /* Carga diferida (~370 KB): solo cuando alguien pulsa "escanear". */
  const LIB_SRC = 'https://cdnjs.cloudflare.com/ajax/libs/html5-qrcode/2.3.8/html5-qrcode.min.js';
  const LIB_SRI = 'sha512-r6rDA7W6ZeQhvl8S7yRVQUKVHdexq+GAlNkNNqVC7YyIV+NwqCTJe2hDWCiffTyRNOeGEzRRJ9ifvRm/HCzGYg==';

  const dialog   = document.getElementById('scanner-dialog');
  const viewEl   = document.getElementById('scanner-view');
  const statusEl = document.getElementById('scanner-status');

  let libPromise = null;
  let scanner    = null;
  let cameraOps  = Promise.resolve();   /* start/stop encadenados: nunca se pisan */
  let session    = 0;                   /* cada apertura/cierre invalida la anterior */

  function loadLib() {
    if (window.Html5Qrcode) return Promise.resolve();
    libPromise = libPromise || new Promise((resolve, reject) => {
      const script = document.createElement('script');
      Object.assign(script, { src: LIB_SRC, integrity: LIB_SRI, crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' });
      script.onload = resolve;
      script.onerror = () => {
        script.remove();
        libPromise = null;   /* permite reintentar al volver la conexion */
        reject(new Error('No se pudo cargar el escáner. Revisa tu conexión.'));
      };
      document.head.appendChild(script);
    });
    return libPromise;
  }

  function setStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.classList.toggle('is-error', isError);
    viewEl.hidden = isError;   /* sin camara, el visor negro vacio sobra */
  }

  function cameraErrorMessage(err) {
    const text = `${err?.name || ''} ${err?.message || err || ''}`;
    if (/NotAllowed|Permission|denied/i.test(text)) {
      return 'Permiso de cámara denegado. Habilítalo en los ajustes del navegador para escanear.';
    }
    if (/NotFound|Overconstrained|device not found/i.test(text)) return 'No se encontró una cámara disponible.';
    if (/NotReadable|TrackStart|Could not start/i.test(text)) return 'La cámara está siendo usada por otra aplicación.';
    return err?.message || 'No se pudo iniciar la cámara.';
  }

  /* Html5Qrcode marca `isScanning` en el evento 'playing' del video, que llega
     despues de que start() resuelve. Si se detiene antes, ese evento tardio lo
     deja "escaneando" y el siguiente start() falla. Se espera a 'playing' (max 2 s). */
  function surfaceReady() {
    const video = document.querySelector('#scanner-view video');
    if (!video || scanner.isScanning) return null;
    return new Promise((resolve) => {
      video.addEventListener('playing', resolve, { once: true });
      setTimeout(resolve, 2000);
    });
  }

  /* Apaga el stream (ahorra bateria), siempre despues del arranque en curso.
     getState() y no `isScanning`: justo tras start() el flag aun es false. */
  function releaseCamera() {
    cameraOps = cameraOps
      .then(() => {
        if (scanner && scanner.getState() !== window.Html5QrcodeScannerState.NOT_STARTED) {
          return scanner.stop();
        }
        return null;
      })
      .catch(() => {});
  }

  function createScanner() {
    const F = window.Html5QrcodeSupportedFormats;
    return new window.Html5Qrcode('scanner-view', {
      verbose: false,
      useBarCodeDetectorIfSupported: true,   /* API nativa cuando existe: mas rapida */
      formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF, F.QR_CODE],
    });
  }

  async function open(onScan) {
    const current = ++session;
    if (!dialog.open) dialog.showModal();
    setStatus('Iniciando cámara…');

    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setStatus('La cámara requiere una conexión segura (HTTPS).', true);
      return;
    }

    try {
      await loadLib();
      await cameraOps;
      if (current !== session) return;

      scanner = scanner || createScanner();
      const starting = scanner.start(
        { facingMode: 'environment' },
        {
          fps: 12,
          /* Ventana ancha y baja: los codigos de barras son horizontales. */
          qrbox: (w, h) => ({
            width: Math.max(50, Math.floor(w * 0.85)),
            height: Math.max(50, Math.floor(Math.min(h * 0.6, w * 0.4))),
          }),
        },
        (text) => {
          if (current !== session) return;   /* ignora lecturas repetidas del mismo frame */
          session++;
          navigator.vibrate?.(40);
          dialog.close();
          onScan(String(text).trim());
        },
        () => {},   /* frame sin codigo: normal mientras se apunta */
      );
      cameraOps = starting.then(surfaceReady).catch(() => {});
      await starting;
      /* Si se cerro mientras arrancaba, el 'close' ya encolo el stop tras este start. */
      if (current === session) setStatus('Apunta la cámara al código de barras.');
    } catch (err) {
      if (current === session) setStatus(cameraErrorMessage(err), true);
    }
  }

  dialog.addEventListener('close', () => {
    session++;
    releaseCamera();
  });

  /* Clic en el fondo difuminado = cerrar */
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden && dialog.open) dialog.close();
  });

  return { open };
})();
