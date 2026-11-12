# Tinotify

Prototipo independiente orientado a estudiantes del Consultorio Jurídico de la
Universidad de Antioquia para explorar la consulta de expedientes y la detección
de novedades de SIGAC. La integración institucional y la aplicación móvil están
pendientes. Este repositorio no acredita respaldo ni autorización institucional.

## Estado actual

La implementación es una biblioteca Python experimental instalable, organizada
en `backend/src/tinotify`, con pruebas en `backend/tests`. No incluye todavía un
servidor ejecutable ni una aplicación móvil.

| Capacidad | Estado |
| --- | --- |
| Extraer casos desde HTML | Implementada y probada con ejemplos ficticios |
| Extraer actuaciones y metadatos de anexos | Implementada; no descarga documentos |
| Reconciliar observaciones | Estado JSON v2, multiplicidad, versiones y ambigüedades explícitas |
| Clasificar prioridad | Alta para `ASESOR-->ESTUDIANTE` y `DIRECCION-->ESTUDIANTE` |
| Generar notificaciones | Avisos locales genéricos por tipo y prioridad; no hay entrega push |
| Cliente HTTP | Implementado con restricciones parciales de rutas y TLS verificado por defecto |
| Seleccionar rol | POST implementado; no acredita autenticación ni autorización |
| Reconocer página y menú | Comprobaciones preliminares; devuelven `autenticada=False` |
| Autenticación real con SIGAC | No implementada ni validada |
| API FastAPI, SQLite/PostgreSQL y app Expo | Previstas, no implementadas |
| Múltiples estudiantes | No soportados de forma segura actualmente |

La suite actual contiene **241 pruebas: 54 originales y 187 adicionales**.
Una expectativa original cambió para exigir avisos sin datos del expediente.
Su aprobación no demuestra preparación
para producción ni compatibilidad con SIGAC real. Los riesgos de aislamiento,
concurrencia, identificación y persistencia siguen abiertos en
[seguridad](docs/security.md).

La [reconciliación de actuaciones](docs/reconciliacion.md) distingue primera
observación, modificación confirmada y cambio ambiguo. Sin IDs estables no puede
identificar perfectamente una actuación. El parser no inventa IDs de SIGAC.
Los estados v1 requieren conversión explícita a otro archivo y una nueva línea
base, que puede omitir novedades durante la transición. Los hashes no anonimizan.
La revisión actual del estado es v2.2. Un ID sintácticamente válido es solo un
candidato: producción no tiene contratos estables de SIGAC habilitados. Los
estados anteriores o los cambios de confianza exigen transición explícita sin
elevar IDs antiguos. Véase [contratos de identidad](docs/contratos-identidad.md).

## Requisitos y dependencias

- Python 3.11; entorno verificado con CPython 3.11.9 en Windows.
- Ejecución: Beautiful Soup y HTTPX.
- Desarrollo: pytest.
- Para el comando de instalación por grupos: pip con soporte para `--group`
  (verificado localmente con pip 26.3).

[backend/pyproject.toml](backend/pyproject.toml) declara las dependencias directas
y el grupo `local`, con versiones exactas de sus dependencias de ejecución y
pruebas observadas en el entorno auditado. No incluye FastAPI, Expo ni el paquete
intermediario redundante `bs4`. El entorno existente puede conservar este último;
no es necesario desinstalarlo para ejecutar las pruebas.

Los pins facilitan repetir el entorno verificado, pero no son un lock con hashes
ni garantizan idéntica resolución en otras plataformas. No se consultaron bases
externas de vulnerabilidades. El empaquetado usa `setuptools==65.5.0` y
`wheel==0.45.1` como herramientas de construcción; no son dependencias de ejecución.
La distribución se llama `tinotify-backend` y el paquete importable es `tinotify`.

## Desarrollo local

Desde la raíz del repositorio, preparar el entorno e instalar el paquete editable
antes de ejecutar pytest. Si ya existe `.venv`, omitir su creación:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip --version
# Requiere que pip admita --group. La instalacion necesita acceso al indice.
.\.venv\Scripts\python.exe -m pip install --group backend/pyproject.toml:local
.\.venv\Scripts\python.exe -m pip install --no-deps -e .\backend
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
```

La instalación editable puede descargar las herramientas de construcción fijadas
en el manifiesto. Si ya están disponibles en el entorno, puede añadirse
`--no-build-isolation --no-index` para construir sin acceder al índice. La
instalación por grupos requiere una versión de pip que admita `--group`.

Las pruebas usan datos ficticios, transportes HTTP simulados y directorios
temporales para comprobar persistencia. No necesitan credenciales ni acceso a
SIGAC. `pytest.ini` permite ejecutarlas desde la raíz con importaciones del
paquete instalado, sin configurar `PYTHONPATH` ni modificar `sys.path`.

La validación inicial de la migración utilizó entornos temporales. Al cerrar la
etapa 2 se instaló también Tinotify en modo editable en el `.venv` principal,
desde el proyecto local `backend/`, sin instalar ni actualizar otras dependencias.
Las 54 pruebas pasaron desde la raíz con ese entorno y `pip check` no encontró
conflictos. En otro entorno existente sigue siendo necesario instalar el paquete
antes de ejecutar las nuevas pruebas.

## Distribución y validación

Para construir una wheel con el entorno preparado:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir dist .\backend
```

Este comando puede preparar herramientas en un entorno de construcción aislado.
La wheel solo contiene el paquete `tinotify` y sus metadatos; las pruebas y el
HTML ficticio permanecen en el repositorio y no forman parte de la distribución.

Durante la migración se verificaron exactamente 54 pruebas en cada paso, además
de la instalación editable y una wheel instalada en otro entorno temporal. Las
dos instalaciones se comprobaron desde fuera del repositorio con la red bloqueada.
Los entornos reutilizaron las dependencias existentes mediante una referencia
local de solo lectura; no fue una resolución independiente de dependencias desde
cero. La única herramienta nueva autorizada fue `wheel==0.45.1`, instalada en el
entorno temporal. Los archivos de estado de prueba se eliminaron al finalizar.

## Estructura actual

```text
tinotify/
├── backend/
│   ├── pyproject.toml
│   ├── src/tinotify/
│   │   ├── domain/                   # Actuaciones, identificadores y avisos
│   │   ├── parsers/                  # casos_parser.py y parser.py
│   │   ├── services/                 # sigac_service.py y reconciliacion.py
│   │   ├── integrations/sigac/       # Cliente, roles, menú y sesión
│   │   ├── persistence/monitor.py
│   │   └── api/                      # Paquete vacío; sin FastAPI
│   └── tests/
│       ├── test_*.py                 # Dieciséis archivos, 241 pruebas
│       └── fixtures/caso_prueba.html
├── docs/
│   ├── architecture.md
│   ├── contratos-identidad.md
│   ├── reconciliacion.md
│   └── security.md
├── .env.example
├── .gitignore
├── pytest.ini
└── README.md
```

La arquitectura actual y las siguientes etapas se describen en
[arquitectura](docs/architecture.md). La app móvil aún no tiene carpeta ni código.

## Configuración y privacidad

`.env.example` contiene únicamente valores de demostración para una futura capa
de configuración. **El código actual no carga `.env` ni consume esas variables**;
por tanto, no activan un modo sintético ni deshabilitan las llamadas del cliente.
Actualmente solo la suite de pruebas emplea transportes simulados.

No incorporar credenciales, cookies, sesiones, HTML reales, documentos ni datos
personales al repositorio, las pruebas, los logs o los reportes de errores. Las
carpetas privadas y archivos locales habituales están excluidos en `.gitignore`.
La exclusión no elimina archivos ya versionados ni detecta datos incrustados en
código. Revisar también metadatos de anexos, identificadores de casos y autoría
de commits antes de publicar. No usar variables `EXPO_PUBLIC_*` para secretos.

La integración real queda condicionada a revisar permisos institucionales. No
implementar almacenamiento de credenciales de SIGAC ni usar expedientes reales
como fixtures. Reconocer un menú no sustituye la autorización del servidor.

## Hoja de ruta

1. Preparar documentación y dependencias: completado.
2. Empaquetar y migrar módulos manteniendo las pruebas aprobadas: implementado.
3. Identidad, versión de contenido y reconciliación conservadora: implementado.
4. Implementar persistencia transaccional y aislamiento por estudiante.
5. Crear una API FastAPI sobre datos sintéticos.
6. Revisar permisos y diseñar la integración institucional y las sesiones.
7. Implementar React Native, Expo y TypeScript, con entrega de avisos persistente.

## Contribuciones y licencia

Los cambios de comportamiento deben incluir pruebas con ejemplos sintéticos y
explicar su impacto sobre privacidad. No adjuntar sesiones o datos reales para
reproducir fallos. Consultar [seguridad](docs/security.md) antes de reportarlos.

La licencia está pendiente de decisión. No se ha añadido un archivo `LICENSE` ni
se declara todavía una licencia open source. La futura licencia del código no
otorgará derechos sobre SIGAC, marcas institucionales o expedientes.
