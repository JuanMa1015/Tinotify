# Consistencia de identidad del detalle SIGAC

Esta validación comprueba concordancia de señales en una respuesta del endpoint.
NO acredita independencia entre la cabecera, `hidCaso` y el parámetro solicitado,
estabilidad institucional permanente ni completitud del historial. No habilita
monitorización o persistencia real. No se han ejecutado consultas reales para
implementar o verificar este cambio.

## Evidencia estructural y alcance

La inspección manual comunicada por el operador confirmó `form#form1`,
`name="form1"`, `action="casos.guardarCaso.con"`, `method="post"` y
`enctype="multipart/form-data"`. Su campo oculto tiene `name` e `id` iguales
a `hidCaso`, sin atributo `form`. La cabecera es un `div` con clases
`ui-state-default ui-corner-all`, anterior al formulario. Ambos comparten
un `div.ui-widget-content.ui-corner-all`. Las filas históricas extremas
observadas son descendientes del formulario, cuyo cierre aparece después.
No se presupone unicidad de esas clases ni que cada separador haya sido inspeccionado.

La implementación no inventa un selector de región histórica ni corta contenido
en el primer `hr`. Conserva el parser genérico para separar tablas, bloques,
anexos y regiones interactivas. Si no puede interpretar la información general,
el historial o los controles finales, rechaza la respuesta. No añade excepciones
ni omite tablas para aceptar un nuevo layout.

## Contrato de extracción

1. Mantener las validaciones HTTP, sesión y documento completo existentes.
2. Exigir cierres explícitos y no anidados de formularios y rechazar atributos
   relevantes duplicados; no confiar en reparaciones DOM de formularios malformados.
3. Exigir un único elemento con `id="form1"` y un único formulario con
   `name="form1"`, que sean el mismo formulario y tengan los atributos confirmados.
   El formulario no puede estar en otro formulario, controles, plantillas o anexos.
4. Exigir un único candidato global por `name` o `id` `hidCaso`; debe ser el
   mismo `input` oculto habilitado, con ambos atributos exactos, descendiente de
   ese formulario, sin propietario externo ni pertenencia a tablas de anexos.
5. Entre los ancestros `div` con las clases confirmadas debe existir exactamente
   un contenedor candidato con cabecera, y exactamente una cabecera en él.
   La cabecera debe preceder al formulario y estar fuera de formularios,
   controles, plantillas y anexos. Contenedores anidados igualmente candidatos,
   cabeceras duplicadas o formularios duplicados provocan rechazo; no se elige
   arbitrariamente el primero ni el ancestro más cercano.
6. Contrastar la cabecera y el campo oculto con el número solicitado, que sigue
   teniendo que pertenecer al último listado estricto validado.
7. Retirar el formulario de una copia DOM y someter el exterior al parser genérico.
   Si produce actuaciones o falla por ambigüedad, rechazar la respuesta.
8. Mantener además el parseo estricto del documento completo y compararlo con el
   parseo del formulario: todas las actuaciones deben coincidir en orden, contenido
   y multiplicidad. Se entregan exclusivamente las extraídas del formulario.
   Un `contenedor_id` opcional no puede reducir ese conjunto ni cambiar su orden.

El parseo exterior no demuestra ausencia de cualquier estructura histórica
desconocida; mantiene la gramática y los límites conservadores existentes.
La separación general/historial/controles sigue sometida a las mismas reglas y
rechazos del parser, sin una nueva heurística de exclusión.

## Comparación y normalización

- `Caso.numero` solicitado debe ser un entero positivo. Su forma de comparación
  es `str(numero)`.
- Cabecera: texto DOM con espacios consecutivos colapsados y extremos recortados;
  etiqueta exacta `Información del caso Nro.`, dígitos ASCII positivos canónicos,
  guion y estado no vacío. El estado no se restringe a `En proceso`.
- Campo oculto: valor textual exacto, sin recortar espacios ni eliminar ceros.
- No se eliminan ceros iniciales, signos ni se traducen dígitos Unicode. Se rechazan
  representaciones no canónicas: el parser del listado ya entrega un entero y no
  aporta evidencia suficiente para afirmar equivalencia de esas variantes en la
  respuesta. Una variante real exigiría revisión explícita; no se acepta por fallback.

## Fallos y privacidad

El cliente devuelve `SigacIdentityError`, subclase de `SigacClientError`, con
diagnóstico v2 y etapa histórica existente. Códigos constantes:

- `consistencia_identidad_detalle_no_confirmada`.
- `historial_fuera_detalle_o_ambito_ambiguo`.

Un rechazo de consistencia invalida la sesión local y limpia cookies. No realiza
nuevas solicitudes ni reintentos. Los errores del parser conservan sus códigos.
No se imprimen señales originales, URLs, cuerpos, identificadores o credenciales.
Las estructuras y textos de respuesta se procesan temporalmente en memoria.

La validación precede a la entrega al ensayo, reconciliación y persistencia.
No cambia el esquema SQLite v2, huellas o algoritmos de reconciliación. Las pruebas
sintéticas contrastan instantáneas de todas las tablas y bytes del archivo SQLite
antes y después de rechazos, tanto sin línea base como con estado existente.

## Validación local realizada

Antes del cambio funcional: 23 regresiones fallaron por aceptación indebida;
3 casos ya pasaban. La suite permanente ampliada incluye 51 casos de identidad,
envolturas, propiedad DOM, normalización, ámbito, orden, multiplicidad y SQLite.
No se incorporó HTML real: las envolturas del endpoint son sintéticas y están
separadas de los fixtures del parser genérico.

La suite completa del entorno actual tiene bloqueos previos por dependencias
declaradas pero no instaladas (`fastapi`, `psycopg_pool`). No instalar dependencias
ni modificar las pruebas para ocultar ese problema.

## Próxima prueba, pendiente de autorización

Proponer un único ensayo manual de lectura sin persistencia, tras revisar el diff:

```powershell
.\.venv\Scripts\python.exe -B backend/scripts/ensayo_sigac.py --autorizar-sigac-real --tipo 2 --total-casos 15 --indice-caso 1 --consultas 2 --diagnostico
```

Requiere autorización humana separada, confirmación interactiva y credenciales
sin eco. El total 15 debe seguir contrastado. Máximo nueve solicitudes en un
recorrido exitoso (seis de autenticación, dos historiales y un listado repetido).
Ante cualquier rechazo se detiene. No guardar respuestas ni informes sensibles.
El éxito solo acreditaría consistencia observada y lectura funcional; la completitud
seguiría sin verificar. La selección por posición pertenece exclusivamente al
ensayo sin persistencia y no habilita el seguimiento persistente real.

Persisten límites: diferencias entre el DOM de Chrome y BeautifulSoup en HTML
malformado, posibles variantes legítimas aún no observadas y mayor coste CPU por
los parseos de control. Todo cambio de contrato deberá revisarse sin relajar
validaciones automáticamente. Un servidor que devuelva conjuntamente marcadores
coherentes y contenido equivocado sigue sin ser detectable por estas señales.
