# Despliegue de jemPOS en Railway

Guia paso a paso para publicar jemPOS en un dominio propio. Escrito para quien
administra el despliegue (tu). Asume un solo servicio web + un MySQL en Railway.

---

## 0. Lo que ya quedo listo en el repo

- `Procfile` — arranca `gunicorn run:app` con 2 workers y logs a stdout.
- `.python-version` — fija Python 3.13, la misma version del entorno local.
- `requirements.txt` — incluye `cryptography`, necesaria para que
  `mysql-connector-python` pueda autenticarse contra MySQL 8
  (`caching_sha2_password`) sin TLS en la red interna de Railway.
- `app/security.py` — ProxyFix + Flask-Talisman: en produccion fuerza HTTPS,
  manda HSTS y marca la cookie de sesion como `Secure`.
- `.gitignore` — `.env`, `jempos.sql` y `flask_session/` nunca se suben.
- **Contacto real** en una sola fuente, `CONTACTO` en
  [app/routes/seo.py](app/routes/seo.py): WhatsApp +57 310 615 2268, Instagram
  @jempos__ y jemposoporte@gmail.com. De ahi salen a la vez el JSON-LD que lee
  Google (con `sameAs` al perfil de Instagram) y la columna Contacto del footer
  del landing y de las paginas legales, asi que no pueden desincronizarse.
- **Imagen de previsualizacion** `static/img/og-cover.jpg` (1200x630): antes
  `og:image` apuntaba a un archivo inexistente y compartir el enlace por
  WhatsApp no generaba tarjeta.
- **Textos legales definitivos**: el aviso legal y la politica de privacidad ya
  no son Lorem ipsum. Estan redactados para Colombia (Ley 1581 de 2012, Ley
  1480 de 2011, Ley 527 de 1999) e incluyen la transferencia internacional de
  datos a Railway y Gmail, que es obligatorio declarar. Falta un dato: ver el
  paso 8.

---

## 1. Comprobar en local y subir el codigo a GitHub

Antes de empujar, con MySQL local levantado, pasa los chequeos del repo. Cubren
sesiones, HTTPS forzado, paginas legales, rastreo, datos estructurados,
accesibilidad y los flujos de venta y cartera:

```bash
.venv/Scripts/python.exe scripts/check_produccion.py
.venv/Scripts/python.exe scripts/check_seo_activos.py
.venv/Scripts/python.exe scripts/check_rendimiento_ux.py
.venv/Scripts/python.exe scripts/check_filtros_paginacion.py
.venv/Scripts/python.exe scripts/check_cartera_b2b.py
.venv/Scripts/python.exe scripts/check_fiado_caja.py
```

Todos deben terminar en `OK`. Un `AssertionError` aqui es un fallo que se iria
a produccion.

Railway despliega desde una rama. Decide cual:

```bash
git add -A
git commit -m "chore: preparar produccion (Python 3.13, cryptography, contacto real, legales)"
git push origin v1.1
```

Si prefieres desplegar desde `main`, fusiona `v1.1` a `main` primero y usa esa.

---

## 2. Crear el proyecto en Railway

1. railway.app → **New Project** → **Deploy from GitHub repo** → elige el repo.
2. En el servicio creado: **Settings → Source → Branch** → selecciona la rama
   del paso 1.
3. El primer build fallara: todavia no hay variables de entorno. Es normal.

---

## 3. Agregar la base de datos

En el mismo proyecto: **+ New → Database → Add MySQL**.

Railway crea la base `railway` y expone estas variables en el servicio MySQL:
`MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`.

---

## 4. Cargar el esquema y las migraciones  ✅ HECHO

> Estado: la base `railway` ya quedo cargada el 2026-09-23: 17 tablas, 7
> triggers, 37 claves foraneas y los datos del volcado. Esta seccion queda como
> referencia para rehacerlo (por ejemplo, al recrear la base o al montar un
> entorno de pruebas).

El dump `jempos.sql` esta en `.gitignore` (lleva datos reales), asi que se
importa a mano desde tu maquina usando el proxy publico de Railway.

En el servicio MySQL, pestaña **Variables**, copia `MYSQL_PUBLIC_URL`. Tiene la
forma `mysql://root:CLAVE@HOST.proxy.rlwy.net:PUERTO/railway`.

Con el runner del repo, que se conecta con las credenciales del entorno. Las
variables del shell tienen prioridad sobre `.env`, asi que no hace falta tocar
tu `.env` local:

```powershell
$env:DB_HOST="HOST.proxy.rlwy.net"; $env:DB_PORT="PUERTO"
$env:DB_USER="root"; $env:DB_PASSWORD="CLAVE"; $env:DB_NAME="railway"
.venv/Scripts/python.exe scripts/run_migration.py jempos.sql
```

Despues, en este orden, lo que el dump no trae (es de julio; las migraciones
son posteriores). El runner es idempotente: repetirlo no rompe nada.

```powershell
.venv/Scripts/python.exe scripts/run_migration.py migrations/2026-09-16_clientes_cedula.sql
.venv/Scripts/python.exe scripts/run_migration.py migrations/2026-09-16_proveedores_telefono2.sql
.venv/Scripts/python.exe scripts/run_migration.py migrations/2026-09-22_cartera_b2b.sql
.venv/Scripts/python.exe scripts/run_migration.py scripts/db_indexes.sql
```

Cierra la sesion de PowerShell al terminar para no dejar las credenciales de
produccion en variables de entorno.

### Dos diferencias entre tu MariaDB local y el MySQL de Railway

Railway sirve **MySQL 9.7.2**; en local el proyecto corre sobre **MariaDB**. No
son intercambiables y dos cosas hubo que corregir para que el mismo SQL sirva
en ambos:

1. **`DELIMITER` y los triggers.** `jempos.sql` trae 7 triggers envueltos en
   bloques `DELIMITER $$ ... $$`. `DELIMITER` no es SQL: es una instruccion del
   cliente `mysql`. `scripts/run_migration.py` ahora la interpreta y corta por
   el delimitador vigente. Antes partia el archivo por `;` y habria troceado
   el cuerpo de cada trigger, dejando la base a medio crear.
2. **`ADD COLUMN IF NOT EXISTS` no existe en MySQL.** Es una extension de
   MariaDB; MySQL responde error 1064. Las tres migraciones se reescribieron
   sin ella y con **una clausula por sentencia**. Lo segundo importa: un ALTER
   con varias clausulas es atomico, asi que si la columna ya existe pero la
   clave no, el motor rechaza el bloque entero por 1060, el runner lo salta
   como "ya aplicado" y la clave nunca se crea. La idempotencia la da el
   runner, que trata 1060/1061/1826 como no-op.

Si mas adelante generas un volcado nuevo, hazlo desde la base de Railway
(MySQL) y no desde la local (MariaDB), o volveras a encontrarte estas mismas
diferencias.

---

## 5. Variables de entorno del servicio web

Servicio web → **Variables**. Las `${{MySQL.*}}` son referencias de Railway: se
resuelven al host **interno**, que no sale a internet y no cobra ancho de banda.
Si tu servicio MySQL tiene otro nombre, cambia `MySQL` por ese nombre.

| Variable | Valor |
|---|---|
| `SECRET_KEY` | (generado, ver abajo) |
| `DB_HOST` | `${{MySQL.MYSQLHOST}}` |
| `DB_PORT` | `${{MySQL.MYSQLPORT}}` |
| `DB_USER` | `${{MySQL.MYSQLUSER}}` |
| `DB_PASSWORD` | `${{MySQL.MYSQLPASSWORD}}` |
| `DB_NAME` | `${{MySQL.MYSQLDATABASE}}` |
| `SESSION_TYPE` | `filesystem` |
| `FLASK_ENV` | `production` |

Genera la clave (no reutilices la de tu `.env` local: esa ya vivio en disco sin
cifrar y rotarla despues invalida todas las sesiones):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Opcionales**, pero sin ellas la recuperacion de contrasena falla al enviar:
`EMAIL_SENDER`, `EMAIL_PASSWORD` (contrasena de aplicacion de Google, no la de
la cuenta), `EMAIL_SMTP_HOST=smtp.gmail.com`, `EMAIL_SMTP_PORT=587`,
`BACKUP_ALERT_EMAIL`, `LOG_DIR=logs`.

Guardar las variables dispara un redespliegue. Revisa **Deployments → Logs**:
debe aparecer el arranque de gunicorn sin trazas de error.

---

## 6. Conectar tu dominio

1. Servicio web → **Settings → Networking → Custom Domain** → escribe tu
   dominio. Railway devuelve un destino `CNAME` (algo `.up.railway.app`).
2. En tu proveedor de DNS crea el registro:
   - **Subdominio** (`app.tudominio.com`): `CNAME` → el destino que dio Railway.
   - **Dominio raiz** (`tudominio.com`): el estandar DNS no permite `CNAME` en
     la raiz. Necesitas un proveedor con `ALIAS`/`ANAME`/CNAME flattening
     (Cloudflare, por ejemplo). Si el tuyo no lo tiene, usa `www` y redirige la
     raiz hacia `www` desde el panel del proveedor.
3. Si usas Cloudflare, deja el proxy (nube naranja) **activado** y el modo SSL
   en **Full (strict)**. En **Flexible** Cloudflare habla HTTP con Railway,
   Talisman responde con redireccion a HTTPS y se forma un bucle infinito.
4. La propagacion y el certificado tardan entre minutos y un par de horas.
   Railway marca el dominio en verde cuando el certificado esta emitido.

---

## 7. Verificacion

Con el dominio ya activo:

- `https://tudominio.com/` → redirige a `/landing`.
- `http://tudominio.com/` → redirige a `https://` (Talisman).
- `https://tudominio.com/health` → `{"ok": true, ...}`.
- `https://tudominio.com/robots.txt` → el `Sitemap:` al final debe decir
  `https://tudominio.com/...`. Si sale `http://` o un host `.railway.app`,
  ProxyFix no esta viendo las cabeceras `X-Forwarded-*`.
- `https://tudominio.com/sitemap.xml` → las cuatro URLs con tu dominio.
- `https://tudominio.com/static/img/og-cover.jpg` -> la imagen de
  previsualizacion (1200x630). Se genera con
  `python scripts/generar_og_cover.py` y esta versionada; solo hay que volver a
  correrlo si cambia el texto o el logo.
- El footer muestra WhatsApp, Instagram y el correo, y los tres enlaces abren.
- Inicia sesion y entra al POS: valida que la base quedo bien importada.

---

## 8. Pendiente antes de anunciar el sitio

**Unico bloqueante: identificar al responsable del tratamiento.**

La Ley 1581 de 2012 obliga a que el aviso legal y la politica de privacidad
digan quien responde por los datos. Son cuatro valores que no se pueden deducir
del codigo, y estan juntos en un solo sitio, `EMPRESA` en
[app/routes/legal.py](app/routes/legal.py):

```python
EMPRESA = {
    "razon_social": "POR DEFINIR",   # tu nombre completo, o la razon social
    "nit": "POR DEFINIR",            # tu cedula, o el NIT de la empresa
    "domicilio": "POR DEFINIR",      # direccion de notificaciones
    "ciudad": "POR DEFINIR",         # define tambien el juez competente
}
```

Si operas como persona natural, `razon_social` es tu nombre completo y `nit` tu
cedula. Si constituiste empresa, los del certificado de Camara de Comercio.

Mientras alguno siga en `POR DEFINIR`, el codigo se protege solo:

- las dos paginas legales se sirven con `<meta name="robots" content="noindex">`,
- salen del `sitemap.xml`,
- y muestran un aviso visible de que falta completarlas.

En cuanto rellenes los cuatro valores, las tres cosas se revierten sin tocar
nada mas. Se hace asi porque un aviso legal a medias que Google alcance a
indexar queda en su cache y en los resultados semanas despues de corregirlo.

**Despues del despliegue:**

- Da de alta el dominio en Google Search Console y envia el sitemap.
- Comprueba la tarjeta al compartir en
  [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/) y
  mandandote el enlace por WhatsApp.
- Valida los datos estructurados en la
  [prueba de resultados enriquecidos](https://search.google.com/test/rich-results).

---

## Limites conocidos de esta configuracion

- **Una sola instancia.** Las sesiones son `filesystem` (archivos dentro del
  contenedor) y el limitador de peticiones guarda los contadores en memoria.
  Con dos replicas el balanceador manda al usuario a un contenedor que no tiene
  su sesion y lo saca. Para escalar horizontalmente hace falta Redis:
  agregar el servicio, `SESSION_TYPE=redis` + `SESSION_REDIS`, y
  `storage_uri` en el `Limiter` de `app/__init__.py`.
- **Cada redespliegue cierra las sesiones abiertas.** El disco del contenedor
  es efimero, asi que `flask_session/` se pierde. Molesto, no grave: los
  usuarios vuelven a iniciar sesion.
- **Sin healthcheck configurado a proposito.** El chequeo interno de Railway no
  siempre manda `X-Forwarded-Proto`, y sin esa cabecera Talisman responde 301
  hacia HTTPS y el despliegue se marcaria como caido. Si lo quieres activar,
  antes hay que eximir `/health` de `force_https`.
- **Respaldos.** Railway no respalda el MySQL del plan base. `scripts/db_backup.py`
  existe para eso; programalo donde puedas dejarlo corriendo.
