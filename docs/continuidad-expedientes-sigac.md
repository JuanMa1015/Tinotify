# Continuidad observada de expedientes SIGAC

Ensayo manual independiente, sin SQLite, notificaciones ni consultas de historial.
No habilita monitorización ni acredita un contrato institucional de identidad.
Preparado y probado únicamente con HTTP simulado; la ejecución real requiere
autorización humana posterior específica.

## Ejecución posterior autorizada

Desde la raíz, con el entorno Python del proyecto:

```powershell
.\.venv\Scripts\python.exe backend/scripts/continuidad_expedientes_sigac.py --autorizar-sigac-real --tipo 2 --total-casos 15
```

Revisar previamente que el total completo siga siendo 15. Se requiere una terminal
interactiva, escribir `SIGAC-CONTINUIDAD` y proporcionar usuario y contraseña sin
eco. No usar argumentos, variables de entorno, redirecciones ni archivos para
las credenciales. No instalar dependencias para ejecutar este ensayo.

## Límites y garantías

- Dos clientes y transportes independientes, secuenciales. Se cierra el primero
  y se vacían sus cookies antes de crear el segundo. No se solicita logout remoto.
- Cada autenticación existente hace seis solicitudes: formulario, login, selector
  de rol, selección ESTUDIANTE, principal y listado. Máximo doce en total, un único
  listado por sesión, sin reintentos, historiales ni descargas. El cliente dedicado
  rechaza cualquier solicitud adicional o fuera de esa secuencia.
- Se conserva el contrato estricto existente del parser y cliente. Un fallo impide
  continuar: no hay comparación ni conclusión basada en una extracción parcial.
- `autenticacion=true` significa acceso al listado validado; no es una nueva
  prueba independiente de rol activo ni de autorización institucional de integración.
- Solo se conservan temporalmente en memoria el entero normalizado, el texto DOM
  original de la primera celda (incluidos espacios) y los dígitos de `abrir(...)`.
  No se conserva el HTML original ni se escriben datos de expedientes. El texto DOM
  no es una reproducción de bytes HTML: entidades y etiquetas ya fueron interpretadas.
- Se comparan conjuntos y representaciones por número, nunca nombres, cliente o
  estado. Duplicados, números ausentes, discrepancias con `abrir(...)`, total
  incorrecto o tabla ambigua provocan error, no deduplicación silenciosa.
- Diferencias de representación solo se comparan para identificadores comunes.
  Un número nuevo no se asocia a uno ausente. Conjuntos distintos o representación
  distinta producen `inconcluso`; igualdad completa produce `continuidad_observada`.
- Salida JSON: autenticación, cantidades y unicidad por sesión, igualdad de
  conjuntos, cantidades añadidas/ausentes y un booleano de representación distinta.
  `null` significa no comprobado; después de un error no se inicia la otra sesión.
  Nunca se imprimen identificadores, excepciones, URLs, HTML, cookies o credenciales.
  Los logs se silencian durante la ejecución y las advertencias detienen el ensayo.
- Códigos de salida: 0 continuidad observada, 3 inconcluso, 1 error, 2 cancelación,
  130 interrupción. No se guardan informes automáticamente.

Dos sesiones solo demuestran continuidad en esos dos instantes. No demuestran
no reutilización futura, unicidad global, estabilidad permanente, completitud de
historiales ni correspondencia del historial con el expediente: no se consulta.
Un cambio de conjunto puede deberse a asignaciones distintas o a identificadores
distintos; el ensayo no decide cuál. UUID locales y huellas no sustituyen evidencia
institucional. La eliminación de referencias Python no garantiza borrado seguro
de memoria ni controla swap, volcados del sistema o registros del servidor SIGAC.
