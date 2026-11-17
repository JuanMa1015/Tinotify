# Cierre de las rutas de escritura SQLite v2

Implementación local, sin consultas SIGAC, instalaciones, migraciones o apertura
de bases reales. No habilita monitorización, endpoints ni notificaciones.

## Recorrido autorizado

1. Un cliente SIGAC autenticado estricto llama a `leer_historial_validado`.
2. Se ejecuta `SigacClient.consultar_historial`: pertenencia, sesión, identidad,
   ámbito y parser completo existentes. Un rechazo no emite acreditación.
3. Se emite `LecturaSigacValidada`, registrada por identidad de objeto en una
   tabla privada efímera. No hay constructor desde HTML, actos, booleanos o JSON.
4. `ServicioNovedadesLocal.observar_validada` delega a
   `ObservadorLocal.observar_validada`. Se exige perfil real e instancia SIGAC.
   El caso local procede del número contenido en la lectura; no se acepta que
   el llamador cambie el caso o sustituya las actuaciones.
5. El observador usa una transacción interna que también verifica la lectura y
   su referencia local. Digest, generación, reconciliación, eventos, recibo y
   vista se confirman en el mismo `BEGIN IMMEDIATE` existente.

`caso_local` es el direccionamiento UUID local preexistente, NO un identificador
institucional ni evidencia adicional de estabilidad. No se cambia ese contrato
ni se declara independencia entre cabecera e `hidCaso`. El monitor real y el
CLI persistente siguen cerrados mientras falte su contrato institucional.

## Límite de confianza explícito

La acreditación confirma que el código de aplicación ejecutó sus validadores.
NO es una firma criptográfica, una autorización institucional ni una prueba de
que SIGAC nunca devuelve contenido equivocado con marcadores concordantes.

El constructor público rechaza datos arbitrarios. `object.__new__` puede crear
un objeto vacío de esa clase, pero la resolución lo rechaza por no figurar en el
registro. Los handles no son serializables, copiables ni mutables mediante sus
atributos públicos. El registro débil conserva exclusivamente número y actos en
RAM mientras viva el handle; no HTML, credenciales, cookies o cliente HTTP.

El código Python del proceso es de confianza. Acceso a módulos privados,
introspección de closures, monkeypatch, transportes HTTP inyectados, sustitución
de servicios y acceso directo a `sqlite3` o `UnidadSqliteLocal._c` son operaciones
privilegiadas FUERA de esta frontera. Quien controla código o el archivo SQLite
puede eludir controles de aplicación. No se afirma protección frente a ese actor.
Los MockTransport de las pruebas simulan el origen y no acreditan TLS ni SIGAC real.

Las APIs sintéticas son herramientas internas para datos ficticios de un llamador
local de confianza; no son endpoints de importación de datos no confiables. No se
puede determinar el origen real de campos arbitrariamente copiados y reconstruidos
como una fixture: esa reclasificación deliberada es una violación del límite de
confianza, no una operación autorizada por cambiar un perfil. No exponer esas APIs
a solicitudes o plugins no confiables.

## Rutas cerradas

| Entrada | Comportamiento |
| --- | --- |
| `ServicioNovedadesLocal.observar_html` | Rechaza perfil/instancia reales y detalles con marcadores SIGAC incluso bajo perfil sintético. Solo parser genérico para fixtures. |
| `ServicioNovedadesLocal.observar` | No acepta historial SIGAC etiquetado ni acreditaciones. La escritura real directa se rechaza en el observador. |
| `ObservadorLocal.observar` | Rechaza perfil real, instancia SIGAC y datos etiquetados de origen SIGAC. |
| `ServicioSeguimiento.sincronizar` con SQLite | Rechaza origen real y respuestas SIGAC; para datos sintéticos delega al mismo `ObservadorLocal`. |
| `AlmacenSqliteLocal.transaccion` | Escritura pública de perfil real prohibida; lecturas permitidas. No basta la credencial fija local. |
| Monitor local | Todo servicio con almacén real se rechaza antes de autenticar, incluso con un doble de cliente. |

`HistorialSigac` sigue siendo una subclase de tuple, preservando lectura, orden y
multiplicidad del cliente. Su etiqueta SOLO sirve para RECHAZAR mezclas; cualquiera
puede construirla y eso nunca concede acceso. Convertir deliberadamente esos datos
a listas para tratarlos como ficticios no pertenece al flujo de aplicación real.
Los harnesses antiguos hacen esa conversión únicamente sobre fixtures sintéticas
conocidas; las pruebas nuevas de perfil real recorren la entrada acreditada.

`perfil` es una propiedad sin setter y se contrasta con los metadatos del archivo
al abrir transacciones. Mutar únicamente ese nombre no cambia el perfil almacenado
ni concede confianza. El código privado interno sigue siendo parte del proceso
privilegiado; no se presenta un prefijo `_` como una ACL del sistema operativo.
El contexto transaccional interno y los métodos de escritura de la unidad también
comprueban la lectura, en lugar de confiar solo en la guarda del servicio. Las
transacciones de lectura utilizan además `PRAGMA query_only=ON`; una modificación
SQL en esa conexión se rechaza aunque se acceda al atributo privado de conexión.
El propietario del archivo sigue pudiendo abrir otra conexión fuera del servicio.

## Idempotencia y compatibilidad

### Restricción posterior de alcance en la unidad real

La unidad real limita ahora todas sus operaciones de escritura al caso derivado
de la lectura y a la instancia `sigac-real`. La comprobación reside en Python,
en `UnidadSqliteLocal`, dentro de la transacción existente; no añade RLS, triggers,
columnas ni cambios en SQLite v2. Las firmas públicas se conservan.

| Método de escritura | Objetivo contrastado antes de modificar |
| --- | --- |
| `seguir` | Caso e instancia solicitados frente a la lectura. |
| `reservar` | Expediente y cabecera reales del seguimiento en la base. |
| `asociar_digest` | Seguimiento de la reserva y propietario real del trabajo; no basta el dataclass recibido. |
| `confirmar` | Seguimiento, trabajo y pertenencia real antes de actualizar identidades, generaciones, eventos, recibos y vista mínima. |
| `guardar_vista` | Caso explícito y expediente/cabecera obtenidos de la base antes de borrar o insertar filas derivadas. |
| `procesar_aviso` | Expediente propietario del evento, incluso aunque el llamador solo entregue su UUID. |

Una infracción de alcance deja la unidad abortada. Aunque el consumidor capture
`PermissionError`, no se permiten más escrituras y el contexto vuelve a comprobar
el estado antes de COMMIT: revierte también las escrituras legítimas anteriores
de esa transacción. Esto no consume ni invalida la acreditación; otra unidad
correcta puede reutilizarla con sus precondiciones e idempotencia habituales.

Las unidades sintéticas legítimas conservan su funcionamiento. No obtienen por
ello acceso a archivos reales ni una acreditación. Las consultas locales generales
no se convierten en autorización por estudiante; este cambio limita escrituras.
Código con acceso directo a `_c`, conexiones SQL propias, modificación de atributos
internos o al archivo sigue siendo privilegiado y fuera de esta garantía. No se
afirma que SQLite conozca el significado institucional de la acreditación.

La reproducción original permitía crear otro seguimiento dentro del contexto.
Se adaptó únicamente esa prueba anterior para exigir rechazo. La nueva matriz
incluye trabajos vigentes de B, reservas reconstruidas que aparentan pertenecer
a A, vistas y eventos de B, cambio de instancia y captura interna del error.
Antes de corregir, 11 rechazos no se producían y una reserva disfrazada fallaba
por otro control en vez del alcance. El caso legítimo de A ya aprobaba.

Resultados de esta corrección: 79 pruebas focalizadas aprobadas (los 67 casos de
la auditoría anterior y 12 nuevos casos de alcance). La suite completa intentada
con red bloqueada dio 1445 aprobadas, 1 omitida, 1 fallida y 10 errores de colección.
El fallo restante sigue siendo la importación API en un subproceso sin FastAPI;
los errores corresponden a `fastapi` y `psycopg_pool` ausentes. No se instalaron.
No hubo cambios de rama, commits, consultas SIGAC, bases reales ni notificaciones.

No cambia `_DDL`, esquema SQLite v2, JSON v2.2, huellas ni reconciliador. No se migra
ningún archivo ni se recrea información. Se usan `contenido_hash` y `digest_version`
existentes y la representación canónica v1 del observador.

Para SQLite, `ServicioSeguimiento.sincronizar` pasa por el digest y la generación
del observador. Misma clave y contenido lógico: recibo anterior sin escritura.
Misma clave con otro contenido, caso, política o generación lógica: conflicto y
rollback. El orden irrelevante se ignora y las multiplicidades permanecen.
El parámetro nuevo `generacion_esperada=0` conserva la llamada de primera base;
las transiciones posteriores deben proporcionar su generación. No se autorefresca
ni se fusiona un lote antiguo. Reenvíos usan la generación ORIGINAL de la operación.

Recibos anteriores sin digest se rechazan incluso si el llamador afirma que el
contenido es el mismo: no hay evidencia para verificarlo. No se rellenan, migran,
eliminan ni aceptan por fallback. Lecturas de estado existentes siguen disponibles.
La rama PostgreSQL de seguimiento no se cambia ni se valida remotamente en esta tarea.

El perfil real no acepta ya el título o actuaciones del llamador. Guarda el mismo
conjunto mínimo de metadatos y título genérico; no descripciones, nombres, fechas
judiciales detalladas, HTML, anexos, credenciales o cookies. Las bases previas no
adquieren retroactivamente procedencia acreditada: hace falta revisar su origen,
sin migrarlas o borrar datos automáticamente.

## Verificación y consumidores

Antes de modificar: cuatro regresiones fallidas y 37 pruebas SQLite aprobadas.
Las cuatro regresiones originales ahora aprueban. Se añadieron pruebas de objetos
fabricados/no registrados, cambio de perfil, transacción directa, lectura real
validada mediante MockTransport, idempotencia, conflictos sin cambios de bytes,
recibos antiguos sin digest y recuperación de commit incierto.

La prueba de minimización de perfil real conserva sus aserciones, pero obtiene
el contenido mediante el cliente validado; no utiliza datos arbitrarios. Las
pruebas de monitor con `ClienteGuion`/`SigacFalso` usan almacenamiento sintético.
La prueba que comprueba el rechazo de un archivo de otro perfil conserva la fábrica
productiva y sigue exigiendo detenerse antes de pedir credenciales.

Resultados finales realmente ejecutados, con red bloqueada:

- Antes: 4 regresiones fallidas y 37 pruebas SQLite v2 aprobadas.
- Después: las 4 regresiones aprueban; 19 casos nuevos de frontera y las pruebas
  de concurrencia, reinicio y commit incierto aprueban.
- Focalizadas: 128 aprobadas, 1 excluida por la dependencia FastAPI ausente.
- Suite completa intentada: 1426 aprobadas, 1 omitida, 1 fallida y 10 errores de
  colección. El fallo restante es el test previo de importación API en un
  subproceso sin FastAPI. Los errores son por `fastapi` y `psycopg_pool` ausentes.
- No se instalaron dependencias ni se ocultaron módulos bloqueados.

Los módulos de API cuyo entorno carece de FastAPI no están acreditados por esta
ejecución. Algunos consumidores antiguos también referencian entradas reales ya
cerradas en etapas anteriores; deberán revisarse al completar el entorno. No se
deben relajar estas guardas para restaurar esos comportamientos obsoletos.

## Archivos de esta corrección

- Nuevo `backend/src/tinotify/integrations/sigac/lectura_validada.py`.
- `backend/src/tinotify/integrations/sigac/sigac_client.py`: tupla etiquetada de rechazo.
- `backend/src/tinotify/persistence/sqlite_local.py`: puertas de escritura y lectura SQL.
- `backend/src/tinotify/services/observacion_local.py`: entrada acreditada y núcleo atómico.
- `backend/src/tinotify/services/seguimiento.py`: delegación SQLite al mismo núcleo.
- `backend/src/tinotify/services/monitor_local.py`: bloqueo temprano de todo almacén real.
- `backend/src/tinotify/demo/novedades.py`: separación de APIs reales/sintéticas.
- Nuevo `backend/tests/test_frontera_persistencia_sigac.py`.
- `backend/tests/test_bloqueos_identidad_persistencia.py`: descripción actualizada; mismas cuatro regresiones.
- `backend/tests/test_sqlite_local_v2.py`: minimización con lectura acreditada.
- `backend/tests/test_monitor_local.py`: dobles sobre perfil sintético, fábrica real en el test de rechazo.
- `backend/tests/test_recorrido_sigac_sqlite_v2.py` y `backend/tests/helpers/recorrido_sigac_sqlite_worker.py`:
  conversión explícita y exclusiva de sus fixtures conocidas para la simulación sintética.
- Este documento y `docs/auditoria-recorrido-sigac-sqlite-v2.md`: contrato y referencia al cierre.

Continúan pendientes la identidad institucional independiente, la completitud
real, la autorización institucional y la validación de consumidores bloqueados
por dependencias. No se declara preparación para producción ni entrega externa
exactamente una vez. Los eventos persistidos no equivalen a push entregado. El
almacenamiento sigue siendo local y monousuario, sin aislamiento multiusuario.
