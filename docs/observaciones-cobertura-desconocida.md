# Observaciones SIGAC con cobertura desconocida

Política local monousuario. No habilita consultas SIGAC, monitorización real ni
entrega externa. Las pruebas usan únicamente HTTP simulado y SQLite temporal.

## Escritura conservada

La única entrada real sigue siendo `ObservadorLocal.observar_validada` mediante
la acreditación emitida después de validar identidad, ámbito e integridad.
La primera lectura aceptada establece una referencia de ocurrencias observadas,
sin eventos históricos. No demuestra completitud.

Las siguientes lecturas deben conservar el multiconjunto de huellas conocido.
Las ocurrencias excedentes producen eventos internos de primera observación;
no acreditan creación reciente. Una ausencia, incluso acompañada de incorporaciones,
rechaza íntegramente la operación. No se borra, fusiona ni reconstruye la referencia.
La comparación no depende del orden y conserva la multiplicidad.

No cambian reconciliación, huellas, identidades, digests, recibos, generaciones,
contratos de escritura ni DDL SQLite v2. Se conservan transacción única,
rollback, control optimista de generación y recuperación de commit incierto.
No se migran archivos existentes. La cobertura se declara desconocida como
semántica constante de consulta, sin añadir estados persistidos.

## Contratos de consulta real, versión 1

Todas las rutas requieren la autorización local existente y conservan `no-store`.

| Ruta | Respuesta |
| --- | --- |
| `GET /real/cases` | Lista de referencias: `id`, título genérico, generación, `referencia_establecida`, `ocurrencias_observadas`, cantidad de `eventos_internos` y semántica de cobertura. |
| `GET /real/cases/{id}` | Referencia más `ocurrencias` con `local_id` y generación. Sin descripciones, anexos detallados, huellas ni marca `nueva`. |
| `GET /real/observaciones` | Objeto con semántica y lista `observaciones`: id del evento, caso local, `local_id`, generación, tipo y `creacion_reciente_acreditada=false`. |
| `GET /real/novedades` | HTTP 410 explícito: avisos reales deshabilitados; consultar observaciones. Nunca una lista vacía artificial. |

Semántica común: `contrato_version=1`, `cobertura="desconocida"`,
`referencia="ocurrencias_observadas"`, `entrega_externa="no_autorizada"`.
Son valores definidos por el servidor, no argumentos que autoricen entregas.

`ServicioNovedadesLocal.novedades` y `ServicioAvisos.pendientes` rechazan el perfil
SQLite real. La comprobación usa el almacén y su perfil, no la propiedad mutable
`sintetico` del consumidor ni un booleano del cliente. La consulta separada
`observaciones()` no construye `AvisoPendiente` o `Notificacion`.

Se consultan todos los eventos internos existentes, también si tienen disposición
heredada `procesado`; un acuse anterior no borra la observación. No se altera la
disposición almacenada ni se usa como elegibilidad para entrega. El tipo de eventos
anteriores se conserva: no se convierten modificaciones o ambigüedades en primeras
observaciones. No hay recorte silencioso al límite de 100 avisos de la API antigua.

Es un cambio explícito del contrato real: los clientes antiguos deben actualizarse.
Las rutas y respuestas sintéticas conservan su formato. No usar respuestas vacías
para aparentar compatibilidad. Errores de lectura siguen siendo errores; la API no
los transforma en éxito sin observaciones.

## Android

La sección real utiliza un componente y un contrato distintos de la demo.
Muestra cobertura desconocida, ocurrencias conservadas y observaciones posteriores
que podrían ser históricas. No utiliza insignias `NUEVA`, modelos de notificación
ni el componente que ofrecía iniciar sesiones/monitor desde esa sección.
Solo consulta referencias ya guardadas; actualizar no consulta SIGAC.

Una lista vacía válida dice que no hay observaciones posteriores registradas,
sin afirmar ausencia de cambios en SIGAC. Un error de red, HTTP o formato presenta
error y no se convierte en esa lista. Las respuestas antiguas/incompatibles se
rechazan. Las consultas de listado y eventos son solicitudes independientes:
no se promete una instantánea única entre ambas ante escrituras concurrentes.

## Inventario de consumidores y límites

- SQLite y `ObservadorLocal`: eventos y recibos internos. Las consultas añadidas
  son SELECT; no modifican tablas, vistas ni DDL.
- `ServicioAvisos`: no convierte eventos SQLite reales en avisos. Su contrato
  sintético y PostgreSQL existente se conserva.
- `ServicioNovedadesLocal`: separa consultas reales de novedades sintéticas.
- API local real y Android: consumen observaciones, sin puente de entrega.
- CLI `sigac_local estado`: informa cantidad de observaciones internas y cobertura,
  sin crear avisos. Las entradas reales de consulta persistente y monitor continúan
  bloqueadas. El monitor sintético conserva su comportamiento.
- Demo Expo: usa la cola en memoria de `ServicioDemo`, distinta de SQLite real.
  Sus emisores no consumen `observaciones()` ni el almacén real.
- Monitor JSON y `SigacService`: API genérica heredada con creación de notificaciones
  a partir de sus propios resultados. No consumen la acreditación ni los eventos
  SQLite de esta ruta real. No se habilitan como alternativa de seguimiento SIGAC.
- Adaptador PostgreSQL y backend sintético remoto: circuitos distintos, no conectados
  a la entrada acreditada SQLite real. No se afirma que esta política esté aplicada
  a cualquier futuro uso real de esos contratos; requeriría revisión separada.

No existe una garantía frente a código Python hostil con acceso al proceso,
monkeypatching o escritura directa al archivo. Tampoco se promete identidad física
de duplicados idénticos, cobertura completa, prueba institucional independiente
de identidad ni entrega exactamente una vez. Dos lecturas iguales no elevan cobertura.

## Validación local

Desde la raíz, con el entorno existente y sin instalar dependencias:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH=(Resolve-Path backend/src).Path
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider backend/tests/test_observaciones_cobertura_desconocida.py backend/tests/test_frontera_persistencia_sigac.py backend/tests/test_auditoria_completitud_sigac.py backend/tests/test_sqlite_local_v2.py backend/tests/test_api_observaciones_reales.py
Push-Location mobile
npm.cmd test
.\node_modules\.bin\tsc.cmd --noEmit
Pop-Location
```

La prueba ASGI necesita FastAPI declarado; si falta, se informa como omitida,
sin atribuirle validación HTTP ejecutada. Las pruebas móviles verifican contrato
puro, errores y separación del componente por análisis estático, no renderizado
en dispositivo ni push físico. No requieren credenciales o conexión a servicios.

Resultado de esta entrega: suite backend ejecutada con red bloqueada,
1486 aprobadas, 2 omitidas, 1 fallo y 10 errores de recopilación. El fallo de
importación de API y los diez errores ya existían por ausencia de `fastapi` y
`psycopg_pool`; la nueva prueba HTTP queda omitida por falta de FastAPI.
Las 12 pruebas nuevas de política se ejecutaron. En móvil: 31 pruebas aprobadas
y TypeScript sin errores. No se instalaron dependencias.

## Archivos de esta entrega

Producción y adaptadores de consulta:

- `backend/src/tinotify/services/avisos_persistentes.py`
- `backend/src/tinotify/demo/novedades.py`
- `backend/src/tinotify/persistence/sqlite_local.py` (solo método SELECT nuevo)
- `backend/src/tinotify/api/real_local.py`
- `backend/scripts/sigac_local.py`
- `mobile/src/CasosLocales.tsx`
- `mobile/src/ObservacionesReales.tsx`
- `mobile/src/contratoObservacionesReales.ts`
- `mobile/package.json` (solo comando de pruebas)

Pruebas y documentación:

- `backend/tests/test_observaciones_cobertura_desconocida.py`
- `backend/tests/test_api_observaciones_reales.py`
- `backend/tests/test_auditoria_completitud_sigac.py`
- `backend/tests/test_frontera_persistencia_sigac.py`
- `backend/tests/test_auditoria_acreditacion_sigac.py`
- `backend/tests/test_alcance_unidad_sigac.py`
- `mobile/test/observacionesReales.test.ts`
- `mobile/test/sinteticoApi.test.ts`
- `docs/observaciones-cobertura-desconocida.md`

Las cuatro pruebas existentes de auditoría cambian únicamente su consumidor de
consulta real, salvo una expectativa explícita: un evento procesado continúa
visible como observación interna. Las comprobaciones de escritura, rollback,
alcance, reinicio e idempotencia se conservan.
