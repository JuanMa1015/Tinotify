# Ensayo local de lectura SIGAC

Código preparado con el contrato HTTP aportado por el usuario. Las pruebas son
sintéticas: no acreditan autenticación ni extracción real. Preparar este código
no autoriza ejecutarlo contra SIGAC. No hay conexión con Supabase, Render,
Android, push ni procesos programados.

## Contrato implementado

| Paso | Solicitud | Comprobación |
| --- | --- | --- |
| Formulario | GET `index.jsp`, bajo el origen HTTPS SIGAC fijo | Documento completo y un formulario POST al destino confirmado; campos exactamente conocidos |
| Login | POST `sesion.validar.ses`, formulario URL-encoded | Campos `cboTipo`, `txtUsuario`, `txtCaso`, `txtClave`, `cmdIngresar`; 302 al selector o principal exactos y cookie JSESSIONID aplicable |
| Selector | GET `general.formCambiarTipoUsuario.con` | Formulario POST de cambio de rol que ofrece ESTUDIANTE y cmdAceptar= Aceptar |
| Rol | POST `sesion.cambiar.ses` | Payload confirmado `chkTipoUsuario=ESTUDIANTE&cmdAceptar=Aceptar`; 302 a la principal |
| Principal | GET `general.principal.con` | Documento completo, sin formulario de login o selección de rol |
| Procesos | GET `casos.seleccionarCasos.con?motivo=ACTUAR_ESTUDIANTE` | Listado estructuralmente válido y total completo contrastado |
| Historial | POST `casos.formCaso.con` | `hidCaso` obtenido exclusivamente del último listado validado; `hidMotivo=ACTUAR_ESTUDIANTE`; parser DOM; total opcional |

`autenticada` solo pasa a verdadero después del listado protegido; ni 302 ni
cookie ni página principal bastan por separado. No es prueba criptográfica de
la identidad institucional ni garantía de que la sesión no caduque después.
El servidor sigue siendo responsable de autorizar cada solicitud. El programa
rechaza un expediente fuera del listado; no acepta un ID arbitrario por CLI.
Refrescar un listado con error revoca la habilitación local y limpia la sesión.

### Dos destinos de entrada, selección explícita común

El usuario observó un segundo destino exacto del 302 de login: la principal,
sin variantes ni parámetros. Esa observación no acredita autenticación ni rol.
El cliente admite únicamente selector y principal como destinos de entrada;
en ambos casos consulta explícitamente el selector conocido, valida que ofrezca
ESTUDIANTE, envía su selección y exige el 302 esperado a la principal. No se
consulta la principal antes de seleccionar el rol ni se siguen redirecciones
automáticamente. Si pedir el selector tras el login directo devuelve principal,
acceso, error o un formulario distinto, se detiene sin saltarse la selección.
La disponibilidad real del selector en esta nueva situación sigue pendiente.

Ambos recorridos usan seis solicitudes: GET acceso, POST login, GET selector,
POST rol, GET principal y GET listado. El ensayo con un caso y dos lecturas
conserva nueve solicitudes (añade historial, refresco de listado e historial).
Ante un fallo de autenticación se invalida el acceso local y se limpian cookies,
también ante advertencias, errores internos e interrupciones normales de Python.
No se reintenta ni se amplía la lista de destinos al fallar.

`autenticada` conserva su nombre por compatibilidad, pero significa acceso al
recurso comprobado mediante el protocolo de selección y el listado protegido.
La propiedad de solo lectura `rol_activo_confirmado` permanece siempre en false:
no existe una señal positiva comprobada del rol activo. Ofrecer ESTUDIANTE,
enviar su selección, reconocer enlaces o permitir el listado no constituyen
por separado esa señal. No se añade ninguna afirmación de rol activo al JSON.

Si el servidor ignora la selección y vuelve al selector, rechaza el POST o
deniega el listado, se detiene. Si ignora silenciosamente el cambio y devuelve
exactamente el contrato esperado, permitiendo el listado con otro rol, el cliente
no puede distinguirlo: puede confirmar acceso al recurso, nunca el rol activo.
Una prueba sintética reproduce explícitamente ese límite. Detectarlo requiere
observar una señal de rol activo antes de ampliar el contrato, sin inventarla.

El observador separado mantiene su máximo de dos solicitudes, su clasificación,
la ausencia de seguimiento y la limpieza incondicional de cookies. La principal
no se convierte por ello en prueba de rol ni habilita acceso sin selector.

No se presupone el valor real de `cboTipo`: se exige explícito y se comprueba
contra las opciones habilitadas del formulario inicial. El valor de
`cmdIngresar` se lee del HTML. `txtCaso` usa el valor del control (vacío si el
HTML no tiene atributo value), conforme al envío de un input HTML; puede
pedirse un valor explícito sin eco mediante `--pedir-caso-login`. Ningún ejemplo
histórico de usuario o expediente está codificado.

La forma DOM real de los controles no fue aportada con el contrato HTTP. Esta
implementación admite `cboTipo` como select simple y los tres campos de datos
como input; exige txtClave de tipo password y cmdIngresar con value explícito.
Son comprobaciones conservadoras, no afirmaciones de observación real. Ante
otra estructura se detiene antes del POST: revisar solo ese control, sin probar
valores alternativos ni ampliar automáticamente el contrato.

Los destinos permiten exclusivamente las rutas nombradas, relativas o absolutas
del origen HTTPS confirmado, sin query, fragmentos ni escapes. El destino de rol
a la principal ya figuraba en las pruebas existentes; si el servidor devuelve
otro, se detiene para revisión. No sigue cadenas de redirecciones ni SSO. Campos
adicionales, CAPTCHA o MFA que requieran ampliar el flujo bloquean el ensayo;
no se intentan eludir ni se reintenta el login.

## Integridad y límites

- Se reutiliza el parser de `526f01b`, con códigos diagnósticos y conteos añadidos
  sin cambiar sus condiciones de aceptación o rechazo. Sus tres fixtures y pruebas
  se mantienen. No se recuperan manifiestos ni dependencias antiguas. No se modifica el motor
  ni JSON v2.2, ni se abren estados históricos.
- El flujo HTTP usa el modo estricto de `extraer_casos`: una tabla con columnas
  Caso, Cliente, Estado, todas sus filas interpretables, IDs consistentes y sin
  duplicados. Su modo legacy mantiene el comportamiento anterior; no se usa en
  este recorrido. Otras columnas o estructuras requieren revisión explícita.
- Se exigen cierres de body/html en las páginas del recorrido. El transporte
  comprueba Content-Length si no hay compresión y limita HTML descomprimido a
  8 MiB. El exceso se rechaza, no se trunca. Estos controles detectan algunas
  respuestas incompletas; no son una prueba universal de completitud semántica.
- El total de procesos sigue contrastándose; para el primer ensayo se han
  confirmado 15. No se requiere contar manualmente actuaciones. Sin
  `--total-actuaciones`, se permite explorar un historial estructuralmente válido
  y no vacío, informando `completitud_no_verificada`. Se mantiene el rechazo de
  HTML malformado, errores HTTP, sesiones inválidas y estructuras ambiguas.
  Si se proporciona un total conocido, se exige su coincidencia y se informa
  `total_contrastado`, que tampoco prueba por sí solo completitud semántica.
  No hay recorrido automático de paginación porque ese contrato no ha sido
  observado. La falta de contador no impide probar lectura funcional.
- Para páginas con tablas ajenas, `--contenedor-historial` debe identificar el
  ámbito histórico completo demostrado. No elegir solo una tabla que funcione.
  Sin ese parámetro se valida todo el ámbito de tablas de la página; ante
  estructuras ajenas no interpretables se rechaza sin fallback heurístico.
- Un servidor puede entregar un subconjunto válido, o datos distintos del
  mismo tamaño. Ningún contador/parser demuestra por sí solo ausencia de
  omisiones: el contraste con la interfaz autorizada y su paginación sigue
  pendiente. La pertenencia local tampoco prueba que un servidor haya devuelto
  el expediente solicitado si no existe una señal de respuesta contrastable.
- Las repeticiones comparan multiconjuntos de huellas (orden irrelevante,
  duplicados conservados). Una variación se informa como cambios observados,
  nunca como estabilidad. Anexos con referencias volátiles pueden causar
  diferencias; no se interpretan como identidades estables.

## Credenciales y sesión

Un cliente por cuenta, sin uso concurrente. HTTPX verifica TLS, no usa proxies
del entorno y mantiene cookies solo en memoria. No se persisten contraseñas,
cookies, HTML, nombres ni identificadores de expedientes. No hay archivo .env
de SIGAC, parámetros CLI de credenciales ni lectura de cookies del navegador.
Usuario y clave se piden con getpass en terminal interactiva, sin fallback con
eco. Los strings y cuerpos existen temporalmente en RAM; Python no garantiza
borrado criptográfico de memoria. El cierre limpia el cookie jar local; no
ejecuta un logout remoto no observado ni promete invalidar la sesión remota.

El ejecutable deshabilita globalmente logging en su proceso dedicado, incluidos
los loggers hijos httpcore que podrían registrar Set-Cookie, y solo imprime un resumen de
cantidades. Los errores HTTP se transforman en mensajes genéricos sin conservar
la cadena de excepción con el request sensible. No usar depuradores, tracing,
grabación de terminal o instrumentación que capture cuerpos o variables locales
durante el ensayo real. El cliente HTTP inyectado es una frontera de confianza
para pruebas; el ejecutable real construye siempre el cliente seguro por defecto.

## Prueba local sin red

Desde la raíz, con el entorno ya existente y dependencias ya instaladas:

```powershell
.\backend\.venv\Scripts\python.exe -B backend/scripts/install_local.py
.\backend\.venv\Scripts\python.exe -B -m pytest backend/tests/test_sigac_flujo.py backend/tests/test_parser_historial.py -q -p no:cacheprovider
```

El instalador reconstruye solo el paquete local, con `--no-index` y sin instalar
dependencias externas. Las pruebas del nuevo flujo bloquean sockets y utilizan
MockTransport. Un resultado aprobado no equivale a viabilidad real de SIGAC.

## Ejecución real futura, solo después de autorización separada

1. Confirmar autorización de uso de la cuenta y de este ensayo. No enviar
   credenciales, cookies, capturas privadas ni HTML al chat o al repositorio.
2. Usar el valor observado de cboTipo y los 15 procesos confirmados, con el
   primer proceso del listado y dos consultas. No contar actuaciones ni enviar
   nuevas capturas o HTML. Identificar el contenedor completo si fuera necesario
   para delimitar una página mixta. No crear una
   actuación real para esta prueba. Si el listado cambia de orden y no puede
   contrastarse la selección por posición, detener el ensayo.
3. Sin grabar la terminal, completar las variables no secretas y ejecutar:

```powershell
$tipoObservado = Read-Host 'Valor observado de cboTipo'

.\backend\.venv\Scripts\python.exe -B backend/scripts/ensayo_sigac.py `
  --autorizar-sigac-real --tipo $tipoObservado `
  --total-casos 15 --indice-caso 1 --consultas 2
```

Si existe un ID de contenedor completo demostrado, añadir
`--contenedor-historial <ID_VERIFICADO>`; nunca sustituirlo por uno sintético.
Si txtCaso exige un valor explícito distinto del formulario, añadir
`--pedir-caso-login`: se solicitará sin eco. El programa exige además escribir
`SIGAC-LECTURA`, y después pide usuario y clave sin mostrarlos. Sin flag, con
confirmación incorrecta o sin terminal interactiva no abre conexiones.

El máximo son tres consultas al historial; no hay bucles ni reintentos de red.
Dos consultas suman nueve solicitudes en el recorrido confirmado. No se hacen
descargas de anexos ni consultas a otros expedientes. No hay envíos push ni
escrituras de actuaciones; login/rol sí modifican la sesión remota, como parte
del acceso normal.

Salida: resultado, lectura_funcional, completitud, cantidades por consulta,
comparaciones con la base inicial, eventos de baseline/posteriores y
persistencia=ninguna. Sin total de actuaciones siempre se devuelve
`completitud=completitud_no_verificada`, incluso cuando ambas consultas coinciden.
Las diferencias son cantidades de ocurrencias sin coincidencia de versión: no se
imprimen huellas, identificadores ni contenido. Una ausencia no afirma eliminación,
ni una versión distinta afirma modificación confirmada. Códigos: 0 estabilidad observada, 1 error/bloqueo,
2 cancelación/argumentos inválidos, 3 cambios observados y 130 interrupción.
Un 0 solo acredita este recorrido y contraste; no monitoreo autónomo, renovación
de sesión, cambios futuros o ausencia universal de omisiones. La primera base
no genera eventos históricos; errores no se convierten en observaciones vacías.

No ejecutar de nuevo tras un bloqueo probando otros campos o relajando controles.
Revisar el dato técnico exacto que falta, sin almacenar la respuesta sensible.

## Diagnóstico local opt-in del fallo histórico

El mensaje genérico anterior agrupa dos clases:

- `RespuestaIncompleta`: documento sin estructura/cierres confirmados, página de
  acceso/rol donde se esperaba una protegida, ninguna actuación reconocida o
  discordancia con un total opcional conocido.
- `ErrorParseoHistorial`: ámbito no verificable, contenedor inválido o ambiguo,
  separadores/cabeceras/filas inválidos, controles de formulario dentro de una
  actuación o metadatos/referencias de anexos no admitidos.

Para un ensayo **posteriormente autorizado**, añadir `--diagnostico` al comando
anterior, conservando `--total-casos 15 --indice-caso 1 --consultas 2` y sin exigir
`--total-actuaciones`. La opción no autoriza conexiones por sí sola: conserva el
flag de autorización, confirmación interactiva y credenciales sin eco.

Ante un fallo se mantiene exit code 1; con esa opción se imprime únicamente un
JSON de `diagnostico_version=2`, `etapa`, `categoria` y
`estadisticas_estructurales`. Etapa y categoría pertenecen a catálogos cerrados.
Sin la opción se conserva la salida resumida anterior. Una respuesta válida no
cambia por activar diagnóstico: su resumen añade los cuatro campos v2 con etapa
`finalizado` y categoría `lectura_estable` o `lectura_con_cambios`.
No hay nuevo recorrido,
reintentos, archivos de captura, descarga ni devolución de actuaciones parciales.

| Categoría o familia | Condición exacta |
| --- | --- |
| `documento_incompleto` | Falta html/body o alguno de los cierres que ya exigía la validación |
| `contenedor_ausente`, `contenedor_duplicado`, `contenedor_invalido`, `contenedor_es_anexo`, `contenedor_sin_tablas` | El ámbito explícito no cumple la condición indicada; nunca se imprime su ID |
| `ambito_tablas_no_interpretadas` | Quedan tablas con contenido sin bloques interpretables y además se extrajeron actuaciones o se indicó un contenedor explícito |
| `historial_antes_del_primer_separador`, `actuacion_separador_ausente` | Cabecera/contenido histórico antes del primer separador o segunda cabecera dentro de un mismo bloque |
| `actuacion_*` | Cabecera, formato de fecha, responsable, título opcional, comunicación, fila, etiqueta o contenido no cumplen su validación existente; cada punto tiene un código distinto |
| `anexo_*`, `anexos_*` | Anidación, estructura de fila, falta/multiplicidad de enlaces, contenido fuera de tablas de anexos o referencia no admitida; sin mostrar URLs ni valores |
| `sin_actuaciones_reconocidas`, `total_actuaciones_discordante` | El parser devuelve cero elementos o no coincide un total opcional proporcionado |
| `sesion_no_confirmada`, `respuesta_http_no_valida`, `respuesta_no_html`, `respuesta_html_vacia` | Rechazo del cliente anterior a la extracción; no se convierte en historial vacío |
| `limite_respuesta_excedido`, `longitud_respuesta_discordante`, `fallo_transporte_o_codificacion` | Límite de transporte, tamaño declarado incompatible o comunicación/decodificación fallida |
| `formulario_*`, `tipo_acceso_no_ofrecido` | Formulario, campos, controles, opciones o valor de submit distintos del contrato; no se muestran valores ni nombres procedentes del HTML |
| `autenticacion_no_confirmada`, `rol_*`, `redireccion_no_confirmada` | Acceso/rol/respuesta o destino no confirmados, conservando los rechazos existentes |
| `listado_no_confirmado`, `listado_cambiado_entre_lecturas`, `expediente_no_listado` | Listado inválido o cambiado, o expediente fuera del listado validado |
| `advertencia_biblioteca` | Advertencia convertida en error; nunca se imprime su texto |
| `error_interno` | Excepción inesperada o error sin código específico; solo se informa su etapa, sin clase libre ni traza |
| `fallo_no_clasificado` | Valor reservado del exportador ante un código ajeno al catálogo; no se copia el valor recibido |

El código `ambito_tablas_no_interpretadas` **no confirma que una tabla sea ajena**:
también puede ser historial malformado. No debe resolverse omitiendo esas tablas
ni seleccionando solo los bloques que funcionen. El diagnóstico no propone IDs,
selectores, textos o enlaces del documento.

Los conteos permiten conocer tablas/filas/separadores del documento y ámbito,
tablas de anexos y cantidad de enlaces, envolturas/formularios excluidos según
las reglas previas, tablas no interpretadas y bloques detectados/válidos/rechazados.
No hay desglose por tabla o actuación, posiciones, fechas, textos, nombres,
identificadores, hashes ni valores de atributos. Las claves están en una lista
cerrada; solo se exportan enteros no negativos (no strings ni booleanos).

Los totales del documento/ámbito proceden del DOM construido por BeautifulSoup;
pueden reflejar reparación sintáctica. Los contadores de recorrido solo describen
lo examinado **hasta el primer fallo**; no son un inventario exhaustivo ni una
garantía de completitud. Si falla antes de parsear HTML puede haber estadísticas
vacías. Un bloque contado como válido no se entrega cuando falla el conjunto.

La salida diagnóstica se vuelve a filtrar en el ejecutable y solo se muestra en
terminal; no se escribe en disco. Las respuestas y la sesión siguen siendo
transitorias en RAM. En este modo, una advertencia de biblioteca se convierte
en un error sin detalles, en vez de permitir que escriba mensajes en stderr;
también mantiene cerrado el recorrido. La ejecución y la causa del fallo real siguen pendientes:
las pruebas de estas categorías utilizan exclusivamente HTML sintético.

### Versión 2: procedencia de etapa y conservación de códigos

La etapa vive exclusivamente en un contexto en RAM que solo admite el enum
`EtapaSigac`; no almacena entradas, respuestas ni excepciones. Se actualiza antes
de cada operación: credenciales, creación del cliente, formulario, envío/login,
redirección, cookie, selector/rol, principal, listado inicial o repetido, historial
inicial o repetido, reconciliación, comparación, cierre y salida. La limpieza del
cliente conserva la etapa del fallo original si termina normalmente; si falla la
propia limpieza se informa `cierre_cliente`. No se deriva una etapa de URLs o HTML.

Al envolver `RespuestaIncompleta` se conserva su código, incluso
`documento_incompleto`. Los errores ValueError del listado reciben un código
específico; las advertencias y excepciones inesperadas se distinguen sin imprimir
mensajes originales. No se muestran trazas, clases libres ni valores de atributos.
Ejemplo ilustrativo de error (no es resultado de una consulta real):

```json
{"diagnostico_version":2,"etapa":"formulario_acceso","categoria":"documento_incompleto","estadisticas_estructurales":{}}
```

Esta versión corresponde solo a la salida diagnóstica, no al estado JSON v2.2.
Las reglas de extracción, hashes, reconciliación y persistencia permanecen intactas.
La clasificación del monitor mantiene el tratamiento anterior de acceso ante
listados rechazados; la conservación de códigos no agrega reintentos ni corrige
la pérdida de sesión ya identificada tras un timeout del listado.

La matriz automatizada usa el comando con tipo 1 y 15 procesos **sintéticos**:

| Escenario simulado | Etapa | Categoría | Solicitudes HTTP simuladas |
| --- | --- | --- | ---: |
| Control válido, dos lecturas | finalizado | lectura_estable | 9 |
| Fallo al construir cliente | creacion_cliente | error_interno | 0 |
| Submit sin value | formulario_acceso | formulario_submit_sin_valor | 1 |
| Campo deshabilitado | formulario_acceso | formulario_campos_no_confirmados | 1 |
| Documento inicial incompleto | formulario_acceso | documento_incompleto | 1 |
| Selector sin ESTUDIANTE | selector_rol | rol_estudiante_no_ofrecido | 3 |
| Destino de rol no admitido | redireccion_rol | redireccion_no_confirmada | 4 |
| Fila del listado inválida | listado_inicial | listado_no_confirmado | 6 |
| Advertencia en historial | historial_inicial | advertencia_biblioteca | 7 |
| Anidación profunda | historial_inicial | error_interno | 7 |
| Listado cambiado al repetir | listado_repetido | listado_cambiado_entre_lecturas | 8 |

Los errores no incluyen `lectura_funcional=true` ni entregan actuaciones parciales.
La estructura demasiado profunda sigue rechazada, no se aumenta ningún límite ni
se cambia el parser para aceptarla. Las pruebas comprueban salida, stderr y logging
contra marcadores sensibles ficticios. El control válido mantiene baseline sin
eventos, dos lecturas y completitud no verificada. Ninguno acredita SIGAC real.

## Anexos sin enlace de descarga

El ensayo real se detuvo con `anexo_enlace_ausente` en una fila de `tablaAnexos` con
dos celdas `td`, texto en la primera y la segunda sin ningún nodo. El diagnóstico
estructural descartó `<td/>`, enlaces fuera de celda, script/style/comentarios y
contenido en la segunda celda; el contexto indicó que la tabla cuelga de la fila
«Anexos» de su actuación, sin filas con forma de cabecera ni filas equivalentes en
otras tablas. La revisión visual del expediente confirmó una tabla con una fila
descriptiva sin enlace y otra con enlace PDF. No se confirmó que sea exactamente la fila
rechazada.

Se admite entonces `Anexo(descripcion, "", "", sin_enlace=True)`. **`sin_enlace` significa
solo que la respuesta no trajo referencia de descarga**: no afirma que el archivo no exista
(puede deberse a permisos o a un error). Ningún texto de notificación debe decir
«sin archivo». Una fila se conserva como anexo únicamente si cumple las siete condiciones:

1. La tabla es el contenido de la segunda celda de la fila «Anexos» de su propio bloque.
2. La fila tiene exactamente dos celdas, ambas `td`.
3. La primera celda tiene texto y no tiene forma de fecha completa (cabecera de actuación).
4. La segunda celda no tiene ningún nodo no vacío: ni texto, `<br>`, `&nbsp;`, imagen,
   script, style ni comentario.
5. La etiqueta de apertura original de la segunda celda se verificó como no autocerrada;
   si no puede verificarse, se rechaza.
6. La fila no contiene ningún `<a href>`.
7. La misma tabla contiene al menos un anexo con enlace válido (se evalúa al cerrar la
   tabla; sin él, se rechaza el historial). Un anexo sin enlace que sea el único de su
   tabla sigue rechazado hasta tener evidencia de ese caso.

Cualquier otra fila sin enlace sigue rechazando el historial completo con
`anexo_enlace_ausente` y los indicadores diagnósticos existentes, que se conservan. Un fallo
inesperado al evaluar las condiciones rechaza; nunca admite. Ninguna fila se ignora: cada
una admitida aparece como `Anexo` y en el contador del resumen.

Resumen del ensayo: `anexos_sin_enlace_por_consulta` informa solo una cantidad por consulta
de historial. Tras una ejecución real autorizada debe aceptar el historial y mostrar al menos
un anexo sin enlace, coherente con la observación visual; no se exige coincidir con un
conteo manual total. Si vuelve a rechazar, la fila rechazada tiene otra forma y no se amplía
la regla sin evidencia. **Esta implementación no se ha ejecutado contra SIGAC.**

### Huella y compatibilidad

`VERSION_HUELLA` sigue en 1. `Anexo.contenido()` añade `"sin_enlace": true` solo para anexos
sin enlace; los anexos con enlace conservan exactamente sus tres claves. Las pruebas de
`test_huellas_compatibilidad.py` fijan valores golden capturados con el código anterior
(anexos normales, orden, duplicados, Unicode NFD, archivo vacío con referencia y la
extracción de las fixtures existentes), y comprueban que el anexo sin enlace tiene una
representación inequívoca, que el orden no afecta, que los duplicados sí y que pasar de sin
enlace a con enlace cambia la huella. El estado persistido guarda solo `version_hash` y
exige igualdad de `fingerprint_version`; ninguna actuación con una fila de este tipo pudo
guardarse antes, porque el historial completo se rechazaba. Riesgos: una respuesta
intermitente podría generar eventos de ida y vuelta, y una nota informativa dentro de una
tabla poblada podría confundirse con un anexo (la forma por sí sola no lo distingue).

## Región interactiva `div#tabs`

SIGAC usa un `form#form1` global; el historial y el formulario de registro de actuaciones
comparten la tabla principal, y el formulario va agrupado en `div#tabs` dentro de una fila de
una sola celda. Esa región no es una actuación. Solo se excluye si se cumplen **todos** los
criterios (no depende de ningún `<form>` independiente ni del identificador por sí solo); si
falla uno, el historial se rechaza por controles como antes (`actuacion_con_controles`):

1. Existe exactamente un elemento con `id="tabs"`, es un `<div>` y está dentro de la tabla.
2. Su fila directa tiene una sola celda `td` y, fuera de la región, solo contenedores
   estructurales (`tr`, `td`, `table`, `tbody`) sin texto: una fila de contenido con un
   `div#tabs` dentro no se excluye.
3. Todos los controles de la tabla están dentro de la región, y esta contiene al menos un
   `textarea`, un control de envío y un panel `div#tabs-<n>`.
4. No contiene `tablaAnexos` ni filas con fecha completa en la primera celda.
5. Después de la fila solo hay filas vacías o separadoras.
6. La fila anterior es un separador, una fila vacía o la fila «Anexos».
7. Tras retirar esa única fila, ningún bloque conservado tiene controles.

Solo se retira esa fila (o el bloque que contenía únicamente esa fila); nunca filas
adicionales. Con `contenedor_id` explícito no se aplica. Resumen del ensayo:
`regiones_interactivas_excluidas_por_consulta` y `filas_interactivas_excluidas_por_consulta`
(solo enteros; `null` si el cliente no los informa). Esperado: 709 actuaciones con 1 región
excluida si el formulario es un bloque propio; 710 si va pegado o anidado en la última
actuación, que debe conservar sus anexos. Las huellas coinciden con las del historial sin
formulario; `VERSION_HUELLA` sigue en 1.

Limitación previa, no introducida aquí: un control dentro de la fila separadora inicial de la
**primera** actuación hace que esa fila deje de ser separador y el bloque quede como «prefijo»
de la tabla, que se ignora. Es una estructura no observada y no se modificó.

### Diagnóstico de la región interactiva (solo si no se excluye)

Si una actuación se rechaza por controles y no se excluyó ninguna región (sin `contenedor_id`),
el diagnóstico añade enteros `region_*` que evalúan cada criterio por separado, sin cambiar el
resultado: `region_c1_ok` a `region_c7_ok` (1 = se cumple), conteos de controles fuera de la
región separados en `en_prefijo` (antes del primer separador) y `en_actuaciones`, y
`region_fila_previa_tipo` (0 no hay, 1 separador, 2 vacía, 3 con tablaAnexos, 4 otra, 5 ancestro).
Un valor que no puede determinarse se omite; nunca se informa 0 en su lugar.

## Diagnóstico del destino del login (versión 2)

No cambia el contrato de destinos admitidos ni se siguen redirecciones adicionales.
Tras un HTTP 302, todos estos rechazos mantienen la etapa `redireccion_login`:

| Categoría | Condición |
| --- | --- |
| `location_ausente` | Encabezado ausente o de valor vacío. Un valor con espacios es un error de formato. |
| `location_multiple` | Más de un encabezado Location, incluso si coinciden o uno está vacío. |
| `redireccion_formato_no_admitido` | Espacios/controles, análisis inválido, esquema sin host, consulta o fragmento no vacíos, porcentaje o barra invertida. |
| `redireccion_origen_no_admitido` | Origen/esquema no admitido por la comparación estricta existente. |
| `redireccion_a_acceso` | Destino `index.jsp` del mismo origen, tras superar los controles anteriores. No demuestra credenciales rechazadas. |
| `redireccion_destino_no_confirmado` | Otra ruta no admitida, incluidos prefijos `./` y parámetros añadidos a la ruta. |

Precedencia: encabezados duplicados, ausencia/vacío, formato inicial, origen,
formato restante y destino. Si coinciden varios defectos se informa el primero,
sin revelar el valor de Location. Un delimitador de consulta o fragmento vacío
sigue admitido como antes; no se amplía ninguna regla de aceptación.

Los HTTP distintos de 302 mantienen `envio_login`: 200/401/403 conservan
`autenticacion_no_confirmada`; los demás producen `respuesta_http_inesperada`.
En particular, 429 y 5xx incluyen únicamente `http_estado` (entero 100–599)
en `estadisticas_estructurales`; nunca Retry-After, Location ni el cuerpo.
No hay reintentos. El destino correcto sin cookie aplicable mantiene
`sesion_no_confirmada` en `verificacion_sesion`. Las validaciones de formularios
y cambio de rol conservan sus categorías previas.

Ni una redirección admitida ni una cookie acreditan por sí solas autenticación:
se siguen exigiendo selección de rol y listado protegido válido. Esta
diferenciación se verifica con HTTP simulado; no acredita funcionamiento real.
Si HTTPX rechaza una cabecera malformada antes de entregarla al validador
(por ejemplo, ciertos caracteres de control), se conserva
`fallo_transporte_o_codificacion` en `envio_login`; no se intercepta ni se relaja
esa validación de la biblioteca para fabricar una categoría de redirección.

Comando preparado para una nueva ejecución **solo tras autorización separada**,
desde la raíz del repositorio. Carga el código local sin depender de una copia
instalada que pudiera estar desactualizada; no instala paquetes ni guarda datos:

```powershell
.\.venv\Scripts\python.exe -B -c "import runpy,sys; sys.path.insert(0,'backend/src'); runpy.run_path('backend/scripts/ensayo_sigac.py',run_name='__main__')" --autorizar-sigac-real --tipo 2 --total-casos 15 --indice-caso 1 --consultas 2 --diagnostico
```

La confirmación y las credenciales se solicitan en la terminal, nunca como
argumentos. Sin total de actuaciones se informa `completitud_no_verificada`.

## Conservación de cabeceras históricas

Tras analizar los bloques de cada tabla de historial, el número de filas propias con la forma
que el parser reconoce como cabecera (dos celdas y fecha completa en la primera) debe ser igual
al número de actuaciones extraídas de esa tabla. Las exclusiones legítimas (tabla de formulario,
región `div#tabs`) se aplican antes. Si no coincide, se rechaza todo el historial con
`actuaciones_cabeceras_discordantes` y los enteros `cabeceras_historicas_tabla` y
`actuaciones_extraidas_tabla` (solo en ese rechazo). Detecta, entre otros, una actuación que
quedó absorbida en el prefijo de la tabla (por ejemplo por un control en su separadora
inicial). Una fila con fecha que no es cabecera sigue rechazándose por su código específico; el
conteo no se ajusta para hacerlo coincidir. No prueba completitud frente a SIGAC:
verifica la conservación dentro de las tablas procesadas, no que la respuesta
contenga todas las actuaciones del sistema de origen.

## Exclusión conservadora de tablas con controles

La regresión sintética de dos tablas históricas, una con controles y otra válida,
falló antes de corregir el parser en ambos órdenes: se devolvía solo la tabla válida.
La exclusión anticipada por «formulario» impedía llegar a la conservación de
cabeceras de la tabla descartada.

La exclusión anterior solo se conserva si no hay señales históricas estáticas en
las filas propias de la tabla. Son señales: una etiqueta que empieza por fecha
`AAAA-MM-DD`, o una categoría histórica conocida con contenido textual estático.
Se comprueban en una copia sin input, textarea, select ni button: los valores y
borradores de controles no se convierten en contenido histórico. Las tablas
internas de una celda de etiqueta no se usan para atribuirle una cabecera.
Una señal obliga a validar, pero no demuestra por sí sola una actuación.

Conservación: el parser mantiene las filas históricas y la exclusión estricta de
la región interactiva ya delimitada cuando cumple sus criterios. Exclusión: un
formulario sin esas señales puede seguir descartándose bajo las condiciones
anteriores. Rechazo: una mezcla histórica/interactiva que no puede delimitarse
falla con el código existente `actuacion_con_controles`; otras estructuras rotas
mantienen sus códigos. Nunca se devuelve la parte ya extraída de otra tabla.

Las expectativas antiguas que aceptaban la exclusión de una tabla con fecha
histórica se sustituyen por rechazo. La fixture DOM mixta se valida con su
contenedor histórico sintético explícito, cuya frontera conocemos: sin él se
rechaza. No se añade ningún selector de SIGAC ni un fallback por éxito. Los hashes
golden permanecen idénticos y las fixtures originales no se modifican.

No cambian `VERSION_HUELLA`, la representación de anexos sin enlace, JSON v2.2,
las identidades ni la reconciliación. No hay migración ni reescritura de estados.
Un estado establecido antes con una extracción parcial no puede reconstruirse
mediante esta corrección; información recuperada después puede ser primera
observación sin demostrar creación reciente.

Las pruebas integradas usan HTTP simulado y el reconciliador real. Verifican
estabilidad, inserciones, multiplicidad, reordenaciones, edición ambigua, ausencias,
reapariciones, disponibilidad intermitente de anexos y cambios en la región
interactiva. Tres lecturas con una novedad y su repetición producen un solo evento;
el resumen sigue comparando contra la primera lectura. El ensayo no invoca el
motor con una extracción rechazada. El monitor tampoco la entrega a su frontera
de persistencia: se prueba con un servicio en memoria, sin SQLite ni datos reales,
tanto antes de establecer una base como después de una lectura válida.

Una prueba reproduce desde cero 709 actuaciones ficticias, una región/fila
interactiva y un anexo sin enlace por consulta. No utiliza la respuesta real ni
acredita que el parser corregido siga aceptando el HTML real: eso requiere otra
autorización y ejecución de lectura. El valor 2 del comando corresponde a la
opción Consultorio observada por el usuario; no demuestra rol activo.

Límite explícito: una respuesta bien formada que omita actuaciones completas
puede superar las validaciones y repetirse estable. Una prueba conserva ese
resultado como `completitud_no_verificada`. Estas señales y contadores no
sustituyen una garantía del origen sobre alcance, paginación, filtros o carga
diferida. No se exige contar manualmente el historial ni se activan avisos reales.

## Prefijo histórico anterior al primer separador

La regresión de una cabecera de tres celdas y contenido histórico con controles
antes del primer separador falló antes de corregir: se devolvía solo el bloque
posterior, sin excepción. Ahora se comprueban las señales históricas estáticas
del prefijo, aunque contenga controles. Se reutiliza el mismo detector que
ignora textos y valores de los controles; un prefijo puramente interactivo sin
esas señales mantiene su comportamiento anterior.

Si una cabecera malformada o contenido histórico estático no puede interpretarse,
se rechaza la extracción completa con `historial_antes_del_primer_separador`.
Cuando una cabecera completa ya hacía fallar el control de conservación se
mantienen `actuaciones_cabeceras_discordantes` y sus conteos, sin cambiar el
diagnóstico anterior. No se devuelve ninguna parte extraída como lectura válida.

Las pruebas del ensayo y del monitor cubren el rechazo tanto antes de establecer
una línea base como después de una lectura válida: la observación ambigua no
invoca reconciliación ni la frontera de persistencia. Las huellas y el algoritmo
puro permanecen iguales. Esto no demuestra completitud del HTML recibido ni
estabilidad institucional de sus identificadores.
