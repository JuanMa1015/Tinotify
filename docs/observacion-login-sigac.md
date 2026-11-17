# Observación limitada de la redirección de login

Preparación local con HTTP simulado. No autoriza solicitudes reales. Este modo
es independiente del ensayo de actuaciones y no consulta roles, procesos ni
historiales. No utiliza SQLite, Supabase, Render, Firebase ni Android.

## Alcance y seguridad

La entrada dedicada `backend/scripts/observar_login_sigac.py` requiere el flag
de autorización, terminal interactiva y confirmación `SIGAC-OBSERVAR-LOGIN`.
Solicita usuario y clave sin eco; no los acepta como argumentos. `--tipo` debe
ser una opción previamente observada de `cboTipo`. `txtCaso` y `cmdIngresar`
proceden del formulario; solo si es necesario, `--pedir-caso-login` pide un
valor de txtCaso sin eco.

Reutiliza exactamente el GET inicial y el POST de login del cliente, con los
mismos controles del formulario, límite de respuesta, TLS y origen. Ejecuta
como máximo esas dos solicitudes; no sigue redirecciones, tampoco las conocidas.
No hay reintentos ni comprobación posterior de sesión. Nunca marca la sesión
autenticada. Limpia las cookies anteriores al empezar y todas las cookies al
terminar, incluso ante fallos o interrupciones normales de Python.

El ejecutable bloquea logs de bibliotecas y convierte advertencias y errores
en códigos constantes. No guarda HTML, respuestas, cookies, credenciales ni
destinos; mantiene solo los datos temporales necesarios en RAM. No usar el
método de biblioteca dentro de procesos con depuración HTTP habilitada: la
entrada dedicada es la frontera que bloquea esos logs.

## Resultado

Mantiene `diagnostico_version: 2` y `etapa: redireccion_login` para una observación
terminada. `autenticacion_confirmada` y `redireccion_seguida` son siempre `false`.
La categoría solo puede ser:

| Categoría | Evidencia limitada |
| --- | --- |
| `retorno_acceso` | Coincidencia con la ruta del acceso conocido; no demuestra contraseña incorrecta. |
| `selector_rol` | Coincidencia con la ruta del selector conocido; no confirma una sesión. |
| `principal_conocida_fuera_de_etapa` | Etiqueta conservada: principal observada antes de seleccionar explícitamente el rol. Es un destino de entrada conocido, pero no confirma sesión ni permite omitir el selector. |
| `menu_conocido_fuera_de_etapa` | Ruta presente en código y pruebas preliminares; no acredita su función real tras login. |
| `destino_desconocido` | Sin coincidencia con el catálogo. No se muestra ni se sigue. |

Indicadores booleanos, nunca valores extraídos:

- `prefijo_punto`: la ruta, tras retirar el prefijo fijo de SIGAC si existe,
  empieza por `./`.
- `parametros_en_ruta`: contiene punto y coma; no se interpretan sus valores.
- `ruta_fuera_ambito_esperado`: ruta absoluta fuera del prefijo fijo de SIGAC
  o presencia de un segmento `..`.
- `variante_conocida`: al comparar léxicamente un único `./` inicial y/o
  parámetros finales sin barras, coincide con una ruta del catálogo.

Esa comparación NO normaliza ni autoriza navegación. Rutas fuera del ámbito
quedan desconocidas. No se resuelven segmentos padre, escapes ni prefijos
repetidos. Un destino con parámetros en la ruta puede incluir secretos:
solo se informa su presencia. No se calculan hashes del encabezado.

Se conservan los rechazos por encabezado ausente/vacío/duplicado, origen no
admitido y formato inválido, incluidas consultas o fragmentos no vacíos. Los
delimitadores vacíos conservan el comportamiento previo. Los estados distintos
de 302 conservan la clasificación actual del login, incluidos 429 y 5xx.
Si HTTPX rechaza una cabecera antes de entregarla, puede aparecer fallo de
transporte en lugar de una clasificación de redirección.

Código de salida 0 significa solamente observación completada, incluso para un
destino desconocido o retorno al acceso. No significa autenticación ni destino
aprobado. Fallos: 1; cancelación/argumentos: 2; interrupción: 130. Los fallos
usan el diagnóstico versión 2 existente con categorías y etapa del fallo.

## Comando preparado, no ejecutado contra SIGAC

Requiere autorización humana posterior para un único intento con una cuenta
legítima. Desde la raíz del repositorio, en PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -c "import runpy,sys; sys.path.insert(0,'backend/src'); runpy.run_path('backend/scripts/observar_login_sigac.py',run_name='__main__')" --autorizar-sigac-real --tipo 1
```

Carga el código local sin instalar dependencias ni usar una copia instalada
antigua. No pasar contraseñas en el comando, no activar logs ni guardar una
transcripción de la terminal. El valor 1 procede de la observación previa del
usuario; si cambia el formulario, el flujo se detiene sin probar otros valores.

No se pide total de procesos, índice de caso ni cantidad de lecturas porque no
se realizan esas operaciones. Un resultado desconocido no revela su ruta;
requiere una revisión privada autorizada. No se inventan categorías de página
intermedia o error. Incorporar un destino al flujo real exige evidencia de su
función, señales estructurales, compatibilidad con el rol y aprobación separada.

## Límites

El POST puede crear una sesión remota o registrar un intento en SIGAC. Borrar
cookies locales no cierra esa sesión en el servidor; no se envía logout porque
sería otra solicitud. Un timeout no demuestra que el servidor no recibió el
POST: detenerse, sin reintentar automáticamente. Ningún mecanismo en Python
garantiza borrado físico de secretos de RAM ni limpieza ante terminación forzada
del proceso. El cierre normal no persiste cookies.
