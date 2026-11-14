# 4B.4: bloqueo previo al harness funcional remoto

La propuesta posterior [4B.4-A](fixtures-inertes-4b4a.md) prepara un ciclo de vida
solo para fixtures inertes e inventario ampliado. Mantiene bloqueado el vinculo
Auth y no implementa el harness remoto; este documento conserva el diagnostico inicial.

## Estado de esta entrega

Base auditada: `origin/main` en `f301aee1f3dbcd31fdb5fe3e6cae2ab27917c9a7`
(PR #6 fusionado). Rama: `feature/4b4-validacion-remota`.

**La implementacion del harness remoto se detiene por falta de provision y
limpieza acotadas de fixtures.** Se aplica la condicion solicitada: si el modelo
impide limpiar sin privilegios excesivos, documentar y proponer antes de avanzar.
Esta entrega solo incorpora diagnostico y propuesta; no contiene un harness,
un nuevo autenticador, comparador ejecutable, migraciones o cambios de permisos.
No debe presentarse como validacion funcional remota superada.

Se revisaron las tres migraciones, los documentos 4B.3 y de persistencia, el codec,
las interfaces, el adaptador Psycopg, los servicios y las pruebas unitarias y de
integracion existentes. No se consulto Supabase en esta fase. El estado remoto
registrado en 4B.3 es historico: no demuestra que las migraciones esten actualmente
aplicadas ni que existan conexiones operativas o permisos de fixture provisionados.

No se solicitan secretos, se modifica Render/FastAPI ni se conecta SIGAC. No se
instala ninguna dependencia. La CI existente conserva Linux/Windows, integracion
Docker local en Linux y ningun secreto o conexion remota de esta nueva fase.

## Bloqueos confirmados en codigo

| Hallazgo | Evidencia | Consecuencia |
| --- | --- | --- |
| Los servicios no provisionan perfiles/evidencias | 4B.2-B, grants de las lineas 14-24; actor() exige perfil activo; acceso() exige fuente simulador y binding/epocas vigentes | No puede arrancarse un fixture nuevo solo con las capacidades operativas |
| No hay DELETE operativo ni funcion de limpieza | 4B.2-B solo concede DML interno finito; sus diez funciones no incluyen provision/eliminacion; interfaces.py tampoco | No se pueden retirar filas confirmadas por una ejecucion remota |
| No existe pertenencia de fixtures por ejecucion | Las ocho tablas carecen de registro de ensayo y vinculo inmutable a un run_id | Un prefijo de caso, UUID proporcionado o fuente simulador no autorizan borrar |
| Auth no resuelve la limpieza | 4B.1 linea 34: auth_subject referencia auth.users con ON DELETE SET NULL; las demas FK de negocio no tienen cascada de borrado | Eliminar una identidad Auth dejaria datos de Tinotify y no es una estrategia de limpieza |
| La prueba local depende de administracion desechable | integration/conftest.py: entorno_pg inserta Auth, perfiles y accesos como admin; postgres_aislado elimina su propio contenedor | No se puede redirigir ese fixture a Supabase ni convertirlo en provision remota |
| El adaptador rechaza privilegios directos o membresias administrativas | postgres.py: comprobar_identidad y capacidad() de 4B.2-B | Dar DELETE o acceso de propietario al login de aplicacion romperia el contrato, ademas de ampliar privilegios |

La ausencia de purga es deliberada en el motor de negocio: conserva actuaciones
ausentes e idempotencia. No se debe modificar esa regla para satisfacer un test.
Marcar un aviso como procesado tampoco elimina sus eventos, sincronizaciones o
actuaciones. Los comprobantes fuente=simulador no acreditan por si solos que un
perfil completo sea desechable o pertenezca al ensayo actual.

Un ROLLBACK por prueba es util, pero no cubre todo el objetivo: las sesiones de
concurrencia tienen transacciones independientes y las pruebas de idempotencia,
visibilidad tras COMMIT y recuperacion deben observar efectos confirmados. Una
transaccion exterior no revierte los commits de otras conexiones del pool.
Omitir esos commits cambiaria lo que se pretende validar.

## Solucion propuesta para aprobacion, no implementada

Recomendada: una capacidad de ciclo de vida de ensayos **separada de los roles
API/sync/notificaciones**, habilitada solo en Development mediante una nueva
migracion revisada. Conservar intactas las migraciones aplicadas y el dominio.
No basta con conceder DELETE temporalmente al harness o usar postgres para limpiar.

El contrato de esa capacidad debe cerrar estos puntos antes de escribir SQL:

1. Registro del ensayo y pertenencias inmutables: UUID run_id no reutilizable,
   proyecto Development permitido, operador/capacidad autorizada, vigencia,
   cuotas y referencias exactas a perfiles, instancia, cabeceras y casos creados.
   Requiere diseno adicional del registro/relaciones: **no existe en las ocho
   tablas** y no se introduce en esta entrega.
2. Provisiones y cierre mediante funciones finitas parametrizadas. Propietario
   NOLOGIN/NOBYPASSRLS, sin propiedad de tablas, con permisos minimos y politicas
   RLS por pertenencia al ensayo. search_path fijo y nombres calificados;
   REVOKE PUBLIC y EXECUTE solo para la capacidad de control aprobada. Sin DML
   directo para sus llamadores, ni membresia del propietario interno.
3. Reutilizar exclusivamente sujetos Auth ficticios preprovisionados por un
   procedimiento humano aprobado. Verificar su reserva para ensayos y ausencia
   de datos previos ajenos. No insertar directamente en auth.users, crear cuentas
   reales o usar service_role como identidad ordinaria del harness.
4. Reservar el ensayo antes de crear datos. Nunca aceptar un estudiante/caso ya
   existente como desechable porque el cliente aporte su UUID. La provision solo
   puede registrar recursos nuevos de ese ensayo, con cuotas pequenas.
5. Cerrar nuevas operaciones y detener workers; bloquear perfiles/recursos en
   orden determinista y verificar reservas activas, generaciones y fencing.
   Las carreras cierre/sincronizacion deben demostrar que no reaparecen datos
   despues de limpiar. No basta con que el proceso cliente diga que termino.
6. Eliminar exclusivamente pertenencias verificadas del ensayo, dentro de una
   transaccion. Revisar el orden de FK: eventos antes de sincronizaciones y
   actuaciones; accesos antes de expedientes; importaciones antes de cabeceras
   y perfiles; despues expedientes, cabeceras y perfiles propios del ensayo.
   No modificar Auth ni recursos previos. Si hay referencias ajenas, detenerse.
   No TRUNCATE, DROP, reset, reparaciones o filtros globales por prefijo.
7. Cierre idempotente y verificable: recuentos restantes por pertenencia, rechazar
   run/token/rol ajenos o expirados y conservar solo un recibo minimo del cierre
   con retencion aprobada. No registrar DSN, tokens, sujetos, filas o contenido.
8. Ante fallo de conexion, dejar el ensayo identificado como limpieza pendiente;
   recuperar con su misma identidad de operacion. Una reclamacion controlada por
   el operador debe recuperar ensayos abandonados. No dar acceso global para
   resolver una interrupcion ni declarar exito si la limpieza es incierta.

Esta propuesta necesita revision de modelo, RLS, autorizacion de control y
retencion. No se afirma que el propietario NOLOGIN o un run_id, aislados, basten
para garantizar su seguridad.

Alternativa conservadora: mantener las ocho tablas/permisos actuales y posponer
los ensayos funcionales remotos. Seguir con pruebas locales y preflight de lectura.
La alternativa no satisface la validacion remota, pero evita residuos y cambios
de privilegios. No se propone destruir el proyecto compartido de desarrollo.

## Requisitos del harness despues de resolver el bloqueo

Estas son condiciones de aceptacion futuras, no opciones ya disponibles:

- Opt-in cerrado por defecto; importarlo o ejecutar pytest ordinario no obtiene
  secretos, abre conexiones ni genera datos. Rechazar antes de conectar si falta
  aprobacion humana ligada a proyecto/run_id/commit/alcance/vigencia. Una variable
  de entorno o aprobar este PR no sustituye aprobar escrituras remotas.
- Confirmacion explicita del ref `urxfnmyuwbvnvrxkkppw` y vinculo revisado con el
  endpoint/ruta de pooler utilizados. No basta con imprimir ese ref: un nombre
  compartido de pooler y su certificado no identifican solos un proyecto.
- TLS verify-full real con CA revisada, prueba negativa de host/CA erroneos,
  conexiones directas o de pooler de sesion aprobadas. Sin fallback TLS o identidad
  administrativa; mantener comprobaciones efectivas del adaptador.
- Logins operativos diferentes por capacidad, NOADMIN/NOBYPASSRLS, sin grants
  directos o membresias de propietarios. El control de fixtures es separado y
  sus permisos deben revisarse sin dar acceso de administracion a la aplicacion.
- Autenticador sintetico exclusivamente de tests que verifique una atestacion
  de ensayo autorizada, vigente y limitada al run/proyecto/sujetos registrados.
  Debe cumplir la interfaz Autenticador, no aceptar UUID arbitrarios ni devolver
  Principal desde claims sin verificar. No implementar ni simular login productivo.
- Datos completamente ficticios, UUID/instancia/casos exclusivos por ejecucion,
  cuotas y manifest local protegido. No contrasenas, cookies o HTML SIGAC.
- El generador de atestaciones y la capacidad de provision no son permisos
  institucionales. Los contratos de identificadores sinteticos quedan en tests.
- La recuperacion no debe matar backends ajenos como hace el ensayo local con
  su administrador. Simular fallos solo sobre conexiones propias y con un
  mecanismo aprobado; no conceder pg_signal_backend para imitar el contenedor.
- CI de PR/main sin secretos remotos ni trabajo remoto automatico. Mantener la
  matriz Linux/Windows y Docker desechable; la ejecucion humana remota es separada.

## Fingerprints: limites encontrados y comparacion propuesta

No se ha generado una referencia local publicada ni capturado un snapshot remoto
en esta fase; **no hay comparacion ejecutada ni equivalencia declarada**. La
comparacion automatizada tambien queda pendiente del diseno aprobado. El
preflight 4B.3 existente es un inventario util, pero insuficiente para demostrar
equivalencia completa:

- En politicas, emite public/rol_no_interno y hashes de condiciones, pero no la
  lista exacta de roles internos destinatarios. Cambiar de reader a writer puede
  conservar esos indicadores y hashes; pg_policy.polroles distingue ambos.
- No inventaria tipo, orden, NOT NULL, generacion y defaults de todas las columnas
  de negocio. En PG17 NOT NULL esta en pg_attribute, no en pg_constraint. La
  comprobacion de attnotnull que contiene 4B.3 corresponde solo a auth.users.id.
- No incluye conname en sus entradas de constraints. Renombrar
  actuaciones_orden_uq conservaria el hash de su definicion, pero confirmar()
  usa ese nombre en SET CONSTRAINTS. El nombre es parte de la compatibilidad.
- El orden de algunos arrays depende del recorrido del catalogo/OID. Un diff
  textual del JSON no es un comparador canonico y puede producir falsas diferencias.

No se modifican ahora el preflight ni sus migraciones para ocultar estos limites.
El comparador futuro debe ser versionado y reproducible con este procedimiento:

1. Registrar SHA completo del commit limpio auditado, hashes LF de **todas** las
   migraciones y del extractor de catalogos, version del formato de snapshot,
   version/build de PG17 y digest de imagen local. La referencia se genera desde
   ese mismo commit, nunca de un JSON antiguo editado o de otro branch.
2. Aplicar en el PostgreSQL aislado las mismas migraciones declaradas aplicadas
   al remoto. Si el historial remoto esta incompleto o no es legible, detenerse
   antes de comparar o escribir. Una referencia con ocho tablas no equivale a un
   remoto que solo tenga 4A. No migrar automaticamente para forzar la coincidencia.
3. Capturar catalogos con transaccion de lectura, extraccion sin datos personales
   y perfil de representacion documentado (search_path/quoting/encoding/version).
   No ejecutar funciones de negocio ni incluir cuerpos, settings arbitrarios,
   filas, direcciones o credenciales en los artefactos.
4. Ampliar el inventario para nombres/firmas, columnas y su orden, tipos y typmod,
   NOT NULL/defaults/generacion/collation, PK/FK/CHECK/UNIQUE, validacion/diferibilidad,
   indices, RLS, roles destinatarios exactos y expresiones, funciones/propietarios/
   security/search_path y ACL efectivas de tabla/columna/funcion, membresias y
   defaults. No reemplazar nombres requeridos por etiquetas anonimas comparables.
5. Resolver OID a identidades calificadas estables. Canonizar objetos por sus
   claves; ordenar multisets conservando duplicados y distinguir NULL/false/
   ausente. Mantener el orden de columnas: confirmar() contiene INSERT posicional.
   No normalizar espacios dentro de literales o cuerpos ni alterar semantica SQL
   para conseguir hashes iguales. Usar JSON determinista y SHA-256 versionado.
6. Separar la capa de objetos Tinotify de la del proveedor. Informar diferencias
   de version/build, Auth, supautils y event triggers como evidencia separada;
   no descartar automaticamente una diferencia RLS/ACL/propiedad porque ocurra en
   Supabase. Una diferencia sin explicacion validada bloquea las escrituras.
7. Probar localmente igualdad determinista, reordenacion de catalogos, columnas
   NOT NULL/defaults alterados, cambio de rol RLS, renombrado de constraints,
   permisos heredados, objetos ausentes/extra, commits diferentes y snapshots
   corruptos/incompletos. Igualdad del snapshot no prueba comportamiento remoto.

La referencia historica 4B.3 registra PG remoto 17.11, seis event triggers y
supautils, frente al contenedor oficial sin esas protecciones. Son observaciones
anteriores, no una nueva consulta ni una comparacion de fingerprints de esta fase.
Estas huellas de catalogo no son huella_version de actuaciones; ninguna cambia
la identidad, reconciliacion o JSON v2.2. Los hashes tampoco anonimizan datos.

## Matriz de validacion que queda pendiente

| Grupo | Casos minimos antes de autorizar el ensayo remoto |
| --- | --- |
| Cierre por defecto | Sin opt-in/aprobacion/ref/CA/capacidad/atestacion: cero conexion o escritura segun la etapa de rechazo |
| Aislamiento | Dos estudiantes sinteticos y varios casos; recursos cruzados denegados; contexto limpio tras commit/rollback/reuso |
| Seguimiento | seguir/reservar/leer/confirmar/exportar/pendientes/procesar; primera linea base sin historicos; ausencias sin borrado |
| Idempotencia | Misma clave antes/despues de reinicio y respuesta COMMIT incierta; un recibo/evento; documentar limite de payload sin digest |
| Concurrencia | Dos conexiones y claves iguales/distintas; bloqueos, fencing, lease, acceso expirado; sin carreras de cierre/limpieza |
| Recuperacion | Fallos propios antes/durante COMMIT y limpieza; errores genericos sin secretos; recibo y reanudacion sin duplicados |
| Lifecycle | No adoptar IDs existentes, no ampliar alcance, cuotas, run ajeno, expiracion, limpieza repetida, interrupcion y cero residuos ajenos |
| Fingerprints | Misma referencia/commit, casos negativos descritos; proveedor informado sin equivalencia supuesta |

La aprobacion humana de escrituras futuras debe indicar el proyecto, commit,
run_id, capacidades previamente provisionadas, cuotas, ventana, datos sinteticos
y estrategia de limpieza/recuperacion. No puede inferirse de la autorizacion para
crear este documento o PR. No se incluyen comandos para insertar o limpiar remoto.

## Verificacion local de esta entrega

Solo se repiten pruebas existentes. No se agregan tests para simular un harness
que no se ha implementado ni se modifica CI para conseguir un resultado verde.

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\backend\.venv\Scripts\python.exe -m pip check
$env:TINOTIFY_TEST_POSTGRES='1'
$env:TINOTIFY_TEST_POSTGRES_VERSION='17.11' # repetir tambien con 17.12
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres.py -q -p no:cacheprovider
Remove-Item Env:TINOTIFY_TEST_POSTGRES_VERSION
Remove-Item Env:TINOTIFY_TEST_POSTGRES
```

El modulo funcional tiene 19 pruebas. No se repiten manualmente los seis casos
de integration/test_preflight.py: uno ejecuta DROP ROLE en su contenedor. La CI
existente sigue ejecutandolos exclusivamente en Docker desechable; no se habilita
su reutilizacion remota. Ningun DROP/TRUNCATE/DELETE SQL se ejecuta en los comandos
manuales anteriores; la limpieza local elimina solo el contenedor/red propios.

Resultados reales de esta revision: **332 aprobadas, 25 omitidas por opt-in** en
la suite ordinaria; **19 funcionales aprobadas en PostgreSQL 17.11** y **19 en
17.12** locales con TLS. `pip check` correcto. Persiste el aviso previo de
deprecacion HTTPX/Starlette TestClient. Son pruebas del codigo existente: no
validan Supabase, limpieza remota, atestaciones nuevas o equivalencia de catalogos.

## Decision solicitada

Revisar y aprobar primero el diseno de una capacidad de provision/limpieza
sintetica por ejecucion y la ampliacion del inventario de catalogos. Su DDL,
permisos, implementacion y aplicacion tendran revisiones separadas. Si no se
aprueba ese cambio, mantener bloqueado el harness funcional remoto.

Referencias: [preflight 4B.3](preflight-supabase.md),
[persistencia](persistencia-postgresql.md),
[pg_policy](https://www.postgresql.org/docs/17/catalog-pg-policy.html),
[pg_attribute](https://www.postgresql.org/docs/17/catalog-pg-attribute.html),
[pg_constraint](https://www.postgresql.org/docs/17/catalog-pg-constraint.html).
