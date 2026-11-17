# Flujo Android ↔ API local (datos sintéticos)

**Estado tras SQLite local v2:** solo se autoriza la simulación local con archivos
nuevos. Los archivos v1 se rechazan sin migración. Las órdenes persistentes de
SIGAC descritas más abajo están deshabilitadas por falta de contrato verificado
de identidad del expediente; no ejecutar esos ejemplos como siguiente paso.
El perfil real v2 guarda metadatos mínimos, no textos judiciales. Véase
[SQLite local v2](sqlite-local-v2.md) para contratos, pruebas y límites vigentes.

Primer flujo de solo lectura: la app Expo consulta una API FastAPI local y muestra casos y
actuaciones **ficticios**. No usa SIGAC, credenciales reales, Supabase, Render ni push.

## Endpoints (solo `GET`, sin sesión, solo en la aplicación demo)

| Ruta | Respuesta |
| --- | --- |
| `GET /demo/catalog/cases` | `[{id, titulo, total_actuaciones, demo}]` |
| `GET /demo/catalog/cases/{id}/actuaciones` | `{id, titulo, demo, sintetico, actuaciones: [{fecha, direccion, remitente, descripcion, anexos: [{descripcion, sin_enlace}]}]}` |

Inexistente: 404 genérico. Identificador no UUID: 422 genérico. Cualquier método distinto de
`GET`: 405. Los anexos solo muestran descripción y `sin_enlace`; no hay referencias de
descarga ni huellas. La API de producción (`tinotify.api:app`) sigue exponiendo solo `/health`.
Las rutas `/demo/*` con sesión (códigos de demostración) no cambian.

## Iniciar el backend (PowerShell, desde la raíz del repositorio)

```powershell
$env:TINOTIFY_MODE = 'demo'
$env:TINOTIFY_DEMO_CODE_A = '<cadena local de 24 o más caracteres>'
$env:TINOTIFY_DEMO_CODE_B = '<otra cadena local distinta de 24 o más caracteres>'
.\backend\.venv\Scripts\python.exe -m uvicorn tinotify.api.demo:crear_app --factory --host 127.0.0.1 --port 8000
```

Los códigos solo protegen las rutas de demostración con sesión; no son credenciales de SIGAC.

## Iniciar Expo (otra terminal)

```powershell
cd mobile
npx expo start
```

La app usa `http://127.0.0.1:8000` por defecto (único HTTP permitido; cualquier otra URL
debe ser HTTPS). Con un teléfono por USB: `adb reverse tcp:8000 tcp:8000`. En la pantalla
inicial, «Ver casos sintéticos locales (solo lectura)».

## Novedades persistidas localmente (SQLite de desarrollo)

Detecta una actuación sintética nueva, la conserva entre reinicios y la deja consultable desde
Android. No usa SIGAC, credenciales reales, Supabase, Render ni push.

**Persistencia.** `AlmacenSqliteLocal` (`persistence/sqlite_local.py`) implementa el contrato
`AlmacenSeguimiento` existente con la misma semántica que las funciones SQL (reserva idempotente,
generación y fencing, confirmación atómica de registros y eventos, sin borrar actuaciones por
ausencia, avisos pendientes). Reutiliza `ServicioSeguimiento` y `ServicioAvisos`; no duplica la
reconciliación. Se eligió SQLite y no el adaptador PostgreSQL porque este exige TLS `verify-full`,
roles y funciones SQL de la migración y un autenticador que no existe, y no hay PostgreSQL local.
Solo desarrollo: acepta únicamente una credencial local fija. El archivo no guarda HTML.

**Escenario completo** (procesos separados = reinicios reales). Desde la raíz del repositorio:

```powershell
$db = 'backend/.local/novedades.sqlite3'
.\backend\.venv\Scripts\python.exe backend/scripts/novedades_local.py --db $db reiniciar --confirmar
.\backend\.venv\Scripts\python.exe backend/scripts/novedades_local.py --db $db observar --actuaciones 3  # baseline, 0 avisos
.\backend\.venv\Scripts\python.exe backend/scripts/novedades_local.py --db $db observar --actuaciones 4  # 1 novedad
.\backend\.venv\Scripts\python.exe backend/scripts/novedades_local.py --db $db observar --actuaciones 4  # 0 novedades nuevas
.\backend\.venv\Scripts\python.exe backend/scripts/novedades_local.py --db $db estado
```

Las observaciones pasan por el parser real con HTML ficticio. Una extracción rechazada, vacía o con
menos actuaciones que la anterior no crea ni modifica el baseline.

**Backend con persistencia** (agrega `TINOTIFY_LOCAL_DB` al arranque descrito arriba):

```powershell
$env:TINOTIFY_LOCAL_DB = 'backend/.local/novedades.sqlite3'
```

**Endpoints de consulta (solo `GET`, sin sesión; 503 genérico si no hay persistencia):**

| Ruta | Respuesta |
| --- | --- |
| `GET /demo/local/cases` | `[{id, titulo, generacion, total_actuaciones, novedades_pendientes, demo}]` |
| `GET /demo/local/cases/{id}` | Estado y actuaciones persistidas, cada una con `nueva` |
| `GET /demo/local/novedades` | Avisos pendientes con tipo, prioridad, textos genéricos y la actuación afectada |

Consultar nunca marca un aviso como procesado ni entregado; no hay endpoints que escriban,
observen o procesen. En la app: «Ver casos sintéticos locales» → pestaña «Novedades».

## Datos reales locales (consulta manual autorizada)

Une la extracción real de SIGAC con el flujo persistente y la app, **sin automatización ni push**. La
consulta a SIGAC la ejecuta solo la persona autorizada, a mano; la API y la app nunca inician consultas ni
reciben credenciales de SIGAC.

**1. Consulta (manual, interactiva).** Desde la raíz, en una terminal real (no canalizar credenciales):

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/sigac_local.py consultar --autorizar-sigac-real `
  --tipo <valor observado de cboTipo> --total-casos 15 --indice-caso 1 --etiqueta "Mi expediente"
```

Pide escribir `SIGAC-CONSULTA-LOCAL` y después usuario y clave sin eco (y `txtCaso` con
`--pedir-caso-login`). Las credenciales viven solo en memoria. Se valida el archivo y su perfil antes de
pedirlas y se reutilizan el cliente, el parser y las comprobaciones existentes. Imprime solo cantidades. La
primera extracción válida es el baseline (sin avisos); las siguientes detectan actuaciones nuevas con la
reconciliación existente. `sigac_local.py estado` muestra cantidades sin acceder a SIGAC.

**2. Qué se guarda.** El perfil real v2 está limitado a identidades locales,
huellas, generaciones, recibos y eventos genéricos; no guarda fechas de actuaciones,
remitentes, textos ni detalles de anexos. El perfil sintético conserva una vista
detallada exclusivamente ficticia. Los archivos v1 antiguos quedan intactos: no
se convierten ni se limpian automáticamente. Un UUID derivado del número no prueba
identidad institucional estable, por lo que no habilita este flujo real. Ningún
archivo SQLite está cifrado por la aplicación; tratar huellas e IDs como sensibles.

**3. Consistencia.** Una extracción rechazada, vacía o parcial no cambia nada. Como SIGAC no entrega
identificadores estables, una actuación previa que ya no coincide exactamente (ausente, modificada o con
una referencia de anexo distinta) se interpreta como extracción sospechosa: se rechaza la observación
completa y se informan solo cantidades. Nunca se eliminan actuaciones por ausencia. La completitud
histórica sigue `completitud_no_verificada` salvo que se contraste `--total-actuaciones`.

**4. Backend con acceso protegido.** Genera un código local y arranca con rutas reales protegidas:

```powershell
$codigo = .\backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:TINOTIFY_MODE = 'demo'
$env:TINOTIFY_DEMO_CODE_A = '<cadena local de 24 o más caracteres>'
$env:TINOTIFY_DEMO_CODE_B = '<otra cadena local distinta>'
$env:TINOTIFY_REAL_DB = 'backend/.local/real.sqlite3'
$env:TINOTIFY_REAL_ACCESS_CODE = $codigo
.\backend\.venv\Scripts\python.exe -m uvicorn tinotify.api.demo:crear_app --factory --host 127.0.0.1 --port 8000
```

| Ruta (solo `GET`) | Respuesta |
| --- | --- |
| `/real/cases` | Casos reales guardados con `novedades_pendientes` |
| `/real/cases/{id}` | Actuaciones con `nueva` |
| `/real/novedades` | Avisos pendientes con la actuación afectada |

Protección: las rutas no existen sin `TINOTIFY_REAL_DB` y `TINOTIFY_REAL_ACCESS_CODE` (mínimo 32
caracteres); exigen `Authorization: Bearer <código>` (comparación en tiempo constante, 401 genérico),
bloquean tras 5 fallos en un minuto (429) y responden `Cache-Control: no-store`. `adb reverse` es solo
transporte local, no autenticación. Las rutas abiertas `/demo/*` nunca sirven datos reales. La API de
producción no tiene rutas `/demo` ni `/real`.

**5. En Android.** «Ver casos sintéticos locales» → pestaña «Reales» → pega el código una vez (se guarda
solo en este teléfono con SecureStore; «Olvidar el código» lo borra). Consultar nunca marca avisos.

## Datos reales v2 en Android (vigente; sustituye a los pasos 1 y 4 anteriores)

La consulta manual vigente usa `--caso-numero` y el almacén v2 (`backend/.local/real_v2.sqlite3`); ver
`docs/contratos-identidad.md`. v2 guarda solo identidades locales, huellas, generaciones y recibos: **no hay
fechas, remitentes ni descripciones**. Android muestra hoy: «Expediente local», número de ocurrencias
conservadas (709), generación, cobertura desconocida y observaciones posteriores (ninguna tras la línea base).

**Backend (loopback únicamente, solo lectura, sin sesión SIGAC ni monitor):**

```powershell
.ackend\.venv\Scripts\python.exe -B backend/scripts/servir_real_local.py
```

Escucha solo en `127.0.0.1:8000`, rechaza archivos v1 y guarda su código de acceso en
`backend/.local/codigo_acceso_real.txt` (ignorado por git; no se imprime). No expone `/real/sesion`.

**Samsung por USB (sin exponer nada a Internet):** depuración USB activa, `adb devices` debe listar el
teléfono y luego `adb reverse tcp:8000 tcp:8000`. En la app: «Ver casos sintéticos locales» → «Reales» →
pegar el código una vez. Al terminar: `adb reverse --remove tcp:8000` y detener el backend (Ctrl+C).

## Monitor periódico local (`monitorear`)

Consulta un expediente a intervalos regulares durante **una sesión que tú autorizas**, y persiste lo que
detecta con el mismo almacén real y la misma reconciliación. No hay push, automatización ni despliegue. La
API y la app no pueden iniciarlo ni detenerlo.

**Sesión.** `SigacClient` conserva la sesión autenticada solo en memoria (cookie en RAM, sin reautenticación
automática). El monitor se autentica **una vez**; después cada ciclo relee el listado (confirma que la sesión
sigue viva y que el expediente sigue figurando) y consulta el historial: 2 solicitudes por ciclo en lugar de
la secuencia completa de acceso. El monitor nunca ve las credenciales: el CLI entrega una función de acceso
que las descarta al usarlas. Python no garantiza borrado de memoria. Al terminar se cierran el cliente y las
cookies locales; **no existe un contrato de cierre de sesión remoto**, así que la sesión del servidor vence
por su propio tiempo.

**Si la sesión expira o SIGAC restringe el acceso** (302/401/403, formulario de acceso, selección de rol,
página no protegida, respuesta HTTP o tipo inesperados) el monitor **se detiene** (código de salida 4) y hay
que volver a ejecutarlo para una nueva autorización interactiva. No reintenta el acceso, no mantiene la
sesión con solicitudes artificiales ni intenta eludir controles.

**Iniciar** (terminal real, desde la raíz; pide `SIGAC-MONITOR-LOCAL`, usuario y clave sin eco):

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/sigac_local.py monitorear --autorizar-sigac-real `
  --tipo <valor observado de cboTipo> --total-casos 15 --indice-caso 1 --etiqueta "Mi expediente"
```

**Detener:** `Ctrl+C` (cierra el cliente y libera el bloqueo; no queda ninguna consulta en curso ni en segundo
plano). Frecuencia: `--intervalo-minutos` entre **10 y 240**, por defecto **30**, medida de inicio a inicio.
`--max-ciclos N` detiene tras N consultas. Un bloqueo `<archivo>.sqlite3.monitor.lock` impide dos monitores
sobre el mismo almacén; si quedó uno de una ejecución interrumpida, elimínalo a mano solo tras comprobar que
no hay otro monitor.

**Errores.** Fallo de red: espera limitada (60 s, luego 120 s) y como máximo 3 fallos consecutivos. Extracción
rechazada o sospechosa: no se modifica nada y no se reintenta antes del intervalo normal; 3 seguidas detienen
el monitor (código 5). Expediente ausente del listado, listado no confirmado, autenticación fallida o error
inesperado: se detiene. La salida son líneas JSON con estado, cantidades, códigos y horas; nunca credenciales,
cookies, HTML, números de expediente ni contenido.

Códigos de salida: 0 detención normal; 4 hace falta nueva autorización; 5 fallos repetidos; 1 otros;
2 cancelado o argumentos; 130 interrupción durante el acceso. Las pruebas usan reloj y esperas simulados.

## Autorizar SIGAC desde Android (un usuario, USB local)

La sesión SIGAC se inicia desde la pestaña «Reales» de la app, sin PowerShell. Es una función **local,
apagada por defecto y de un solo usuario**: no existe en la API de producción ni se carga sin activarla.

**Flujo.** Android envía usuario y clave **una vez** a `POST /real/sesion`; el backend ejecuta
`SigacClient.autenticar` en un hilo, descarta los secretos al usarlos y arranca el monitor existente con ese
mismo cliente (sesión solo en memoria). Estados: `autenticacion_pendiente` → `autenticacion_confirmada` →
`monitor_activo` (solo tras completar una consulta), o `error`. Nunca se informa «activo» antes de confirmar
la autenticación.

| Ruta | Función |
| --- | --- |
| `POST /real/sesion` | 200 con el estado, 202 si la autenticación sigue pendiente; 401 código de acceso incorrecto; 403 transporte no local; 409 ya hay sesión; 422 entrada no válida; 429 demasiados intentos |
| `GET /real/monitor` | Estado, motivo, `requiere_autorizacion`, ciclos y última consulta (solo cantidades y horas) |
| `DELETE /real/sesion` | Detención cooperativa y cierre del cliente |

**Seguridad.** Rutas inexistentes salvo `TINOTIFY_REAL_SESSION=1` más los datos reales protegidos; todas
exigen el código de acceso local (no va en la URL). Las credenciales solo se aceptan si la conexión viene del
bucle local, el `Host` es local y no hay cabeceras de proxy o túnel: esto es una defensa de transporte, **no**
autenticación (el código de acceso sigue siendo obligatorio). Las credenciales son `SecretStr`, los errores
son genéricos y no se registran cuerpos. Máximo 3 autenticaciones fallidas cada 15 minutos; una sola sesión
(también frente al CLI, mediante el bloqueo de archivo); sin CORS. La app no guarda usuario ni clave
(`secureTextEntry`, sin autocompletado) y los borra siempre tras cada intento.

**Activar (PowerShell, desde la raíz).** Sin `--reload`:

```powershell
adb reverse tcp:8000 tcp:8000
adb reverse tcp:8081 tcp:8081
$codigo = .\backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:TINOTIFY_MODE = 'demo'
$env:TINOTIFY_DEMO_CODE_A = '<cadena local de 24 o más caracteres>'
$env:TINOTIFY_DEMO_CODE_B = '<otra cadena local distinta>'
$env:TINOTIFY_REAL_DB = 'backend/.local/real.sqlite3'
$env:TINOTIFY_REAL_ACCESS_CODE = $codigo
$env:TINOTIFY_REAL_SESSION = '1'
.\backend\.venv\Scripts\python.exe -m uvicorn tinotify.api.demo:crear_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

En otra terminal, `cd mobile; npx expo start`, y abre el proyecto en Expo Go. En la app: «Ver casos sintéticos
locales» → «Reales» → pega el código una vez → «Autorizar SIGAC».

**Qué ocurre.** Cerrar la app no detiene nada (el monitor vive en el backend). Reiniciar o apagar el backend
elimina la sesión y detiene el monitor (la sesión no se guarda en ningún sitio), pero conserva el historial y
el baseline; hay que autorizar de nuevo. Si SIGAC expira la sesión o restringe el acceso, el monitor se
detiene y la app pide reautorizar. «Detener» cancela el monitor y cierra el cliente; una consulta en curso
termina sola y su resultado no se guarda.

**Límites.** Si el proceso se mata a la fuerza queda `real.sqlite3.monitor.lock`; tras comprobar que no hay otro
monitor, bórralo a mano. El transporte es HTTP sobre el bucle local por USB: nunca lo expongas por Wi-Fi ni
túnel (el backend lo rechaza). Python y JavaScript no garantizan borrar la clave de memoria.
