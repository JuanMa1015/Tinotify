# Seguridad y privacidad

## Alcance y estado

Auditoría inicial del 11 de noviembre de 2026. Se revisaron los nueve módulos,
once archivos de pruebas, el fixture HTML, exclusiones y el historial Git local
alcanzable (un commit, 22 contenidos únicos antes de esta preparación).
Se inspeccionaron las dependencias instaladas sin consultas externas.

No se contactó SIGAC ni otro servicio, no se implementó autenticación y no se
utilizaron expedientes reales. Las comprobaciones adicionales se realizaron en
memoria y las pruebas de persistencia usaron temporales con datos ficticios.
Las 54 pruebas existentes aprobaron con la red bloqueada. Un primer intento en
el sandbox falló por permisos de reemplazo de temporales; la repetición
autorizada fuera del sandbox aprobó las 54.

La etapa 1 amplió exclusiones y documentación. La etapa 2 reorganizó los módulos
y configuró su empaquetado sin cambiar algoritmos ni comportamiento funcional.
La etapa 3 implementó reconciliación conservadora, estado v2 y avisos genéricos;
los avances y límites se indican abajo. Las prioridades consideran el
uso futuro con datos sensibles; no significan que exista ya una API expuesta.

## Hallazgos

| ID | Gravedad | Ubicación | Riesgo y tratamiento propuesto |
| --- | --- | --- | --- |
| SEC-01 | Alta al compartir instancia | `monitor.py`, `sigac_service.py` | El estado solo distingue número de caso. No hay contexto de estudiante ni verificación de pertenencia. Introducir identidad interna y autorización por usuario/caso antes de servir a múltiples estudiantes. |
| SEC-02 | Alta con escritores concurrentes | `monitor.py` | V2 usa temporales únicos, no adelanta memoria al fallar y detecta bases ya alteradas. Sigue habiendo una ventana entre comprobación y reemplazo; requiere un único escritor hasta implementar persistencia transaccional. |
| SEC-03 | Alta para entrega futura | `monitor.py`, `sigac_service.py` | El estado queda confirmado antes de entregar un aviso. Un fallo posterior puede perder la notificación. Guardar evento pendiente y detección en la misma transacción; entrega con reintentos e idempotencia. Hoy solo se devuelven objetos locales. |
| SEC-04 | Media | `sigac_client.py` | Validar rutas relativas no limita endpoints ni parámetros. Acepta destinos arbitrarios del mismo origen y segmentos codificados. Definir lista explícita de operaciones, rutas, parámetros y destinos de redirección admitidos. |
| SEC-05 | Media, condicionada a configuración | `sigac_client.py` | Un cliente inyectado puede cambiar origen o TLS; se comprobó otro origen con transporte simulado. Definir y comprobar el contrato del cliente de producción sin perder la inyección de transportes de prueba. |
| SEC-06 | Media; aumenta si se descargan anexos | `parser.py` | La validación por sufijo permite rutas absolutas, recorridos relativos y fragmentos. Hoy solo conserva referencias. Validar ruta y consulta exactas antes de cualquier futura descarga. |
| SEC-07 | Media | `sigac_client.py`, parsers | Sin límites explícitos de bytes o registros. Respuestas excesivas pueden consumir memoria o tiempo. Limitar lectura y procesamiento y distinguir respuestas incompletas. |
| SEC-08 | Corregido en el payload local | `notificaciones.py` | La etapa 3 retiró caso y dirección del payload y usa textos genéricos por tipo de evento. La futura entrega push y el acceso autorizado a detalles siguen pendientes. |
| SEC-09 | Media de privacidad | Metadatos del historial Git | El commit contiene identidad y correo de autoría. Estos metadatos acompañan al historial publicado. Revisar la identidad elegida antes de publicar; no se documentan sus valores. |
| SEC-10 | Mitigado con límites explícitos | Modelos, servicio y reconciliación | V2 conserva multiplicidad y todos los campos de versión. Confirma ediciones solo con ID estable y expresa ambigüedad sin él. Las observaciones indistinguibles siguen sin permitir reconstruir identidades físicas. |

No se confirmaron hallazgos críticos en el alcance local revisado. La gravedad
deberá reevaluarse cuando existan API, autenticación, descarga o despliegue.

## Persistencia y parsers: deuda adicional

- V2 tiene esquema versionado y rechaza corrupción sin destruirla; no implementa
  reparación ni retención automática. V1 exige conversión explícita a otro archivo.
- La memoria avanza después de una escritura exitosa; las consultas idénticas no
  escriben estado. La comprobación de base no sustituye un bloqueo entre procesos.
- Validar todos los expedientes antes de sincronizar no vuelve transaccionales
  las escrituras posteriores por caso.
- Registros malformados pueden omitirse sin señalar que el historial es parcial.
- Los listados vacíos o expedientes sin actuaciones se tratan como errores.
- Las fechas no tienen zona horaria y los identificadores conocidos crecen sin límite.
- Las huellas son resúmenes deterministas, no cifrado ni garantía de anonimato.
- Un caso guardado junto a hashes sigue revelando seguimiento y correlaciones.

La etapa 3 prueba remitentes distintos con contenido igual, duplicados, ediciones,
anexos, consultas parciales, reinicios, fallos de escritura y migración. Siguen
pendientes concurrencia transaccional, usuarios distintos y reintentos de entrega.

La suite contiene 241 casos: 54 originales y 187 adicionales. Solo se sustituyó
la expectativa de un caso original para exigir que el aviso no revele el caso.
Se ejecuta con datos sintéticos, red bloqueada y archivos temporales eliminados.
No se instalaron dependencias en la etapa 3. Véase
[reconciliacion.md](reconciliacion.md) para el contrato de IDs, la política de
ambigüedad y el riesgo de omitir novedades al establecer la línea base v2.

La revisión final detectó que el primer contrato de tipos confundía sintaxis y
estabilidad. La corrección separa candidatos de afirmaciones verificadas y
revalida estas últimas contra un catálogo de código revisado y una habilitación
separada. El catálogo real está vacío; no se acepta que un booleano, un campo
de configuración o el JSON aporten evidencia. Los contratos sintéticos se
definen exclusivamente en pruebas. El formato v2.2 conserva la referencia del
contrato y su alcance, y bloquea el seguimiento ante cambios de confianza hasta
una transición explícita sin sobrescribir el origen. Véase
[contratos-identidad.md](contratos-identidad.md) para sus garantías y límites.

## Sesiones, roles y redirecciones

El cliente predeterminado verifica TLS, no hereda proxies del entorno y no sigue
redirecciones automáticamente. Rechaza URLs externas en las rutas normales.
Son controles útiles, pero no constituyen una lista de operaciones permitidas.

La selección de rol envía un POST y comprueba una respuesta 302 con destino
relativo. No demuestra que el rol haya quedado activo. Las comprobaciones de
menú devuelven `autenticada=False`: no identifican al estudiante ni acreditan
pertenencia a un caso. No asumir que ver enlaces equivale a autorización.

No compartir clientes HTTP, cookies o estado de sesión entre estudiantes.
El diseño futuro deberá contemplar caducidad, revocación, limpieza al cerrar
sesión y separación estricta por usuario. La autenticación institucional queda
pendiente de revisar permisos; no se almacenarán contraseñas de SIGAC.

## Datos y revisión de publicación

No se detectaron credenciales ni valores de cookies/tokens mediante la revisión
y los patrones locales aplicados al código propio y al historial alcanzable.
Los fixtures se presentan como ficticios. Esta conclusión no certifica su
procedencia ni demuestra ausencia absoluta de datos identificables.

`.venv/pyvenv.cfg` contiene rutas del equipo. Cachés y bytecode pueden conservar
rutas o contenidos anteriores. Permanecen excluidos; no se auditó exhaustivamente
el código de todas las dependencias ni objetos Git no alcanzables.

Antes de cada publicación:

1. Revisar archivos versionados y diff completo, incluidos fixtures y documentación.
2. No incluir HTML de SIGAC, documentos, nombres, fechas vinculables, identificadores
   reales de casos o enlaces de anexos, aunque no contengan contraseñas.
3. Mantener cookies, sesiones, exportaciones, logs y bases de datos fuera de Git.
4. Revisar metadatos de autoría y cualquier configuración de remoto sin imprimir secretos.
5. Usar ejemplos sintéticos con procedencia controlada para reportes y pruebas.

`.gitignore` reduce inclusiones accidentales, pero no protege archivos ya
versionados ni datos incrustados en un archivo permitido. Los tokens push y
referencias a anexos también deben tratarse como información sensible.

## Dependencias y límites de la revisión

`pip check` no encontró conflictos en el entorno Python 3.11.9 auditado.
`backend/pyproject.toml` fija versiones directas y un grupo del entorno local.
El paquete intermediario `bs4` no se declara porque basta `beautifulsoup4`.
No se instalaron, actualizaron ni eliminaron dependencias durante la auditoría
inicial y la etapa 1. En la etapa 2 se autorizó instalar exclusivamente
`wheel==0.45.1` como herramienta nueva en un entorno temporal. Las dependencias
existentes conservaron sus versiones. Al cierre de la etapa 2, el entorno `.venv`
principal recibió únicamente la instalación editable del proyecto local Tinotify,
sin nuevas dependencias ni actualizaciones. Se reutilizó la herramienta temporal
autorizada para construir sin acceder al índice y se verificaron las 54 pruebas
desde la raíz con la red bloqueada.

Las ubicaciones actuales de los módulos están en [architecture.md](architecture.md).
Los nombres breves de la tabla de hallazgos identifican esos mismos módulos.
Después de cada paso de migración se comprobaron exactamente 54 pruebas,
ausencia de imports antiguos ya migrados y equivalencia sintáctica de la lógica
con el commit base. Se validaron una instalación editable y una wheel instalada
en entornos temporales distintos, importando desde fuera del checkout con la red
bloqueada. Las dependencias se reutilizaron mediante acceso local a las ya
instaladas; no se comprobó una resolución independiente desde un entorno vacío.
El HTML ficticio se conservó idéntico y no quedaron estados de monitor en el
repositorio ni en los directorios temporales de pruebas.

No se consultaron bases externas de vulnerabilidades. El acceso autorizado al
índice durante la etapa 2 se limitó a descargar la herramienta `wheel`; no se
enviaron archivos del proyecto ni se contactó SIGAC. La aprobación de pruebas y
los pins no garantizan ausencia de vulnerabilidades. El manifiesto no contiene
hashes de distribuciones y otras plataformas requieren validación.

## Reportar un problema

Preparar una descripción con rutas afectadas, impacto y reproducción sintética.
No publicar credenciales, cookies, expedientes o datos personales en issues,
capturas o adjuntos. Todavía no hay un canal privado de seguridad configurado;
deberá definirse antes de la publicación abierta. Si ocurre una exposición real,
detener la publicación y acordar contención, revocación y tratamiento del historial
sin reproducir el contenido sensible.
