# 4B.4-A: control propuesto de fixtures inertes e inventario v1

## Alcance real

Base exacta: PR #7, `d6d6829`; rama `feature/4b4a-fixtures-inventario`.
La nueva migracion `20261114020000_controlar_fixtures_inertes.sql` esta preparada
para revision y solo se ejecuto en PostgreSQL 17 local desechable. Las tres
migraciones anteriores conservan sus SHA-256 LF, protegidos tambien por tests.
No se consulto o modifico Supabase remoto, Supabase Auth, Render, FastAPI o SIGAC en esta fase.
No se agregaron dependencias ni un harness remoto.

**El vinculo de sujetos Auth sigue bloqueado.** No existe evidencia suficiente
para distinguir en auth.users un sujeto preprovisionado sintetico de otro usuario.
No se usa metadata editable de Auth, prefijos, UUID, un booleano del cliente o
fuente=simulador como demostracion. No se implementa esa provision ni se lee,
modifica, crea o elimina Auth desde la migracion. Las pruebas existentes crean
sus propios UUID ficticios en el Auth minimo del contenedor, nunca en Supabase.

Se implementa un subconjunto verificable: perfiles nuevos con auth_subject=NULL
y estado=pendiente, cabecera y casos vacios, accesos no_verificado/fuente=ninguna.
Un trigger impide cambiar identidad, activar el perfil o vincularle Auth mientras
este registrado como fixture. actor() no puede reconocerlo y acceso() no permite
sincronizarlo. No se altera el contrato Autenticador ni se fabrica Principal.

Por tanto, **no se acredita una sincronizacion positiva y posterior limpieza de
un mismo fixture autenticado**. Ese escenario y su cuota de actuaciones/eventos
quedan detenidos hasta demostrar el aislamiento Auth y revisar una ampliacion.
Los tests de carrera con sincronizacion validan que una sincronizacion sintetica
ajena continua intacta; no sustituyen esa prueba pendiente.

## Contrato y estado persistente

Nuevo esquema privado `app_fixture`, nunca destinado a Data API. Son tres tablas
de control, no un segundo modelo de expedientes; las ocho de negocio conservan
sus columnas/constraints. No se adopta ningun recurso existente.

| Tabla | Autoridad |
| --- | --- |
| entorno | Una fila protegida: project_ref Development fijo y habilitado=false inicialmente |
| ensayos | UUID generado en servidor, login SQL creador (OID+nombre), clave idempotente, SHA-256 de secreto de control, vigencia, estado y recibo |
| perfiles | Pertenencia inmutable de perfiles nuevos, cabecera y casos generados; FK diferibles para creacion/borrado atomicos |

El secreto de control debe generarse con CSPRNG: 32 bytes representados por 64
hexadecimales. Se pasa como parametro SQL, nunca en comandos de shell, chat,
SQL interpolado o logs. El servidor almacena su SHA-256, no el secreto. La
longitud no prueba entropia: el futuro llamador debe usar un generador seguro.
La autorizacion combina login restringido, pertenencia protegida, secreto y estado;
ningun UUID, token o variable de entorno basta por separado.

El ciclo normal es registrado -> provisionado -> cerrado -> limpio; puede cerrarse
un ensayo registrado sin provisionarlo. No se reabre limpio. Expirar impide crear
recursos pero permite al propietario cerrar/limpiar. Los recibos se conservan.

| Funcion publica en app_fixture | Comportamiento |
| --- | --- |
| registrar(clave,credencial,segundos) | Registro idempotente por login+clave, sin recursos; misma clave con otro secreto/TTL falla |
| provisionar(ensayo,credencial,perfiles,casos,politica) | Crea solo IDs del servidor y estructura inerte; replay exige mismos parametros |
| consultar(ensayo,credencial) | Estado, vigencia y recuento de pertenencias; no revela secretos ni filas de negocio |
| cerrar(ensayo,credencial) | Cierre idempotente; nuevas provisiones quedan prohibidas |
| limpiar(ensayo,credencial) | Solo cerrado/limpio; comprueba plantilla y pertenencias antes de borrar |
| recuperar_expirado(ensayo) | Capacidad separada; solo ensayos registrados y expirados, incluso de otro controlador; sin elegir recursos |

No hay parametros estudiante_id/expediente_id, SQL, tablas o filtros para borrar.
politica es un valor estructural de la plantilla, no una evidencia de confianza
de identificadores ni permiso institucional; no habilita reconciliacion activa.
Se generan perfiles mediante INSERT sin ON CONFLICT; una colision revierte en
vez de registrar una fila previa. Un controlador B no puede actuar sobre un
ensayo de A, aunque conozca su token. La recuperacion expirada es una autoridad
adicional explicita, no un permiso implicito del controlador.

Cuotas iniciales fijas: 1-2 perfiles y 1-2 casos por perfil; TTL 60-900 s; hasta
dos ensayos no limpios por login y ocho globales; maximo 1000 recibos, incluidos
los cerrados. Los expirados no se excluyen de la cuota hasta limpiar. Rebasar una
cuota falla, sin truncar ni eliminar filas. Revisar estos valores antes del despliegue.
No se introduce una purga automatica de recibos ni se permite reutilizar claves.
Al llegar al limite de recibos se detiene el registro hasta una decision revisada.

## Modelo de privilegios y amenazas

| Rol | Permiso estable |
| --- | --- |
| tinotify_fixture_control | NOLOGIN/NOBYPASSRLS; USAGE app_fixture y EXECUTE de cinco funciones de control |
| tinotify_fixture_recovery | NOLOGIN/NOBYPASSRLS; USAGE y solo EXECUTE de recuperar_expirado |
| tinotify_fixture_owner | NOLOGIN/NOINHERIT/NOBYPASSRLS, sin atributos administrativos; propietario de funciones, nunca tablas |
| API/sync/notificaciones, anon/authenticated/service_role/PUBLIC | Sin acceso al registro o funciones de control |

Los logins no se crean en la migracion y necesitan provision/aprobacion propias.
Usar cuentas tecnicas con nombres sin datos personales. El registro de su identidad
SQL es metadata administrativa, no identidad de un estudiante. Sus secretos no se
versionan. Las funciones rechazan logins administrativos, membresias de propietarios,
mezcla con roles operativos, mezcla control/recuperacion y privilegios directos.
Cada login solo puede ser miembro de su unica capacidad; se rechazan tambien
grupos predefinidos sensibles, ADMIN OPTION y CREATE de base/esquemas privados.

El propietario interno tiene SELECT limitado por RLS a perfiles registrados;
INSERT/DELETE solo en estudiantes, cabeceras, expedientes y accesos. No obtiene
DML de actuaciones, eventos, sincronizaciones, importaciones o Auth. UPDATE(id)
solo permite los bloqueos de perfiles/configuracion; ningun endpoint cambia esas
claves. En el registro tiene DML finito, sin DELETE de recibos o habilitacion del
entorno. Los llamadores no reciben DML directo ni membresia del propietario.

Las tres tablas nuevas tienen ENABLE/FORCE RLS y propietario postgres. Se agregan
17 politicas de negocio **solo TO tinotify_fixture_owner**, ademas de las 25
anteriores: no amplian las politicas de los servicios existentes. El trigger
fixture_perfil_inerte solo restringe perfiles registrados; los demas no cambian.

SECURITY DEFINER tiene propietario interno, search_path=pg_catalog,pg_temp,
nombres calificados, helpers sin EXECUTE publico y GRANT por firma. La migracion
requiere postgres/PG17 y la base con RLS/propiedad esperados. El bootstrap temporal
SET/INHERIT del operador se retira antes de COMMIT, como en 4B.2-B; no se usa
SET ROLE para eludir errores. La auditoria final verifica roles, propietario/RLS,
contexto de funciones y ACL de esquema, tabla, columna y funcion; falla ante
defaults o grants residuales. No los repara concediendo mas permisos.

Modelo de amenazas: controla parametros maliciosos, token robado a otro login,
GUC de sujeto falsificado, grants accidentales, carreras y fallos de transaccion.
No protege contra un administrador DDL que elimine los guards o edite el registro.
No se afirma que RLS o un propietario NOLOGIN resistan a un superusuario.

El flag de entorno es una autorizacion del operador, **no prueba criptografica
del proyecto remoto**. Antes de habilitarlo debe acreditarse el endpoint/proyecto
Development por un mecanismo independiente. No hay funcion para habilitarlo.
Aplicar DDL tampoco concede autorizacion de ejecucion o acceso institucional.

## Limpieza, concurrencia y recuperacion

Registro serializa la comprobacion de cuotas con la fila de entorno bloqueada.
Las mutaciones exigen READ COMMITTED para no evaluar cuotas con snapshots antiguos.
Las operaciones de un ensayo bloquean su fila, y limpieza bloquea sus perfiles
en orden UUID. No se agregan pertenencias tras provisionar. El estado cerrado
impide una provision concurrente. Se prueban esperas reales mediante blocking_pids,
no solo dos llamadas que podrian terminar ejecutandose secuencialmente.

Antes de borrar se exige la plantilla inerte exacta, sus IDs registrados y ausencia
de actuaciones, eventos, sincronizaciones o importaciones. Si hay datos inesperados,
falla y revierte: no adquiere DELETE adicional ni los adopta como desechables.
El orden es accesos -> expedientes -> cabeceras -> perfiles de negocio -> pertenencias;
las FK del registro son diferibles y se satisfacen antes de COMMIT. Cada DELETE
tiene predicado de pertenencia del servidor. Ninguna operacion purga por prefijo,
recorre ensayos para borrarlos globalmente o usa TRUNCATE/reset/repair.

La actualizacion del recibo limpio y todas las eliminaciones son una transaccion.
Se comprueba el numero de perfiles eliminado y que no queden perfiles de negocio.
Las FK inmediatas impiden ocultar hijos restantes. El recibo limpio repetido
devuelve el mismo estado; una pertenencia residual hace fallar la comprobacion.

El llamador futuro debe persistir clave y secreto de registro de forma segura
antes de conectar. Ante COMMIT incierto repite registrar con ambos, o consulta
el mismo ensayo y repite cerrar/limpiar: no genera otro ID. Las pruebas cubren
rollback antes de commit y respuesta descartada despues del commit; no afirman
haber reproducido una caida de red de Supabase. Recuperacion requiere un login
distinto autorizado y que el servidor compruebe expiracion. Si la plantilla esta
alterada, tambien se detiene y exige revision humana, sin limpiezas administrativas
automaticas. No hay un trabajador de recuperacion programado.

## Inventario ampliado y representacion determinista

`supabase/checks/4b4a_inventario.sql` sustituye al inventario 4B.3 para esta cadena.
Es un WITH/SELECT de catalogos, funciona sin USAGE de los esquemas de datos y no
ejecuta funciones de negocio. Cubre once tablas y 22 firmas: columnas por attnum,
tipo/typmod/NOT NULL/default/generacion/collation, constraints nominales, indices,
RLS y roles destinatarios exactos, funciones y contexto, triggers, ACL directas y
permisos efectivos por esquema/tabla/columna/funcion, membresias y defaults.

Las identidades controladas se muestran por nombre. Los demas identificadores y
todos los nombres de constraints se conservan mediante SHA-256 exacto; se muestra
tambien actuaciones_orden_uq por ser parte del contrato nominal. Renombrarlo cambia
su identidad aunque no cambie la definicion. Hashes no son anonimizacion: tratar
artefactos como metadata protegida y no versionar snapshots remotos sin revision.
Un marcador no previsto no se considera igual a otro por compartir la etiqueta;
debe revisarse tambien su identidad y detener una equivalencia automatica.

Los arrays se ordenan por claves estables y collation pg_catalog.C; las ACL incluyen
otorgante y delegacion y preservan multiplicidad. No se usa OID como identidad de
salida. Las columnas mantienen su orden fisico. No se normalizan literales/cuerpos
para fabricar hashes iguales. El informe versiona formato y perfil de deparser
(version PG, encoding, quoting, hash de search_path); comparar contextos incompatibles
requiere revision, no descartar campos automaticamente.

La consulta del historial existente agrega la cuarta version y revision_informe=2;
solo lee versiones/recuentos, nunca statements. El historial valido completo sera
[1,1,1,1]. Esta entrega no comprobo el historial remoto actual ni aplico pendientes.

Referencia reproducible futura: checkout limpio del mismo SHA, hashes LF de las
cuatro migraciones/extractor, digest de imagen PG17 y snapshots bajo el mismo perfil.
Las pruebas capturan y comparan dos inventarios locales y demuestran drift por
NOT NULL/default, nombre de constraint, rol RLS, grants de columna y membresias.
No se ha capturado un inventario remoto nuevo ni demostrado equivalencia.

Todas las migraciones locales se ensayan NOSUPERUSER, incluyendo 4A para reproducir
sus membresias ADMIN automaticas sin SET/INHERIT. La preparacion posterior del
contenedor restaura SUPERUSER al administrador local: ese atributo, el bootstrap
local y los logins ficticios difieren del remoto y aparecen en el inventario.
No ignorarlos silenciosamente. Supautils/event triggers del proveedor y su build
no estan emulados; sus contadores se informan aparte. Tampoco se demuestra con
el inventario la clasificacion de sujetos Auth ni la configuracion externa Data API.

## Pruebas y aprobaciones pendientes

Las pruebas nuevas son opt-in con el fixture Docker existente, que solo admite
Docker local y nunca lee DSN o secretos del desarrollador. No existe comando de
ejecucion remota funcional en esta entrega. CI mantiene Linux/Windows sin secretos;
Linux ejecuta integracion desechable. Las tres migraciones anteriores tienen
guardas de SHA-256 normalizado a LF; no se cambian los algoritmos o JSON v2.2.

Resultados locales ejecutados: **336 aprobadas y 59 omitidas** en la suite sin
PostgreSQL; **59 integraciones aprobadas en 17.11** y **59 en 17.12**, con TLS y
las cuatro migraciones aplicadas NOSUPERUSER. `pip check` y `git diff --check`
correctos. Se conserva el aviso previo HTTPX/Starlette TestClient. Se prueban
pertenencias ajenas, helpers/roles incorrectos, Auth/activacion bloqueados,
cuotas concurrentes, cierre/provision y limpieza con bloqueo observado,
rollback/respuesta descartada, recuperacion expirada y deteccion de drift.
Estos resultados no acreditan ejecucion de DDL o limpieza en Supabase.

Antes de desplegar se necesita aprobacion humana independiente para:

1. Nueva migracion, esquema privado, trigger, politicas y bootstrap de roles;
   validar permisos/efectos reales de Supabase sin reparar errores por elevacion.
2. Verificar que app_fixture tampoco aparece en Exposed schemas; no cambiar la
   Data API automaticamente ni depender del checkbox de exposicion de tablas.
3. Confirmar proyecto/ruta TLS, cuotas, retencion de recibos y roles tecnicos
   separados; provisionar logins/secretos fuera del repositorio si se autoriza.
4. Habilitar entorno y autorizar cada ensayo concreto y su recuperacion. No se
   incluye SQL para hacerlo remoto ni se infiere permiso de aprobar este PR.
5. Resolver el bloqueo Auth antes de permitir perfiles activos, actuaciones/eventos
   de fixtures, una limpieza de esos datos o el harness remoto completo.

El PR es revisable como una capacidad **inerte**. No declarar cerrada la validacion
funcional remota, limpieza de ensayos autenticados o equivalencia con Supabase.
