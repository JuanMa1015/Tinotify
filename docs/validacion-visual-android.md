# Variante Android de validación visual sintética

## Alcance y selección

`mobile/visual/` es otro proyecto Expo, no una variable que cambie la demo. Tiene
su propio `package.json`, `app.config.js`, `index.ts` y Metro. Se selecciona usando
**ese directorio** como raíz. La aplicación principal conserva sus archivos,
dependencias, EAS, entrada, sesiones y comportamiento. No ejecutar comandos de
construcción desde `mobile/` para obtener esta variante.

Paquete Android: `com.tinotify.visualsintetica`. Esquema:
`tinotify-visual-sintetica`. No reemplaza `com.tinotify.demo`. No hay cuenta Expo,
projectId EAS, `owner`, configuración Google ni variables de credenciales en esta
configuración. El lanzador de desarrollo se configura en `launcher`, para no
restaurar automáticamente la última URL. Las actualizaciones OTA se deshabilitan.

La entrada registra `Visual`, que abre directamente la pantalla compartida
`ObservacionesReales` bajo una etiqueta permanente de datos sintéticos. No importa
`App.tsx`, CasosLocales, SecureStore ni la sesión de demostración. No hay formulario
de credenciales ni control para monitorizar, registrar dispositivos o activar push.

## Aislamiento JavaScript y transporte

La pantalla y el contrato de observaciones se reutilizan sin modificarlos. Metro
sustituye exclusivamente `./api` **desde esa pantalla** por `visual/api.ts`.
`aislamiento.cjs` rechaza módulos de notificaciones, Firebase y SecureStore, incluso
si se solicitan indirectamente o mediante una ruta absoluta. También rechaza el
código de la demo fuera de los dos archivos compartidos. El Metro normal no carga
este resolver. Evitar ejecutar o probar la entrada visual con otro Metro.

El transporte visual permite únicamente GET a:

- `http://127.0.0.1:8000/real/cases`
- `http://127.0.0.1:8000/real/observaciones`
- `http://127.0.0.1:8000/real/cases/<identificador>` (segmento alfanumérico o guiones)

Rechaza otras rutas, URLs, parámetros, códigos y métodos; no lee variables
`EXPO_PUBLIC_*`, cookies ni almacenamiento persistente. El código de acceso es el
**valor público ficticio** de `backend/tests/helpers/observaciones_android.py`.
No configurarlo jamás como código de una base real. La ruta `/real` identifica el
contrato probado, no el origen de los datos. Solo iniciar la factory sintética de
esta guía. Loopback y este código público no acreditan que cualquier servidor del
puerto 8000 sea sintético: el operador debe comprobar qué proceso escucha allí.

Usa explícitamente `expo/fetch`, no el `fetch` global intercambiable de React Native.
En el código Android de Expo 58 instalado, `redirect: 'error'` deshabilita
`followRedirects` y `followSslRedirects`; `credentials: 'omit'` evita el cookie jar.
Hay un timeout de 20 segundos, sin reintentos. Errores HTTP, JSON inválido y contratos
incompatibles no se convierten en listas vacías. La pantalla conserva el mensaje
de cobertura desconocida y no acredita creación reciente de actuaciones.

## Aislamiento nativo previsto

El `expo.autolinking.exclude` del **manifiesto visual** excluye
`expo-notifications`, `expo-secure-store`, `expo-device` y `expo-crypto`. Las
dependencias directas se limitan a Expo, React, React Native, dev-client y
build-properties con las versiones exactas ya presentes en el lock de `mobile/`.
No se ha instalado ni actualizado ningún paquete. Se reutiliza la resolución del
`node_modules` padre; este subproyecto no es una instalación npm independiente.
No ejecutar `npm install` dentro de `visual/` ni generar un segundo lock divergente.

Se excluye el plugin de notificaciones y no se proporciona `googleServicesFile`.
La única dependencia Firebase Messaging directa identificada en la demo procede
de `expo-notifications/android/build.gradle`, ahora fuera de su autolinking.
La prueba ejecuta los resolvers Expo y React Native instalados y revisa los Gradle
de los proyectos seleccionados. Esto **no resuelve el grafo Maven completo** ni
demuestra ausencia de Firebase en un binario.

Se bloquean POST_NOTIFICATIONS y RECEIVE_BOOT_COMPLETED y se deshabilitan copias de
seguridad de la app. HTTP claro se habilita para Metro y el backend USB. Esa opción
nativa no es una lista de destinos autorizados: la restricción de rutas de consulta
vive en el transporte visual. Un dev-client puede abrir otros bundles manualmente;
no usar su interfaz para cargar proyectos, URLs o historiales ajenos. El aislamiento
no pretende contener código hostil en el dispositivo o modificaciones del proyecto.

Expo Go no permite acreditar estas exclusiones nativas: usar en la futura prueba
una APK propia revisada. No se ha generado el proyecto Android, construido APK,
instalado herramientas ni realizado prueba física en esta etapa.

## Verificaciones sin Android SDK (ya disponibles)

Desde PowerShell, con las dependencias actuales de `mobile/`:

```powershell
Set-Location C:\Users\gonza\Desktop\Proyectos\Tinotify\mobile
node --test test/*.test.ts
.\node_modules\.bin\tsc.cmd --noEmit

Set-Location visual
$env:EXPO_OFFLINE='1'
$env:EXPO_NO_TELEMETRY='1'
$env:EXPO_NO_DOTENV='1'
$env:CI='1'
node ../node_modules/expo/bin/cli config --type public --json
node ../node_modules/expo-modules-autolinking/bin/expo-modules-autolinking.js resolve --platform android --json --project-root .
node ../node_modules/expo/bin/cli export --platform android --dev --source-maps --no-bytecode --no-minify --max-workers 2 --output-dir exportaciones/validacion
Set-Location ..
node --test test/visualBundle.integration.ts
```

La última prueba exige la exportación, no la omite si falta. Analiza el grafo real
de Metro mediante su source map, incluyendo imports de dependencias. La exportación
es solo JavaScript de desarrollo y recursos, no una APK ni un proyecto nativo.
Salida y caches están ignorados. Repetir desde un directorio de exportación nuevo
si quedó más de un mapa. Los tests ordinarios verifican el grafo local, exclusiones,
identidad, contrato y transporte con respuestas simuladas, sin iniciar servicios.

## Backend para la prueba posterior (no ejecutado en esta etapa)

Solo después de revisar el proceso que ocupa 8000, desde la raíz del repositorio:

```powershell
@'
import uvicorn
from backend.tests.helpers.observaciones_android import escenario
with escenario("referencia") as (app, _):
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
'@ | .\.venv\Scripts\python.exe -B -
```

Cambiar únicamente el nombre por `vacio`, `posterior`, `historica` o
`dos_expedientes`, reiniciando el servidor y pulsando Actualizar consulta local.
Esta factory utiliza bases nuevas en TemporaryDirectory y HTTP simulado para su
preparación; no abrir archivos SQLite existentes ni usar la factory por variables
de entorno de producción. Inyecta un emisor que falla ante cualquier entrega y
deshabilita sesiones SIGAC. No solicita credenciales.

## Construcción posterior propuesta: requiere otra autorización

**No ejecutar todavía.** Faltan SDK/ADB/herramientas Android. No instalarlas en esta
etapa. Con ellas disponibles y autorizadas, en una terminal nueva:

```powershell
Set-Location C:\Users\gonza\Desktop\Proyectos\Tinotify\mobile\visual
$env:EXPO_OFFLINE='1'
$env:EXPO_NO_TELEMETRY='1'
$env:EXPO_NO_DOTENV='1'
if (Test-Path android) { throw 'Revisar el proyecto generado existente antes de continuar' }
node ../node_modules/expo/bin/cli prebuild --platform android --no-install
```

**Parada de revisión aquí:** verificar el proyecto generado antes de compilar.
Comprobar applicationId, plugins, autolinking y paquete de módulos; no deben aparecer
expo-notifications, google-services ni módulos Firebase. No usar `--clean` sobre
proyectos existentes. Examinar posteriormente el grafo Gradle (puede necesitar
descargar artefactos públicos; `EXPO_OFFLINE` no controla Gradle):

```powershell
Set-Location android
.\gradlew.bat :app:dependencies --configuration debugRuntimeClasspath
.\gradlew.bat :app:processDebugMainManifest
```

Revisar el informe completo y manifiesto fusionado. **Detenerse** si aparecen
Firebase Messaging, FirebaseInitProvider, servicios/receptores de notificaciones,
permisos bloqueados, configuración Google o una identidad equivocada. No ampliar
permisos ni actualizar dependencias para superar una comprobación. Solo después
de esa revisión y autorización correspondiente:

```powershell
.\gradlew.bat :app:assembleDebug
```

La APK esperada estaría en
`mobile/visual/android/app/build/outputs/apk/debug/app-debug.apk`. Antes de instalar,
inspeccionar la APK con Android SDK APK Analyzer/apkanalyzer: applicationId,
permisos, manifiesto fusionado, clases DEX y dependencias Firebase/notificaciones.
Una búsqueda solo de nombres de archivo o solo del manifiesto no prueba ausencia
de código. No declarar Firebase ausente hasta completar esas comprobaciones.

## Ejecución física posterior

Con APK inspeccionada e instalación expresamente autorizada, teléfono por USB,
Wi-Fi/datos móviles desactivados y sin tethering. No habilitar transporte LAN.
Usar el número de serie local, sin publicarlo:

```powershell
$adbTinotify='C:\Users\gonza\AppData\Local\Android\Sdk\platform-tools\adb.exe'
$serieAndroid='SERIE_LOCAL_DEL_TELEFONO'
& $adbTinotify -s $serieAndroid reverse tcp:8000 tcp:8000
& $adbTinotify -s $serieAndroid reverse tcp:8081 tcp:8081
```

En otra terminal:

```powershell
Set-Location C:\Users\gonza\Desktop\Proyectos\Tinotify\mobile\visual
$env:EXPO_OFFLINE='1'
$env:EXPO_NO_TELEMETRY='1'
$env:EXPO_NO_DOTENV='1'
node ../node_modules/expo/bin/cli start --dev-client --offline --localhost --port 8081
```

Abrir exclusivamente el proyecto local en ese dev-client. Para indicar la URL
explícitamente (después de instalar; no realizado):

```powershell
& $adbTinotify -s $serieAndroid shell am start -a android.intent.action.VIEW -d 'tinotify-visual-sintetica://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A8081' com.tinotify.visualsintetica
```

## Aceptación y límites

- Entrada directa con distintivo sintético; sin restauración de demo ni permisos push.
- Cobertura desconocida y primera observación sin afirmar creación reciente.
- Escenarios: vacio (0 expedientes), referencia (1, 0 eventos), posterior/historica
  (1, 1 evento interno), dos_expedientes (2, 0 eventos). Abrir y cerrar detalles.
- Fallo HTTP o desconexión muestra error; nunca consulta vacía exitosa.
- Ninguna llamada propia fuera de los GET permitidos, ninguna entrega externa.
- Sin escrituras en bases existentes. No activar SIGAC, Supabase, Render o Firebase.

Las pruebas unitarias no acreditan renderizado nativo ni ausencia de inicialización
en un teléfono. El binario, los plugins y bibliotecas Maven requieren revisión tras
construir. Metro/dev-client contienen herramientas de desarrollo: no son un sandbox
de red ni una aplicación de producción. La falta de conectividad externa es una
defensa adicional, no evidencia de que no se haya intentado una conexión. Registrar
y revisar comportamiento de red durante la prueba física, sin capturar credenciales
ni contenido judicial. Ninguna de estas tareas habilita monitorización real.

## Evidencia de esta preparación

- 62 pruebas móviles aprobadas, cero fallos y cero omisiones: 31 anteriores,
  17 nuevas de aislamiento, 2 sobre el grafo Metro exportado y 12 de integración
  ASGI sintética anterior. Las 12 últimas transportan capturas ASGI mediante fetch
  simulado; no equivalen a una prueba de red o renderizado Android.
- TypeScript `tsc --noEmit` correcto; `git diff --check` correcto para cambios
  seguidos. Nuevos archivos revisados también por espacios y formato.
- Exportación JavaScript Android de desarrollo, offline, sin Hermes bytecode:
  Metro informa 715 módulos; el source map indexado enumera 722 fuentes incluyendo
  código de arranque. La prueba del mapa no encuentra notificaciones/Firebase,
  App.tsx, SecureStore ni el transporte normal de la demo.
- Resolución real de autolinking Expo 58 y React Native sin notificaciones ni
  Firebase en la selección; Gradle de módulos seleccionados sin declaraciones
  Firebase detectadas. Grafo Maven, proyecto Android y APK todavía pendientes.
- Los hashes de nueve archivos principales de la demo, incluido su lock y la
  pantalla compartida, permanecen iguales a los del inicio de esta tarea.
- Advertencias previas: Node sobre tipo de módulos no declarado y Starlette sobre
  su adaptador HTTPX; no se han alterado manifiestos compartidos ni dependencias
  para silenciarlas.

No se ha repetido la suite backend completa en esta tarea: no se modificó backend.
Su resultado previo no se presenta como una ejecución nueva. No se construyó APK,
no se instaló nada y no se inició una prueba física.
