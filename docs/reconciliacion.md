# Identificación y reconciliación de actuaciones (etapa 3)

## Contrato y límites de identidad

Una observación no demuestra por sí sola la identidad de una actuación física.
El modelo `domain/actuaciones.py` separa:

- `Actuacion`: contenido observado y un identificador candidato o verificado opcional.
- `Actuacion.huella_version`: resumen determinista del contenido completo.
- `ActuacionReconciliada.identidad_local`: UUID persistente asignado por Tinotify.
- `ActuacionReconciliada.estado`: línea base, sin cambios, primera observación,
  modificación o ambigüedad.
- `EventoReconciliacion`: primera observación, modificación confirmada o cambio
  ambiguo. El estado de una observación puede seguir siendo ambiguo sin repetir
  eventos en consultas posteriores idénticas.

`IdentificadorSigac` es ahora un alias de candidato y solo valida sintaxis.
Acepta una cadena ASCII de hasta 128 caracteres, comenzando
por letra o número y continuando con letras, números, punto, guion, guion bajo o
dos puntos. La existencia, unicidad y estabilidad del identificador en el sistema
de origen requieren un contrato verificado por el adaptador que lo proporcione.
La validación sintáctica no demuestra esas propiedades del servidor. El motor
no usa candidatos como claves estables, aunque su valor se repita.

Un `IdentificadorEstableVerificado` se utiliza solo después de comprobar el
catálogo de contratos revisados, su habilitación y su alcance vigentes. El
catálogo predeterminado de producción está vacío. El contrato, la frontera de
confianza y las transiciones se describen en
[contratos-identidad.md](contratos-identidad.md).

Actualmente no se ha validado ese contrato con SIGAC. El parser no extrae ni
inventa IDs de atributos HTML, posiciones, fechas, códigos de anexos o hashes:
devuelve `identificador_origen=None`. Los IDs se prueban con objetos sintéticos.
La entrada al motor rechaza cadenas crudas como objetos de identidad. Una
consulta que repita una clave estable verificada en el mismo alcance se rechaza;
los candidatos repetidos conservan su multiplicidad. No se realiza red.

## Versiones de contenido

La huella utiliza SHA-256 de un JSON con `fingerprint_version=1` y estos campos:
fecha, etapa, origen, destino, remitente, descripción y metadatos de cada anexo
(descripción, nombre y referencia).

La serialización ordena claves, conserva Unicode y utiliza separadores fijos.
Los textos se normalizan a NFC y los saltos de línea a LF. Origen y destino
normalizan mayúsculas y espacios de borde. Los demás espacios del contenido se
conservan. No se inventan zonas horarias: la fecha usa su representación ISO.
Representaciones distintas de una misma hora con offsets diferentes pueden
producir versiones distintas.

Los anexos se ordenan por su representación canónica: cambiar únicamente su
orden no crea otra versión, pero agregar, quitar, modificar o repetir metadatos
sí lo hace. No se descargan archivos ni se detectan cambios binarios que mantengan
los mismos metadatos. No se eliminan parámetros de referencias suponiendo que
sean volátiles. Una referencia cambiante puede originar diferencias ambiguas.

Las huellas y los UUID no anonimizan información. Los IDs de caso, los IDs de
origen y los hashes persistidos deben tratarse como datos sensibles.

## Algoritmo único

`services/reconciliacion.py` es un motor puro que recibe el estado de un caso y
observaciones. Devuelve un estado nuevo y el resultado sin modificar la entrada.

1. Validar que no se repitan IDs de origen en la consulta.
2. Ordenar canónicamente las observaciones, sin usar su posición en el historial.
3. Revalidar contratos y emparejar claves de origen conocidas solo dentro del
   mismo contrato, revisión, instancia y caso.
4. Emparejar observaciones sin ID por igualdad de versión, una a una. Las colas
   de ocurrencias conservan multiplicidad; no se convierten los registros en un set.
5. Si un ID conocido cambia de versión, conservar el UUID y emitir una
   modificación confirmada.
6. Asignar UUID a cada ocurrencia todavía no conocida. Si faltan observaciones
   históricas que podrían corresponder a ella, clasificarla como ambigua.
7. Una nueva observación sin ID, con todas las anteriores representadas, es una
   primera observación para Tinotify; no demuestra creación reciente en SIGAC.
8. Conservar los registros ausentes sin emitir eliminaciones. Se mantiene el
   máximo de ocurrencias observado por versión anónima, incluso tras consultas
   parciales. Las reapariciones conocidas no producen avisos repetidos.
9. La primera consulta de cada caso establece línea base sin eventos históricos.

Si aparece un ID de origen donde antes había observaciones anónimas ausentes,
se registra como ambiguo y no se fusiona automáticamente con ellas. Si un ID
desaparece de una observación, tampoco se fabrica una correspondencia. Un ID
diferente, validado y sin candidatos anónimos ausentes identifica otra primera
observación, aunque tenga contenido idéntico al de un ID conocido.

Las identidades locales de duplicados exactos representan ocurrencias observadas
indistinguibles: no permiten saber cuál de dos actuaciones físicas se editó.
Dos historias que producen exactamente el mismo contenido observable son
indistinguibles para este motor. No hay coincidencias aproximadas ni reglas por
proximidad de fecha. Una ambigüedad no se resuelve por repetir la consulta.

## Eventos y avisos

| Situación sintética | Evento |
| --- | --- |
| Línea base `[A]`, después `[A, B]` | Primera observación de B |
| Línea base `[A]`, después `[A, A, A]` | Dos ocurrencias observadas adicionales |
| ID estable A con versión modificada | Modificación confirmada, mismo UUID |
| Sin IDs, `[A]` pasa a `[B]` | Cambio ambiguo; identidades locales distintas |
| `[A, B]` pasa a `[A]` y luego vuelve a `[A, B]` | Sin eliminación ni avisos de reaparición |
| Consulta idéntica tras reiniciar | Sin avisos repetidos |

El servicio conserva todos los campos del parser y expone
`ResultadoCaso.reconciliacion`. `MonitorActuaciones.sincronizar` sigue devolviendo
avisos como interfaz de compatibilidad; utiliza el mismo motor que `reconciliar`.

Cada evento interno conserva la ocurrencia que lo originó. Los avisos públicos
se agrupan por tipo y prioridad dentro de una consulta, por lo que dos eventos
iguales pueden producir un solo aviso genérico. El payload solo contiene tipo,
prioridad, título y mensaje: no contiene caso, dirección, UUID, remitente,
descripción ni referencias. Se mantienen las prioridades de asesor/dirección
hacia estudiante cuando la observación permite conocer esa dirección.

Esto no es una cola persistente de entrega: un fallo después de guardar estado
y antes de consumir los eventos puede perder un aviso. No se implementó push.

## Estado v2 y protección de archivos

El archivo actual tiene estas claves exactas (ejemplo estructural; la huella de
política debe calcularse por la aplicación, no copiarse de este ejemplo):

```json
{
  "schema_version": 2,
  "state_revision": 2,
  "fingerprint_version": 1,
  "trust_policy": "0000000000000000000000000000000000000000000000000000000000000000",
  "migrated_from_v1": false,
  "cases": {}
}
```

Cada caso contiene `records`, una lista con `local_id`, `source_id` opcional,
`contract_ref`, `origin_scope`, `version_hash` y `status`. La política viva valida
la referencia y el alcance; el archivo no aporta su propia evidencia. No se
guardan HTML, textos completos o metadatos crudos
de anexos. Se conservan referencias internas e información derivada sensible.

Se valida esquema, versión, algoritmo, tipos, UUID, hashes, estados y unicidad.
Se rechazan JSON corrupto, claves repetidas y valores no finitos. Un archivo
alterado o borrado después de cargarse se rechaza antes de continuar; no se
recrea o pisa silenciosamente.

Las actualizaciones usan un temporal único en el mismo directorio, flush/fsync
y reemplazo del archivo. La memoria solo avanza después de una escritura exitosa.
Un fallo limpia el temporal y permite reintentar sin perder la novedad.
La comparación con el estado leído detecta instancias ya obsoletas, pero existe
una ventana entre comprobación y reemplazo: **solo se admite un escritor**.
No se añadió bloqueo transaccional, SQLite ni soporte multiusuario.

## Migración explícita desde v1

Los v2 de revisión anterior y los cambios de política también requieren
transición explícita. No se elevan sus IDs a verificados. El procedimiento
completo y la pérdida deliberada de continuidad entre archivos están en
[contratos-identidad.md](contratos-identidad.md).

El formato anterior era un diccionario de casos a listas de hashes únicos.
No contiene información suficiente para recuperar identidades, cantidades o
versiones completas. Cargarlo lanza `EstadoAntiguo`; no activa un segundo motor.

La conversión autorizada por el operador utiliza
`MonitorActuaciones.migrar_estado_v1(origen, destino)`. El destino debe ser otro
archivo y no existir. La operación valida v1, crea v2 vacío con
`migrated_from_v1=true` y conserva el origen intacto. Debe seleccionarse después
el destino v2 como único archivo activo y detener cualquier ejecución antigua.

La primera observación de cada caso en v2 establece una nueva línea base sin
avisos históricos. **Pueden omitirse novedades ocurridas durante el cambio de
versión.** No se pretende reconstruirlas a partir de hashes. La migración avisa
de ese riesgo y repetirla no sobrescribe ni reinicia un destino existente.
Los fallos de escritura capturados limpian el destino nuevo; una interrupción
abrupta del proceso puede dejarlo incompleto, que se rechazará al cargarlo.

Se mantienen `Actuacion.huella` y `MonitorActuaciones.identificar_actuacion` como
compatibilidad de cálculo legacy, sin usarlos como identidad ni alimentar dos
motores. El parser continúa permitiendo importar `Actuacion` y `Anexo` desde
su módulo anterior, aunque sus definiciones están ahora en `domain`.

## Pruebas y límites restantes

Se conservan los 54 casos originales. Solo cambia la expectativa de
`test_crear_notificacion`: ya no se exige divulgar el caso ni una frase que
presente cualquier novedad como actuación nueva. La propiedad `huella` legacy
conserva su expectativa original; `huella_version` tiene pruebas independientes.

La suite añade duplicados, cantidades, inserciones, reordenaciones, cada campo
de contenido, anexos, Unicode, serialización, IDs repetidos, estados corruptos,
migración, reinicios, fallos de escritura y consultas parciales. Usa datos
ficticios y estados temporales, sin red ni dependencias nuevas.

Persisten límites: falta de contrato real de IDs, ambigüedad inevitable sin
ellos, crecimiento del estado por retención de observaciones, ausencia de
eliminaciones confirmadas, fechas sin política institucional de zona horaria,
límites del parser ante HTML parcial y ausencia de entrega transaccional.
