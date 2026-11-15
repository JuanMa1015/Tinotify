# 4B.4-B: preflight previo a la cuarta migracion

Base: main con PR #8 fusionado en c20e86b. Esta fase prepara herramientas; no
ejecuta consultas contra Supabase, ni aplica DDL o habilita app_fixture. No cambia
las cuatro migraciones, el paquete de negocio, Auth, Render, FastAPI o SIGAC.
El destino futuro sigue siendo Development exclusivo con datos ficticios.

## Contrato y limites

La etapa objetivo tiene exactamente las tres primeras migraciones, ocho tablas,
cinco roles Tinotify, diez funciones y 25 politicas. No debe existir app_fixture,
sus tres roles, sus funciones, sus politicas de negocio ni el trigger reservado.
El historial esperado es [1,1,1,0], sin duplicados, huecos o versiones ajenas.
Eso no prueba que el SQL aplicado coincida con Git ni que el proveedor permita
ejecutar el DDL siguiente. No usar migration repair o reutilizar objetos ajenos.

`supabase/checks/4b4b_preflight.sql` es una sola sentencia WITH/SELECT, con funciones
de inspeccion pg_catalog permitidas. No consulta filas de negocio, Auth, secretos,
actividad de sesiones o cuerpos del historial. Inspecciona colisiones, propiedad,
CREATEROLE/CREATE observables para postgres, dependencias nativas y acceso al
historial. `4b4a_inventario.sql` se reutiliza intacto: sus entradas futuras aparecen
ausentes en esta etapa. No se eliminan entradas del snapshot ni se exige presencia
de objetos futuros. `4b3_historial.sql` lee solo version/recuentos, por separado.
Si falta SELECT/USAGE o hay RLS sobre el historial, detener: no interpretar una
lectura parcial como historial vacio ni conceder privilegios automaticamente.

El catalogo incluye los ocho objetos y todas sus columnas/constraints/indices,
propietarios, RLS/FORCE, destinatarios RLS exactos, cuerpos de funciones resumidos
con hashes, ACL de tablas/columnas/esquemas/funciones, permisos efectivos para los
roles inventariados, membresias/defaults y objetos inesperados en los esquemas
controlados. Los nombres no previstos se representan con hashes; no son anonimos.
No se inventarian todos los objetos ajenos de todo el cluster ni se demuestra
que un hook administrado futuro sea inocuo por observar un contador.

Cada snapshot debe contener exactamente las **25 identidades de politica** de
20261114010000, verificadas por (esquema, tabla, SHA-256 UTF8 del nombre). El
comparador mantiene un contrato nominal revisado contra ese DDL, independiente
del contenido de cualquiera de los dos snapshots. Exige ademas comando,
caracter permisivo y destinatario unico con su nombre/hash esperados. Se rechazan
ausencias, extras, sustituciones y dos filas con la misma identidad aunque sus
cuerpos sean diferentes, tambien si ambos snapshots contienen la misma alteracion.
No se reconstruyen politicas ausentes ni se deducen identidades de su posicion.
Los hashes de USING/WITH CHECK siguen comparandose con la referencia de procedencia
revisada: el contrato nominal no es una validacion independiente de sus expresiones.
Los campos existentes bastan; no cambia el formato del catalogo o snapshot.

## Lo observable no demuestra ejecucion DDL

La cuarta migracion crea roles NOLOGIN sin atributos administrativos, esquema,
tablas, politicas, trigger y funciones. Requiere postgres/PG17 y ocho tablas de
postgres con RLS/FORCE. Sus GRANT sobre tablas requieren propiedad o delegacion;
el esquema nuevo requiere CREATE en base. CREATE ROLE requiere CREATEROLE; en
PG17, crear un rol con CREATEROLE genera ADMIN pero no SET/INHERIT automaticos.
La migracion concede explicitamente SET/INHERIT temporal al migrador y los retira.
ALTER FUNCTION OWNER requiere poder asumir el propietario nuevo y que este tenga
CREATE en el esquema; ese CREATE temporal tambien se retira. No se cambia el SQL
ni se usa una identidad privilegiada para sortear fallos.

Fuentes oficiales revisadas: [CREATE ROLE PG17](https://www.postgresql.org/docs/17/sql-createrole.html),
[ALTER FUNCTION PG17](https://www.postgresql.org/docs/17/sql-alterfunction.html) y
[roles administrados de Supabase](https://supabase.com/docs/guides/database/postgres/roles).
Supabase puede imponer restricciones adicionales: atributos de postgres no son
una prueba de capacidad para GRANT/OWNER futuros. El lector no ejecuta pruebas de
escritura, SET ROLE o funciones SECURITY DEFINER para intentar acreditarlo.

Siempre quedan no verificables por estas herramientas: identidad futura efectiva
de la CLI, restricciones/hooks DDL del proveedor, Exposed schemas/exposicion de
tablas y acreditacion de proyecto/endpoint/TLS. El resultado nunca autoriza
despliegue. `bloqueado` indica incompatibilidades observadas;
`evidencia_insuficiente` significa que faltan pruebas independientes, incluso si
todos los campos del catalogo coinciden. Ambos exigen detener escrituras.

## Referencia real y reproducible

El fixture opt-in admite tres o cuatro migraciones, en contenedores distintos y
sin leer DATABASE_URL o configuraciones del desarrollador. El modo tres arranca
un PostgreSQL nuevo y aplica solo las tres primeras como NOSUPERUSER; nunca aplica
la cuarta y nunca la deshace. Mantiene postgres NOSUPERUSER y no crea logins de
servicios/fixtures. Solo crea Auth minimo VACIO (su tabla, sin sujetos) y tres filas
de historial sintetico de las versiones que realmente acaba de aplicar. El
bootstrap del contenedor sirve exclusivamente a pruebas negativas reversibles.
No es una identidad de aplicacion o un procedimiento remoto.

Desde un checkout limpio del mismo commit, con dependencias ya verificadas y
Docker local disponible, ejecutar en PowerShell:

```powershell
$env:TINOTIFY_TEST_POSTGRES='1'
$env:TINOTIFY_TEST_POSTGRES_VERSION='17.12'
New-Item -ItemType Directory -Force exportaciones | Out-Null
backend/.venv/Scripts/python -B -m pytest backend/tests/integration/test_preflight_4b4b.py -v -p no:cacheprovider --basetemp exportaciones/referencia-4b4b
Remove-Item Env:TINOTIFY_TEST_POSTGRES_VERSION
Remove-Item Env:TINOTIFY_TEST_POSTGRES
```

Usar un basetemp dedicado y vacio: pytest administra ese directorio. No apuntarlo
a datos existentes. `exportaciones/` ya esta excluido de Git. El test positivo
genera `referencia-tres.json` dentro del subdirectorio de ese test y verifica dos
capturas iguales, 25 politicas e historial [1,1,1,0]. Contiene el digest real de
imagen, commit y hashes LF de cuatro migraciones, tres consultas, comparador,
fixture/generador de referencia y workflow.
El servidor nuevo demuestra la etapa; escribir etapa=3 en un JSON no lo demuestra.

CI Linux ejecuta las integraciones y conserva SOLO ese JSON sintetico como
artefacto durante tres dias, mediante upload-artifact fijado por SHA. No publica
las carpetas TLS/env del fixture ni snapshots remotos. Descargarlo desde el run
correspondiente y conservar su procedencia/digest de artefacto. El commit del
snapshot es el checkout real: en un PR puede ser el commit de merge de prueba de
GitHub. Para comparar, usar exactamente ese checkout o regenerar referencia en
un commit comun. No atribuirle el SHA de otro commit ni editar el manifiesto.
Para PG17.11, repetir con esa version en otro directorio; no intercambiar
referencias entre parches sin revisar efectos del deparser.

### 4B.4-C: referencia PG17.11 del checkout fijo 838067ae

La primera lectura comunicada por el usuario en Development declara PG17.11,
postgres como current_user/session_user, READ ONLY, REPEATABLE READ y row_security
on. No se realizaron lecturas adicionales desde el agente. La referencia 17.12
de main no se convierte en 17.11 editando metadata: se requiere PostgreSQL real.

`.github/workflows/referencia-pg1711.yml` prepara esa referencia en un runner Linux
desechable. Se activa mediante un PR hacia main que cambie ese archivo, desde
`codex/referencia-pg1711-838067ae` del mismo repositorio. No usa workflow_dispatch,
por lo que no requiere fusionar un workflow manual en main antes de ejecutarlo.
Debe comprobarse el run real del PR borrador: si GitHub no ejecuta el job,
detenerse y proponer otra via, sin fusionarlo o cambiar permisos para eludirlo.

El workflow tiene contents: read, acciones fijadas por SHA, sin secrets de proyecto
ni environment remoto. Hace checkout explicito e inmutable de
`838067ae69f88ad132a4bafb351306f5c2eb8f21`, verifica HEAD/arbol limpio e instala
las dependencias existentes con hashes/solo wheels y el paquete local sin red.
Ejecuta UNICAMENTE este nodo con TINOTIFY_TEST_POSTGRES_VERSION=17.11:

```text
backend/tests/integration/test_preflight_4b4b.py::test_referencia_real_tres_migraciones_reproducible
```

Ese test parametriza el fixture con tres migraciones, crea un contenedor nuevo,
mantiene NOSUPERUSER y genera historial sintetico [1,1,1,0]. No aplica ni revierte
la cuarta migracion, no provisiona sujetos Auth y no necesita credenciales del
desarrollador. El CI habitual del PR tambien se ejecuta sin cambios; sus pruebas
y artefacto 17.12 son independientes de esta referencia fija 17.11.

Antes de publicar se exige server_version_num=170011, las 25 identidades nominales
con comandos/roles exactos mediante validar_snapshot del checkout fijo, checksum
interno, historial sin versiones ajenas, ausencia de colisiones/app_fixture,
ocho tablas con RLS/FORCE y propietario esperado, y hashes LF de los once archivos
del manifiesto contra los bytes del checkout. El digest de imagen del snapshot
debe coincidir con RepoDigests de `docker image inspect postgres:17.11` en ese
mismo runner. La version/build exacta y el digest quedan en el JSON original.

Se publican solo dos archivos durante tres dias:

| Archivo | Contenido |
| --- | --- |
| referencia-tres.json | Bytes originales generados por el test, sin sustituir SHA, version o hashes |
| procedencia.json | Commit fuente, commit/ref del workflow, commit del evento, repo/run/intento, version PG, digest imagen y hashes de referencia/manifiesto/checksum |

El nombre del artefacto usa el HEAD fuente VERIFICADO y el run/intento:
`referencia-pg1711-838067ae69f88ad132a4bafb351306f5c2eb8f21-<run>-<intento>`.
Se copian solo los archivos finales a un directorio dedicado de RUNNER_TEMP;
no se suben credenciales, env, TLS, logs ni aliases current duplicados de pytest.
La estructura del snapshot y el comparador no cambian.

Hay dos procedencias legitimas: W es el commit del workflow conductor aprobado,
y S=838067ae es el checkout del codigo/datos de referencia. GitHub puede identificar
el run con W u otro commit del evento; no debe presentarse ese valor como S.
El checkout contiene la version original de backend-tests.yml en S, incluida en
su manifiesto; el workflow conductor nuevo se acredita por workflow_commit/ref
y el run GitHub, no fingiendo que formaba parte de S. Conservar ambas evidencias.

Procedimiento de obtencion, sin autorizar consultas remotas:

1. Abrir y mantener el PR en borrador. Confirmar que el workflow de referencia
   realmente arranca sin fusionarlo y que todos sus pasos terminan correctamente.
2. Descargar el artefacto del run correcto. Comparar SHA-256 del ZIP descargado
   con el digest publicado por Actions, y el JSON con referencia_sha256 de la
   procedencia. No confundir checksum de ZIP, JSON y checksum interno del snapshot.
3. Verificar source_commit y snapshot.commit contra 838067ae; contrastar W/ref y
   run/intento con GitHub. Ejecutar validar_snapshot y comparar los once hashes
   de archivos con un checkout limpio de S. Confirmar PG170011, etapa e historial.
4. Guardar los JSON en exportaciones/ fuera de Git. No reutilizar la referencia
   PG17.12, sobrescribir artefactos anteriores ni editar campos para aprobar.
5. Solo tras otra autorizacion, capturar Supabase con los scripts exactos de S y
   empaquetar desde el mismo checkout S. Comparar con esta referencia 17.11.

Ejemplo posterior OFFLINE, desde S y con archivos completos ya autorizados:

```powershell
backend/.venv/Scripts/python backend/scripts/comparar_catalogos.py empaquetar --origen remoto --preflight exportaciones/preflight.json --catalogo exportaciones/catalogo.json --historial exportaciones/historial.json --salida exportaciones/remoto-tres.json
backend/.venv/Scripts/python backend/scripts/comparar_catalogos.py comparar --referencia exportaciones/pg1711/referencia-tres.json --remoto exportaciones/remoto-tres.json
```

No basta coincidir en 17.11: builds, roles, ACL y efectos del proveedor siguen
sujetos a comparacion/revision exactas. Igualdad conserva evidencia_insuficiente.
No se habilita app_fixture, modifica Supabase/Auth/permisos, conecta Render o SIGAC
ni se aplica DDL remoto. El resultado real del workflow y su artefacto se registran
en el PR: preparar este archivo no acredita una ejecucion todavia no observada.

### Commit del artefacto, de referencia y de empaquetado remoto

En un run pull_request hay tres commits distintos que no deben confundirse:
B es la base main, H el head de la rama del PR y M el merge de prueba que GitHub
construye. El workflow actual usa actions/checkout sin ref alternativo, por lo
que el checkout y github.sha son M. El nombre del artefacto usa github.sha;
empaquetar obtiene snapshot.commit de git rev-parse HEAD, tambien M. En cambio,
workflow_run.head_sha identifica H. Ese campo de metadata del run no sustituye M.

Comprobacion real del artefacto del run 43621790825, correspondiente a 240c733:

| Evidencia | SHA observado |
| --- | --- |
| Head de rama H / workflow_run.head_sha | 240c733dd91054f2c23a80f6de66f4d7b8f5a154 |
| Sufijo del artefacto / checkout CI M / snapshot.commit | 413f236054e0263f5a38ea291e4b438c13fed864 |
| SHA-256 del archivo referencia-tres.json descargado | 908e80d3fc2af4aa2ddd09b878d6991a9d45aa17591e0012627951044a8cac86 |

Se leyo el JSON sintetico descargado, no solo su nombre: etapa=3 y 25 politicas.
El ZIP contiene dos copias iguales por el alias current de tmp_path de pytest;
ambas tienen ese mismo hash y commit. Esto no aporta dos referencias independientes.
Es un ejemplo HISTORICO: esta correccion cambia el comparador y requiere artefacto
nuevo. No reutilizar su manifiesto con el checkout posterior ni editar su SHA.

La igualdad exigida es:

```text
C_referencia = artefacto.snapshot.commit = checkout que genero la referencia
C_remoto     = git HEAD del checkout limpio que ejecuta empaquetar --origen remoto
C_referencia = C_remoto, y ambos manifiestos de archivos deben ser iguales
```

No basta que dos trees o los archivos relevantes sean identicos si sus commits
son diferentes. El comparador rechaza esa pareja. Empaquetar no acepta un parametro
para elegir el SHA: lee HEAD y verifica archivos relevantes limpios/versionados.
Las pruebas usan un Git ficticio para demostrar mismo HEAD aceptado y otro HEAD
rechazado aun con el mismo manifiesto; no escriben commits ni cambian la evidencia.

Para usar un artefacto CI, verificar primero procedencia/digest y leer su commit.
El siguiente procedimiento Git es solo una preparacion manual, no una consulta
a Supabase. Ejecutarlo desde el repositorio y con una referencia ya descargada
en exportaciones/referencia-tres.json:

```powershell
$shaReferencia = (Get-Content -LiteralPath exportaciones/referencia-tres.json -Raw | ConvertFrom-Json).commit
if ($shaReferencia -notmatch '^[0-9a-f]{40}$') { throw 'SHA de referencia invalido' }
git fetch origin refs/pull/9/merge
if ($LASTEXITCODE -ne 0) { throw 'No se pudo obtener el merge de prueba' }
$shaDisponible = git rev-parse FETCH_HEAD
if ($shaDisponible -ne $shaReferencia) { throw 'Cambio el merge de prueba: regenerar referencia, sin editar el SHA' }
git worktree add --detach exportaciones/checkout-evidencia $shaReferencia
```

En ese worktree, comprobar HEAD y copiar alli a exportaciones/ la referencia y
las capturas previamente autorizadas. Ejecutar su comparador/empaquetador con
Python 3.11; no hace falta instalar dependencias externas para esa herramienta.
No reutilizar rutas relativas que apunten a otro checkout. Si M ya no se puede
obtener o cambio main, regenerar una referencia desde un commit accesible comun.
Tras fusionar el PR, el nuevo commit de main tambien exige referencia nueva.
No renombrar H como M ni reemplazar snapshot.commit a mano en ninguna alternativa.

La captura SQL remota debe usar los archivos exactos de ese mismo checkout; el
empaquetador no puede probar retroactivamente que se ejecutaron esos archivos.
Registrar esa procedencia durante la captura humana. El checksum detecta cambios
accidentales, no una declaracion falsa de procedencia por quien controle el JSON.

## Captura remota: comandos preparados, NO autorizados ni ejecutados

Primero aprobar por separado identidad, proyecto Development, ruta TLS y lectura.
No solicitar tokens/DSN/secretos en chat. No activar app_fixture ni conectar Render.
En SQL Editor, verificar la identidad seleccionada; leer como postgres no prueba
que db push vaya a ejecutarse asi. Ejecutar en una sola sesion:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
-- Pegar sin modificaciones supabase/checks/4b4b_preflight.sql.
-- Si historial.existe/sin_rls/usage/select_version no son todos true: ROLLBACK y parar.
-- Pegar supabase/checks/4b4a_inventario.sql.
-- Pegar supabase/checks/4b3_historial.sql.
ROLLBACK;
```

Exportar cada celda JSON completa a preflight.json, catalogo.json e historial.json
en un directorio privado fuera de Git. No guardar CSV, screenshots o respuestas
envolventes como si fueran el JSON esperado. Si SQL Editor no mantiene la misma
sesion/snapshot entre ejecuciones, usar el bloque completo revisado en una sola
ejecucion o detenerse; no afirmar consistencia temporal. Conservar los tres
resultados, sin editar filas ni hashes. Un error SQL o permiso insuficiente se
registra como bloqueo/evidencia insuficiente; no intentar otra identidad elevada.

Desde el mismo checkout limpio usado por la referencia, empaquetar OFFLINE:

```powershell
backend/.venv/Scripts/python backend/scripts/comparar_catalogos.py empaquetar --origen remoto --preflight exportaciones/preflight.json --catalogo exportaciones/catalogo.json --historial exportaciones/historial.json --salida exportaciones/remoto-tres.json
backend/.venv/Scripts/python backend/scripts/comparar_catalogos.py comparar --referencia exportaciones/referencia-tres.json --remoto exportaciones/remoto-tres.json
```

La herramienta no importa Psycopg, abre sockets, ejecuta SQL ni consulta remotos
Git. Solo admite archivos .json dentro de exportaciones/ del repositorio; resuelve
rutas y rechaza escapes por .., symlinks o junctions. Esa carpeta debe estar bajo
control del operador local: no se afirma aislamiento frente a un atacante que
cambie enlaces concurrentemente en su filesystem. Solo lee archivos y metadata Git local; empaquetar crea un archivo nuevo sin
sobrescribir. Compara objetos completos y orden de arrays, sin normalizar SQL.
Rechaza formato desconocido, campos ausentes/extra, tipos erroneos, claves JSON
duplicadas, JSON no finito, checksum incorrecto, etapa/commit/hashes incompatibles
o manifiesto relevante sucio/no versionado. Limita cada archivo a 16 MiB.
Los resultados no imprimen valores de snapshots ni contenido de evidencias.
Un checksum no demuestra autenticidad: una persona que reescribe datos y checksum
puede fabricar un archivo. La confianza exige procedencia del artefacto CI y
captura humana revisada; no se presenta el JSON como una atestacion criptografica.

## Diferencias y decisiones

Todas las diferencias se bloquean por defecto. Solo se puede aportar un archivo
JSON con registros exactos campo/referencia_sha256/remoto_sha256/causa/evidencia,
usando `--justificaciones exportaciones/justificaciones.json`. Los hashes son
SHA-256 del valor JSON canonico (funcion digest del comparador). No son hashes
arbitrarios del texto mostrado. No se aceptan comodines, secciones enteras,
evidencias obsoletas o campos sin diferencia. No se aceptan ACL, RLS, constraints,
funciones, propietarios o membresias como excepciones.

Campos de contexto admitidos, cada uno con causa y evidencia externas exactas:

| Campo | Limite de la justificacion |
| --- | --- |
| /catalogo/contexto/server_version | Solo build diferente con el MISMO server_version_num; otro parche bloquea |
| /catalogo/proveedor/event_triggers | Contador concreto, sin afirmar inocuidad ni omitir la revision de hooks |
| /catalogo/proveedor/ajustes_supautils | Contador concreto; no se leen valores sensibles |
| /catalogo/roles/2/rolsuper | Exclusivamente postgres true local -> false remoto; el orden de roles esta validado. La referencia generada aqui ya es NOSUPERUSER, por lo que normalmente no aplica |

Las causas/evidencias son declaraciones humanas, no documentos autenticados por
el programa. Esperada_justificada no resuelve los no verificables. Diferencias de
permisos efectivos derivadas de una diferencia administrativa siguen bloqueando;
no se borran indirectamente por justificar rolsuper. No hay opcion de aprobar
despliegue: comparar devuelve siempre codigo 2. Empaquetar devuelve 0 solo por
construir un archivo valido, no por acreditar compatibilidad o permiso remoto.

Pruebas: RLS/FORCE, propietarios, grants de columna, funciones, constraints nominales,
roles y objetos extra; colisiones de esquema/rol/politica/trigger; falta de acceso
al historial, corruptos/incompletos, procedencia incompatible y excepciones
inadmisibles. Los cambios DDL negativos ocurren solo en contenedores propios y
se revierten; el comparador nunca los ejecuta ni repara. Las pruebas unitarias
usan metadata artificial y no acreditan semantica PostgreSQL.

Validacion local inicial: 371 aprobadas y 82 integraciones omitidas; pip check
correcto. Docker Desktop Linux Engine no disponible: integraciones y generacion
real de referencia pendientes del NUEVO run CI. No reutilizar las 69 aprobaciones
de 4B.4-A como resultado de esta fase. Consultar en el PR el SHA y resultados
actuales de Linux/Windows/PostgreSQL y SonarQube. No se capturo Supabase remoto.
