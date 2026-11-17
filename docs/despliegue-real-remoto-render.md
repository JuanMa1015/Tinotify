# Sustituir el backend sintético por el backend real en el servicio Render existente

Decisión de producto: Tinotify usará solo datos reales de SIGAC; no hay segundo servicio ni modo sintético en producción. El código
sintético permanece en el repositorio (no se borra) pero **no se carga** en producción. Los pasos marcados **[AUTORIZACIÓN]**
modifican Render o ramas remotas y requieren aprobación explícita.

## 0. Configuración REAL confirmada del servicio (por la persona operadora, en el panel)

Repositorio `JuanMa1015/Tinotify` · **rama `main`** (no `deploy/sintetico-render`) · Root Directory `backend/` · Start Command
`tinotify.sintetico_remoto.app:crear_app` con Uvicorn · Auto-Deploy **Off** · Secret Files disponibles · el servicio tiene el Secret
File `supabase-ca.crt`.

**Referencia exacta de lo desplegado.** Git no registra qué commit desplegó Render: con Auto-Deploy Off, solo el panel (*Events* / *Deploys*)
muestra el hash. No se ha inventado. Lo que sí se sabe: `origin/main` = `4934a3f` («Merge pull request #11 … deploy/sintetico-render»,
2026-11-15 16:38 -0500) y su árbol de archivos es **idéntico** al de `origin/deploy/sintetico-render` (`611e9a2`); por tanto, si el
último despliegue fue posterior al 15-nov-2026 16:35, el código en ejecución equivale a `4934a3f`. **Antes de cambiar nada, anota el
hash que muestre el panel como «commit desplegado».** Es la referencia de recuperación.

## 1. Qué cambia y qué se pierde

| | Antes (sintético, `main`) | Después (real, `deploy/real-remoto`) |
| --- | --- | --- |
| Rama del servicio | `main` | `deploy/real-remoto` |
| Arranque | `python -m uvicorn tinotify.sintetico_remoto.app:crear_app --factory --host 0.0.0.0 --port "$PORT" --workers 1 --no-proxy-headers` | `python -m uvicorn tinotify.real_remoto.app:crear_app --factory --host 0.0.0.0 --port "$PORT" --workers 1 --no-proxy-headers --no-access-log` |
| Rutas | `/health` `{"estado":"ok"}`, `/sintetico/*` | `/health` `{"status":"ok"}`, `/real/*` |
| Datos | ficticios, PostgreSQL (Supabase) | SIGAC real, solo memoria; sin base de datos |
| Conservado | build, `rootDir: backend`, `healthCheckPath: /health`, `PYTHON_VERSION`, 1 worker, plan, URL, Auto-Deploy Off | |

Se pierde en producción: la API `/sintetico/*`, su monitor, la conexión a Supabase y, hasta que se actualice la app, cualquier pantalla
de Android que use `/sintetico/*` o `127.0.0.1`. Supabase y su esquema no se modifican. `main` tampoco: el servicio deja de leerla.
El código real **no importa nada** de `tinotify.sintetico_remoto` ni carga `psycopg` (prueba automática) y sus dependencias de terceros
están cubiertas por `backend/requirements.txt`, que es idéntico al de `main`.

## 2. La rama `deploy/real-remoto`

Base: **`origin/main` (`4934a3f`)**, para que el servicio solo cambie de rama y conserve todo lo ya desplegado. Sobre esa base se añaden
únicamente los cambios del backend real:
- **Nuevos** (103 archivos): `backend/src/tinotify/real_remoto/`, servicios y scripts del backend real, pruebas y documentación.
- **Modificados que conservan mis cambios** (`.gitignore`, `identificadores.py`, `sigac_client.py`, `casos_parser.py`, `avisos_persistentes.py`,
  `seguimiento.py`, `docs/etapa-4b.md`) y los dos archivos del parser que `main` tiene en una versión anterior (`parser.py` y
  `diagnostico_historial.py`: el árbol de trabajo es un superconjunto de la versión de `main`, solo con ampliaciones).
- **Sin tocar, tal como están en `main`**: `backend/src/tinotify/sintetico_remoto/*` (incluido `datos.py`), `backend/tests/test_sintetico_postgres_config.py`,
  `supabase/`, `.github/`, `docs/preflight-supabase-4b4b.md`, requirements.
- **No incluidas**: `test_sintetico_remoto.py`, `integration/test_sintetico_postgres.py` e `integration/test_sintetico_reversion.py`, del árbol de trabajo
  (instantánea anterior del paquete sintético, incompatible con la versión de `main`; la prueba de `main` sobre el sintético, `test_sintetico_postgres_config.py`, sí se conserva).
- **`render.yaml`**: el de `main` con rama, arranque y variables del backend real (referencia; el servicio existente se edita en el panel).
- **Nunca**: `mobile/`, APK, bases SQLite, `backend/.local/`, Secret Files, texto judicial.

Verificación sin crear nada: `verificar_rama_despliegue.py` (rutas prohibidas, 9 secretos de este equipo, claves privadas, URLs con
contraseña, JWT y 1.237 fragmentos de texto judicial real de v1 en solo lectura; imprime solo conteos y rutas infractoras).

## 3. Cambios en Render **[AUTORIZACIÓN]**

Antes: anota rama, Start Command, Build Command, **commit desplegado** y la lista de variables; guarda en tu gestor de contraseñas los
valores de las `TINOTIFY_SR_*` (sin ellos no hay rollback de configuración). El Secret File `supabase-ca.crt` **se deja** (el servicio real
no lo lee; así el rollback no necesita volver a subirlo).

1. **Secret Files** — añadir `acreditacion_sigac.json` y `referencia_portable.json` (desde `backend/.local/`), nombres exactos (quedan en `/etc/secrets/`).
2. **Variables** — retirar: `TINOTIFY_SR_MODO`, `TLS`, `PROXIES_CONFIABLES`, `TOKEN`, `ALMACEN`, `INTERVALO_S` y todas las `TINOTIFY_SR_PG_*`
   (host, puerto, modo, base, usuario, contraseña, CA, conexiones). Conservar `PYTHON_VERSION=3.11.18`. Añadir `TINOTIFY_RR_MODO=remoto`,
   `TINOTIFY_RR_TLS=proxy`, `TINOTIFY_RR_PROXIES_CONFIABLES=privadas`, `TINOTIFY_RR_ACREDITACION_FILE=/etc/secrets/acreditacion_sigac.json`,
   `TINOTIFY_RR_REFERENCIA_FILE=/etc/secrets/referencia_portable.json` y `TINOTIFY_RR_TOKEN` (secreto nuevo ≥ 32 caracteres, no el sintético).
   Opcionales: `TINOTIFY_RR_TIPO` (2), `TINOTIFY_RR_TOTAL_CASOS`, `TINOTIFY_RR_TTL_MIN` (20), `TINOTIFY_RR_MAX_LOGINS` (3),
   `TINOTIFY_RR_VENTANA_LOGIN_MIN` (15). Prohibidas (el servicio no arranca; el log da solo sus **nombres**): `TINOTIFY_SR_*`,
   `TINOTIFY_REAL_*`, `SIGAC_*`, `SUPABASE*`, `PG*`, `DATABASE_URL`.
3. **Settings** — Branch → `deploy/real-remoto`; Start Command → el de la sección 1; Build Command y Health Check Path sin cambios
   (comprobar que coinciden con `render.yaml`); Auto-Deploy Off.
4. **Manual Deploy** → *Deploy latest commit*. Si el arranque se rechaza, Render debería mantener el deploy anterior (a confirmar en el panel).

## 4. Verificaciones sin SIGAC

Antes del cambio: `verificar_remoto_real.py --url https://tinotify.onrender.com` → `"aplicacion": "sintetico"`. Después:

```powershell
.\backend\.venv\Scripts\python.exe -B backend\scripts\verificar_remoto_real.py --url https://tinotify.onrender.com
.\backend\.venv\Scripts\python.exe -B backend\scripts\verificar_remoto_real.py --url https://tinotify.onrender.com --con-token
```
Esperado sin token: `/health` con clave `status`, `/real/cases` 401, `/sintetico/casos` 404, `"aplicacion": "real_remoto"`. Con token:
`/real/sesion/estado` 200, `expedientes` 1, `sesion_activa` false, veredicto `ok`. Un 403 con pista de transporte indica que el par TCP del
proxy de Render no está en `privadas`: el log trae `transporte_rechazado ... par=<ip>` y se fija ese rango (CIDR ≥ /24) en
`TINOTIFY_RR_PROXIES_CONFIABLES`; no se desactiva la validación HTTPS. Ninguna de estas rutas llega a SIGAC.

## 5. Prueba única de autenticación real **[AUTORIZACIÓN ESPECÍFICA; NO ejecutar antes]**

```powershell
.\backend\.venv\Scripts\python.exe -B backend\scripts\prueba_login_remoto.py --url https://tinotify.onrender.com
```
Solo pide credenciales si, con GET sin autenticación, comprueba que el destino es el backend real; un solo `POST /real/sesion`; cierra la
sesión. 200 = Render alcanza SIGAC y la lectura contiene la referencia; 403 = SIGAC no confirmó el acceso o se rechazó el transporte;
502 = SIGAC no respondió como se esperaba o no es alcanzable desde Render; 422 = la lectura no contiene la referencia.

## 6. Recuperación (rollback) a la configuración anterior

`main` y `deploy/sintetico-render` no se modifican en ningún paso (`main@4934a3f`, `deploy/sintetico-render@611e9a2`, mismo árbol). Orden
(Render usa la configuración vigente al redesplegar, por eso se restaura primero la configuración):
1. Restaurar las variables `TINOTIFY_SR_*` desde tu gestor; retirar las `TINOTIFY_RR_*` y los Secret Files `acreditacion_sigac.json` y
   `referencia_portable.json` (`supabase-ca.crt` sigue ahí).
2. Settings → Branch → **`main`**; Start Command → `python -m uvicorn tinotify.sintetico_remoto.app:crear_app --factory --host 0.0.0.0 --port "$PORT" --workers 1 --no-proxy-headers`
   (o el valor que anotaste, si difería).
3. Manual Deploy del último commit de `main` — equivale al código anterior si el commit desplegado era `4934a3f` (o su equivalente
   `611e9a2`); si el panel mostraba otro hash, desplegar ese commit concreto (*Deploys → Rollback*, tras restaurar la configuración).
4. Comprobar: `/health` → `{"estado":"ok"}` y `/sintetico/casos` → 401.
Supabase no se modifica durante el cambio ni durante el rollback.

## 7. Bloqueos y riesgos

**Bloqueos técnicos:** ninguno en el código ni en la rama (ver verificaciones). La rama `deploy/real-remoto` queda publicada solo cuando se ejecuta
la sección 2 con tu autorización; el cambio de Render es un paso aparte.

**Riesgos que solo se resuelven al desplegar:**
- SIGAC podría no ser alcanzable desde las IP de Render (lo resuelve la prueba única de la sección 5).
- El rango del proxy de Render no está verificado (falla cerrado; se corrige con un CIDR).
- El hash exacto desplegado no consta en Git (ver sección 0): anótalo antes de cambiar nada.
- Plan gratuito: se duerme tras 15 min sin tráfico (~1 min de arranque en frío) y descarta el historial en memoria (por diseño); Android deberá
  ampliar su timeout. 750 horas gratuitas al mes por espacio de trabajo.
- Credenciales institucionales en un tercero (TLS terminado en el proxy de Render): decisión tuya.
- Tres errores de clave bloquean el login 15 minutos.
- Hasta actualizar Android, la app seguirá apuntando a `127.0.0.1` o al sintético.

## 9. Monitor (opcional, se activa solo con sus variables)

Con las variables del monitor (ver `render.real-remoto.propuesta.yaml`) el servicio añade: guardar las credenciales **cifradas** (AES-256-GCM;
la llave solo está en Render) al iniciar sesión con `"recordar": true`, y revisar **todos** los expedientes comparando huellas con clave contra
el estado en Supabase (`tinotify_real`; ver `docs/monitor-real-supabase.md`). Rutas: `POST /real/monitor/ejecutar`, `GET /real/monitor/avisos` y
`POST /real/monitor/avisos/{id}/entregado` (token del monitor, distinto del de la app); `GET /real/monitor/estado` y `DELETE /real/credenciales` (token
de la app). Las respuestas llevan solo conteos y los UUID de los avisos. Sin esas variables, el servicio se comporta como antes (sin rutas de monitor).
Quitar las variables del monitor es el rollback de esta fase. Validado en Linux (Python 3.11.9, dependencias con hashes) y contra PostgreSQL 17 real con el
login restringido: `bash supabase/checks/validar_almacen_real_python.sh`.
