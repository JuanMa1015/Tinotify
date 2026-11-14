# 4B.3: auditoria de compatibilidad y aplicacion controlada

La [auditoria inicial 4B.4](validacion-remota-4b4.md) confirma que falta un ciclo
de vida de fixtures remotos y documenta limites de este inventario para comparar
esquemas completos. No se ha implementado ni ejecutado un harness remoto.

## Alcance y resultado observado

Base: `origin/main`, `5fe6412` (PR #5 fusionado). Esta entrega no modifica las
migraciones, el adaptador, el motor, el parser, Render ni secretos. No aplica DDL
remoto ni provisiona usuarios/permisos. El proyecto `urxfnmyuwbvnvrxkkppw` sigue
siendo **desarrollo exclusivo con datos ficticios**; `production` es la etiqueta
de la rama principal del proyecto en la CLI, no autorizacion para datos reales.

Consulta remota del **14 de noviembre de 2026 UTC / 13 de noviembre en Bogota**,
mediante Supabase CLI 3.1.0, `db query --remote=<ref> --read-only`:

| Comprobacion ejecutada | Resultado |
| --- | --- |
| Identidad de lectura | `supabase_read_only_user`; session_user=current_user |
| Contexto | transaction_read_only=on, row_security=on |
| Servidor | PostgreSQL 17.11, block_size=8192, UTF8, collation C disponible |
| Dependencias | plpgsql y gen_random_uuid nativo disponibles; no requiere instalar pgcrypto |
| Esquemas | app y app_private, ambos de postgres; postgres tiene CREATE |
| Roles 4A | Los tres esperados, NOLOGIN/NOINHERIT, sin atributos administrativos ni BYPASSRLS |
| Membresias 4A | postgres tiene ADMIN, sin SET ni INHERIT; no es escalamiento de servicios |
| Esquemas / clientes | PUBLIC sin USAGE/CREATE; anon, authenticated, service_role y roles 4A tambien sin ambos |
| Objetos privados | Cero tablas, funciones y objetos ajenos; no hay colisiones observadas |
| Roles internos nuevos | No existen, como exige la migracion pendiente |
| Defaults postgres globales / privados | Sin entradas explicitas; no equivale a ausencia de defaults de PostgreSQL |
| postgres observable | NOSUPERUSER, CREATEROLE, CREATE en base/esquemas, USAGE auth/plpgsql, REFERENCES auth.users.id |
| Auth | id UUID no nulo con indice unico inmediato valido; no se leyeron usuarios |
| Proveedor | Seis event triggers habilitados y 19 ajustes supautils visibles; valores no leidos |
| Historial | 4A una vez; 4B.1 y 4B.2-B cero veces; sin versiones ajenas ni huecos de orden |

**Veredicto: precondiciones de catalogo compatibles; aptitud operativa aun
condicionada a las comprobaciones pendientes.** No es autorizacion para migrar.
No se ha acreditado nuevamente Exposed schemas, el checkbox de exposicion,
la identidad actual de db push ni el efecto de hooks del proveedor sobre DDL
futuro. Ninguna prueba remota de escritura se ha ejecutado.

## Cadena de migraciones inmutable

| Orden | Version | Resultado / dependencia |
| --- | --- | --- |
| 1 | 20261112050000 | 4A aplicada; crea dos esquemas propiedad de postgres y tres roles NOLOGIN cerrados |
| 2 | 20261112160000 | 4B.1 pendiente; exige PG17/current_user=postgres/4A/Auth; crea ocho tablas con FK, CHECK, UNIQUE, indices y ENABLE/FORCE RLS, sin politicas permisivas |
| 3 | 20261114010000 | 4B.2-B pendiente; exige las ocho tablas, roles y permisos de propietario; crea dos propietarios internos, diez funciones y 25 politicas |

No modificar ni repetir 4A. La tercera no contiene guardas para todos los estados
previos: orden/historial y ausencia de sus roles/funciones deben comprobarse antes.
Objetos existentes sin historial correspondiente son una discrepancia, nunca una
invitacion a reutilizarlos con IF NOT EXISTS o reparar el historial automaticamente.

SHA-256 del contenido Git normalizado a LF, no del checkout CRLF:

```text
20261112050000 777b0b12b445a00eb31cd1c54931e35b0f31b8e6d8f81bb23dc9812982e2fba8
20261112160000 3f59a91573b872feb5c8bf39032219e08090614f319e9d84e48b8ee5248e9324
20261114010000 ddecca3d86606712d670a2f4690f8e852966fec4b96b00a76646c5376a091ae8
```

## Que acredita cada mecanismo

`4b3_preflight.sql` es una unica consulta WITH/SELECT de catalogos. Obtiene OID de
Auth/historial mediante pg_class/pg_namespace: no exige USAGE en esos esquemas
para inventariarlos ni consulta sus filas. Inspecciona roles, membresias, ACL de
esquema/tabla/columna/funcion, defaults relevantes de postgres, RLS, politicas,
propietarios, constraints e indices. Funciones y expresiones se resumen mediante
SHA-256 de definiciones; no se imprimen sus cuerpos. Esos hashes son referencias
de comparacion, no anonimizacion ni prueba completa de equivalencia semantica.
Identificadores desconocidos se ocultan o cuentan; no se imprimen sesiones SQL,
direcciones de clientes, configuraciones arbitrarias o cadenas de conexion.

`4b3_historial.sql` se ejecuta por separado solo si el primero confirma existencia,
USAGE del esquema y SELECT. Lee unicamente version y recuentos; no `statements`,
`name`, operadores o contenido de migraciones. La separacion evita que la falta
de permisos de historial inutilice todo el diagnostico. Falta de acceso significa
**evidencia insuficiente**, no historial vacio ni autorizacion para conceder acceso.

Las consultas funcionan antes y despues: antes de 4B.1 es normal que no haya
tablas/funciones/roles nuevos; despues deben coincidir con su etapa. La salida
no toma una decision automatica de despliegue. NULL significa ausente/no aplicable,
no una comprobacion superada. Comparar cada fase con la matriz de abajo.

La CLI 3.1.0 instalada confirma las opciones `--remote`, `--file`, `--read-only`,
`--dry-run` y `--skip-vault`. Para proyecto hospedado, --read-only utiliza la
Management API y esta auditoria comprobo su identidad efectiva. El endpoint
oficial dedicado `/v1/projects/{ref}/database/query/read-only` es beta y requiere
database_read (OAuth database:read). No extraer el token del almacen para llamar
curl manualmente; usar el login seguro ya configurado de la CLI.

Solo se invocan funciones de inspeccion de pg_catalog. SELECT y --read-only por
si solos no impiden todos los efectos de funciones: no agregar pg_terminate_backend,
dblink, llamadas HTTP o funciones app_private al preflight. Tampoco usar EXPLAIN
ANALYZE como sustituto de una revision de efectos.

### Identidad y operaciones administrativas pendientes

| Operacion futura | Permiso / limite que debe revisarse |
| --- | --- |
| CREATE ROLE interno | CREATEROLE de postgres; roles personalizados sin SUPERUSER/BYPASSRLS; no tocar roles reservados de Supabase |
| GRANT de membresia | ADMIN sobre el rol nuevo; el ADMIN automatico PG17 no concede SET/INHERIT |
| ALTER FUNCTION OWNER | Propiedad actual, posibilidad de SET al nuevo propietario y CREATE de este en app_private |
| REVOKE/GRANT de ACL despues de transferir | Capacidad temporal INHERIT del operador sobre propietarios internos, ya prevista en 4B.2-B |
| CREATE POLICY, ENABLE/FORCE RLS | Propiedad de tablas; no conceder administracion a servicios |
| FK a auth.users.id | USAGE auth y REFERENCES de postgres; no necesita otorgarse Auth al writer interno |
| Cierre de migraciones | ACL residuales de defaults/event triggers deben provocar fallo, sin reparaciones automaticas |

La migracion pendiente concede temporalmente SET/INHERIT solo al operador para
transferir/cerrar funciones, y retira esa concesion antes de COMMIT; conserva
el ADMIN automatico sin SET/INHERIT. Los propietarios nuevos permanecen NOLOGIN,
NOINHERIT, NOADMIN y NOBYPASSRLS, sin ser propietarios de las tablas. No se usa
SET ROLE dentro de sus funciones. Ningun cliente/servicio debe ser miembro suyo.

El diagnostico como supabase_read_only_user no acredita la sesion de migracion.
La verificacion historica 4A observo CLI -> login temporal -> rol efectivo postgres;
no se ha repetido ese acceso administrativo en esta fase. migration list o incluso
db push --dry-run pueden inicializar un login administrativo temporal. **No se
ejecutaron ahora**: requieren autorizacion expresa para ese mecanismo. Un dry-run
enumera pendientes, pero no ejecuta ni valida CREATE ROLE, RLS o ALTER OWNER.
La documentacion publica consultada no acredita el orden interno exacto de
COMMIT/registro de historial de este binario; no prometer atomicidad entre ambos.

## Ejecutar el diagnostico sin secretos

Desde la raiz, con las herramientas existentes y login seguro ya completado:

```powershell
$env:SUPABASE_TELEMETRY_DISABLED='1'
$env:DO_NOT_TRACK='1'
npm.cmd exec --offline -- supabase db query --remote=urxfnmyuwbvnvrxkkppw --read-only --file supabase/checks/4b3_preflight.sql
# Solo si historial.existe, usage_disponible y select_disponible son true:
npm.cmd exec --offline -- supabase db query --remote=urxfnmyuwbvnvrxkkppw --read-only --file supabase/checks/4b3_historial.sql
```

No usar --debug, password en argumentos, DSN, --yes, login alternativo privilegiado
o lectura de archivos de credenciales para superar un 401/403. Si falla, detenerse.
No versionar la salida completa; conservar solo resultados revisados de catalogos.

Si la CLI carece de acceso: abrir el SQL Editor del proyecto correcto en Dashboard.
Seleccionar supabase_read_only_user si esta disponible; no crear ese rol. En un
snippet sin credenciales, pegar lo siguiente sustituyendo el comentario por el
contenido completo de UN archivo, ejecutar la seleccion completa:

```sql
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '5s';
-- Pegar 4b3_preflight.sql; contiene una unica consulta terminada en ;
ROLLBACK;
```

Repetir para historial solo si es accesible. Si hay error, ejecutar ROLLBACK en
esa misma sesion. Si el Editor no conserva transaccion/sesion o solo permite una
identidad no autorizada, detenerse; no quitar READ ONLY para hacerlo funcionar.
No pegar migraciones en el Editor ni compartir capturas con secretos.

## Criterios de parada y aplicacion futura

1. Revisar PR y SHA del checkout. Verificar que solo existen las tres migraciones
   anteriores y sus hashes LF coinciden. Congelar escritores y coordinar una sola
   ejecucion; no activar adaptador, Render, trabajadores o SIGAC.
2. Repetir los dos SELECT. Detenerse ante major distinto de 17, encoding distinto
   de UTF8, block_size distinto de 8192, dependencia ausente, propietario/roles
   inesperados, defaults no cerrados por los REVOKE, permisos residuales o
   colisiones de objetos. Revisar minor/build/collation aunque coincida el major.
3. Exigir historial ordenado y sin duplicados/versiones ajenas: actualmente
   `[1,0,0]`. Si objetos e historial no coinciden, detenerse. No db pull/reset,
   migration repair, DROP, cambios de rol o GRANT para eludir errores.
4. En Dashboard, revisar **sin guardar** Data API -> Exposed schemas: app y
   app_private ausentes. Registrar por separado Automatically expose new tables.
   Su estado historico activo no se considera una verificacion actual.
5. Revisar autorizacion administrativa, permisos de postgres y restricciones del
   proveedor. Acordar respaldo/restauracion y ventana de mantenimiento. Roles son
   globales al cluster y un respaldo solo de datos no los reconstruye. No ejecutar
   copias, restauraciones o pruebas de escritura sin alcance/autorizacion propios.
6. Tras autorizacion expresa adicional, ejecutar SOLO la planificacion:

```powershell
# NO ejecutado en 4B.3; puede inicializar acceso administrativo.
npm.cmd exec --offline -- supabase db push --remote=urxfnmyuwbvnvrxkkppw --dry-run --skip-vault
```

Debe enumerar exactamente 20261112160000 y 20261114010000. Si propone 4A, otra
migracion o solicita secretos en parametros, detenerse. No --include-all,
--include-seed, --include-roles, config push o manipulacion del historial.

7. Con revision del plan, identidad efectiva postgres acreditada y autorizacion
   especifica para **ambas** pendientes, el comando futuro de aplicacion seria:

```powershell
# NO autorizado ni ejecutado en esta entrega. Aplica TODAS las pendientes.
npm.cmd exec --offline -- supabase db push --remote=urxfnmyuwbvnvrxkkppw --skip-vault
```

No hay opcion de version objetivo en el help instalado. No esconder/renombrar
archivos para seleccionar una migracion. Si se exige aprobar cada una por separado,
disenar primero un procedimiento independiente y revisado; no improvisarlo aqui.
Cada archivo tiene su propio bloque transaccional: **las dos migraciones no son
una transaccion conjunta**. Una primera completada puede persistir si falla la
segunda. Tras cualquier error/desconexion detenerse y repetir SOLO el preflight
y el historial. Un COMMIT incierto o DDL sin historial exige analisis; no reintentar
automaticamente ni borrar tablas/roles. Incluso ROLLBACK no revierte efectos
externos de un event trigger del proveedor.

8. Verificacion posterior de solo lectura con los mismos scripts:

| Fase | Evidencia esperada |
| --- | --- |
| Solo 4A | Historial [1,0,0]; 2 esquemas, 3 roles, 0 tablas/funciones/roles nuevos |
| Tras 4B.1 | Historial [1,1,0]; 8 tablas ordinarias de postgres con ENABLE/FORCE RLS; 0 funciones/politicas/roles nuevos; sin ACL no propietarias |
| Tras ambas | Historial [1,1,1]; 8 tablas, 5 roles Tinotify, 10 funciones, 25 politicas internas; sin objetos/rutinas ajenos, indices invalidos ni constraints no validados |

Tras ambas, comparar propietarios/flags/search_path y ACL por firma con 4B.2-B:
helpers solo reader/ejecucion writer; seguir/exportar API+sync; reservar/leer/confirmar
sync; pendientes API+notificaciones; procesar solo notificaciones. PUBLIC/anon/
authenticated/service_role sin EXECUTE ni DML; servicios sin acceso directo de
tabla/columna, CREATE de esquema ni membresia de propietarios. Writer conserva
solo los grants internos previstos, incluidos UPDATE de claves para bloqueos.
No confundir el propietario de un helper SECURITY INVOKER con su identidad efectiva.

Comparar tambien fingerprints de constraints, indices, funciones y condiciones
RLS contra una ejecucion aislada del **mismo commit**, con la misma normalizacion
de catalogos. Un recuento correcto no demuestra que sus definiciones sean correctas.
El preflight informa; no reemplaza las guardas de la migracion ni las pruebas RLS
con conexiones operativas futuras autorizadas.

## Diferencias y riesgos pendientes

- El remoto 17.11 no es el 17.12 del ensayo original. Coinciden major, UTF8 y
  bloque 8192; eso no prueba todas las rutas de insercion/B-tree, TLS del pooler o
  comportamiento del proveedor. No cambiar limites por una estimacion.
- Supabase tiene supautils y event triggers; el PostgreSQL oficial aislado no.
  CREATEROLE visible y un ensayo NOSUPERUSER no prueban que un hook permita todas
  las membresias/transferencias. Nunca asumir supabase_admin ni otorgar BYPASSRLS.
- No hay defaults explicitos relevantes, pero funciones tienen EXECUTE de PUBLIC
  por defecto nativo. La migracion lo revoca por firma y audita ACL al final.
- Automatically expose new tables controla defaults de postgres/public; no
  garantiza privacidad de esquemas custom ni sustituye RLS/ACL/Exposed schemas.
  No cambiarlo automaticamente: no es imprescindible para este DDL privado.
- Las migraciones no contienen passwords ni logins reales. Aplicarlas no habilita
  autenticacion institucional, integracion SIGAC, rutas de negocio o workers.
- No se ha probado el binario CLI contra DDL remoto ni su registro de historial
  ante un fallo de red. Tampoco un respaldo/restauracion remoto, retencion o datos
  reales. Esas verificaciones requieren autorizacion y plan propios.

## Validacion local reproducible

Las nueve guardas sin PostgreSQL rechazan escrituras incluso dentro de WITH,
funciones peligrosas, lecturas de Auth/passwords y sentencias adicionales. Seis
pruebas de integracion nuevas ejecutan inventario con rol sin datos/READ ONLY,
detectan desviaciones de permisos de columna/RLS/EXECUTE PUBLIC y heredado, y verifican
historial duplicado/fuera de orden sin leer sus cuerpos. Cada desviacion se
revierte en el contenedor exclusivo del fixture; no usa DSN externos.

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:TINOTIFY_TEST_POSTGRES='1'
$env:TINOTIFY_TEST_POSTGRES_VERSION='17.11' # solo 17.11 o 17.12; default 17.12
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/integration -q -p no:cacheprovider
Remove-Item Env:TINOTIFY_TEST_POSTGRES_VERSION
Remove-Item Env:TINOTIFY_TEST_POSTGRES
```

La opcion de version cambia exclusivamente la imagen oficial del contenedor
desechable; no acepta hosts, DSN, tags arbitrarios ni versiones de otro major.
CI conserva Linux/Windows y la integracion Linux usa 17.12 por defecto.

Resultados ejecutados localmente: **332 aprobadas sin PostgreSQL, 25 omitidas**
por opt-in; **25 integraciones aprobadas en 17.11** y **25 en 17.12**, ambas con
TLS verify-full y bootstrap de la migracion nueva NOSUPERUSER. `pip check` correcto.
Se conserva el aviso previo de deprecacion de HTTPX/Starlette TestClient.
No se instalaron nuevas dependencias Python ni se alteraron hashes/manifiestos.
Solo se descargo la imagen oficial 17.11 para el ensayo aislado.

Referencias oficiales: [CLI query/read-only](https://supabase.com/docs/reference/cli/supabase-db-query),
[endpoint de lectura](https://supabase.com/docs/reference/api/v1-read-only-query),
[roles de Supabase](https://supabase.com/docs/guides/database/postgres/roles-superuser),
[roles PG17](https://www.postgresql.org/docs/17/role-attributes.html),
[ALTER FUNCTION OWNER](https://www.postgresql.org/docs/17/sql-alterfunction.html),
[supautils](https://github.com/supabase/supautils),
[exposicion automatica](https://supabase.com/kb/troubleshooting/cant-change-the-default-privileges-of-supabase_admin-in-the-public-schema-448af9).
