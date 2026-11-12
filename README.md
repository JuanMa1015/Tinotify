# Tinotify

Prototipo independiente orientado a estudiantes del Consultorio Jurídico de la
Universidad de Antioquia para explorar la consulta de expedientes y la detección
de novedades de SIGAC. La integración institucional y la aplicación móvil están
pendientes. Este repositorio no acredita respaldo ni autorización institucional.

## Estado actual

La implementación es una biblioteca Python experimental con módulos y pruebas
en la raíz. No incluye todavía un servidor ejecutable ni una aplicación móvil.

| Capacidad | Estado |
| --- | --- |
| Extraer casos desde HTML | Implementada y probada con ejemplos ficticios |
| Extraer actuaciones y metadatos de anexos | Implementada; no descarga documentos |
| Detectar nuevas actuaciones | Implementada con estado JSON local y limitaciones conocidas |
| Clasificar prioridad | Alta para `ASESOR-->ESTUDIANTE` y `DIRECCION-->ESTUDIANTE` |
| Generar notificaciones | Objetos locales; no hay entrega push |
| Cliente HTTP | Implementado con restricciones parciales de rutas y TLS verificado por defecto |
| Seleccionar rol | POST implementado; no acredita autenticación ni autorización |
| Reconocer página y menú | Comprobaciones preliminares; devuelven `autenticada=False` |
| Autenticación real con SIGAC | No implementada ni validada |
| API FastAPI, SQLite/PostgreSQL y app Expo | Previstas, no implementadas |
| Múltiples estudiantes | No soportados de forma segura actualmente |

La suite actual contiene **54 pruebas**. Su aprobación no demuestra preparación
para producción ni compatibilidad con SIGAC real. Los riesgos de aislamiento,
concurrencia, identificación y persistencia siguen abiertos en
[seguridad](docs/security.md).

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
externas de vulnerabilidades. El empaquetado instalable queda para otra etapa:
**no ejecutar `pip install -e backend` todavía**.

## Desarrollo local

Desde la raíz del repositorio, si ya existe `.venv`, utilizar su intérprete:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
```

Las pruebas usan datos ficticios, transportes HTTP simulados y directorios
temporales para comprobar persistencia. No necesitan credenciales ni acceso a
SIGAC. Se debe ejecutar pytest desde la raíz, donde permanecen los módulos.

En un equipo nuevo, estos comandos preparan un entorno sin activar PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip --version
# Requiere que pip admita --group. La instalacion necesita acceso al indice.
.\.venv\Scripts\python.exe -m pip install --group backend/pyproject.toml:local
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
```

Son instrucciones para preparar otro entorno; esta etapa de documentación no
instala ni actualiza paquetes. Si pip no admite grupos, debe prepararse una
versión compatible antes de utilizar el comando.

## Estructura actual

```text
tinotify/
├── *.py                 # Módulos y pruebas existentes, sin migrar
├── caso_prueba.html      # Fixture ficticio usado por las pruebas de anexos
├── backend/
│   └── pyproject.toml    # Manifiesto; todavía no contiene los módulos
├── docs/
│   ├── architecture.md
│   └── security.md
├── .env.example
├── .gitignore
└── README.md
```

La arquitectura objetivo y la migración por etapas se describen en
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

1. Preparar documentación y dependencias sin modificar la lógica existente.
2. Empaquetar y migrar módulos manteniendo las pruebas aprobadas.
3. Unificar identidad de actuaciones y reforzar parsers y rutas permitidas.
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
