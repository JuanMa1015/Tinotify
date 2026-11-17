# SQLite local v2: observación atómica y continuidad sintética

Implementación exclusiva de desarrollo monousuario. No autoriza SIGAC, usuarios
reales, despliegue ni migración de archivos existentes. No modifica el motor puro,
JSON v2.2, PostgreSQL ni la aplicación Android. SQLite v2, revisión de estado JSON
2 y `fingerprint_version=1` son versiones distintas.

## Formato y compatibilidad

Se mantienen las ocho tablas locales: meta, seguimientos, expedientes,
actuaciones, sincronizaciones, eventos, vista_casos y vista_actuaciones.

- meta exige versión 2, perfil exacto y firma del DDL revisado. Objetos ajenos
  o diferencias del esquema bloquean la apertura.
- expedientes conserva generación y fencing; `(id,generacion)` es único.
- sincronizaciones añade `contenido_hash` y `digest_version`. Las operaciones
  de observación v2 siempre los guardan. Reservas internas sin digest no se
  aceptan como recibos verificables de la operación pública. La clave es única
  en todo el archivo: no puede reutilizarse para otro caso o instancia.
- eventos tiene FK a la identidad local de actuación. Sus UUID son persistentes.
- vista_casos conserva la generación de su proyección.
- vista_actuaciones usa PK `(expediente_id,local_id)`, orden único y generación.
  Sus FK diferibles vinculan identidad/huella al registro y generación al caso.

Un archivo existente se inspecciona sin escritura antes de DDL. El preflight
inicial usa conexión immutable de lectura para reconocer el formato; un archivo
v1, vacío, incompatible o con perfil equivocado se rechaza sin inicializarlo.
No se ejecuta DDL contra ningún archivo existente. Para integridad de un v2
reconocido se usa una copia temporal privada y su rollback journal, si existe;
la recuperación normal de SQLite se comprueba allí antes de abrir el original.
No se ejecutan reparaciones ni migraciones. El formato usa journal DELETE, no WAL.

Un archivo corrupto rechazado queda intacto. Una inicialización interrumpida no
se completa automáticamente. No hay comando de borrado/reinicio: el comando
antiguo `reiniciar` queda deshabilitado. Para otro experimento, elegir otra ruta.
Las comprobaciones de integridad no son una frontera contra un propietario
malicioso que reemplace archivos mientras se usan. Una copia no verificable
durante actividad concurrente bloquea la apertura, sin reintento automático.

## Contrato de operación

`ServicioNovedadesLocal.observar(caso, actuaciones, *, clave,
generacion_esperada, titulo=...)` exige una clave UUID y generación no negativa.
El caso es un UUID local canónico, no una afirmación de identidad institucional.
`generacion(caso)` permite capturar la precondición ANTES de obtener el lote.
`consultar_recibo(...)` recibe la misma clave, lote, título y generación originales.

La conveniencia sintética `observar_html` admite clave/generación explícitas o
captura ambas antes del parseo cuando se omiten juntas; no reintenta operaciones.
No omitir metadatos al recuperar una operación cuyo resultado se desconoce.
Los scripts y pruebas sintéticos nunca convierten esa conveniencia en autorización
para SIGAC. La interfaz interna de seguimiento conserva sus reservas y fencing;
su confirmación también escribe una proyección mínima en la misma transacción.

Una observación pública usa una sola conexión y `BEGIN IMMEDIATE`:

1. Buscar/crear seguimiento dentro de la transacción y comprobar el recibo.
2. Misma clave/digest: devolver el recibo, sin reescribir vista ni crear eventos.
3. Misma clave/digest distinto o ausente: conflicto explícito.
4. Para una operación nueva, comprobar generación esperada contra la actual.
5. Leer registros autoritativos y validar política y conservación de multiplicidad.
6. Si faltan versiones previas, rechazar como parcial/ambigua; no usar la vista.
7. Invocar el reconciliador existente y confirmar registros, generación y eventos.
8. Asociar la vista a las ocurrencias reconciliadas y confirmar la transacción.

No hay HTTP dentro de la transacción. Claves foráneas, rollback y
`synchronous=FULL` permanecen habilitados. Dos escritores no fusionan lotes:
el segundo con generación antigua obtiene conflicto aunque su lote pueda ser
una lectura legítima de otro momento. Para decidir otra operación hace falta
una precondición y observación actualizadas; no se reintenta automáticamente.

## Digest canónico: versión 1

SHA-256 sobre JSON UTF-8 sin ASCII forzado, claves ordenadas, separadores
compactos y NaN prohibido, producido por `contenido_logico` y `resumir`:

```
operacion_version: 1
fingerprint_version: 1
instancia, caso, perfil, politica
generacion_esperada
titulo: título sintético o constante «Expediente local» en perfil real
observaciones: lista ordenada por la serialización de cada elemento
  contenido: Actuacion.contenido_versionado()
  identidad: asdict(politica.aplicar(identificador_origen, contexto)) o null
```

La lista conserva repeticiones: no se convierte en set. El orden global de
actuaciones no tiene significado para la reconciliación; un reenvío reordenado
recupera el recibo sin cambiar la presentación ya confirmada. El orden interno
de filas de descripción sí importa. Los anexos se ordenan conservando duplicados
conforme a la huella existente. Unicode NFC y saltos de línea usan el contrato
de Actuacion. No se incluyen IDs locales aleatorios recién generados ni horas
de ejecución. Cambiar generación, caso, política o perfil cambia el digest.
El digest no convierte un candidato en identidad verificada ni anonimiza datos.
Solo se persiste el digest, no el documento canónico con contenido de actuaciones.

## Commit incierto e interrupciones

Un error después de que SQLite haya cerrado la transacción no se presenta como
rollback demostrado: se clasifica `ResultadoCommitIncierto`. La operación consulta
su recibo desde otra conexión; si está confirmado devuelve ese recibo sin repetir
la escritura y con cero novedades nuevas. Si falta o no puede comprobarse, se
detiene conservando la clave y lote originales. No cambia la clave ni reenvía.
Una operación repetida antigua no retrocede la vista de una generación posterior.

Las pruebas matan procesos antes, dentro de la ejecución SQLite de COMMIT y tras
confirmar antes de devolver respuesta. Fuerzan cache spill para ejercitar rollback
journals. También prueban un COMMIT que falla por una FK diferible y un ACK perdido.
Esto no demuestra resistencia a toda avería física, firmware o corte eléctrico.

## Privacidad e identidad

Perfil real mínimo: identidades locales, hashes, estados, generaciones, política,
recibos y eventos genéricos con prioridad/fecha de observación. Las vistas reales
guardan contenido `{}` y título fijo. No se persisten HTML, contraseñas, cookies,
descripciones, responsables, fechas de actuaciones o detalles de anexos. El perfil
sintético conserva campos detallados solo para datos ficticios.

Huellas e identificadores siguen siendo sensibles. El archivo, journals, copias y
temporales necesitan directorio privado, ACL del sistema y protección de disco;
la aplicación no implementa cifrado ni borrado seguro. No hay aislamiento multiusuario.
Los recibos/eventos no se purgan automáticamente: conservar claves evita su reutilización.
La consulta de avisos mantiene su límite de 100; no hay entrega push ni garantía
de entrega exactamente una vez. Consultar un pendiente no lo marca procesado.

**Selección institucional bloqueada:** `sigac_local.py consultar/monitorear` y la
entrada persistente por índice no habilitan consultas. El observador/ensayo de
lectura sin persistencia permanece independiente. Faltan un contrato revisado
para el identificador de expediente, alcance de unicidad, no reutilización,
evidencia de estabilidad y una señal de correspondencia de respuesta con el caso.
`hidCaso` observado y un UUID derivado no demuestran esas garantías. No se habilita
una configuración booleana ni se inventa un ID institucional. En una integración
futura también deberá verificarse pertenencia única al listado autorizado en cada
sesión; un UUID suministrado por el cliente no concede acceso.

## Pruebas reproducibles sin credenciales

Desde la raíz, con las dependencias existentes y sin instalar nada:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend\src).Path
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider backend/tests/test_sqlite_local_v2.py
```

El módulo bloquea sockets; los workers también. Todos los archivos son temporales
y sintéticos. Los workers son procesos independientes: primera ejecución A/B,
segunda A/B/C y tercera sin cambios; verifican IDs, recibos y un solo evento.
También cubren idempotencia, conflictos de generación, duplicados, privacidad,
archivos v1 byte a byte intactos, reapertura y coherencia transaccional.

No declarar completitud: un subconjunto estructuralmente válido y estable puede
establecer una primera base incompleta. La guarda impide perder lo ya conocido,
pero no descubre actuaciones que nunca llegaron ni fecha de creación real de una
primera observación. Los cambios ambiguos se rechazan en esta capa conservadora;
no se altera el reconciliador puro para forzar una conclusión.
