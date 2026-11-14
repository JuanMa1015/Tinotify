# 4B.2-B: persistencia PostgreSQL, pendiente de revision y aplicacion remota

La [revision 4B.4](validacion-remota-4b4.md) detiene el harness remoto: los permisos
actuales no provisionan ni limpian fixtures por ejecucion. Propone un contrato
separado para revision, sin ampliar las capacidades operativas de este adaptador.

## Alcance y compatibilidad

Se reutilizan exactamente las ocho tablas de 4B.1 y el motor puro `reconciliar`.
No se han reescrito 4A/4B.1 ni cambiado JSON v2.2, el parser o `/health`.
`actuaciones.version_hash` representa la version actual, no historia de versiones
ni contenido. No hay columnas para descripciones, responsables, anexos o HTML.
Los eventos guardan tipo/prioridad; los avisos se reconstruyen genericos. No se
inventan versiones anteriores al importar ni identidades para entradas ambiguas.
Las tablas de observaciones/versiones historicas siguen pospuestas por el diseno.

`codec_postgres` conserva contrato, alcance, multiplicidad, orden y UUID de los
registros v2.2, usando BYTEA con UTF-8 surrogatepass para las claves. La validacion
de confianza usa el catalogo vigente; una fila SQL no habilita un contrato.
Exportar usa REPEATABLE READ y falla si un caso incluido no esta autorizado:
no produce silenciosamente un estado parcial. Una politica distinta exige una
transicion explicita; no se cambia la firma ni se generan avisos historicos.

No se implementa importacion de archivos JSON ni transicion de epocas desde este
adaptador. `importaciones` permanece cerrada y no hay un segundo escritor del JSON.
`MonitorActuaciones` conserva su uso local; seleccionar el servicio PostgreSQL
debe ser una decision explicita de composicion. No activar ambos para el mismo
seguimiento. Los limites SQL de claves/cantidades no se amplian ni truncan.

## Controlador y conexiones

Se fija Psycopg 3.3.9, su distribucion binaria 3.3.9 y psycopg-pool 3.3.3.
Soportan Python 3.11 y PostgreSQL 17, con transacciones explicitas, SQL
parametrizado, BYTEA, UUID y JSONB. Las wheels llevan libpq, evitando compiladores
en Render; sus actualizaciones deben revisar tambien las bibliotecas incluidas.
`tzdata` se fija solo para Windows. Se verificaron hashes SHA-256 de las wheels
de Linux x86_64 y Windows x64. No se introduce ORM ni nuevas tablas de negocio.

`ConfiguracionPostgres` requiere host/usuario explicitos, CA local y
`sslmode=verify-full`. Rechaza postgres/service_role/supabase_admin, degradacion
TLS, options/service externos y el puerto conocido del pooler transaccional.
El operador debe seleccionar conexion directa o pooler de SESION desde Connect
del proyecto correcto; no se deduce el host ni se presume IPv4 directo.
`prepare_threshold=None` evita estado preparado innecesario. No se permite
desactivar TLS mediante una variable de entorno para desarrollo.

El pool se crea cerrado y solo abre por decision del llamador. Tiene hasta cuatro
conexiones por defecto, autocommit para establecer transacciones sin anidarlas,
comprobacion de conexion, reset y descarte de conexiones rotas. Cada conexion se
rechaza si su login es administrativo, miembro de un propietario privilegiado,
tiene privilegios directos de tabla/columna o si current_user difiere de session_user.
Se comprueba tambien TLS efectivo y verify-full. Al devolverla se restablecen rol y opciones.
El sujeto y los limites son SET LOCAL y desaparecen por COMMIT o ROLLBACK.
Nunca se cambia a un rol privilegiado para resolver un error.

Configuracion propuesta, NO cargada automaticamente por FastAPI:

| Entrada | Origen y condicion |
| --- | --- |
| DSN API/sync/notificaciones | Gestor de secretos; login diferente por capacidad, nunca cliente movil |
| Certificado CA | Archivo publico revisado del proveedor; ruta explicitamente inyectada |
| Modalidad | `directa` o `sesion`; puerto/host reales de Connect |
| Pool | 1 a 16 conexiones, valor inicial 4; ajustar al presupuesto total del proyecto |
| Autenticador | Implementacion confiable de servidor; no un user_id ni claims sin verificar |

No leer `.env` al importar. No registrar DSN, credenciales, claims, filas ni
excepciones SQL con sus parametros. Los errores del adaptador son genericos y,
cuando corresponde, contienen solo SQLSTATE. `/health` no importa ni inicializa
el adaptador y sigue funcionando sin driver conectado, DSN, CA o autenticador.
La configuracion y el servicio Render existentes no se despliegan ni modifican.

## Identidad y limites de confianza

`Autenticador.verificar` es una interfaz de composicion confiable que debe validar
firma, algoritmo, issuer, audience, vigencia y sujeto antes de entregar `Principal`.
No se implementa ni habilita un verificador JWT de produccion en esta fase. Los
autenticadores ficticios viven solamente en pruebas. Instanciar Principal no
demuestra validacion criptografica. No exponer estos dataclasses como payloads
HTTP ni construirlos desde UUID enviado por el movil.

El almacen exige ese autenticador, comprueba forma/vigencia antes de obtener una
conexion y de nuevo antes de COMMIT. Solo el sujeto validado llega a un contexto
local de transaccion. SQL resuelve el perfil activo por auth_subject; nunca acepta
estudiante_id como argumento de una funcion de servicio. Recursos de otro usuario
son invisibles o denegados. Un GUC no verifica JWT y no constituye autorizacion:
RLS contiene errores de consultas, no un backend o credenciales SQL comprometidos
capaces de suplantar el contexto que administran. No se promete esa proteccion.

La identidad Tinotify no prueba permiso SIGAC ni autorizacion institucional. Todas
las operaciones de datos exigen comprobante sintetico vigente por caso/binding y
epocas positivas. `fuente='sigac'` se rechaza aun si la fila dice verificado.
Solo el operador del entorno ficticio provisiona esos comprobantes. No hay
funciones operativas de autoatestacion, renovacion institucional o cookies.
Sin autenticador real revisado y sin permisos institucionales no debe habilitarse
ninguna ruta de negocio ni sincronizacion real.

## Migracion nueva y privilegios

`20261114010000_habilitar_persistencia_sintetica.sql` es una migracion NUEVA;
no se ha aplicado a Supabase remoto. Crea dos propietarios internos NOLOGIN,
NOBYPASSRLS y sin administracion, nunca propietarios de tablas. No tienen miembros
operativos. RLS sigue ENABLE/FORCE y las politicas limitan filas al perfil activo.

| Rol | Acceso operativo |
| --- | --- |
| tinotify_api | Seguir un caso propio, exportar estado y consultar pendientes |
| tinotify_sync | Seguir, reservar, leer caso y confirmar atomicamente |
| tinotify_notifications | Consultar pendientes y marcar un evento propio procesado |
| anon/authenticated/service_role/PUBLIC | Sin DML ni EXECUTE de funciones de servicio |
| tinotify_guard_reader | SELECT interno y resolucion de perfil; sin DML |
| tinotify_state_writer | DML finito interno, sin DELETE, Auth, importaciones o evidencia de acceso |

Los tres roles 4A permanecen NOLOGIN y no reciben permisos directos de tabla.
Logins futuros se provisionan separadamente por un operador autorizado, con
INHERIT solo de su capacidad y sin acceso a propietarios/roles administrativos.
No se crean esos logins o secretos en la migracion. No se configura ninguno real.

Las funciones SECURITY DEFINER tienen propietario explicito, search_path fijo
`pg_catalog,pg_temp`, nombres calificados y EXECUTE revocado de PUBLIC y de roles
no destinatarios por firma. No reciben SQL/identificadores dinamicos del cliente.
Los bucles de DDL solo usan listas constantes de la migracion. El CREATE temporal
del esquema para transferir funciones se revoca antes de COMMIT; estos roles
nuevos carecen de LOGIN y miembros operativos. PostgreSQL 17 concede al creador
NOSUPERUSER ADMIN sobre roles nuevos, pero no SET/INHERIT. El bootstrap concede
explicitamente SET/INHERIT solo al operador para transferir propiedad y cerrar
ACL, y revoca esa concesion antes de COMMIT. La membresia administrativa
automatica permanece sin SET/INHERIT. No se ejecuta SET ROLE ni se modifica 4A.
El operador necesita autoridad para crear roles y administrar los objetos;
si carece de ella, detenerse sin reparaciones automaticas de permisos.

Para SELECT FOR UPDATE, PostgreSQL necesita privilegio UPDATE. El propietario
interno writer obtiene UPDATE exclusivamente de `estudiantes.id` y de
`accesos_sigac.estudiante_id` para bloquear perfil/comprobante. Las funciones
publicadas no actualizan esas columnas ni evidencia. No se concede ese permiso
a conexiones operativas ni una funcion que permita SQL arbitrario.

## Atomicidad, concurrencia e idempotencia

La unidad de trabajo READ COMMITTED aplica orden de bloqueos:
perfil -> cabecera -> expediente -> comprobante -> trabajo. El bloqueo del perfil
serializa escrituras del mismo estudiante incluso entre casos: es conservador y
limita rendimiento; no se afirma paralelismo por caso para ese estudiante.
No hay HTTP, descarga o parseo dentro de la transaccion.

El servicio reserva y confirma en la MISMA transaccion corta. La reserva tiene
fencing incremental, generacion base, worker, token y lease de 60 s. Confirmar
recomprueba acceso, tiempo efectivo, epocas, token, fencing, politica y generacion.
Reconstruye el caso, llama al motor existente y persiste registros/eventos/recibo
juntos. Mantiene ausentes y rechaza payloads que intenten eliminarlos o cambiar
identidad. SQL exige orden contiguo y UUID no repetidos; PK/FK/UNIQUE siguen siendo
la autoridad de integridad. La primera observacion no emite historicos.

La clave de idempotencia identifica una operacion por estudiante/cabecera/caso.
Repetir una operacion confirmada devuelve su recibo; no vuelve a ejecutar el motor.
No hay digest del payload en 4B.1: reutilizar una clave con datos diferentes NO
crea una nueva operacion ni permite detectar esa diferencia; el llamador debe
usar una clave nueva. No se inventa una columna o tabla para ocultar ese limite.
Eventos son unicos por trabajo/ordinal, permitiendo A->B->A con identidad estable.

Una consulta posterior parcial no borra actuaciones. Cuota inicial de 20000
registros por caso/lote, configurable hasta 100000; fallo revierte todo y no
trunca ni purga estado. Importaciones, nuevas epocas y transiciones requieren
otra operacion revisada. No se reconstruyen versiones historicas inexistentes.

Fallo de conexion puede dejar COMMIT incierto. Se devuelve error generico y el
llamador debe repetir con la MISMA clave para resolver el recibo, no con UUID
nuevo ni retries ciegos. El pool descarta conexiones rotas y permite operaciones
posteriores; no reejecuta el motor por su cuenta. Deadlocks/timeouts/conflictos
revierten y se informan con SQLSTATE; no se eluden restricciones.

## Avisos y retencion

`eventos` es la cola de resultados pendientes de esta fase. Se consulta en orden
de prioridad y se marca procesado de forma idempotente, comprobando propiedad y
acceso. ServicioAvisos devuelve solo tipo/prioridad/textos genericos e ID opaco;
no reconstruye remitente/direccion ni contenido que SQL no almacena. El titulo
puede ser el generico de prioridad normal, conservando el campo prioridad real.
Procesado no equivale a entrega push. No hay reservas por dispositivo, proveedor,
reintentos de entrega o garantia exactly-once: esas funciones siguen pendientes.

No hay purga automatica: conservar registros e idempotencia durante la epoca evita
reapariciones falsas. Retencion, revocacion institucional, cierre, borrado y
backups de datos reales siguen requiriendo politica institucional. Los hashes no
anonimizan; aun sin texto juridico el estado es sensible. No almacenar credenciales,
cookies, documentos o HTML completo en estas tablas.

## Pruebas reproducibles

Suite ordinaria: pytest desde la raiz con el paquete instalado. La integracion
se omite por defecto y no necesita Docker ni PostgreSQL para las pruebas unitarias.

```powershell
$env:TINOTIFY_TEST_POSTGRES='1'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/integration -v
Remove-Item Env:TINOTIFY_TEST_POSTGRES
```

El fixture SOLO admite un Docker local (Unix socket/named pipe); no lee DSN,
DATABASE_URL ni secretos del desarrollador. Crea PostgreSQL 17.12 desechable,
red dedicada y puerto solo en 127.0.0.1, certificado/clave y password ficticios
temporales. Usa verify-full en conexiones reales y rechaza un nombre de servidor
incorrecto. La migracion nueva se aplica ademas con postgres NOSUPERUSER, usando
un harness exclusivo del contenedor para restaurar el fixture al terminar.
Se comprueba que no queden membresias SET/INHERIT hacia propietarios internos.
Admin solo aplica migraciones y provisiona fixtures; el adaptador usa
logins NOADMIN/NOBYPASSRLS con capacidades separadas. Datos son UUID y contenido
completamente sinteticos. Contenedor, volumen, red y claves temporales se limpian
en finally; una terminacion forzosa del proceso/host requiere revisar solo los
recursos `tinotify-test-*` de esa ejecucion, nunca borrado global.

CI mantiene unidades en Linux/Windows. Linux repite integracion TLS con Docker y
OpenSSL, sin proyecto Supabase ni secretos de produccion. No se prueba el pooler
real, el certificado de Supabase, provisiones de permisos del remoto o Render;
no se afirma esa compatibilidad operacional sin preflight autorizado.

Validacion local: 323 pruebas aprobadas sin PostgreSQL (incluidas las 303 previas)
y 19 pruebas de integracion aprobadas en PostgreSQL 17.12 con TLS verify-full.
`pip check` y la instalacion no editable tambien se verificaron. Se mantiene el
aviso de deprecacion de HTTPX en TestClient de Starlette, sin ocultarlo.

Referencias: [Psycopg](https://www.psycopg.org/psycopg3/docs/),
[RLS PostgreSQL](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
[TLS verify-full](https://www.postgresql.org/docs/17/libpq-ssl.html).
