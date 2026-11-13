# Infraestructura y cierre de la etapa 4A

## Estado verificado el 12 de noviembre de 2026

La migracion `20261112050000_preparar_esquemas_privados.sql` fue aplicada por
el usuario con Supabase CLI. La verificacion posterior utilizo SELECT de solo
lectura, `config diff` y `db push --dry-run --skip-vault`. No aplico mas SQL.

| Comprobacion | Resultado |
| --- | --- |
| Proyecto | `urxfnmyuwbvnvrxkkppw` |
| PostgreSQL | 17.11 |
| `app`, `app_private` | Existen y pertenecen a `postgres` |
| Roles Tinotify | Exactamente `tinotify_api`, `tinotify_sync`, `tinotify_notifications` |
| Atributos | NOLOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION y NOBYPASSRLS |
| Membresias de escalamiento | Ninguno puede asumir `postgres` ni `service_role` |
| Acceso a ambos esquemas | PUBLIC, anon, authenticated, service_role y los tres roles Tinotify sin USAGE ni CREATE |
| Objetos en los esquemas | Cero tablas, vistas, secuencias y rutinas |
| Historial remoto | Una sola fila; version 20261112050000 aplicada exactamente una vez |
| Dry-run posterior | Codigo 0; ninguna migracion pendiente |
| Data API | Activa; Exposed schemas contiene solo graphql_public y public |
| Automatic exposure | Automatically expose new tables sigue activo; no se modifico |
| Backend | 241 pruebas con datos ficticios y red bloqueada |

La comprobacion de Exposed schemas se completo con la captura del Dashboard
proporcionada por el usuario despues de aplicar. `config diff` confirma que la
Data API esta activa, pero no proporciono esa lista. La ausencia de ajustes
`pgrst.db_schemas` en una consulta SQL no demuestra que un esquema este oculto.
La seccion `[api]` de `supabase/config.toml` describe configuracion local; no
ha desactivado la Data API remota. No se ejecuto `config push`.

## Este proyecto es desarrollo, no produccion de Tinotify

El proyecto remoto se usa **exclusivamente para desarrollo con datos ficticios**.
Supabase CLI puede etiquetar su rama principal como `production`. Esa etiqueta
no es una autorizacion institucional ni una decision de poner Tinotify en
produccion. No cargar expedientes, documentos, estudiantes, sesiones o
credenciales reales de SIGAC.

La separacion es una restriccion operativa: el backend actual no carga `.env`
ni aplica `TINOTIFY_ENV` o `TINOTIFY_DATA_MODE`. Produccion futura requerira un
proyecto y secretos separados, revision institucional, retencion, backups,
recuperacion y autorizacion expresa. No se ha creado ese proyecto ni desplegado
FastAPI, trabajadores, Expo, EAS o Vercel.

## Herramientas y configuracion local

Supabase CLI 3.1.0 esta fijada exactamente como dependencia de desarrollo en
`package.json`; `package-lock.json` conserva versiones e integridad. El paquete
raiz es privado. No se requiere PostgreSQL local ni Docker y no se instalaron
clientes SQL ni nuevas dependencias Python en 4A.

Restaurar herramientas en otro equipo necesita autorizacion para descargas:

```powershell
Set-Location 'C:\Users\gonza\Desktop\Proyectos\Tinotify'
npm.cmd ci --no-audit --no-fund
$env:SUPABASE_HOME = Join-Path $env:USERPROFILE '.supabase'
$env:SUPABASE_TELEMETRY_DISABLED = '1'
$env:DO_NOT_TRACK = '1'
npm.cmd exec --offline -- supabase --version
```

Debe devolver 3.1.0. `--offline` se refiere a npm: no bloquea la red de una
operacion remota de la CLI. Las variables de telemetria se exportan antes de
usar la herramienta; no asumir que lee el `.env` raiz.

La estructura ya se inicializo. No repetir `init --force`, `db reset`,
`migration repair`, `db pull` ni ejecutar manualmente el SQL aplicado mediante
el Dashboard. El historial oficial es `supabase_migrations.schema_migrations`.
Una correccion futura requiere otra migracion revisada: no editar la ya aplicada.
Su comentario de cabecera conserva el contexto original de preparacion y no
se modifica para cambiar el estado documental del despliegue.

## Identidades y limites de confianza

Se comprobaron el ejecutable instalado 3.1.0, el catalogo y la ruta observada
del dry-run. Sin password de base configurada, la CLI obtiene un login
administrativo temporal por la Management API, conecta mediante el protocolo
PostgreSQL y establece `postgres` como rol efectivo de la sesion. El catalogo
confirmo que `cli_login_postgres` puede asumirlo y que `postgres` tiene los
permisos necesarios. Es el mecanismo normal de la herramienta, no un GRANT
introducido para evitar un error. El archivo de migracion no cambia de rol.

`db query --remote=<ref> --read-only` usa el modo read_only de la Management API.
La sesion de lectura no era `postgres` y carecia de permisos de creacion; no
se uso ese resultado para inferir los de la conexion de migracion. Con una URL
SQL, `db query --read-only` utiliza una transaccion de lectura. No ejecutar
funciones con efectos externos aunque la sentencia comience con SELECT.

El administrador de migracion no sera la identidad habitual de FastAPI o los
trabajadores. Esos procesos necesitaran logins y secretos distintos, roles
restringidos y autorizacion por estudiante y caso. Los tres roles de 4A son
NOLOGIN y todavia no tienen permisos de negocio. Supabase Auth no acredita
permisos institucionales; no existe integracion autenticada con SIGAC.

## Secretos y datos locales

`.env.example` solo incluye ref y URLs publicas y nombres de DSN vacios. Ni el
backend ni la CLI consumen automaticamente ese archivo de ejemplo. Un DSN con
password detectado durante la preparacion se retiro sin reproducirlo ni copiarlo.
No rellenar credenciales en un ejemplo versionado.

Usar login interactivo y almacenamiento local seguro; nunca pegar PAT,
passwords, codigos de verificacion, cookies o cadenas autenticadas en el chat,
argumentos, SQL, logs o documentacion. No desactivar el almacen seguro para
resolver problemas de autenticacion. Render recibira secretos fuera del repo;
EXPO_PUBLIC_* solo admite configuracion publica, nunca claves privilegiadas.

Quedan ignorados `node_modules/`, `.supabase/`, `supabase/.temp/`,
`supabase/.branches/`, `.env*` salvo el ejemplo, archivos pgpass, claves,
exportaciones y backups. Los archivos `supabase/migrations/*.sql` y
`supabase/checks/*.sql` si son versionables tras revision. Un ignore no protege
secretos dentro de archivos permitidos ni archivos ya rastreados.

## Repetir la verificacion sin modificar esquemas

Autenticarse/vincular requiere permiso y se realiza interactivamente, sin
credenciales en argumentos. Este checkout ya esta vinculado; no necesita otro
login mientras la sesion sea valida. Para inspeccion autorizada:

```powershell
npm.cmd exec --offline -- supabase db query --remote=urxfnmyuwbvnvrxkkppw --read-only --file supabase/checks/4a_preflight.sql
npm.cmd exec --offline -- supabase migration list --remote=urxfnmyuwbvnvrxkkppw
npm.cmd exec --offline -- supabase db push --remote=urxfnmyuwbvnvrxkkppw --dry-run --skip-vault
```

El archivo preflight es una unica consulta de catalogos, sin DDL, y conserva
comprobaciones para antes y despues de aplicar. Ahora se espera encontrar los
dos esquemas y tres roles restringidos: su existencia no es un error posterior.
La seccion requisitos describe solo la identidad que ejecuta esa consulta.
PUBLIC se comprueba mediante ACL de esquema: no es un rol normal que pueda
pasarse por nombre a `has_schema_privilege`.

El dry-run debe indicar que la base esta al dia. No valida el DDL ni RLS y
puede inicializar acceso administrativo de control de la CLI; no es garantia
de cero efectos de autenticacion. No usar --yes, --include-all, --include-seed,
--include-roles ni ejecutar db push real como parte de una verificacion.

## Limites y trabajo posterior

4A no crea tablas de negocio, politicas RLS, usuarios de Auth ni logins de
aplicacion; no demuestra aislamiento multiusuario. Los defaults globales de
`postgres` no se cambiaron. Cada futura tabla, secuencia o rutina necesitara
ACL explicitamente revisadas, RLS y privilegios minimos en su misma migracion.

Automatically expose new tables sigue activo. Cualquier cambio de ese ajuste
requiere aprobacion; desactivarlo no sustituiria revisar grants existentes ni
EXECUTE para PUBLIC en funciones futuras. No crear objetos de Tinotify en public
ni incorporar app/app_private a Exposed schemas.

La etapa 4B se disenara y aprobara por separado. No se anaden en 4A un modelo de
datos, controladores PostgreSQL, SQL 4B, FastAPI ni notificaciones push. SQLite
no forma parte del plan. No instalar dependencias ni aplicar nuevas migraciones
sin autorizacion. Las pruebas actuales no acceden a Supabase y usan temporales
que se eliminan al finalizar.

## Referencias

- [CLI](https://supabase.com/docs/reference/cli/supabase-db-push)
- [Esquemas personalizados](https://supabase.com/docs/guides/api/using-custom-schemas)
- [Privilegios por defecto](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html)
- [Data API](https://supabase.com/docs/guides/api/securing-your-api)
