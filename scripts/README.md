# jemPOS DevOps & DBA Scripts

Scripts para automatización, respaldo y optimización de la base de datos MySQL de jemPOS.

## db_backup.py - Respaldo Diario Automatizado

### Descripción
Script Python que genera respaldos comprimidos de la base de datos usando `mysqldump`. 

**Características:**
- Compresión `.sql.gz` para ahorrar espacio
- Nombre con timestamp: `backup_jempos_YYYYMMDD_HHMM.sql.gz`
- Retención automática: mantiene solo últimos 7 días
- Lectura de credenciales desde `.env`
- **Notificación por correo en caso de fallo** (usando Gmail configurado)

### Requisitos
- Python 3.8+
- `mysqldump` (cliente MySQL) instalado y en PATH
  ```bash
  # Ubuntu/Debian
  sudo apt-get install mysql-client
  
  # macOS (Homebrew)
  brew install mysql-client
  
  # Windows: descargar MySQL Community Edition desde mysql.com
  ```

### Uso Manual

```bash
# Desde la raíz del proyecto (donde está .env)
python3 scripts/db_backup.py

# Con .env alternativo
python3 scripts/db_backup.py /ruta/a/.env
```

**Salida esperada:**
```
Using .env: /path/to/.env
Starting backup of database 'jempos' to /path/to/backups/backup_jempos_20260427_0315.sql.gz
Backup completed successfully: /path/to/backups/backup_jempos_20260427_0315.sql.gz
```

### Configuración - Cron Job (Linux/macOS)

#### Opción 1: Cron tradicional

1. Edita crontab:
```bash
crontab -e
```

2. Añade esta línea para ejecutar diariamente a las 3:00 AM:
```cron
0 3 * * * /usr/bin/python3 /ruta/completa/al/proyecto/scripts/db_backup.py >> /var/log/jempos_db_backup.log 2>&1
```

3. Verifica que cron se inició:
```bash
# Ubuntu/Debian
sudo systemctl restart cron

# macOS
brew services restart cron
```

**Nota:** Reemplaza `/ruta/completa/al/proyecto` con la ruta real, p. ej. `/home/ubuntu/jemPOS`.

#### Opción 2: Systemd Timer (recomendado para sistemas modernos)

Crea `/etc/systemd/system/jempos-db-backup.service`:
```ini
[Unit]
Description=jemPOS Daily Database Backup
After=network.target

[Service]
Type=oneshot
User=backup-user
ExecStart=/usr/bin/python3 /path/to/jemPOS/scripts/db_backup.py
StandardOutput=journal
StandardError=journal
```

Crea `/etc/systemd/system/jempos-db-backup.timer`:
```ini
[Unit]
Description=jemPOS Daily Backup Timer

[Timer]
OnCalendar=*-*-* 03:00:00
Unit=jempos-db-backup.service

[Install]
WantedBy=timers.target
```

Habilita y arranca:
```bash
sudo systemctl daemon-reload
sudo systemctl enable jempos-db-backup.timer
sudo systemctl start jempos-db-backup.timer
sudo systemctl status jempos-db-backup.timer
```

### Configuración de Notificaciones por Correo

El script puede enviar alertas por correo cuando el backup **falla**.

#### Requisitos de Email
El script lee automáticamente estas variables de `.env`:
- `EMAIL_SENDER` - Correo de Gmail (p. ej. `jemposoporte@gmail.com`)
- `EMAIL_PASSWORD` - Contraseña de aplicación Gmail (16 caracteres)
- `EMAIL_SMTP_HOST` - Servidor SMTP (p. ej. `smtp.gmail.com`)
- `EMAIL_SMTP_PORT` - Puerto SMTP (p. ej. `587`)

**Opcional:**
- `BACKUP_ALERT_EMAIL` - Correo receptor de alertas (si no está, usa `EMAIL_SENDER`)

#### Configurar Gmail (Recomendado)

1. **Habilita 2FA en tu cuenta Google**
   - Ve a https://myaccount.google.com/security
   - Baja a "Contraseñas de aplicaciones"

2. **Genera una contraseña de aplicación**
   - Tipo de app: Mail
   - Tipo de dispositivo: Linux
   - Google te genera una contraseña de 16 caracteres

3. **Actualiza `.env`:**
```env
EMAIL_SENDER=jemposoporte@gmail.com
EMAIL_PASSWORD=abcd efgh ijkl mnop
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
BACKUP_ALERT_EMAIL=admin@ejemplo.com
```

4. **Prueba la configuración manualmente:**
```bash
# Simula un fallo para probar correo
# (Cambia host a algo inválido temporalmente)
python3 scripts/db_backup.py
```

### Ubicación de Respaldos
```
proyecto/
├── backups/
│   ├── backup_jempos_20260427_0300.sql.gz
│   ├── backup_jempos_20260428_0300.sql.gz
│   └── ... (máx. 7 días)
```

### Seguridad

**Permisos recomendados:**
```bash
# Restringe lectura solo al propietario
chmod 700 /path/to/backups
chown backup-user:backup-user /path/to/backups

# Script con permisos de ejecución
chmod 755 scripts/db_backup.py
```

**Buenas prácticas:**
- Considera copiar respaldos a almacenamiento remoto (S3, Backblaze, etc.)
- Monitorea el log `/var/log/jempos_db_backup.log`
- Prueba restaurar desde backup periódicamente
- Guarda `MYSQL_PWD` en `.env.local` si no usas el mismo `.env` en producción

---

## db_indexes.sql - Optimización de Índices

### Descripción
Script SQL que añade índices a las tablas más consultadas para mejorar performance.

### Tablas Optimizadas
- **ventas:** estado_venta, fecha_creacion, id_tienda
- **productos:** codigo_barras, estado_activo, id_categoria
- **turnos_caja:** estado_turno, fecha_apertura
- **movimientos_inventario:** fecha_creacion, id_producto

### Uso

```bash
# Conéctate a MySQL como admin
mysql -h 127.0.0.1 -u root -p jempos < scripts/db_indexes.sql

# O interactivamente
mysql -h 127.0.0.1 -u root -p
> USE jempos;
> SOURCE scripts/db_indexes.sql;
```

### Consideraciones de Performance

1. **Ventana de baja carga:** Ejecuta en horas de poco tráfico
2. **Lock/Bloqueos:** En MySQL 5.6+, usa `ALGORITHM=INPLACE` para menor downtime
3. **Tablas grandes:** Considera `pt-online-schema-change` para 0 downtime
4. **Validación:** Antes de índices, verifica EXPLAIN en queries críticas

```bash
EXPLAIN SELECT * FROM ventas WHERE estado_venta = 'Cerrada' AND fecha_creacion > '2026-04-01';
```

---

## Mantenimiento Regular

### Checklist Mensual
- [ ] Revisa log de backups: `/var/log/jempos_db_backup.log`
- [ ] Verifica que últimos 7 backups existan en `backups/`
- [ ] Prueba restauración desde un backup aleatorio
- [ ] Revisa índices con `SHOW INDEX FROM <tabla>;`

### Checklist Trimestral
- [ ] Analiza tablas: `ANALYZE TABLE ventas, productos, turnos_caja, movimientos_inventario;`
- [ ] Revisa tamaño de BD: `SELECT SUM(data_length + index_length) / 1024 / 1024 FROM information_schema.tables WHERE table_schema='jempos';`
- [ ] Optimiza tablas si es necesario: `OPTIMIZE TABLE <tabla>;`

---

## Troubleshooting

### "mysqldump not found"
```bash
# Verifica ubicación
which mysqldump

# O instala cliente MySQL
sudo apt-get install mysql-client
```

### "Access denied for user 'root'"
- Revisa credenciales en `.env`
- Verifica conectividad: `mysql -h DB_HOST -u DB_USER -p DB_NAME`

### "Backup file is empty or corrupt"
- Revisa permisos en `backups/`
- Verifica espacio disco: `df -h`
- Revisa stderr en log `/var/log/jempos_db_backup.log`

### "Email alert not sent"
- Verifica credenciales de Gmail en `.env`
- Prueba autenticación 2FA habilitada
- Revisa que `BACKUP_ALERT_EMAIL` sea válido
- Revisa log para detalles SMTP

---

**Mantenido por:** DevOps Team jemPOS  
**Última actualización:** 2026-04-27
