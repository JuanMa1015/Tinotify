# Tablas históricas excluidas o anidadas

Corrección local validada únicamente con HTML sintético. No acredita que las
estructuras ambiguas se presenten en SIGAC real ni demuestra completitud.

## Defectos reproducidos

- Una tabla hermana con `id="tablaAnexos"` se excluía por su nombre aunque
  contuviera un bloque histórico completo.
- Una tabla histórica dentro de una descripción se absorbía como texto del
  bloque exterior; no conservaba una ocurrencia independiente.

## Política de clasificación

El nombre de una tabla no demuestra que contenga anexos. Antes de omitir tablas
de anexos no validadas o tablas interiores de una actuación ya interpretada,
se comprueba si contienen señales de la gramática histórica existente:
cabecera de dos celdas con fecha completa en la primera, categoría estática
conocida con contenido, o señales históricas en bloques con separadores propios.
Los valores de controles se retiran de esta comprobación.

Estas señales solo justifican **rechazo**, nunca crean una actuación nueva.
El diagnóstico existente es `ambito_tablas_no_interpretadas`, con incremento
de `tablas_no_interpretadas`. Los errores de anexos o controles detectados antes
conservan sus códigos. No se devuelven las actuaciones acumuladas antes del error.

Las tablas de anexos que el bloque ha interpretado efectivamente como metadatos
en una fila `Anexos` siguen excluidas de las ocurrencias históricas. Una fecha
como descripción legítima de anexo no crea una actuación. No cambia el tratamiento
de anexos sin enlace.

Las envolturas transparentes de layout conservan la extracción de sus tablas
históricas hijas, en orden y con multiplicidad. En el recorrido SIGAC deben estar
dentro del formulario de detalle validado. Una tabla histórica dentro de una
descripción no cuenta con esa delimitación inequívoca: se rechaza, sin inferir
si es una cita o una actuación independiente. Las tablas de presentación con
fechas en valores o menciones en texto siguen siendo contenido ordinario.

## Compatibilidad y persistencia

No cambian las huellas, el reconciliador, los contratos públicos ni SQLite v2.
La fixture `historial_dom_sintetico.html` se conserva intacta, pero ahora prueba
rechazo porque contiene gramática histórica completa dentro de una descripción.
Las comprobaciones positivas usan una variante sintética de presentación.
No se recalculan los hashes golden existentes para aceptar la ambigüedad.

Las regresiones pasan por el cliente simulado y la lectura acreditada, con y sin
línea base. El fallo ocurre antes de emitir la acreditación; tanto las tablas
SQLite como los bytes del archivo temporal permanecen iguales. No se crea
ningún evento, recibo, identidad, generación ni vista por esa lectura rechazada.

## Límites

La clasificación usa únicamente gramática ya reconocida. Puede rechazar una
cita legítima que reproduzca esa gramática: se necesita evidencia estructural
adicional antes de aceptarla. No clasifica arbitrariamente cualquier tabla
anidada como actuación, ni demuestra que un subconjunto bien formado sea el
historial entero. Permanecen sin acreditar el total, la paginación y una señal
institucional de fin de historial; lecturas iguales no demuestran completitud.
