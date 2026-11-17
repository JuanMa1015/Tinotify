# Backend sintético con PostgreSQL (Supabase) en Render — preparado, NO desplegado

Solo datos ficticios. Estado verificado durante la preparación del despliegue:

- Supabase: el esquema `tinotify_sintetico` ya fue creado y verificado (5 tablas, 2 funciones, 2 triggers y 11 políticas RLS).
- PostgreSQL: el login restringido `tinotify_sintetico_render` ya existe y se verificó su conexión TLS mediante el pooler de sesión.
- Código: la preparación del despliegue está aislada en el worktree `Tinotify-Deploy`, rama `deploy/sintetico-render`.
- Render: la nueva versión de la API sintética todavía NO se ha desplegado.

**NO VOLVER A EJECUTAR LA MIGRACIÓN SINTÉTICA NI CREAR NUEVAMENTE EL ROL.**
Las instrucciones históricas de creación y migración que aparecen más adelante no son pasos pendientes.
No ejecutar `supabase db push`, `migration up` ni `migration repair` como parte de este despliegue.

Los pasos marcados **[AUTORIZACIÓN]** requieren aprobación explícita antes de modificar servicios remotos.

## Arquitectura

```
Android ──HTTPS──▶ Render (FastAPI, 1 worker, tinotify.sintetico_remoto.app:crear_app)
                       │  monitor sintético (hilo)  ──┐
                       └─ API /sintetico/*            ├─ psycopg + pool, TLS verify-full, pooler de SESIÓN
                                                      ▼
                          Supabase PostgreSQL · esquema privado `tinotify_sintetico` (5 tablas)
                          login restringido `tinotify_sintetico_*`  (sin acceso a app, app_private, auth, public)
```

- El esquema `tinotify_sintetico` es independiente de las migraciones 1–4 (`app`, `app_private`, `app_fixture`): no las usa ni las
  modifica. Contiene `entorno` (marca de entorno sintético), `casos`, `actuaciones`, `novedades` y `monitor_estado`.
- Defensas en la propia base: RLS forzado, sin permisos para `anon`/`authenticated`/`service_role`/`PUBLIC`, ids de caso solo en el espacio
  `00000000-0000-4000-8000-*`, título y contenido limitados a la gramática exacta del generador sintético (sin texto libre), máximo
  10 casos, 200 actuaciones y 200 novedades por caso (a prueba de concurrencia), una novedad por actuación (`UNIQUE`). La app no
  arranca si el esquema no está marcado como sintético o si el login tiene más alcance del debido.
- Exclusión del monitor: bloqueo asesor de sesión de PostgreSQL. Si Render levanta una instancia nueva mientras la vieja aún vive, la
  nueva espera (`estado: "en_espera"`) y toma el relevo sola; si el proceso muere, PostgreSQL libera el bloqueo.
- Si PostgreSQL no responde: la API sigue viva, los endpoints de datos devuelven `503 {"detail":"Almacen no disponible"}` y el monitor
  reintenta con espera creciente (hasta 5 min) sin pasar a `error`. `/health` no consulta la base.
- Los contratos de `/health`, `/sintetico/casos`, `/sintetico/casos/{id}`, `/sintetico/novedades` y `/sintetico/monitor` no cambian;
  solo aparece el estado de monitor `en_espera` (Android lo muestra tal cual).

## Variables de entorno (nombres; los valores no van al repositorio)

| Variable | Valor / nota |
| --- | --- |
| `TINOTIFY_SR_MODO` | `remoto` |
| `TINOTIFY_SR_TLS` | `proxy` |
| `TINOTIFY_SR_PROXIES_CONFIABLES` | `privadas` (solo se cree `X-Forwarded-Proto` si el par TCP tiene IP privada; ver «Proxy de Render») |
| `TINOTIFY_SR_TOKEN` | **secreto** de Render; ≥ 32 caracteres, el mismo que se escribe en la app |
| `TINOTIFY_SR_ALMACEN` | `postgres` (por defecto `sqlite`) |
| `TINOTIFY_SR_PG_HOST` | host del **pooler de sesión** (Supabase → Connect) |
| `TINOTIFY_SR_PG_PORT` | `5432` (el `6543` transaccional se rechaza) |
| `TINOTIFY_SR_PG_MODO` | `sesion` (pooler de sesión; obligatorio en esta configuración por el bloqueo del monitor) |
| `TINOTIFY_SR_PG_DBNAME` | `postgres` |
| `TINOTIFY_SR_PG_USER` | `tinotify_sintetico_<nombre>.<ref-del-proyecto>` (formato del pooler) |
| `TINOTIFY_SR_PG_PASSWORD` | **secreto** de Render; ≥ 16 caracteres |
| `TINOTIFY_SR_PG_CA_FILE` | ruta del certificado CA, p. ej. `/etc/secrets/supabase-ca.crt` (Secret File de Render) |
| `TINOTIFY_SR_PG_MAX_CONEXIONES` | opcional, 1–4 (por defecto 3; el monitor usa 1 conexión más) |
| `TINOTIFY_SR_INTERVALO_S` | ≥ 60 en remoto (por defecto 300) |
| `PYTHON_VERSION` | `3.11.18` |

Se rechazan al arrancar: cualquier `TINOTIFY_REAL_*`/`SIGAC_*`, `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, variables `PG*` de libpq,
opciones `TINOTIFY_SR_PG_*` desconocidas (p. ej. `SSLMODE`: no es configurable, siempre `verify-full`) y usuarios que no empiecen por
`tinotify_sintetico_`. No se usan claves `service_role` ni la contraseña de `postgres`.

## Proxy de Render y `X-Forwarded-Proto`

El tráfico llega a Render por HTTPS y el balanceador lo reenvía por HTTP con `X-Forwarded-Proto: https`. La app **no** acepta
ese encabezado de cualquiera: con `TINOTIFY_SR_PROXIES_CONFIABLES=privadas` solo lo cree si la conexión TCP directa viene de una IP
privada (10/8, 172.16/12, 192.168/16, fc00::/7). Un cliente de Internet no llega al contenedor sin pasar por el proxy, por lo que su
conexión no sería privada y su cabecera se ignora (403). Arranca con `--no-proxy-headers` para que uvicorn no reescriba el par.

**No verificado:** que el proxy de Render llegue desde direcciones privadas es una suposición razonable, no un hecho comprobado.
Si fallase, `/sintetico/*` devolvería 403 «Se requiere HTTPS» (y `/health` seguiría en 200). En ese caso hay que averiguar el rango real
y fijarlo con CIDR; no se desactiva la validación HTTPS.

## Provisionar el login restringido sin exponer contraseñas **[AUTORIZACIÓN]**

1. Aplica la migración (abajo) con el usuario `postgres` del proyecto. Crea el grupo `tinotify_sintetico_app` (NOLOGIN); **no** crea logins.
2. Crea el login como **tú**, tecleando la contraseña tú mismo (no se la pases a nadie ni la pegues en el chat):
   - recomendado: `psql` conectado al pooler de sesión y `\password` (cifra en el cliente; la contraseña no queda en logs ni historial);
   - alternativa: Dashboard → Database → Roles, o SQL Editor (ojo: el SQL Editor puede conservar la consulta en su historial).
   ```sql
   CREATE ROLE tinotify_sintetico_login LOGIN INHERIT;       -- sin contraseña en el SQL
   GRANT tinotify_sintetico_app TO tinotify_sintetico_login;
   -- \password tinotify_sintetico_login                        (en psql)
   ```
3. Copia la contraseña directamente al campo secreto de Render. Nunca al repositorio, a `render.yaml` ni a un chat.
4. El usuario para el pooler es `tinotify_sintetico_login.<ref-del-proyecto>`.

## Conexión: pooler de sesión, TLS y CA

- Render Free solo ofrece salida IPv4 y, según la documentación de Supabase, la conexión directa del plan gratuito es IPv6: por eso se
  usa el **pooler de sesión** (puerto 5432 del host del pooler). *Verifícalo en Connect del proyecto.* El pooler transaccional (6543) se
  rechaza porque el monitor usa un bloqueo de sesión.
- Siempre `sslmode=verify-full` con la CA del proyecto: Dashboard → Database → SSL Configuration → descargar el certificado y subirlo
  como **Secret File** de Render. El certificado es público; el Secret File solo evita meter archivos en el repositorio.
- Cuotas: el almacén está acotado (< 1 MB con los límites por defecto) frente a los 500 MB gratuitos. **Los proyectos gratuitos de
  Supabase se pausan tras un periodo de inactividad** (confirma el plazo vigente): si se pausa, la API devuelve 503 hasta reactivarlo.

## Migración propuesta (no aplicada)

`supabase/propuestas/20261115000000_crear_almacen_sintetico.sql` — transaccional, sin `IF NOT EXISTS`, con auditoría final que aborta si
queda algún permiso residual. Reversión: `supabase/propuestas/20261115000000_crear_almacen_sintetico_down.sql` (borra solo el esquema
`tinotify_sintetico` y el rol de grupo; funciona con un administrador sin superusuario; se niega si aún hay logins miembros; ver «Reversión»).

Vive deliberadamente en `supabase/propuestas/`, **fuera** de `supabase/migrations/`: la CLI no la recoge, no altera el *dry-run* de las migraciones
3 y 4 y no rompe las herramientas de preflight/comparación, que asumen exactamente cuatro migraciones. Al autorizar su aplicación se mueve con
`git mv supabase/propuestas/20261115000000_crear_almacen_sintetico.sql supabase/migrations/` (y ese cambio hay que revisarlo contra
`backend/scripts/comparar_catalogos.py` y `backend/tests/integration/conftest.py`, que hoy fijan cuatro migraciones). Alternativa sin mover nada:
`supabase db query --file supabase/propuestas/…` (no registra historial).

### Revisión de la migración (revisión 2)

Cada hallazgo se reprodujo primero con una prueba contra PostgreSQL desechable (fallaba con la revisión 1) y se corrigió después.

| # | Hallazgo (demostrado) | Corrección |
| --- | --- | --- |
| 1 | **Carrera del límite de casos**: con 9 casos, dos transacciones abiertas a la vez veían 9 y ambas insertaban → 11. | El trigger toma `pg_advisory_xact_lock(7402100002)` antes de contar; la segunda espera, ve lo confirmado y recibe `54000`. Un caso existente (`ON CONFLICT DO NOTHING`) no cuenta como nuevo. |
| 1b | **Novedades sin tope**: el rol podía insertar novedades con huellas arbitrarias sin límite (el «crecimiento acotado» solo era cierto para casos y actuaciones). | Trigger `limitar_novedades`: máximo 200 por caso, con el mismo bloqueo; reintentos idempotentes siguen funcionando. |
| 2 | **La marca `SINTETICO` no basta**: `descripcion`, `titulo`, `direccion`, `fecha`, claves extra y `anexos` admitían texto libre (p. ej. un nombre real); `casos.titulo` también. | `CHECK contenido_sintetico`: exactamente seis claves y cada campo con la frase/forma del generador (contador numérico, fecha ISO, direcciones fijas, sin anexos), cada uno envuelto en `coalesce(…, false)` porque un `NULL` en un CHECK *pasa*. `casos.titulo` ~ `^Proceso sintético…`. |
| 3 | **Privilegios y políticas**: el rol tenía `INSERT` en `monitor_estado` y `UPDATE` en todas las columnas (p. ej. `casos.id`); políticas `FOR ALL`. | `UPDATE` solo por columnas que la app modifica; sin `INSERT` en `monitor_estado`; una política por orden y tabla. |
| 4 | **ACL**: la auditoría solo miraba `anon`/`authenticated`/`service_role`, no `PUBLIC` ni ACL de columnas/funciones/esquema. | Auditoría exacta con `aclexplode`: solo propietario y `tinotify_sintetico_app`, nada delegable; falla ante cualquier otra entrada (incl. `PUBLIC`). |
| 5 | **Compatibilidad**: el adaptador (`INSERT … ON CONFLICT`, `SELECT … FOR UPDATE`, `UPDATE` de columnas, `DELETE` de actuaciones) y todas las pruebas existentes siguen pasando sin cambios en el código del adaptador. | — |
| 6 | **(rev. 3) `casos.titulo` aceptaba hasta 100 caracteres arbitrarios** tras «Proceso sintético». | `titulo = 'Proceso sintético observado'` exacto (`TITULO_OBSERVADO`, el único que escribe el adaptador). |
| 7 | **(rev. 3) `novedades.titulo`/`mensaje` aceptaban cualquier texto de 1–200/500 caracteres.** | `CHECK textos_del_dominio`: solo los pares (tipo, título, mensaje) de `crear_notificacion`: 3 tipos, 4 títulos y 3 mensajes. Una prueba estática compara el SQL con el dominio y fallará si cambia su redacción. |
| 8 | **(rev. 3) El bloqueo solo protege bajo `READ COMMITTED`.** Con `REPEATABLE READ`/`SERIALIZABLE` el conteo usa una instantánea anterior al bloqueo y la carrera volvía. | Los dos triggers rechazan (`25001`) cualquier transacción que no sea `READ COMMITTED`. |

**Determinismo comprobado (rev. 3).** El generador escribe siempre `TITULO_OBSERVADO` en `casos`. El adaptador crea cada novedad con
`crear_notificacion(0, "", PRIMERA_OBSERVACION)` y solo cambia la *prioridad*: el texto es siempre «Nueva información disponible» /
«Hay información observada por primera vez. Revisa la aplicación.», haya prioridad alta o normal (probado: ambas prioridades, un único texto).
El título «Nueva información importante» solo lo produce el dominio si se le pasa una dirección prioritaria, algo que el adaptador no hace; se admite
en el CHECK por ser un valor legítimo del dominio, no por uso actual.

### Condiciones de aislamiento transaccional de los bloqueos asesores

| Bloqueo | Tipo | Condición para que sea correcto |
| --- | --- | --- |
| `pg_advisory_xact_lock(7402100002)` (límites de casos y novedades) | de **transacción**: se libera al `COMMIT`/`ROLLBACK` | 1) Nivel **READ COMMITTED** (la migración lo exige; es el valor por defecto de PostgreSQL y el que usa el adaptador en sus transacciones de escritura; las lecturas usan `REPEATABLE READ READ ONLY` y no insertan). Si se cambiara `default_transaction_isolation` del rol o se usara `SET TRANSACTION` distinto, el trigger rechaza la inserción. 2) La transacción debe ser explícita y corta (el adaptador usa `conn.transaction()`); en autocommit el bloqueo se libera tras cada sentencia. 3) Funciona con cualquier pooler, también el transaccional, porque no depende de la sesión. 4) La espera está limitada por `lock_timeout` (3 s en el adaptador): un `55P03` se trata como indisponibilidad transitoria. |
| `pg_try_advisory_lock(7402100001)` (monitor único) | de **sesión**: se libera al cerrar la conexión | Requiere una conexión de sesión estable: pooler **de sesión** (5432) o directa; **no** el transaccional (6543). Si el pooler corta la conexión inactiva, el monitor lo detecta y recupera el bloqueo (hay una breve ventana de relevo; las escrituras siguen serializadas por (a) y por la fila `casos`). |

Todas las observaciones toman el bloqueo (a) en su primer `INSERT … ON CONFLICT`, así que se serializan entre sí; no hay interbloqueos porque
todos los escritores lo adquieren primero y las claves de (a) y (b) son distintas.

### Permisos efectivos de `tinotify_sintetico_app` y del login heredado (comprobados con PostgreSQL desechable)

- El login solo es miembro de `tinotify_sintetico_app`; el grupo no es miembro de ningún rol. El login no pertenece a `postgres`, `service_role`, `authenticated` ni `anon`.
- Para cada esquema de usuario, los privilegios efectivos del login (incluida la herencia y `PUBLIC`) son idénticos a los del grupo; solo tiene `USAGE`
  en `tinotify_sintetico` y `public` (por `PUBLIC`), y ningún `CREATE`.
- Ningún privilegio sobre tablas, vistas, secuencias ni columnas ajenas al almacén (`app`, `app_private`, `app_fixture`, `auth`…).
- Ninguna función propia alcanzable: las de los triggers no tienen `EXECUTE` para nadie (los triggers no lo necesitan) y `public` no tiene funciones con `EXECUTE` para `PUBLIC`
  en la base de pruebas (**comprueba lo mismo en el proyecto real** con la consulta de solo lectura del procedimiento).
- Base de datos: `CONNECT` y `TEMP` (heredados de `PUBLIC`, no revocables por rol), sin `CREATE`.
- Un login creado con `NOINHERIT` no hereda los privilegios del grupo: la app lo detecta (`pg_has_role(…,'USAGE')`) y se niega a arrancar.

Riesgos que **no** se pueden eliminar en la base (documentados, no ocultos):
- `PUBLIC` conserva por defecto `CONNECT` y `TEMP` sobre la base de datos y `EXECUTE` sobre funciones de `public`: no se puede revocar «para un solo rol».
  Comprueba antes de aplicar que `public` no tenga funciones propias con `EXECUTE` para `PUBLIC` (consulta de lectura abajo).
- La gramática acopla la base al generador actual: cualquier fixture sintético distinto exige una migración nueva (decisión deliberada).
- Quien tenga `postgres`/`service_role` puede escribir lo que quiera; esto protege al login de la aplicación, no al administrador.
- El bloqueo de límites es global (serializa solo inserciones en `casos` y `novedades`; coste despreciable a este volumen).

## Procedimiento de despliegue (sin ejecutar)

Cada operación remota exige tu autorización **antes** de ejecutarse; entre una y otra se verifica el resultado y se decide si continuar.

0. Confirmar la rama y el PR: Render despliega desde `main`; el código sigue **sin confirmar** en `codex/mvp-android-push-demo`. **[AUTORIZACIÓN: commit, PR, merge]**
1. *(Ya hecho por ti)* Comprobaciones de solo lectura: PG 17.11, `postgres` con CREATEROLE, tres migraciones registradas, sin `tinotify_sintetico_*`,
   `pg_default_acl` vacío, `PUBLIC` sin `CREATE` en `public`, `app`/`app_private` no expuestos, TLS y hostname del pooler. Falta una lectura: funciones de
   `public` con `EXECUTE` para `PUBLIC` (debería no haber ninguna propia):
   `SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f',p.proowner))) a WHERE n.nspname='public' AND a.grantee=0 AND p.prokind='f' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=p.oid AND d.deptype='e');`
   **[AUTORIZACIÓN: conectar a Supabase en modo lectura]**
2. **No** mover la propuesta a `supabase/migrations/` ni usar `db push`/`migration up` (aplicarían también `20261114020000`, pendiente). Se ejecuta el archivo con
   `psql` (contenedor `postgres:17.12`) contra el **pooler de sesión**, `sslmode=verify-full`, con `-v ON_ERROR_STOP=1`; la contraseña de `postgres` se teclea en el prompt.
3. **Aplicar la migración sintética** (única operación DDL). El archivo es una sola transacción (`BEGIN … COMMIT`) y su auditoría final aborta y revierte todo si algo no coincide. **[AUTORIZACIÓN: DDL remoto]**
   **El código de salida de `psql` no es una prueba de lo ocurrido**: `0` indica que se ejecutó hasta el `COMMIT`; distinto de `0` puede ser un error antes del `COMMIT` (nada
   aplicado) **o** una conexión caída justo después de confirmar (aplicado). Sea cual sea el resultado, **verifica el estado remoto** (paso 4) antes de decidir reintentar, revertir o seguir.
   No se reintenta a ciegas: una segunda ejecución con el esquema ya creado falla sin cambiar nada, pero no demuestra que la primera se revirtiera.
4. Lectura posterior (obligatoria tras cualquier resultado): consulta de solo lectura de verificación (5 tablas con RLS forzado, 11 políticas, 2 triggers,
   2 funciones, ACL exactas, rol `tinotify_sintetico_app` NOLOGIN, sin acceso de `anon`/`authenticated`/`service_role`, esquema no expuesto, historial de migraciones intacto,
   sin transacciones abiertas ajenas). Si el esquema existe, la migración se aplicó; si no existe, no. **[AUTORIZACIÓN: lectura]**
5. Crear el login y la contraseña (arriba) y verificar su alcance con el arranque de la app. **[AUTORIZACIÓN]**
6. En Render, **sin sobrescribir `tinotify-api`**: o bien un servicio nuevo de prueba con `render.sintetico.example.yaml` (recomendado), o bien cambiar
   start command y variables del existente. **[AUTORIZACIÓN: modificar Render]**
   `python -m uvicorn tinotify.sintetico_remoto.app:crear_app --factory --host 0.0.0.0 --port "$PORT" --workers 1 --no-proxy-headers`
7. Verificar: `/health` 200; `/sintetico/casos` sin token 401 y con token 200; `/real/cases` 404; HTTP plano rechazado; reiniciar el servicio y comprobar
   que los datos y el contador del monitor persisten; los logs de Render no contienen el token ni la contraseña.
8. Probar desde el Samsung con `EXPO_PUBLIC_SINTETICO_API_URL=https://<servicio>.onrender.com`.

## Reversión

- Render: restaurar start command y variables anteriores (o suspender el servicio nuevo) y desplegar el commit previo.
- Supabase **[AUTORIZACIÓN para cada operación remota]**:
  1. Lectura previa del estado (esquema, rol de grupo, miembros del rol, permisos del grupo en otros esquemas).
  2. `DROP ROLE tinotify_sintetico_login;` (el login asociado impide la reversión; no se borra a ciegas).
  3. Ejecutar `supabase/propuestas/20261115000000_crear_almacen_sintetico_down.sql` con `psql -v ON_ERROR_STOP=1`, igual que la aplicación.
  4. **Verificar el estado remoto** (el esquema y el rol `tinotify_sintetico_app` ya no existen; lo ajeno intacto). El código de salida no sustituye esta lectura.
  5. Solo si la migración llegó a registrarse en el historial: `supabase migration repair --status reverted 20261115000000`.
- Cómo se comporta la reversión (probado con un administrador `NOSUPERUSER CREATEROLE`, el caso de `postgres` en Supabase):
  - Identidad del esquema por **catálogos** (comentario exacto de la migración, propietario alcanzable y contenido exacto de 5 tablas y 2 funciones); no lee filas (el RLS forzado
    las oculta a quien no tiene `BYPASSRLS`).
  - Ignora la membresía **solo-ADMIN** que PostgreSQL 16+ concede al creador del rol; cualquier membresía con `SET` o `INHERIT` (un login) bloquea la reversión.
  - Sin `DROP OWNED` ni `CASCADE`: borra 5 tablas, 2 funciones, el esquema y el rol con sentencias explícitas. Si algo ajeno depende de ellos (una vista, un permiso en otro
    esquema) falla con `2BP01` y la transacción entera se revierte: el almacén queda intacto, no a medias.
  - Requiere PostgreSQL 16+ (en versiones anteriores se niega) y una identidad que sea o pertenezca al propietario del esquema.
  - Un permiso que `tinotify_sintetico_app` tenga en otro esquema (p. ej. un `GRANT` manual) hace fallar el `DROP ROLE` a propósito: hay que retirarlo antes.

## Pruebas locales (PostgreSQL desechable en Docker, con TLS)

```bash
cd backend && TINOTIFY_TEST_POSTGRES=1 python -m pytest tests/integration/test_sintetico_postgres.py
cd backend && python -m pytest tests/test_sintetico_postgres_config.py tests/test_sintetico_remoto.py
```

## Límites conocidos

- Un solo worker y una base: el bloqueo asesor evita monitores dobles, pero la API no está diseñada para varias instancias activas.
- Token único compartido; no hay usuarios.
- Render Free se suspende por inactividad: el monitor solo avanza mientras el servicio está despierto.
- Con PostgreSQL el estado `en_espera` es nuevo para Android (se muestra como texto crudo hasta que se añada su etiqueta).
