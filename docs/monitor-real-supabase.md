# Almacén del monitor real en Supabase (esquema `tinotify_real`) — PROPUESTA, NO aplicada

Archivos: `supabase/propuestas/20261117000000_crear_almacen_real.sql` y `..._down.sql`. No los recoge la CLI (viven en `propuestas`),
no tocan las migraciones 1–4 ni el esquema sintético, y **no se han ejecutado en Supabase**. Los pasos marcados **[AUTORIZACIÓN]** los
ejecutas tú.

## Qué guarda y qué NO

| Tabla | Contenido | Nunca contiene |
| --- | --- | --- |
| `credenciales` | Una fila: usuario/clave de SIGAC **cifrados** (AES-256-GCM) por el backend. | La llave de cifrado (solo en Render) ni texto claro. |
| `estado_expediente` | Un expediente por fila, con un identificador opaco (`caso_ref` = HMAC del número), conteos y marcas. | Números de caso, nombres, descripciones. |
| `huellas` | Huellas con clave (HMAC) de las actuaciones ya vistas, con su multiplicidad. | Fechas, remitentes, textos ni las huellas originales. |
| `avisos` | Bandeja de avisos pendientes/entregados: solo conteos. | Contenido judicial. |
| `ejecuciones` | Resultado de cada revisión: código de catálogo y conteos. | Identificadores ni mensajes. |
| `dispositivos` | Tokens de Firebase de los teléfonos autorizados. | Credenciales SIGAC. |

Cada tabla tiene RLS forzado, sin acceso para `anon`, `authenticated` ni `service_role`, y el rol de la aplicación solo tiene los
privilegios mínimos (UPDATE por columna, sin TRUNCATE ni DDL). El script termina con una auditoría de ACL que falla si algo no coincide.
La Data API de Supabase nunca expone este esquema.

## Aplicarlo **[AUTORIZACIÓN]**

1. Validación local ya hecha (ver «Estado»); se repite con `bash supabase/checks/validar_almacen_real.sh` (Docker local, sin tocar Supabase).
2. En el SQL Editor de Supabase o con `psql` conectado como el administrador del proyecto, ejecuta el contenido de
   `20261117000000_crear_almacen_real.sql` (una sola transacción; si algo falla, no queda nada a medias).
3. Crea el login restringido **tú mismo**, sin escribir la contraseña en ningún sitio compartido:
   ```sql
   CREATE ROLE tinotify_real_login LOGIN INHERIT;       -- sin contraseña en el SQL
   GRANT tinotify_real_app TO tinotify_real_login;
   -- \password tinotify_real_login                        (en psql: cifra en el cliente)
   ```
   El usuario del pooler es `tinotify_real_login.<ref-del-proyecto>`; el pooler de **sesión** (puerto 5432). La contraseña va
   directamente al campo secreto de Render.
4. Verificación de solo lectura (debe dar 7 tablas, todas con RLS forzado, y ningún permiso para clientes):
   ```sql
   SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'tinotify_real' AND c.relkind = 'r' ORDER BY 1;
   ```

## Reversión **[AUTORIZACIÓN]**
`..._down.sql` borra solo el esquema `tinotify_real` y el rol `tinotify_real_app` (antes: `DROP ROLE tinotify_real_login`). Elimina las
credenciales cifradas y el estado: el monitor empezaría con una línea base nueva.

## Variables que usará el backend (Render)

| Variable | Contenido |
| --- | --- |
| `TINOTIFY_RR_PG_HOST`, `_PORT` (5432), `_DBNAME` (postgres) | Pooler de sesión de Supabase |
| `TINOTIFY_RR_PG_USER` | `tinotify_real_login.<ref-del-proyecto>` |
| `TINOTIFY_RR_PG_PASSWORD` | secreto; ≥ 16 caracteres |
| `TINOTIFY_RR_PG_CA_FILE` | `/etc/secrets/supabase-ca.crt` (ya está en el servicio) |
| `TINOTIFY_RR_CLAVE_CIFRADO` | llave de 32 bytes (secreto); cifra las credenciales. **Solo** en Render |
| `TINOTIFY_RR_MONITOR_TOKEN` | token de GitHub Actions para disparar la revisión |

Hoy el backend rechaza cualquier variable `PG*`/`SUPABASE*`; se ajustará al implementar el monitor. Hasta entonces nada de esto está activo.

## Correo: sin SMTP desde Render

Render bloquea el tráfico saliente a los puertos SMTP (25/465/587) en servicios gratuitos. Diseño propuesto: **GitHub Actions envía el
correo**. Render calcula las novedades y devuelve solo conteos; el flujo de Actions (que sí puede usar SMTP) envía el aviso y confirma la
entrega a Render. El destinatario y la contraseña de aplicación del remitente van como **secretos de GitHub** (nunca en el repositorio,
que es público): `TINOTIFY_CORREO_DESTINO`, `TINOTIFY_SMTP_USUARIO`, `TINOTIFY_SMTP_CLAVE`.

## Estado
Validado en un PostgreSQL 17.12 **desechable** (contenedor local, sin puertos, con los roles de Supabase simulados y un administrador
NOSUPERUSER con CREATEROLE como el de Supabase): alta correcta y auditoría de ACL; la baja se niega mientras exista el login y funciona
tras eliminarlo; 16 operaciones legítimas de la aplicación y 30 intentos prohibidos (formatos, columnas no concedidas, DDL, TRUNCATE,
otros esquemas, crear roles) con el resultado esperado; `anon`, `authenticated` y `service_role` sin acceso; 7 tablas con RLS forzado y
22 políticas; el esquema sintético quedó intacto y el ciclo alta-baja-alta es repetible. **No se ha aplicado a Supabase.**
