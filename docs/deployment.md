# Despliegue de la API minima e historial de infraestructura

## 4B.2-A: API preparada para Render, sin desplegar

La aplicación ASGI se importa como `tinotify.api:app` desde el paquete Python
instalado. Solo publica `GET /health`, con HTTP 200 y `{"status":"ok"}`. Es una
comprobación de disponibilidad del proceso, no de PostgreSQL, Supabase o SIGAC.
No carga `.env`, no requiere secretos, no crea estado persistente y no inicia
trabajos programados. No hay autenticación, endpoints de negocio ni conexión SQL.

Después de revisar y fusionar el PR en `main`, crear manualmente un **Web
Service** usando `JuanMa1015/Tinotify`. Estos son los valores exactos:

| Campo | Valor |
| --- | --- |
| Name | `tinotify-api` |
| Branch | `main` |
| Root Directory | `backend` |
| Runtime / Language | `Python 3` |
| Instance Type | `Free` |
| Health Check Path | `/health` |
| Environment | `PYTHON_VERSION=3.11.18` |
| Auto-Deploy | Desactivado; desplegar tras revisión explícita |

Build Command (shell de Render, ejecutado dentro de `backend`):

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-build.txt && python scripts/install_local.py && python -m pip check
```

Start Command:

```sh
python -m uvicorn tinotify.api:app --host 0.0.0.0 --port "$PORT" --workers 1
```

Render proporciona `PORT`; no fijarlo a 8000 ni pegar la sintaxis PowerShell
`$env:PORT` en ese campo. `PYTHON_VERSION` es un valor público y debe coincidir
con `backend/.python-version`. No añadir DSN, claves de Supabase, tokens ni
credenciales de SIGAC: esta etapa no los consume. El build instala únicamente
dependencias de ejecución y herramientas de construcción fijadas con hashes.
`requirements-build.txt` instala el backend de build y sus transitivas como
wheels verificadas antes de construir el código local. No instala pytest.

`scripts/install_local.py` construye únicamente el paquete Tinotify de este
checkout con `--no-index --no-deps --no-build-isolation`. La ausencia de aislamiento
de build evita que pip cree otro entorno y descargue dependencias sin hashes;
las herramientas ya están instaladas y fijadas. El script comprueba que se haya
generado exactamente una wheel, calcula su SHA-256 e instala ese artefacto con
`--no-index --no-deps --require-hashes --only-binary=:all:`. El manifiesto y la
wheel son temporales, no se descargan de Internet y se eliminan al terminar.
No se combinan fuentes locales con la resolución de dependencias externas.

`render.yaml`, en la raíz, conserva la misma configuración como Blueprint
opcional. Guardarlo en Git no crea un servicio. Crear o sincronizar un Blueprint
sí puede desplegar: requiere aprobación y no se ejecuta en esta etapa. No hay
comandos pre-deploy, migraciones ni recursos PostgreSQL en ese archivo.

Después de un despliegue autorizado, usar la URL que asigne Render:

```powershell
# Sustituir el host por el mostrado por Render; no se ha reservado este nombre.
Invoke-RestMethod -Uri 'https://HOST-ASIGNADO-POR-RENDER/health' -Method Get
```

La respuesta esperada contiene exclusivamente `status: ok`. `/docs`, `/redoc`,
`/openapi.json`, `/expedientes`, `/usuarios` y `/sigac` devuelven 404. Este health
check no demuestra que la integración de negocio esté lista.

### Validación antes del despliegue

Desde la raíz del repositorio, en un entorno Python 3.11 limpio:

```powershell
py -3.11 -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r backend/requirements-dev.txt -r backend/requirements-build.txt
.\backend\.venv\Scripts\python.exe backend/scripts/install_local.py
.\backend\.venv\Scripts\python.exe -m pip check
.\backend\.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider
```

El workflow `.github/workflows/backend-tests.yml` repite instalación, `pip check`
y pytest desde la raíz en PR hacia `main` y push a `main`, con `python-version: "3.11"`
en Linux y Windows: setup-python selecciona el parche compatible disponible en
cada runner. Render mantiene el parche exacto 3.11.18; Windows no dispone de ese
binario en setup-python. Sus permisos son solo de lectura y no recibe secretos ni ejecuta
SQL, Supabase CLI o despliegues. SonarQube sigue siendo una comprobación separada;
la ejecución de pytest no importa automáticamente cobertura en SonarQube.
CI usa el mismo instalador local no editable que Render y comprueba que Uvicorn
carga `tinotify.api:app`, sin abrir un puerto en el runner. No se omiten ni rebajan
reglas de SonarQube para permitir la instalación.

### Procedencia y actualización de los requisitos

Los hashes corresponden a wheels no retiradas de las versiones fijadas en PyPI.
Se descargaron los artefactos de `files.pythonhosted.org` por HTTPS y se comprobó
su SHA-256 contra los metadatos oficiales de cada versión. Se autorizan wheels
universales y las de CPython 3.11 para Windows x64 y Linux manylinux x86_64;
otras arquitecturas requieren resolución, revisión y validación adicionales.
El marcador de `colorama` conserva su instalación solo en Windows.

No regenerar hashes en CI: el conjunto autorizado se revisa y versiona antes de
instalarlo. Para actualizar una dependencia, resolver transitivas en un entorno
limpio, descargar las wheels de las plataformas soportadas, calcular SHA-256 y
contrastarlos con PyPI; actualizar juntos pins, hashes y el inventario del
manifiesto, y repetir ambas ramas de CI. `pip --require-hashes` debe rechazar
artefactos distintos o dependencias nuevas que no estén fijadas y verificadas.
Los hashes no constituyen una firma del autor ni garantizan ausencia de fallos.
La suite incluye una wheel completamente ficticia con hash incorrecto y comprueba
que pip la rechaza en `--dry-run --no-index`, sin instalarla ni consultar la red.

Starlette 1.10 conserva compatibilidad con HTTPX 0.28.1, pero avisa que su
`TestClient` deprecará ese transporte en favor de HTTPX2. No se suprime el aviso
ni se sustituye el cliente SIGAC en esta etapa; una actualización futura deberá
revisar ambos contratos antes de cambiar esas dependencias.

La suite verifica el ciclo ASGI, el contrato HTTP y un inicio en un proceso nuevo
con directorio vacío y entorno mínimo, sin variables de credenciales ni imports
del monitor, integración SIGAC o adaptador SQL. Las conexiones HTTP se simulan
mediante `TestClient`. Esto no acredita un despliegue real ni prueba PostgreSQL.

### Límites de Render Free

Render Free suspende servicios tras 15 minutos sin tráfico; el siguiente acceso
puede esperar aproximadamente un minuto al reactivarlos. El sistema de archivos
es efímero y el plan tiene cuotas compartidas de horas, builds y transferencia.
No usar pings artificiales para evitar la suspensión ni guardar JSON del monitor
en ese servicio. Esta API mínima es para comprobación y desarrollo; no ofrece
disponibilidad continua ni sincronización o avisos de fondo.

Referencias: [FastAPI en Render](https://render.com/docs/deploy-fastapi),
[Python](https://render.com/docs/python-version),
[Free](https://render.com/docs/free),
[Blueprint](https://render.com/docs/blueprint-spec).

## Historial 4A

Lo siguiente conserva la verificación histórica de infraestructura. No describe
las capacidades de la API mínima ni afirma que 4B.1 se haya aplicado al remoto.

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
