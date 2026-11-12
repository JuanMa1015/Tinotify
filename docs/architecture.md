# Arquitectura y migración prevista

## Implementación actual

El proyecto es una biblioteca Python 3.11 instalable con módulos bajo
`backend/src/tinotify` y dieciséis archivos de pruebas en `backend/tests`.
`backend/pyproject.toml` declara dependencias, herramientas de construcción
fijadas y descubrimiento de paquetes exclusivamente bajo `src/tinotify`.
La configuración de pytest está en la raíz, en `pytest.ini`.

| Módulo | Responsabilidad actual |
| --- | --- |
| `parsers/casos_parser.py` | Extraer casos desde HTML |
| `parsers/parser.py` | Extraer actuaciones, huellas y metadatos de anexos |
| `persistence/monitor.py` | Comparar actuaciones y guardar identificadores en JSON |
| `domain/notificaciones.py` | Construir objetos de notificación y clasificar prioridad |
| `domain/actuaciones.py` | Observaciones, ID opcional, versiones deterministas y eventos |
| `domain/identificadores.py` | Candidatos, contratos revisados, habilitación y alcance de identidad |
| `services/reconciliacion.py` | Emparejar IDs o versiones exactas conservando multiplicidad |
| `services/sigac_service.py` | Integrar parsers y monitor |
| `integrations/sigac/sigac_client.py` | Cliente HTTP y envío de selección de rol |
| `integrations/sigac/sigac_roles.py` | Roles admitidos y datos de selección |
| `integrations/sigac/sigac_menu.py` | Reconocer enlaces del menú de estudiante |
| `integrations/sigac/sigac_session.py` | Comprobaciones preliminares de páginas; no autentica |

Las rutas de la tabla son relativas a `backend/src/tinotify`. La etapa 2 movió
los módulos sin cambiar algoritmos. La etapa 3 trasladó los modelos de actuación
y anexo al dominio y añadió un único motor puro de reconciliación. El monitor
gestiona el estado JSON v2 e invoca ese motor; el servicio conserva todos los
metadatos y expone eventos y avisos genéricos. Los paquetes mantienen
`__init__.py` vacío e imports absolutos bajo `tinotify`.

El flujo local actual es HTML aportado por el llamador, parsers, adaptación del
servicio y monitor JSON. Los resultados incluyen objetos de notificación.
El cliente HTTP todavía no forma una integración autenticada validada de extremo
a extremo. No hay API, aplicación móvil, SQLite, PostgreSQL ni entrega push.

## Estructura del backend y extensión futura

```text
tinotify/
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   └── tinotify/
│   │       ├── domain/
│   │       ├── parsers/
│   │       ├── services/
│   │       ├── integrations/sigac/
│   │       ├── persistence/
│   │       └── api/
│   └── tests/
│       └── fixtures/
├── mobile/                 # Previsto; todavía no creado
├── docs/
├── .env.example
├── .gitignore
├── pytest.ini
└── README.md
```

`api` solo contiene su `__init__.py` vacío; no hay endpoints ni dependencia de
FastAPI. `domain` conserva las notificaciones actuales y podrá contener otros
modelos e invariantes independientes de FastAPI y de la base
de datos. `parsers` interpretará HTML sin red ni persistencia. `services`
coordinará casos de uso mediante interfaces de persistencia e integración.
`integrations/sigac` concentrará HTTP y validación de respuestas.
`persistence` implementará las transacciones. `api` expondrá contratos mínimos
sin HTML crudo, cookies ni referencias sensibles innecesarias.

Se propone React Native con Expo y TypeScript para `mobile`, FastAPI para la API,
SQLite para el prototipo y PostgreSQL cuando la operación lo requiera. Estas
tecnologías aún no se añaden a las dependencias actuales.

## Aislamiento y autorización

Cada operación futura debe recibir una identidad interna de estudiante desde
un contexto autenticado y aplicar autorización antes de leer o sincronizar un
caso. Un parámetro `user_id` enviado por la app no acredita esa identidad.

El seguimiento se separará por estudiante y caso. Los repositorios exigirán ese
contexto; se probará que un estudiante no puede consultar estado, sesiones o
avisos de otro. Los clientes HTTP y sus cookies no serán globales ni compartidos.

El mecanismo institucional permanece sin decidir hasta revisar permisos y
restricciones. No se implementará almacenamiento de contraseñas de SIGAC.
Seleccionar un rol o reconocer un menú no sustituye autorización institucional.

## Identidad de actuaciones y persistencia

La etapa 3 separa UUID local, candidato de origen, identidad estable verificada,
huella de versión y estado de reconciliación. Solo se confirman ediciones con
contrato revisado, habilitado y compatible con el alcance actual; sin él
se conservan ocurrencias idénticas y se señalan correspondencias ambiguas.
Las ausencias no eliminan registros. El servicio ya no descarta los metadatos.

El contrato completo, el esquema v2 y la migración explícita están en
[reconciliacion.md](reconciliacion.md). No se ha verificado un ID de SIGAC real;
el parser no lo deduce de atributos HTML. El catálogo de producción está vacío;
los contratos sintéticos solo se inyectan en pruebas. La validación sintáctica,
la configuración y el estado persistido no prueban estabilidad. El formato v2.2
exige transición explícita para revisiones o políticas anteriores; véase
[contratos-identidad.md](contratos-identidad.md). El JSON tiene un único escritor,
no es una base de datos transaccional ni constituye aislamiento multiusuario.

El almacenamiento previsto usará transacciones y restricciones de unicidad para
seguimiento por usuario/caso, identidades de actuaciones y eventos pendientes.
La detección y el registro del aviso se confirmarán juntos. Un trabajador
procesará los avisos pendientes con reintentos e idempotencia; no se promete
entrega exactamente una vez por parte de proveedores externos.

Definir retención, borrado por usuario y minimización antes de guardar datos
reales. No persistir HTML o documentos completos por defecto. SQLite no cifra
por sí solo el archivo; controles de acceso, protección y copias de respaldo
requerirán una decisión propia antes de utilizar datos sensibles.

## Comunicación y notificaciones

La futura integración limitará origen, endpoints, parámetros, tamaño de respuesta
y destinos de redirección. Separará expiración de sesión, permiso denegado,
respuesta parcial y errores de estructura. Las referencias de anexos necesitarán
validación adicional antes de habilitar descargas.

Los avisos locales ya son genéricos; los detalles se consultarán dentro de la app
tras comprobar identidad y permisos. Los tokens push son datos sensibles.
La prioridad conservará las reglas actuales para asesor/dirección hacia estudiante.

El cliente HTTP actual es síncrono. Al introducir FastAPI se decidirá entre
ejecución síncrona apropiada o un adaptador asíncrono; no se bloqueará el bucle
asíncrono con llamadas de red síncronas.

## Migración por etapas

| Etapa | Cambio propuesto | Verificación |
| --- | --- | --- |
| 1, completada | Exclusiones, README, manifiesto, ejemplo de entorno y documentación | Código funcional intacto; 54 pruebas aprobadas |
| 2, implementada | Empaquetado `src/tinotify`, traslado de módulos y pruebas | 54 pruebas aprobadas por paso y con instalaciones editable y wheel; sin cambios de comportamiento |
| 3, completada | Identidad, contratos de confianza y reconciliación con estado v2.2 | 241 pruebas; candidatos, alcance, pérdida de confianza, duplicados, ambigüedad y transiciones |
| 4, pendiente | SQLite transaccional con aislamiento y eventos pendientes | Reinicio, errores de escritura, concurrencia e independencia de usuarios |
| 5, pendiente | FastAPI sobre datos sintéticos | Contratos y autorización comprobados sin acceder a SIGAC |
| 6, pendiente | Diseño institucional de autenticación y sesiones | Revisión de permisos y aprobación previa a la integración real |
| 7, pendiente | Expo y notificaciones | Privacidad de avisos, caducidad y reintentos |

La etapa 2 actualizó los imports de código y pruebas y trasladó `caso_prueba.html`
a `backend/tests/fixtures`, cambiando sus dos referencias en `test_anexos.py`.
El archivo HTML se conservó idéntico. El cuerpo del monitor y el resto de la
lógica se compararon sintácticamente con el commit base, excluyendo únicamente
imports y las rutas autorizadas del fixture.

Las pruebas se ejecutan desde la raíz, tras instalar el paquete editable,
mediante `python -m pytest -v`. `pytest.ini` selecciona `backend/tests` y el modo
de importación `importlib`, sin ajustes de `sys.path` ni `PYTHONPATH` para localizar
el paquete. También se probaron editable y wheel desde fuera del repositorio,
comprobando el origen real de todos los módulos importados. Las dependencias ya
instaladas se reutilizaron sin alterarlas; no se validó una instalación completa
de dependencias desde cero. El estado temporal de las pruebas se eliminó.

El monitor sigue resolviendo su ruta predeterminada respecto al directorio de
ejecución del llamador. Mover el módulo no cambió esa regla ni su persistencia.

## Configuración y decisiones pendientes

Las variables de `.env.example` son propuestas ficticias no consumidas por el
código actual. No proporcionan todavía una barrera de red ni un modo de pruebas.
La configuración futura deberá validar valores y mantener secretos fuera de
logs, repositorio y variables públicas de Expo.

Quedan pendientes identidad de usuario, permisos institucionales, política de
retención, validación del ID real de origen, proveedor push, CI, cifrado y despliegue.
La licencia también permanece sin decidir y no se añade en esta etapa.

Los riesgos que motivan estas decisiones están descritos en
[security.md](security.md); documentarlos no significa que estén resueltos.
